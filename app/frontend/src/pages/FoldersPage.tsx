import { FormEvent, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, FolderOpen, FolderPlus, FolderTree, RefreshCw, Search, Trash2 } from 'lucide-react'
import { api, previewPageUrl, previewUrl, thumbnailUrl } from '../api/client'
import type { Folder, FolderContentsItem, FolderContentsPage } from '../types'
import { useI18n } from '../i18n'

interface Props {
  onOpenDocument: (id: string) => void
}

const ROOT_PARENT = '__root__'
const PAGE_LIMIT = 50
const parentKey = (id: string | null | undefined) => id || ROOT_PARENT
const emptyDocumentPage = (): FolderContentsPage => ({ kind: 'documents', scope: 'all', folder_id: null, limit: PAGE_LIMIT, next_cursor: null, total_estimate: 0, items: [] })

type FolderScope = 'all' | 'direct' | 'unfiled'

export default function FoldersPage({ onOpenDocument }: Props) {
  const { t } = useI18n()
  const [folders, setFolders] = useState<Folder[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [documentPage, setDocumentPage] = useState<FolderContentsPage | null>(null)
  const [unfiledDocumentCount, setUnfiledDocumentCount] = useState(0)
  const [name, setName] = useState('')
  const [renameName, setRenameName] = useState('')
  const [renameParentId, setRenameParentId] = useState('')
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [showUnfiledOnly, setShowUnfiledOnly] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  const selected = useMemo(() => folders.find((folder) => folder.id === selectedId) || null, [folders, selectedId])
  const folderChildren = useMemo(() => buildFolderChildren(folders), [folders])
  const folderById = useMemo(() => new Map(folders.map((folder) => [folder.id, folder])), [folders])
  const folderOptions = useMemo(
    () => [...folders].sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true, sensitivity: 'base' })),
    [folders]
  )
  const selectedSubtreeIds = useMemo(() => selectedId ? descendantFolderIds(selectedId, folders) : new Set<string>(), [folders, selectedId])
  const childFolders = useMemo(() => folderChildren.get(parentKey(selectedId)) || [], [folderChildren, selectedId])
  const parentFolderOptions = useMemo(
    () => selected ? folderOptions.filter((folder) => !selectedSubtreeIds.has(folder.id)) : folderOptions,
    [folderOptions, selected, selectedSubtreeIds]
  )
  const documents = documentPage?.items || []
  const selectedDocumentCount = documentPage?.total_estimate ?? 0
  const showDocumentShortcuts = Boolean(selected || showUnfiledOnly || appliedQuery.trim())
  const showFileShortcutPanel = showDocumentShortcuts && (Boolean(documents.length) || Boolean(documentPage?.next_cursor) || !childFolders.length || showUnfiledOnly || Boolean(appliedQuery.trim()))

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    setRenameName(selected?.name || '')
    setRenameParentId(selected?.parent_id || '')
  }, [selected?.id, selected?.name, selected?.parent_id])

  function currentScope(folderId = selectedId, unfiledOnly = showUnfiledOnly): FolderScope {
    if (folderId) return 'direct'
    return unfiledOnly ? 'unfiled' : 'all'
  }

  async function fetchContents(folderId = selectedId, unfiledOnly = showUnfiledOnly, search = query) {
    const normalizedSearch = search.trim()
    const isHomeLanding = !folderId && !unfiledOnly && !normalizedSearch
    const scope = currentScope(folderId, unfiledOnly)
    const unfiledPromise = api.folderContents({ kind: 'documents', scope: 'unfiled', limit: 1 })
    const documentsPromise = isHomeLanding
      ? Promise.resolve(emptyDocumentPage())
      : api.folderContents({ kind: 'documents', scope, folderId, q: normalizedSearch, limit: PAGE_LIMIT })
    const [documentsResult, unfiledDocuments] = await Promise.all([documentsPromise, unfiledPromise])
    setAppliedQuery(normalizedSearch)
    setDocumentPage(documentsResult)
    setUnfiledDocumentCount(unfiledDocuments.total_estimate)
  }

  async function load(folderId = selectedId, unfiledOnly = showUnfiledOnly, search = query) {
    setError('')
    try {
      const folderRows = await api.folders()
      setFolders(folderRows)
      if (folderId && !folderRows.some((folder) => folder.id === folderId)) {
        folderId = null
        setSelectedId(null)
      }
      setExpandedIds((current) => expandedWithSelectedAncestors(current, folderRows, folderId))
      await fetchContents(folderId, unfiledOnly, search)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    }
  }

  async function loadMore() {
    if (!documentPage?.next_cursor) return
    setBusy('load-more:documents')
    try {
      const next = await api.folderContents({
        kind: 'documents',
        scope: documentPage.scope,
        folderId: documentPage.folder_id,
        q: appliedQuery,
        limit: PAGE_LIMIT,
        cursor: documentPage.next_cursor,
      })
      setDocumentPage({ ...next, items: [...documents, ...next.items] })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
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
      await load(folder.id, false)
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
      await load(updated.id, false)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function remove(folder: Folder) {
    const containsDocuments = folder.document_count > 0
    const containsContents = containsDocuments || folder.record_count > 0
    const prompt = containsContents
      ? t('folders.deleteFolderWithFilesConfirm', 'Delete folder "{name}" and move its contained files to trash?').replace('{name}', folder.path)
      : t('folders.deleteFolderConfirm', 'Delete folder "{name}"?').replace('{name}', folder.path)
    if (!confirm(prompt)) return
    setError('')
    setBusy(`delete-folder:${folder.id}`)
    try {
      await api.deleteFolder(folder.id, containsContents)
      setSelectedId(null)
      setExpandedIds((current) => {
        const next = new Set(current)
        next.delete(folder.id)
        return next
      })
      setMessage(`${t('folders.deletedFolder', 'Deleted folder')}: ${folder.path}`)
      await load(null, false)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function deleteDocumentShortcut(document: FolderContentsItem) {
    const name = document.original_filename || document.title
    if (!confirm(t('folders.deleteFileConfirm', 'Delete file "{name}"?').replace('{name}', name))) return
    setError('')
    setBusy(`delete-document:${document.id}`)
    try {
      await api.deleteDocument(document.id)
      setMessage(`${t('folders.deletedFile', 'Deleted file')}: ${name}`)
      await load(selectedId, showUnfiledOnly, appliedQuery)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.failed'))
    } finally {
      setBusy('')
    }
  }

  async function moveDocument(document: FolderContentsItem, folderId: string | null) {
    if ((document.folder_id || '') === (folderId || '')) return
    setError('')
    setBusy(`document:${document.id}`)
    try {
      await api.moveDocumentToFolder(document.id, folderId)
      setMessage(`${t('folders.movedDocument', 'Moved document')}: ${document.title}`)
      await load(selectedId, showUnfiledOnly)
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
    void load(folder.id, false)
  }

  function selectHome(unfiledOnly = false) {
    setSelectedId(null)
    setShowUnfiledOnly(unfiledOnly)
    if (!unfiledOnly) {
      setQuery('')
      void load(null, false, '')
      return
    }
    void load(null, true, query)
  }

  function search(event: FormEvent) {
    event.preventDefault()
    void load(selectedId, showUnfiledOnly, query)
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

  function destinationFoldersForItem(item: FolderContentsItem) {
    return folderOptions.filter((folder) => !folder.collection_id || !item.collection_id || folder.collection_id === item.collection_id)
  }

  function renderDestinationSelect(item: FolderContentsItem, onChange: (folderId: string | null) => void) {
    const destinations = destinationFoldersForItem(item)
    const alreadyUnfiled = !item.folder_id
    const noMoveTargets = alreadyUnfiled && !destinations.length
    return (
      <label className="folder-move-select">
        <span>{t('folders.moveToFolder', 'Move to folder')}</span>
        <select value={item.folder_id || ''} disabled={busy === `document:${item.id}` || noMoveTargets} onChange={(event) => onChange(event.target.value || null)}>
          <option value="">{alreadyUnfiled ? t('folders.noFolderCurrent', 'No folder (already unfiled)') : t('folders.removeFromFolder', 'Remove from folder / Unfiled')}</option>
          {destinations.map((folder) => <option key={folder.id} value={folder.id}>{folder.path}</option>)}
        </select>
      </label>
    )
  }

  function renderDocumentShortcut(document: FolderContentsItem) {
    const extension = (document.original_filename || document.title).split('.').pop()?.slice(0, 5).toUpperCase() || 'DOC'
    const statusLabel = t(`status.${document.status}`, String(document.status || '').replace(/_/g, ' '))
    const hoverPreviewUrl = document.mime_type === 'application/pdf'
      ? previewPageUrl(document.id, 1)
      : document.mime_type?.startsWith('image/')
        ? previewUrl(document.id)
        : document.thumbnail_path
          ? thumbnailUrl(document.id)
          : ''
    return (
      <article key={document.id} className="folder-document-shortcut">
        <button type="button" className="folder-shortcut-button" onClick={() => onOpenDocument(document.id)}>
          <span className="folder-shortcut-icon">
            {document.thumbnail_path ? <img src={thumbnailUrl(document.id)} alt="" /> : <span>{extension}</span>}
          </span>
          <span className="folder-shortcut-title">{document.title}</span>
          <small>{statusLabel}</small>
          <span className="folder-shortcut-preview" role="tooltip">
            <span className="folder-shortcut-preview-media">
              {hoverPreviewUrl ? <img src={hoverPreviewUrl} alt="" /> : <span>{extension}</span>}
            </span>
            <span className="folder-shortcut-preview-text">
              <strong>{document.original_filename || document.title}</strong>
              <small>{document.collection_name || t('common.document', 'Document')} · {statusLabel} · {folderLabel(document.folder_id)}</small>
              <p>{document.ocr_snippet || t('folders.noOcrPreview', 'No OCR preview yet.')}</p>
            </span>
          </span>
        </button>
        <button type="button" className="folder-shortcut-delete" title={t('folders.deleteFile', 'Delete file')} disabled={busy === `delete-document:${document.id}`} onClick={() => void deleteDocumentShortcut(document)}><Trash2 size={14} /></button>
        {renderDestinationSelect(document, (folderId) => void moveDocument(document, folderId))}
      </article>
    )
  }

  function renderFolderRows(parentId: string | null, depth = 0): ReactNode {
    return (folderChildren.get(parentKey(parentId)) || []).map((folder) => {
      const children = folderChildren.get(folder.id) || []
      const hasChildren = children.length > 0
      const expanded = expandedIds.has(folder.id)
      const totalCount = folder.document_count
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
            <button type="button" className="folder-delete" title={t('folders.deleteFolder')} disabled={Boolean(busy)} onClick={() => void remove(folder)}><Trash2 size={14} /></button>
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
        <button type="button" className="primary folder-refresh-button" onClick={() => void load(selectedId, showUnfiledOnly, appliedQuery)}><RefreshCw size={16} /> {t('common.refresh')}</button>
      </section>

      {message && <p className="success-message">{message}</p>}
      {error && <p className="warning">{error}</p>}

      <section className="panel folder-layout">
        <aside className="folder-tree-panel">
          <h2><FolderTree size={18} /> {t('folders.tree')}</h2>
          <div className="folder-tree-summary">
            <span><strong>{folders.length}</strong> {t('folders.title')}</span>
            <span><strong>{unfiledDocumentCount}</strong> {t('folders.unfiled', 'Unfiled')}</span>
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
              <p>{selected ? t('folders.currentFolderHelp', 'Browse and file documents in this folder and its children.') : showUnfiledOnly ? t('folders.unfiledHelp', 'Assign loose files into folders.') : appliedQuery ? t('folders.searchHelp', 'Search results are paginated. Open a folder to browse it like a file cabinet.') : t('folders.homeFoldersOnly', 'Home shows folder shortcuts only. Open a folder or Unfiled to see document shortcuts.')}</p>
            </div>
          </div>

          <div className="stat-grid folder-stat-grid">
            <div><strong>{selectedDocumentCount}</strong><span>{selected ? t('folders.documentsInSubtree') : t('common.documents')}</span></div>
            <div><strong>{childFolders.length}</strong><span>{t('folders.childFolders')}</span></div>
            <div><strong>{unfiledDocumentCount}</strong><span>{t('folders.unfiled', 'Unfiled')}</span></div>
            <div><strong>{folders.length}</strong><span>{t('folders.title')}</span></div>
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

          <form className="folder-content-toolbar" onSubmit={search}>
            <label className="toolbar-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('folders.searchPlaceholder', 'Search documents, filenames, folders...')} /></label>
            <button type="submit" className="primary folder-search-button"><Search size={16} /> {t('common.search', 'Search')}</button>
            {!selected && <button type="button" className={!showUnfiledOnly ? 'active' : ''} onClick={() => selectHome(false)}>{t('folders.allItems', 'All items')}</button>}
            {!selected && <button type="button" className={showUnfiledOnly ? 'active' : ''} onClick={() => selectHome(true)}>{t('folders.unfiled', 'Unfiled')}</button>}
          </form>

          <div className="table-card folder-child-card">
            <h3><FolderOpen size={16} /> {t('folders.folderShortcuts', 'Folder shortcuts')}</h3>
            {childFolders.length ? (
              <div className="folder-child-grid">
                {childFolders.map((folder) => (
                  <button key={folder.id} type="button" className="folder-child-row" onClick={() => selectFolder(folder)}>
                    <FolderOpen size={21} />
                    <span>{folder.name}</span>
                    <small>{folder.document_count} {t('common.documents')}</small>
                  </button>
                ))}
              </div>
            ) : <p className="empty-state">{t('folders.noChildFoldersInSelection', 'No child folders here yet.')}</p>}
          </div>


          {showFileShortcutPanel && (
            <div className="table-card folder-items-card">
              <h3>{t('folders.fileShortcuts', 'File shortcuts')} <small>{documents.length} / {documentPage?.total_estimate ?? 0}</small></h3>
              {documents.length ? <div className="folder-shortcut-grid">{documents.map(renderDocumentShortcut)}</div> : <p className="empty-state">{t('folders.noDocuments', 'No documents match this folder/filter.')}</p>}
              {documentPage?.next_cursor && <button type="button" className="folder-load-more primary" disabled={busy === 'load-more:documents'} onClick={() => void loadMore()}>{t('folders.loadMore', 'Load more')}</button>}
            </div>
          )}
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
