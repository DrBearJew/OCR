import { FormEvent, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, FolderPlus, FolderTree, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Document, Folder, RecordRow } from '../types'
import { useI18n } from '../i18n'

interface Props {
  onOpenRecord: (id: string) => void
  onOpenDocument: (id: string) => void
}

const ROOT_PARENT = '__root__'
const parentKey = (id: string | null | undefined) => id || ROOT_PARENT

export default function FoldersPage({ onOpenRecord, onOpenDocument }: Props) {
  const { t } = useI18n()
  const [folders, setFolders] = useState<Folder[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [allRecords, setAllRecords] = useState<RecordRow[]>([])
  const [allDocuments, setAllDocuments] = useState<Document[]>([])
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const selected = useMemo(() => folders.find((folder) => folder.id === selectedId) || null, [folders, selectedId])

  const folderChildren = useMemo(() => buildFolderChildren(folders), [folders])
  const selectedFolderIds = useMemo(() => selectedId ? descendantFolderIds(selectedId, folders) : null, [folders, selectedId])
  const records = useMemo(
    () => selectedFolderIds ? allRecords.filter((record) => record.folder_id && selectedFolderIds.has(record.folder_id)) : allRecords,
    [allRecords, selectedFolderIds]
  )
  const documents = useMemo(
    () => selectedFolderIds ? allDocuments.filter((document) => document.folder_id && selectedFolderIds.has(document.folder_id)) : allDocuments,
    [allDocuments, selectedFolderIds]
  )
  const selectedRecordCount = selected ? selected.record_count : allRecords.length
  const selectedDocumentCount = selected ? selected.document_count : allDocuments.length

  useEffect(() => {
    void load()
  }, [])

  async function load(folderId = selectedId) {
    const [folderRows, recordRows, documentRows] = await Promise.all([
      api.folders(),
      api.records(),
      api.documents()
    ])
    setFolders(folderRows)
    setAllRecords(recordRows)
    setAllDocuments(documentRows)
    setExpandedIds((current) => expandedWithSelectedAncestors(current, folderRows, folderId))
  }

  async function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    const folder = await api.createFolder({ name: name.trim(), parent_id: selectedId })
    setName('')
    setSelectedId(folder.id)
    setExpandedIds((current) => {
      const next = new Set(current)
      if (folder.parent_id) next.add(folder.parent_id)
      next.add(folder.id)
      return next
    })
    setMessage(`Created ${folder.path}`)
    await load(folder.id)
  }

  async function remove(folder: Folder) {
    if (!confirm(`Delete folder "${folder.path}"? Records and documents remain stored, but the folder will be hidden.`)) return
    await api.deleteFolder(folder.id)
    setSelectedId(null)
    setExpandedIds((current) => {
      const next = new Set(current)
      next.delete(folder.id)
      return next
    })
    setMessage(`Deleted ${folder.path}`)
    await load(null)
  }

  function selectFolder(folder: Folder) {
    setSelectedId(folder.id)
    if ((folderChildren.get(folder.id) || []).length) {
      setExpandedIds((current) => new Set(current).add(folder.id))
    }
    void load(folder.id)
  }

  function toggleFolder(folder: Folder) {
    setExpandedIds((current) => {
      const next = new Set(current)
      if (next.has(folder.id)) next.delete(folder.id)
      else next.add(folder.id)
      return next
    })
  }

  function expandAll() {
    setExpandedIds(new Set(folders.filter((folder) => (folderChildren.get(folder.id) || []).length).map((folder) => folder.id)))
  }

  function collapseAll() {
    setExpandedIds(new Set())
  }

  function renderFolderRows(parentId: string | null, depth = 0): ReactNode {
    return (folderChildren.get(parentKey(parentId)) || []).map((folder) => {
      const children = folderChildren.get(folder.id) || []
      const hasChildren = children.length > 0
      const expanded = expandedIds.has(folder.id)
      const totalCount = folder.record_count + folder.document_count
      return (
        <div className="folder-tree-branch" key={folder.id}>
          <div className={`folder-row ${hasChildren ? 'has-children' : 'is-leaf'}`}>
            <button
              type="button"
              className="folder-toggle"
              title={hasChildren ? (expanded ? t('folders.collapseFolder') : t('folders.expandFolder')) : t('folders.noChildFolders') }
              aria-label={hasChildren ? (expanded ? `Collapse ${folder.name}` : `Expand ${folder.name}`) : `${folder.name} has no child folders`}
              aria-expanded={hasChildren ? expanded : undefined}
              disabled={!hasChildren}
              onClick={() => toggleFolder(folder)}
            >
              {hasChildren ? (expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />) : <span className="folder-toggle-placeholder" />}
            </button>
            <button type="button" className={`folder-select ${folder.id === selectedId ? 'active' : ''}`} onClick={() => selectFolder(folder)}>
              <span className="folder-name" style={{ paddingLeft: `${depth * 12}px` }}>{folder.name}</span>
              {totalCount > 0 && <small className="folder-count" title={t('folders.subtreeCountTitle')}>{totalCount}</small>}
            </button>
            <button type="button" className="folder-delete" title={t('folders.deleteFolder')} onClick={() => void remove(folder)}><Trash2 size={14} /></button>
          </div>
          {hasChildren && expanded && renderFolderRows(folder.id, depth + 1)}
        </div>
      )
    })
  }

  const breadcrumb = selected?.path?.split('/') ?? ['Home']

  return (
    <main className="page-grid folders-page">
      <section className="panel page-header-panel">
        <div>
          <h1>{t('folders.title')}</h1>
          <p>Manual folder organization for records and OCR documents.</p>
        </div>
        <button type="button" onClick={() => void load()}><RefreshCw size={16} /> {t('common.refresh')}</button>
      </section>

      {message && <p className="success-message">{message}</p>}

      <section className="panel folder-layout">
        <aside className="folder-tree-panel">
          <h2><FolderTree size={18} /> {t('folders.tree')}</h2>
          <button className={!selectedId ? 'active' : ''} onClick={() => { setSelectedId(null); void load(null) }}>{t('folders.home')}</button>
          <div className="folder-tree-tools">
            <button type="button" onClick={expandAll}>{t('folders.expandAll')}</button>
            <button type="button" onClick={collapseAll}>{t('folders.collapseAll')}</button>
          </div>
          <div className="folder-tree-list">{renderFolderRows(null)}</div>
          <form className="folder-create-form" onSubmit={create}>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder={selected ? `New inside ${selected.name}` : t('folders.newFolder')} />
            <button className="primary"><FolderPlus size={15} /> {t('common.create')}</button>
          </form>
        </aside>

        <section className="folder-content-panel">
          <div className="breadcrumb">{breadcrumb.map((part, index) => <span key={`${part}-${index}`}>{index ? ' / ' : ''}{part}</span>)}</div>
          <h2>{selected?.path || t('folders.allFolders')}</h2>
          <div className="stat-grid folder-stat-grid">
            <div><strong>{selectedRecordCount}</strong><span>{selected ? t('folders.recordsInSubtree') : t('common.records')}</span></div>
            <div><strong>{selectedDocumentCount}</strong><span>{selected ? t('folders.documentsInSubtree') : t('common.documents')}</span></div>
            <div><strong>{folders.filter((folder) => folder.parent_id === selectedId).length}</strong><span>{t('folders.childFolders')}</span></div>
          </div>
          <div className="table-card">
            <h3>{t('common.records')}</h3>
            {records.slice(0, 12).map((record) => (
              <button key={record.id} className="list-row" onClick={() => onOpenRecord(record.id)}>
                <span className="folder-item-title">{record.title}</span>
                <small className="folder-item-meta">{record.document_count} docs · {record.status}</small>
              </button>
            ))}
          </div>
          <div className="table-card">
            <h3>{t('common.documents')}</h3>
            {documents.slice(0, 12).map((document) => (
              <button key={document.id} className="list-row" onClick={() => onOpenDocument(document.id)}>
                <span className="folder-item-title">{document.manual_title_override || document.extracted_title || document.original_filename}</span>
                <small className="folder-item-meta">{document.collection_name} · {document.processing_state}</small>
              </button>
            ))}
          </div>
        </section>
      </section>
    </main>
  )
}

