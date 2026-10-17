import { useEffect, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Download, ExternalLink, FileText, FolderOpen, MoreHorizontal, RefreshCw, Search, Settings2, Tag } from 'lucide-react'
import { api, downloadUrl, previewPageUrl, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { CollectionPageData, Document } from '../types'
import { useI18n } from '../i18n'

const COLLECTION_DOCUMENT_PAGE_LIMIT = 50
const COLLECTION_DOCUMENT_PAGE_LIMIT_OPTIONS = [25, 50, 100]

type CollectionView = 'all' | 'needs_review' | 'failed' | 'recent'

export default function CollectionDetailPage({ slug, onOpenDocument, onOpenSchemas }: { slug: string; onOpenDocument: (id: string) => void; onOpenSchemas: () => void }) {
  const { t, language } = useI18n()
  const [data, setData] = useState<CollectionPageData | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [activeView, setActiveView] = useState<CollectionView>('all')
  const [selectedId, setSelectedId] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [pageLimit, setPageLimit] = useState(COLLECTION_DOCUMENT_PAGE_LIMIT)
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([null])
  const [pageIndex, setPageIndex] = useState(1)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingPage, setLoadingPage] = useState(false)
  const [busyAction, setBusyAction] = useState<'review' | 'export' | 'delete' | 'reextract' | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const collectionName = data?.collection.name
  const selected = useMemo(() => documents.find((document) => document.id === selectedId) || documents[0] || null, [documents, selectedId])
  const selectedCount = selectedIds.size
  const selectedActionIds = useMemo(() => Array.from(selectedIds).filter((id) => !id.startsWith('demo-')), [selectedIds])

  async function loadCollection(): Promise<CollectionPageData | null> {
    setError('')
    try {
      const page = await api.collectionPage(slug)
      setData(page)
      return page
    } catch (err) {
      setError(err instanceof Error ? err.message : t('collectionDetail.loadError', 'Could not load collection'))
      return null
    }
  }

  function resolvedFilters(nextStatus = status, nextQuery = query, nextView = activeView) {
    const filters: Record<string, string> = {}
    if (nextView === 'needs_review') filters.review_state = 'needs_review'
    else if (nextView === 'failed') filters.state = 'failed'
    else if (nextStatus === 'needs_review') filters.review_state = 'needs_review'
    else if (nextStatus) filters.state = nextStatus
    if (nextQuery.trim()) filters.title = nextQuery.trim()
    return filters
  }

  async function loadDocuments(
    cursor: string | null = null,
    nextStatus = status,
    nextQuery = query,
    nextView = activeView,
    limit = pageLimit,
    nextCollectionName = collectionName,
    nextPageIndex = 1,
    nextCursorHistory: Array<string | null> = [null],
  ) {
    if (!nextCollectionName) return
    setError('')
    setLoadingPage(true)
    try {
      const params: Record<string, string> = { collection_name: nextCollectionName, limit: String(limit), ...resolvedFilters(nextStatus, nextQuery, nextView) }
      if (cursor) params.cursor = cursor
      const page = await api.documentsPage(params)
      setDocuments(page.items)
      setCursorHistory(nextCursorHistory)
      setPageIndex(nextPageIndex)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
      setSelectedId((current) => page.items.some((document) => document.id === current) ? current : page.items[0]?.id || '')
      setSelectedIds(new Set())
    } catch (err) {
      setError(err instanceof Error ? err.message : t('collectionDetail.loadDocumentsError', 'Could not load collection documents'))
    } finally {
      setLoadingPage(false)
    }
  }

  async function refresh() {
    const page = await loadCollection()
    await loadDocuments(null, status, query, activeView, pageLimit, page?.collection.name, 1, [null])
  }

  function loadNextCollectionPage() {
    if (!nextCursor || loadingPage) return
    void loadDocuments(nextCursor, status, query, activeView, pageLimit, collectionName, pageIndex + 1, [...cursorHistory, nextCursor])
  }

  function loadPreviousCollectionPage() {
    if (pageIndex <= 1 || loadingPage) return
    const previousHistory = cursorHistory.slice(0, Math.max(1, pageIndex - 1))
    const previousCursor = previousHistory[previousHistory.length - 1] || null
    void loadDocuments(previousCursor, status, query, activeView, pageLimit, collectionName, pageIndex - 1, previousHistory)
  }

  function updateStatus(value: string) {
    setStatus(value)
    setActiveView(value === 'needs_review' ? 'needs_review' : value === 'failed' ? 'failed' : 'all')
    void loadDocuments(null, value, query, value === 'needs_review' ? 'needs_review' : value === 'failed' ? 'failed' : 'all')
  }

  function updateQuery(value: string) {
    setQuery(value)
    void loadDocuments(null, status, value, activeView)
  }

  function updateView(view: CollectionView) {
    setActiveView(view)
    const nextStatus = view === 'failed' ? 'failed' : ''
    setStatus(nextStatus)
    void loadDocuments(null, nextStatus, query, view)
  }

  function updatePageLimit(value: number) {
    setPageLimit(value)
    void loadDocuments(null, status, query, activeView, value)
  }

  function toggleDocumentSelection(documentId: string, checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (checked) next.add(documentId)
      else next.delete(documentId)
      return next
    })
  }

  async function refreshCurrentPage() {
    const page = await loadCollection()
    const cursor = cursorHistory[pageIndex - 1] || null
    await loadDocuments(cursor, status, query, activeView, pageLimit, page?.collection.name || collectionName, pageIndex, cursorHistory)
  }

  async function markSelectedReviewed() {
    if (!selectedActionIds.length || busyAction) return
    setError('')
    setMessage('')
    setBusyAction('review')
    try {
      await api.bulkDocuments({ action: 'set_review_state', document_ids: selectedActionIds, review_state: 'reviewed', review_reason: null })
      setMessage(t('activity.message.reviewUpdated'))
      await refreshCurrentPage()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('activity.message.reviewUpdated'))
    } finally {
      setBusyAction(null)
    }
  }

  async function exportSelectedDocuments() {
    if (!selectedActionIds.length || busyAction) return
    setError('')
    setMessage('')
    setBusyAction('export')
    try {
      const result = await api.bulkDocuments({ action: 'export', document_ids: selectedActionIds })
      if (!Array.isArray(result.documents)) throw new Error(t('collectionDetail.exportFailed'))
      const blob = new Blob([JSON.stringify(result.documents, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `dokocr-documents-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
      setMessage(t('collectionDetail.exportSuccess'))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('collectionDetail.exportFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  async function deleteSelectedDocuments() {
    if (!selectedActionIds.length || busyAction) return
    const confirmation = t('collectionDetail.deleteSelectedConfirm').replace('{count}', String(selectedActionIds.length))
    if (!window.confirm(confirmation)) return
    setError('')
    setMessage('')
    setBusyAction('delete')
    try {
      const results = await Promise.allSettled(selectedActionIds.map((id) => api.deleteDocument(id)))
      const failedIds = selectedActionIds.filter((_, index) => results[index].status === 'rejected')
      await refreshCurrentPage()
      if (failedIds.length) {
        setSelectedIds(new Set(failedIds))
        const failure = results.find((result) => result.status === 'rejected')
        const detail = t('collectionDetail.deleteSelectedPartial').replace('{count}', String(failedIds.length))
        setError(failure?.status === 'rejected' && failure.reason instanceof Error ? `${detail} ${failure.reason.message}` : detail)
      } else {
        setMessage(t('collectionDetail.deleteSelectedSuccess'))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('dashboard.message.deleteFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  async function markDocumentReviewed(document: Document) {
    if (document.id.startsWith('demo-') || document.review_state === 'reviewed' || busyAction) return
    setError('')
    setMessage('')
    setBusyAction('review')
    try {
      await api.patchDocument(document.id, { review_state: 'reviewed', review_reason: null })
      setMessage(t('activity.message.reviewUpdated'))
      await refreshCurrentPage()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('activity.message.reviewUpdated'))
    } finally {
      setBusyAction(null)
    }
  }

  async function reextractDocument(document: Document) {
    if (document.id.startsWith('demo-') || busyAction) return
    setError('')
    setMessage('')
    setBusyAction('reextract')
    try {
      await api.reextractDocument(document.id, false)
      setMessage(t('processing.queued'))
      await refreshCurrentPage()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.reextract'))
    } finally {
      setBusyAction(null)
    }
  }

  function handleRowKeyDown(event: KeyboardEvent<HTMLDivElement>, document: Document) {
    const target = event.target as HTMLElement
    if (target.closest('input, button, a, select, textarea')) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    setSelectedId(document.id)
  }

  useEffect(() => {
    setDocuments([])
    setSelectedId('')
    setSelectedIds(new Set())
    setCursorHistory([null])
    setPageIndex(1)
    setNextCursor(null)
    setTotalEstimate(0)
    void refresh()
  }, [slug])

  const counts = data?.status_counts || {}
  const documentCount = Object.values(counts).reduce((total, count) => total + count, 0)
  const needsReviewCount = data?.needs_review_count || 0
  const viewItems: Array<{ key: CollectionView; label: string; count: number }> = [
    { key: 'all', label: t('collections.viewAll', 'All documents'), count: documentCount },
    { key: 'needs_review', label: t('collections.viewNeedsReview', 'Needs review'), count: needsReviewCount },
    { key: 'failed', label: t('collections.viewFailed', 'Failed'), count: counts.failed || counts.partially_failed || 0 },
    { key: 'recent', label: t('collections.viewRecent', 'Recent'), count: Math.min(totalEstimate || documents.length, pageLimit) },
  ]

  return (
    <main className="collection-detail-console collection-workbench-console">
      <header className="page-header console-header collection-workbench-header">
        <div>
          <span className="eyebrow">{t('dashboard.collection')}</span>
          <h1>{collectionName || slug}</h1>
          <p>{t('collectionDetail.subtitle')}</p>
        </div>
        <div className="button-row">
          <button type="button" onClick={onOpenSchemas}><Settings2 size={17} /> {t('common.schema')}</button>
          <button className="icon-button" title={t('common.refresh')} onClick={() => void refresh()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {message && <p className="success-message">{message}</p>}

      <section className="collection-workbench-stats workflow-card">
        <span><strong>{documentCount.toLocaleString()}</strong>{t('common.documents')}</span>
        <span><strong>{needsReviewCount}</strong>{t('common.needsReview')}</span>
        <span><strong>{counts.complete || 0}</strong>{t('common.complete')}</span>
        <span><strong>{counts.failed || counts.partially_failed || 0}</strong>{t('common.failed')}</span>
      </section>

      <section className="collection-workbench-layout">
        <aside className="collection-view-rail workflow-card">
          <div className="rail-heading">
            <strong>{t('collections.savedViews', 'Saved views')}</strong>
          </div>
          {viewItems.map((item) => (
            <button key={item.key} type="button" className={item.key === activeView ? 'active' : ''} onClick={() => updateView(item.key)}>
              <span>{item.label}</span>
              <em>{item.count.toLocaleString()}</em>
            </button>
          ))}
          <div className="rail-divider" />
          <strong>{t('collections.facets', 'Facets')}</strong>
          <span className="facet-pill"><FolderOpen size={15} /> {t('dashboard.collection')} <em>{collectionName || slug}</em></span>
          <span className="facet-pill"><Tag size={15} /> {t('fields.status')} <em>{status || t('search.anyStatus')}</em></span>
        </aside>

        <section className="workflow-card collection-library-panel">
          <div className="document-toolbar collection-detail-toolbar collection-library-toolbar">
            <label className="toolbar-search">
              <Search size={17} />
              <input placeholder={t('collectionDetail.searchPlaceholder')} value={query} onChange={(event) => updateQuery(event.target.value)} />
            </label>
            <select value={status} onChange={(event) => updateStatus(event.target.value)}>
              <option value="">{t('search.anyStatus')}</option>
              <option value="complete">{t('common.complete')}</option>
              <option value="failed">{t('common.failed')}</option>
              <option value="ocr_processing">{t('common.processing')}</option>
              <option value="needs_review">{t('common.needsReview')}</option>
            </select>
            <SavedViewsBar section="collections" filters={{ status, query }} onApply={(filters) => {
              const nextStatus = filters.status || ''
              const nextQuery = filters.query || ''
              const nextView: CollectionView = nextStatus === 'needs_review' ? 'needs_review' : nextStatus === 'failed' ? 'failed' : 'all'
              setStatus(nextStatus)
              setQuery(nextQuery)
              setActiveView(nextView)
              void loadDocuments(null, nextStatus, nextQuery, nextView)
            }} />
          </div>

          {selectedCount > 0 && (
            <div className="collection-bulk-bar">
              <strong>{selectedCount} {t('documents.selected')}</strong>
              <button type="button" disabled={!selectedActionIds.length || Boolean(busyAction)} onClick={() => void markSelectedReviewed()}>{busyAction === 'review' ? t('common.loading', 'Loading…') : t('documents.markReviewed')}</button>
              <button type="button" disabled={!selectedActionIds.length || Boolean(busyAction)} onClick={() => void exportSelectedDocuments()}>{busyAction === 'export' ? t('common.loading', 'Loading…') : t('common.export', 'Export')}</button>
              <button type="button" className="danger-button" disabled={!selectedActionIds.length || Boolean(busyAction)} onClick={() => void deleteSelectedDocuments()}>{busyAction === 'delete' ? t('common.loading', 'Loading…') : t('common.delete')}</button>
            </div>
          )}

          <div className="collection-doc-table" role="table" aria-label={t('common.documents')}>
            <div className="collection-doc-table-head" role="row">
              <span role="columnheader" aria-label={t('common.select', 'Select')} />
              <span role="columnheader">{t('fields.title')}</span>
              <span role="columnheader">{t('fields.sender')}</span>
              <span role="columnheader">{t('fields.date')}</span>
              <span role="columnheader">{t('fields.amount')}</span>
              <span role="columnheader">{t('fields.status')}</span>
              <span role="columnheader">{t('fields.tags')}</span>
              <span role="columnheader" aria-label={t('common.open')} />
            </div>
            {documents.map((document) => (
              <div
                key={document.id}
                className={`collection-doc-row ${document.id === selected?.id ? 'selected' : ''}`}
                role="row"
                tabIndex={0}
                onClick={() => setSelectedId(document.id)}
                onKeyDown={(event) => handleRowKeyDown(event, document)}
              >
                <span role="cell">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(document.id)}
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => event.stopPropagation()}
                    onChange={(event) => toggleDocumentSelection(document.id, event.target.checked)}
                    aria-label={`${t('common.select', 'Select')} ${document.original_filename}`}
                  />
                </span>
                <span role="cell" className="collection-doc-title"><FileText size={16} /><span><strong>{document.manual_title_override || document.extracted_title || document.original_filename}</strong><small>{document.original_filename}</small></span></span>
                <span role="cell">{document.extracted_sender || document.extracted_recipient || '—'}</span>
                <span role="cell">{document.extracted_date || new Date(document.updated_at).toLocaleDateString(language === 'de' ? 'de-DE' : undefined)}</span>
                <span role="cell">{document.extracted_amount || '—'}</span>
                <span role="cell"><StatusBadge value={document.review_state === 'needs_review' ? 'needs_review' : document.processing_state} /></span>
                <span role="cell" className="collection-tag-cell">{document.llm_suggested_folder ? <em>{document.llm_suggested_folder}</em> : document.llm_suggested_tags.slice(0, 2).map((tag) => typeof tag === 'string' && tag.trim() ? <em key={tag}>{tag}</em> : null)}</span>
                <span role="cell"><button type="button" className="icon-button" onClick={(event) => { event.stopPropagation(); onOpenDocument(document.id) }} title={t('common.open')}><MoreHorizontal size={16} /></button></span>
              </div>
            ))}
            {!documents.length && <p className="muted-empty">{t('documents.noMatches', 'No documents match the current filters.')}</p>}
          </div>

          <div className="pagination-footer collection-pagination-footer">
            <span>{t('common.showing', 'Showing')} {documents.length} / {totalEstimate || documents.length} {t('common.documents')} · {t('common.page', 'Page')} {pageIndex}</span>
            <label className="list-limit-control">{t('common.rowsPerPage', 'Rows per page')}
              <select value={pageLimit} onChange={(event) => updatePageLimit(Number(event.target.value) || COLLECTION_DOCUMENT_PAGE_LIMIT)}>
                {COLLECTION_DOCUMENT_PAGE_LIMIT_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <div className="collection-page-buttons">
              <button type="button" onClick={loadPreviousCollectionPage} disabled={loadingPage || pageIndex <= 1}>{t('common.previous', 'Previous')}</button>
              <button type="button" className="primary" onClick={loadNextCollectionPage} disabled={loadingPage || !nextCursor}>{loadingPage ? t('common.loading', 'Loading…') : t('common.next', 'Next')}</button>
            </div>
          </div>
        </section>

        <CollectionPeekPanel
          document={selected}
          busy={Boolean(busyAction)}
          onOpenDocument={onOpenDocument}
          onMarkReviewed={markDocumentReviewed}
          onReextract={reextractDocument}
        />
      </section>
    </main>
  )
}

function CollectionPeekPanel({ document, busy, onOpenDocument, onMarkReviewed, onReextract }: { document: Document | null; busy: boolean; onOpenDocument: (id: string) => void; onMarkReviewed: (document: Document) => void; onReextract: (document: Document) => void }) {
  const { t, language } = useI18n()
  if (!document) {
    return (
      <aside className="collection-peek-panel workflow-card empty-peek-panel">
        <FileText size={30} />
        <strong>{t('collectionDetail.noDocumentSelected', 'No document selected')}</strong>
        <span>{t('collectionDetail.selectDocumentForPreview', 'Select a document to preview page 1 and metadata.')}</span>
      </aside>
    )
  }

  const previewSource = collectionDocumentPreviewUrl(document)
  const isPdf = document.mime_type === 'application/pdf' && !document.id.startsWith('demo-')
  const pdfPreviewSource = isPdf ? `${previewUrl(document.id)}#page=1` : null
  const title = document.manual_title_override || document.extracted_title || document.original_filename
  const updated = new Date(document.updated_at).toLocaleString(language === 'de' ? 'de-DE' : undefined)
  const snippet = (document.ocr_text || document.ocr_snippet || '').trim()
  const tags = document.llm_suggested_tags.filter((tag): tag is string => typeof tag === 'string' && tag.trim().length > 0).slice(0, 4)

  return (
    <aside className="collection-peek-panel workflow-card">
      <header>
        <span className="eyebrow">{t('collectionDetail.pageOnePreview', 'Page 1 preview')}</span>
        <h2>{title}</h2>
        <small>{document.original_filename}</small>
      </header>
      <div className="collection-preview-toolbar">
        {isPdf ? (
          <>
            <span><FileText size={16} /> {t('collectionDetail.pdfOptions', 'PDF options')}</span>
            <small className="native-pdf-toolbar-note">{t('collectionDetail.pdfToolbarHint', 'Use the PDF toolbar for pages and zoom.')}</small>
            <a className="icon-button" href={previewUrl(document.id)} target="_blank" rel="noreferrer" title={t('collectionDetail.openFullPdf', 'Open full PDF')}><ExternalLink size={15} /></a>
            <a className="icon-button" href={downloadUrl(document.id)} title={t('common.download')}><Download size={15} /></a>
          </>
        ) : (
          <span><FileText size={16} /> {t('collectionDetail.pageOnePreview', 'Page 1 preview')}</span>
        )}
      </div>
      <div className={`collection-page-preview ${isPdf ? 'collection-pdf-preview' : ''}`}>
        {pdfPreviewSource ? <iframe className="collection-native-pdf-preview" src={pdfPreviewSource} title={`${document.original_filename} PDF preview`} /> : previewSource ? <img src={previewSource} alt={`${document.original_filename} page 1`} /> : <div className="file-icon">{document.original_filename.split('.').pop()?.toUpperCase() || 'DOC'}</div>}
      </div>
      <dl className="collection-peek-fields">
        <div><dt>{t('fields.sender')}</dt><dd>{document.extracted_sender || '—'}</dd></div>
        <div><dt>{t('fields.recipient')}</dt><dd>{document.extracted_recipient || '—'}</dd></div>
        <div><dt>{t('fields.date')}</dt><dd>{document.extracted_date || updated}</dd></div>
        <div><dt>{t('fields.amount')}</dt><dd>{document.extracted_amount || '—'}</dd></div>
        <div><dt>{t('fields.status')}</dt><dd><StatusBadge value={document.review_state === 'needs_review' ? 'needs_review' : document.processing_state} /></dd></div>
      </dl>
      <section className="collection-peek-tags">
        <strong>{t('fields.tags')}</strong>
        <div>{tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>{document.llm_suggested_folder || t('documents.noTags', 'No tags')}</span>}</div>
      </section>
      <section className="collection-peek-ocr">
        <strong>{t('documents.ocrText')}</strong>
        <p>{snippet ? compactText(snippet, 420) : t('documents.noActivityEvents', 'No OCR text preview available yet.')}</p>
      </section>
      <section className="collection-peek-activity">
        <strong>{t('nav.activity')}</strong>
        <span>{t('common.updated', 'Updated')} {updated}</span>
        {document.review_reason && <span>{document.review_reason}</span>}
      </section>
      <div className="collection-peek-actions">
        <button type="button" className="primary" onClick={() => onOpenDocument(document.id)}><ExternalLink size={16} /> {t('common.open')}</button>
        <button type="button" disabled={busy || document.id.startsWith('demo-') || document.review_state === 'reviewed'} onClick={() => onMarkReviewed(document)}>{t('documents.markReviewed')}</button>
        <button type="button" disabled={busy || document.id.startsWith('demo-')} onClick={() => onReextract(document)}>{t('common.reextract')}</button>
      </div>
    </aside>
  )
}

function collectionDocumentPreviewUrl(document: Document): string | null {
  if (document.id.startsWith('demo-')) return null
  if (document.mime_type === 'application/pdf') return previewPageUrl(document.id, 1)
  if (document.mime_type?.startsWith('image/')) return previewUrl(document.id)
  return document.thumbnail_path ? thumbnailUrl(document.id) : null
}

function compactText(value: string, limit: number) {
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > limit ? `${compact.slice(0, limit).trim()}…` : compact
}
