import { FormEvent, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, FolderOpen, FolderPlus, FolderTree, RefreshCw, Search, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Document, Folder, RecordRow } from '../types'
import { useI18n } from '../i18n'

interface Props {
  onOpenRecord: (id: string) => void
  onOpenDocument: (id: string) => void
}

const ROOT_PARENT = '__root__'
const parentKey = (id: string | null | undefined) => id || ROOT_PARENT

type FolderItemKind = 'record' | 'document'

export default function FoldersPage({ onOpenRecord, onOpenDocument }: Props) {
  const { t } = useI18n()
  const [folders, setFolders] = useState<Folder[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [allRecords, setAllRecords] = useState<RecordRow[]>([])
  const [allDocuments, setAllDocuments] = useState<Document[]>([])
  const [name, setName] = useState('')
  const [renameName, setRenameName] = useState('')
  const [renameParentId, setRenameParentId] = useState('')
  const [query, setQuery] = useState('')
  const [showUnfiledOnly, setShowUnfiledOnly] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  const selected = useMemo(() => folders.find((folder) => folder.id === selectedId) || null, [folders, selectedId])
  const folderChildren = useMemo(() => buildFolderChildren(folders), [folders])
  const folderById = useMemo(() => new Map(folders.map((folder) => [folder.id, folder])), [folders])
  const recordById = useMemo(() => new Map(allRecords.map((record) => [record.id, record])), [allRecords])
  const folderOptions = useMemo(
    () => [...folders].sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true, sensitivity: 'base' })),
    [folders]
  )
  const selectedFolderIds = useMemo(() => selectedId ? descendantFolderIds(selectedId, folders) : null, [folders, selectedId])
  const selectedSubtreeIds = useMemo(() => selectedId ? descendantFolderIds(selectedId, folders) : new Set<string>(), [folders, selectedId])
  const childFolders = useMemo(() => folderChildren.get(parentKey(selectedId)) || [], [folderChildren, selectedId])
  const parentFolderOptions = useMemo(
    () => selected ? folderOptions.filter((folder) => !selectedSubtreeIds.has(folder.id)) : folderOptions,
    [folderOptions, selected, selectedSubtreeIds]
  )
  const scopedRecords = useMemo(() => {
    if (selectedFolderIds) return allRecords.filter((record) => record.folder_id && selectedFolderIds.has(record.folder_id))
    if (showUnfiledOnly) return allRecords.filter((record) => !record.folder_id)
    return allRecords
  }, [allRecords, selectedFolderIds, showUnfiledOnly])
  const scopedDocuments = useMemo(() => {
    if (selectedFolderIds) return allDocuments.filter((document) => document.folder_id && selectedFolderIds.has(document.folder_id))
    if (showUnfiledOnly) return allDocuments.filter((document) => !document.folder_id)
    return allDocuments
  }, [allDocuments, selectedFolderIds, showUnfiledOnly])
  const records = useMemo(() => filterRecords(scopedRecords, query, folderById), [scopedRecords, query, folderById])
  const documents = useMemo(() => filterDocuments(scopedDocuments, query, folderById), [scopedDocuments, query, folderById])
  const unfiledRecordCount = useMemo(() => allRecords.filter((record) => !record.folder_id).length, [allRecords])
  const unfiledDocumentCount = useMemo(() => allDocuments.filter((document) => !document.folder_id).length, [allDocuments])
  const selectedRecordCount = selected ? selected.record_count : scopedRecords.length
  const selectedDocumentCount = selected ? selected.document_count : scopedDocuments.length

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    setRenameName(selected?.name || '')
    setRenameParentId(selected?.parent_id || '')
  }, [selected?.id, selected?.name, selected?.parent_id])

  async function load(folderId = selectedId) {
    setError('')
    try {
      const [folderRows, recordRows, documentRows] = await Promise.all([
        api.folders(),
        api.records(),
        api.documents()
      ])
      setFolders(folderRows)
      setAllRecords(recordRows)
      setAllDocuments(documentRows)
      if (folderId && !folderRows.some((folder) => folder.id === folderId)) setSelectedId(null)
      setExpandedIds((current) => expandedWithSelectedAncestors(current, folderRows, folderId))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    setError('')
    setBusy('create-folder')
    try {
      const folder = await api.createFolder({ name: name.trim(), parent_id: selectedId })
      setName('')
      setSelectedId(folder.id)
      setShowUnfiledOnly(false)
      setExpandedIds((current) => {
        const next = new Set(current)
        if (folder.parent_id) next.add(folder.parent_id)
        next.add(folder.id)
        return next
      })
      setMessage(`${t('folders.createdFolder', 'Created folder')}: ${folder.path}`)
      await load(folder.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function updateSelectedFolder(event: FormEvent) {
    event.preventDefault()
    if (!selected || !renameName.trim()) return
    setError('')
    setBusy(`folder:${selected.id}`)
    try {
      const updated = await api.updateFolder(selected.id, {
        name: renameName.trim(),
        parent_id: renameParentId || null,
        collection_id: selected.collection_id,
      })
      setSelectedId(updated.id)
      setMessage(`${t('folders.updatedFolder', 'Updated folder')}: ${updated.path}`)
      await load(updated.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function remove(folder: Folder) {
    if (!confirm(`Delete folder "${folder.path}"? Records and documents remain stored, but the folder will be hidden.`)) return
    setError('')
    setBusy(`delete-folder:${folder.id}`)
    try {
      await api.deleteFolder(folder.id)
      setSelectedId(null)
      setExpandedIds((current) => {
        const next = new Set(current)
        next.delete(folder.id)
        return next
      })
      setMessage(`${t('folders.deletedFolder', 'Deleted folder')}: ${folder.path}`)
      await load(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function moveRecord(record: RecordRow, folderId: string | null) {
    if ((record.folder_id || '') === (folderId || '')) return
    setError('')
    setBusy(`record:${record.id}`)
    try {
      await api.moveRecordToFolder(record.id, folderId)
      setMessage(`${t('folders.movedRecord', 'Moved record')}: ${record.title}`)
      await load(selectedId)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function moveDocument(document: Document, folderId: string | null) {
    if ((document.folder_id || '') === (folderId || '')) return
    setError('')
    setBusy(`document:${document.id}`)
    try {
      await api.moveDocumentToFolder(document.id, folderId)
      setMessage(`${t('folders.movedDocument', 'Moved document')}: ${documentTitle(document)}`)
      await load(selectedId)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  function selectFolder(folder: Folder) {
    setSelectedId(folder.id)
    setShowUnfiledOnly(false)
    if ((folderChildren.get(folder.id) || []).length) {
      setExpandedIds((current) => new Set(current).add(folder.id))
    }
    void load(folder.id)
  }

  function selectHome(unfiledOnly = false) {
    setSelectedId(null)
    setShowUnfiledOnly(unfiledOnly)
    void load(null)
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

  function folderLabel(folderId: string | null | undefined) {
    return folderId ? folderById.get(folderId)?.path || t('folders.unknownFolder', 'Unknown folder') : t('folders.home')
  }

  function destinationFoldersForRecord(record: RecordRow) {
    return folderOptions.filter((folder) => !folder.collection_id || folder.collection_id === record.collection_id)
  }

  function destinationFoldersForDocument(document: Document) {
    const record = document.record_id ? recordById.get(document.record_id) : null
    return folderOptions.filter((folder) => !folder.collection_id || !record || folder.collection_id === record.collection_id)
  }

  function renderDestinationSelect(kind: FolderItemKind, id: string, value: string | null, options: Folder[], onChange: (folderId: string | null) => void) {
    return (
      <label className="folder-move-select">
        <span>{t('folders.moveToFolder', 'Move to folder')}</span>
        <select value={value || ''} disabled={busy === `${kind}:${id}`} onChange={(event) => onChange(event.target.value || null)}>
          <option value="">{t('folders.home')}</option>
          {options.map((folder) => <option key={folder.id} value={folder.id}>{folder.path}</option>)}
        </select>
      </label>
    )
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
              title={hasChildren ? (expanded ? t('folders.collapseFolder') : t('folders.expandFolder')) : t('folders.noChildFolders')}
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
            <button type="button" className="folder-delete" title={t('folders.deleteFolder')} disabled={Boolean(folder.record_count || folder.document_count || busy)} onClick={() => void remove(folder)}><Trash2 size={14} /></button>
          </div>
          {hasChildren && expanded && renderFolderRows(folder.id, depth + 1)}
        </div>
      )
    })
  }

  const breadcrumb = selected?.path?.split('/') ?? [showUnfiledOnly ? t('folders.unfiled', 'Unfiled') : t('folders.home')]

  return (
    <main className="page-grid folders-page">
      <section className="panel page-header-panel">
        <div>
          <h1>{t('folders.title')}</h1>
          <p>{t('folders.subtitle')}</p>
        </div>
        <button type="button" onClick={() => void load()}><RefreshCw size={16} /> {t('common.refresh')}</button>
      </section>

      {message && <p className="success-message">{message}</p>}
      {error && <p className="warning">{error}</p>}

      <section className="panel folder-layout">
        <aside className="folder-tree-panel">
          <h2><FolderTree size={18} /> {t('folders.tree')}</h2>
          <div className="folder-tree-summary">
            <span><strong>{folders.length}</strong> {t('folders.title')}</span>
            <span><strong>{unfiledRecordCount + unfiledDocumentCount}</strong> {t('folders.unfiled', 'Unfiled')}</span>
          </div>
          <button className={!selectedId && !showUnfiledOnly ? 'active' : ''} onClick={() => selectHome(false)}>{t('folders.home')}</button>
          <button className={!selectedId && showUnfiledOnly ? 'active' : ''} onClick={() => selectHome(true)}>{t('folders.unfiledItems', 'Unfiled items')}</button>
          <div className="folder-tree-tools">
            <button type="button" onClick={expandAll}>{t('folders.expandAll')}</button>
            <button type="button" onClick={collapseAll}>{t('folders.collapseAll')}</button>
          </div>
          <div className="folder-tree-list">{renderFolderRows(null)}</div>
          <form className="folder-create-form" onSubmit={create}>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder={selected ? `${t('folders.newInside')} ${selected.name}` : t('folders.newFolder')} />
            <button className="primary" disabled={busy === 'create-folder'}><FolderPlus size={15} /> {t('common.create')}</button>
          </form>
        </aside>

        <section className="folder-content-panel">
          <div className="folder-content-heading">
            <div>
              <div className="breadcrumb">{breadcrumb.map((part, index) => <span key={`${part}-${index}`}>{index ? ' / ' : ''}{part}</span>)}</div>
              <h2>{selected?.path || (showUnfiledOnly ? t('folders.unfiledItems', 'Unfiled items') : t('folders.allFolders'))}</h2>
              <p>{selected ? t('folders.currentFolderHelp', 'Browse and file records/documents in this folder and its children.') : t('folders.homeHelp', 'Browse all records/documents or use Unfiled to assign items into folders.')}</p>
            </div>
          </div>

          <div className="stat-grid folder-stat-grid">
            <div><strong>{selectedRecordCount}</strong><span>{selected ? t('folders.recordsInSubtree') : t('common.records')}</span></div>
            <div><strong>{selectedDocumentCount}</strong><span>{selected ? t('folders.documentsInSubtree') : t('common.documents')}</span></div>
            <div><strong>{childFolders.length}</strong><span>{t('folders.childFolders')}</span></div>
            <div><strong>{unfiledRecordCount + unfiledDocumentCount}</strong><span>{t('folders.unfiled', 'Unfiled')}</span></div>
          </div>

          {selected && (
            <form className="folder-manage-card" onSubmit={updateSelectedFolder}>
              <label>{t('folders.folderName', 'Folder name')}<input value={renameName} onChange={(event) => setRenameName(event.target.value)} /></label>
              <label>{t('folders.parentFolder', 'Parent folder')}
                <select value={renameParentId} onChange={(event) => setRenameParentId(event.target.value)}>
                  <option value="">{t('folders.home')}</option>
                  {parentFolderOptions.map((folder) => <option key={folder.id} value={folder.id}>{folder.path}</option>)}
                </select>
              </label>
              <button className="primary" disabled={busy === `folder:${selected.id}`}>{t('folders.saveFolder', 'Save folder')}</button>
            </form>
          )}

          <div className="folder-content-toolbar">
            <label className="toolbar-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('folders.searchPlaceholder', 'Search records, documents, filenames, folders...')} /></label>
            {!selected && <button type="button" className={!showUnfiledOnly ? 'active' : ''} onClick={() => setShowUnfiledOnly(false)}>{t('folders.allItems', 'All items')}</button>}
            {!selected && <button type="button" className={showUnfiledOnly ? 'active' : ''} onClick={() => setShowUnfiledOnly(true)}>{t('folders.unfiled', 'Unfiled')}</button>}
          </div>

          <div className="table-card folder-child-card">
            <h3><FolderOpen size={16} /> {t('folders.childFolders', 'Child folders')}</h3>
            {childFolders.length ? childFolders.map((folder) => (
              <button key={folder.id} type="button" className="folder-child-row" onClick={() => selectFolder(folder)}>
                <span>{folder.name}</span>
                <small>{folder.record_count} {t('common.records')} · {folder.document_count} {t('common.documents')}</small>
              </button>
            )) : <p className="empty-state">{t('folders.noChildFoldersInSelection', 'No child folders here yet.')}</p>}
          </div>

          <div className="table-card folder-items-card">
            <h3>{t('common.records')} <small>{records.length}</small></h3>
            {records.length ? records.slice(0, 50).map((record) => (
              <div key={record.id} className="folder-managed-row">
                <button className="list-row" onClick={() => onOpenRecord(record.id)}>
                  <span className="folder-item-title">{record.title}</span>
                  <small className="folder-item-meta">{record.document_count} {record.document_count === 1 ? t('records.documentSingular') : t('records.documentPlural')} · {t(`status.${record.status}`, record.status.replace(/_/g, ' '))} · {folderLabel(record.folder_id)}</small>
                </button>
                {renderDestinationSelect('record', record.id, record.folder_id, destinationFoldersForRecord(record), (folderId) => void moveRecord(record, folderId))}
              </div>
            )) : <p className="empty-state">{t('folders.noRecords', 'No records match this folder/filter.')}</p>}
            {records.length > 50 && <p className="folder-list-limit">{t('folders.showingFirst', 'Showing first 50. Use search to narrow the list.')}</p>}
          </div>

          <div className="table-card folder-items-card">
            <h3>{t('common.documents')} <small>{documents.length}</small></h3>
            {documents.length ? documents.slice(0, 50).map((document) => (
              <div key={document.id} className="folder-managed-row">
                <button className="list-row" onClick={() => onOpenDocument(document.id)}>
                  <span className="folder-item-title">{documentTitle(document)}</span>
                  <small className="folder-item-meta">{document.collection_name} · {t(`status.${document.processing_state}`, document.processing_state.replace(/_/g, ' '))} · {folderLabel(document.folder_id)}</small>
                </button>
                {renderDestinationSelect('document', document.id, document.folder_id, destinationFoldersForDocument(document), (folderId) => void moveDocument(document, folderId))}
              </div>
            )) : <p className="empty-state">{t('folders.noDocuments', 'No documents match this folder/filter.')}</p>}
            {documents.length > 50 && <p className="folder-list-limit">{t('folders.showingFirst', 'Showing first 50. Use search to narrow the list.')}</p>}
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

function documentTitle(document: Document) {
  return document.manual_title_override || document.extracted_title || document.original_filename
}

function filterRecords(records: RecordRow[], query: string, folderById: Map<string, Folder>) {
  const needle = query.trim().toLowerCase()
  if (!needle) return records
  return records.filter((record) => [
    record.title,
    record.status,
    record.collection?.name,
    record.folder_id ? folderById.get(record.folder_id)?.path : 'Home',
  ].some((value) => String(value || '').toLowerCase().includes(needle)))
}

function filterDocuments(documents: Document[], query: string, folderById: Map<string, Folder>) {
  const needle = query.trim().toLowerCase()
  if (!needle) return documents
  return documents.filter((document) => [
    documentTitle(document),
    document.original_filename,
    document.collection_name,
    document.processing_state,
    document.folder_id ? folderById.get(document.folder_id)?.path : 'Home',
  ].some((value) => String(value || '').toLowerCase().includes(needle)))
}