function buildFolderChildren(folders: Folder[]) {
  const children = new Map<string, Folder[]>()
  for (const folder of folders) {
    const key = parentKey(folder.parent_id)
    const rows = children.get(key) || []
    rows.push(folder)
    children.set(key, rows)
  }
  for (const rows of children.values()) {
    rows.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))
  }
  return children
}

function descendantFolderIds(folderId: string, folders: Folder[]) {
  const children = buildFolderChildren(folders)
  const ids = new Set<string>()
  function visit(id: string) {
    ids.add(id)
    for (const child of children.get(id) || []) visit(child.id)
  }
  visit(folderId)
  return ids
}

function expandedWithSelectedAncestors(current: Set<string>, folders: Folder[], selectedId: string | null) {
  const next = new Set(current)
  const byId = new Map(folders.map((folder) => [folder.id, folder]))
  const children = new Map<string, number>()
  for (const folder of folders) {
    if (folder.parent_id) children.set(folder.parent_id, (children.get(folder.parent_id) || 0) + 1)
  }

  if (!current.size) {
    for (const folder of folders) {
      if (!folder.parent_id && children.has(folder.id)) next.add(folder.id)
    }
  }

  if (selectedId) {
    next.add(selectedId)
    let parentId = byId.get(selectedId)?.parent_id || null
    while (parentId) {
      next.add(parentId)
      parentId = byId.get(parentId)?.parent_id || null
    }
  }

  return next
}
