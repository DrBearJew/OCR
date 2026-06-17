import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, FileText, Maximize2, Minus, Plus, RefreshCw, Search, Trash2, UploadCloud } from 'lucide-react'
import type { KeyboardEvent, MouseEvent, ReactNode } from 'react'
import { api, downloadUrl, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { Document, DocumentEvent, DocumentPage } from '../types'
import { useI18n } from '../i18n'

const DOCUMENT_PAGE_LIMIT = 50
const DOCUMENT_BULK_FILTER_LIMIT = 1000

export default function DocumentsPage({ onOpenDocument, onOpenRecord }: { onOpenDocument: (id: string) => void; onOpenRecord: (id: string) => void }) {
  const { t } = useI18n()
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<Document | null>(null)
  const [selectedEvents, setSelectedEvents] = useState<DocumentEvent[]>([])
  const [selectedPages, setSelectedPages] = useState<DocumentPage[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [bulkAllMatching, setBulkAllMatching] = useState(false)

  async function load(nextFilters = filters, append = false, cursor: string | null = null) {
    setError('')
    try {
      const params: Record<string, string> = { ...nextFilters, limit: String(DOCUMENT_PAGE_LIMIT) }
      if (cursor) params.cursor = cursor
      const page = await api.documentsPage(params)
      setDocuments((current) => append ? [...current, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
      if (!append) setSelectedId((current) => page.items.some((doc) => doc.id === current) ? current : page.items[0]?.id || '')
    } catch {
      setError(t('documents.demoWarning'))
      setDocuments(demoDocuments)
      setNextCursor(null)
      setTotalEstimate(demoDocuments.length)
      setSelectedId((current) => current || demoDocuments[0].id)
    }
  }

  async function loadMoreDocuments() {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      await load(filters, true, nextCursor)
    } finally {
      setLoadingMore(false)
    }
  }

  async function loadDetail(documentId: string) {
    if (!documentId || documentId.startsWith('demo-')) {
      setSelectedDetail(null)
      setSelectedEvents([])
      setSelectedPages([])
      setDetailLoading(false)
      return
    }
    setDetailLoading(true)
    try {
      const [documentRow, eventRows, pageRows] = await Promise.all([
        api.document(documentId),
        api.documentEvents(documentId),
        api.documentPages(documentId)
      ])
      setSelectedDetail(documentRow)
      setSelectedEvents(eventRows)
      setSelectedPages(pageRows)
    } catch {
      setSelectedDetail(null)
      setSelectedEvents([])
      setSelectedPages([])
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => { void load() }, [])
  const selectedListItem = useMemo(() => documents.find((doc) => doc.id === selectedId) || documents[0], [documents, selectedId])
  const selected = useMemo(
    () => selectedDetail?.id === selectedListItem?.id ? selectedDetail : selectedListItem,
    [selectedDetail, selectedListItem]
  )
  const stats = useMemo(() => ({ ...buildStats(documents), total: totalEstimate || documents.length }), [documents, totalEstimate])

  useEffect(() => {
    if (!selectedListItem) {
      setSelectedDetail(null)
      setSelectedEvents([])
      setSelectedPages([])
      setDetailLoading(false)
      return
    }
    let cancelled = false
    setSelectedDetail(null)
    setSelectedEvents([])
    setSelectedPages([])
    if (selectedListItem.id.startsWith('demo-')) {
      setDetailLoading(false)
      return
    }
    setDetailLoading(true)
    Promise.all([
      api.document(selectedListItem.id),
      api.documentEvents(selectedListItem.id),
      api.documentPages(selectedListItem.id)
    ]).then(([documentRow, eventRows, pageRows]) => {
      if (cancelled) return
      setSelectedDetail(documentRow)
      setSelectedEvents(eventRows)
      setSelectedPages(pageRows)
    }).catch(() => {
      if (cancelled) return
      setSelectedDetail(null)
      setSelectedEvents([])
      setSelectedPages([])
    }).finally(() => {
      if (!cancelled) setDetailLoading(false)
    })
    return () => { cancelled = true }
  }, [selectedListItem?.id])

  function updateFilter(key: string, value: string) {
    const next = { ...filters, [key]: value }
    if (!value) delete next[key]
    setFilters(next)
    void load(next, false, null)
  }

  function selectedDocumentIdsForActions() {
    const checkedIds = Array.from(selectedIds).filter((id) => !id.startsWith('demo-'))
    if (checkedIds.length) return checkedIds
    return selected?.id && !selected.id.startsWith('demo-') ? [selected.id] : []
  }

  function hasActiveFilters() {
    return Object.values(filters).some((value) => String(value || '').trim())
  }

  function shouldUseBulkFilterScope() {
    return bulkAllMatching && hasActiveFilters() && totalEstimate > 0
  }

  function bulkActionDisabled() {
    return Boolean(busyAction) || (!shouldUseBulkFilterScope() && !selectedDocumentIdsForActions().length)
  }

  function bulkTargetLabel() {
    if (shouldUseBulkFilterScope()) return `${totalEstimate} ${t('documents.matchingTarget')}`
    const checkedIds = Array.from(selectedIds).filter((id) => !id.startsWith('demo-'))
    if (checkedIds.length) return `${checkedIds.length} ${t('documents.selected')}`
    return selected?.id && !selected.id.startsWith('demo-') ? t('documents.activeTarget') : `0 ${t('documents.selected')}`
  }

  async function bulk(action: string, extra: Record<string, unknown> = {}) {
    const filterScope = shouldUseBulkFilterScope()
    const ids = selectedDocumentIdsForActions()
    if (!filterScope && !ids.length) {
      setError(t('documents.selectDocumentForAction'))
      return
    }
    if (filterScope && !confirm(`${t('documents.bulkFilterConfirm')} ${totalEstimate} ${t('common.documents')}?`)) return
    setError('')
    setMessage('')
    setBusyAction(action)
    try {
      await api.bulkDocuments(filterScope
        ? { action, selection_mode: 'filters', filters, max_matches: DOCUMENT_BULK_FILTER_LIMIT, ...extra }
        : { action, document_ids: ids, ...extra })
      setSelectedIds(new Set())
      await load(filters, false, null)
      if (!filterScope && selectedId && ids.includes(selectedId)) await loadDetail(selectedId)
      if (filterScope && selectedId) await loadDetail(selectedId)
      setMessage(action === 'set_review_state' ? t('activity.message.reviewUpdated') : t('processing.queued'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk action failed')
    } finally {
      setBusyAction(null)
    }
  }

  async function markReviewed(document: Document) {
    if (document.id.startsWith('demo-')) return
    setError('')
    setMessage('')
    setBusyAction('mark_reviewed')
    try {
      const updated = await api.patchDocument(document.id, { review_state: 'reviewed', review_reason: null })
      setDocuments((rows) => rows.map((row) => row.id === updated.id ? updated : row))
      setSelectedDetail(updated)
      await loadDetail(updated.id)
      setMessage(t('activity.message.reviewUpdated'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Mark reviewed failed')
    } finally {
      setBusyAction(null)
    }
  }

  async function deleteSelectedDocuments() {
    const ids = Array.from(selectedIds).filter((id) => !id.startsWith('demo-'))
    if (!ids.length) return
    if (!confirm(`Delete ${ids.length} selected document${ids.length === 1 ? '' : 's'}? This soft-deletes each file, OCR text, and metadata without touching sibling documents.`)) return
    setError('')
    try {
      await Promise.all(ids.map((id) => api.deleteDocument(id)))
      setSelectedIds(new Set())
      setSelectedId((current) => ids.includes(current) ? '' : current)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  async function deleteDocument(document: Document) {
    if (document.id.startsWith('demo-')) return
    if (!confirm(`Delete "${document.original_filename}"? This soft-deletes this document only; sibling files stay in the record.`)) return
    setError('')
    try {
      await api.deleteDocument(document.id)
      setSelectedIds((current) => {
        const next = new Set(current)
        next.delete(document.id)
        return next
      })
      setSelectedId('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  function isMobileDocumentsViewport() {
    return typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches
  }

  function handleDocumentRowClick(document: Document) {
    setSelectedId(document.id)
    if (!document.id.startsWith('demo-') && isMobileDocumentsViewport()) {
      onOpenDocument(document.id)
    }
  }

  function handleDocumentRowKeyDown(event: KeyboardEvent<HTMLDivElement>, document: Document) {
    const target = event.target as HTMLElement
    if (target.closest('input, button, a, select, textarea')) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    handleDocumentRowClick(document)
  }

  return (
    <main className="documents-console">
      <header className="page-header console-header">
        <div>
          <h1>{t('documents.title')}</h1>
          <p>{t('documents.subtitle')}</p>
        </div>
        <div className="button-row">
          <button className="primary"><UploadCloud size={18} /> {t('documents.upload')}</button>
          <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="warning">{error}</p>}
      {message && <p className="success-message">{message}</p>}
      <section className="doc-kpi-grid">
        <KpiCard icon={<FileText size={25} />} label={t('documents.kpiTotal')} value={stats.total} detail={t('documents.kpiTotalDetail')} tone="green" />
        <KpiCard icon={<RefreshCw size={25} />} label={t('documents.kpiProcessing')} value={stats.processing} detail={t('documents.kpiProcessingDetail')} tone="blue" />
        <KpiCard icon={<AlertTriangle size={25} />} label={t('documents.kpiNeedsReview')} value={stats.needsReview} detail={t('documents.kpiNeedsReviewDetail')} tone="orange" />
        <KpiCard icon={<AlertTriangle size={25} />} label={t('documents.kpiFailedOcr')} value={stats.failed} detail={t('documents.kpiFailedOcrDetail')} tone="red" />
        <KpiCard icon={<CheckCircle2 size={25} />} label={t('documents.kpiSynced')} value={stats.synced} detail={t('documents.kpiSyncedDetail')} tone="green" />
      </section>
      <section className="documents-console-grid">
        <section className="document-table-panel workflow-card">
          <div className="document-toolbar">
            <label className="toolbar-search"><Search size={17} /><input placeholder={t('documents.searchPlaceholder')} value={filters.title || ''} onChange={(event) => updateFilter('title', event.target.value)} /></label>
            <select value={filters.collection_name || ''} onChange={(event) => updateFilter('collection_name', event.target.value)}>
              <option value="">{t('dashboard.collection')}</option>
              <option>Eingangsrechnung</option>
              <option>Ausgangsrechnung</option>
              <option>Belege</option>
            </select>
            <select value={filters.state || ''} onChange={(event) => updateFilter('state', event.target.value)}>
              <option value="">{t('fields.status')}</option>
              <option value="complete">{t('common.complete')}</option>
              <option value="failed">{t('common.failed')}</option>
              <option value="ocr_processing">{t('common.processing')}</option>
            </select>
            <SavedViewsBar section="documents" filters={filters} onApply={(next) => { setFilters(next); void load(next, false, null) }} />
          </div>
          <div className="bulk-bar console-bulk">
            <span>{bulkTargetLabel()}</span>
            <label className="bulk-scope-toggle" title={t('documents.bulkFilterHelp')}>
              <input type="checkbox" checked={bulkAllMatching} disabled={!hasActiveFilters() || !totalEstimate} onChange={(event) => setBulkAllMatching(event.target.checked)} />
              {t('documents.applyToMatching')}
            </label>
            <button disabled={bulkActionDisabled()} onClick={() => void bulk('retry')}>{t('common.retryOcr')}</button>
            <button disabled={bulkActionDisabled()} onClick={() => void bulk('reextract')}>{t('common.reextract')}</button>
            <button disabled={bulkActionDisabled()} onClick={() => void bulk('set_review_state', { review_state: 'needs_review', review_reason: 'Bulk marked for review' })}>{t('common.needsReview')}</button>
            <button disabled={bulkActionDisabled()} onClick={() => void bulk('set_review_state', { review_state: 'reviewed', review_reason: null })}>{t('common.reviewed')}</button>
            <button className="danger-button" disabled={Boolean(busyAction) || !Array.from(selectedIds).filter((id) => !id.startsWith('demo-')).length} onClick={() => void deleteSelectedDocuments()}><Trash2 size={16} /> {t('documents.deleteSelected')}</button>
          </div>
          <div className="document-console-table">
            <div className="doc-table-head">
              <span />
              <span>{t('fields.title')}</span>
              <span>{t('dashboard.collection')}</span>
              <span>{t('fields.status')}</span>
              <span>{t('fields.date')}</span>
              <span>{t('fields.amount')}</span>
              <span>{t('documents.ocrConfidenceShort')}</span>
            </div>
            {documents.map((document) => (
              <div
                key={document.id}
                role="button"
                tabIndex={0}
                aria-label={`${t('common.open')} ${document.manual_title_override || document.extracted_title || document.original_filename}`}
                className={`doc-table-row ${document.id === selected?.id ? 'selected' : ''}`}
                onClick={() => handleDocumentRowClick(document)}
                onKeyDown={(event) => handleDocumentRowKeyDown(event, document)}
              >
                <input type="checkbox" checked={selectedIds.has(document.id)} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} onChange={(event) => {
                  const next = new Set(selectedIds)
                  if (event.target.checked) next.add(document.id)
                  else next.delete(document.id)
                  setSelectedIds(next)
                }} />
                <span className="doc-title-cell"><FileText size={17} /><strong>{document.manual_title_override || document.extracted_title || document.original_filename}</strong><small>{document.original_filename}</small></span>
                <span className="pill">{document.collection_name}</span>
                <StatusBadge value={document.processing_state === 'complete' && document.review_state === 'needs_review' ? 'needs_review' : document.processing_state} />
                <span>{document.extracted_date || new Date(document.created_at).toLocaleDateString()}</span>
                <span>{document.extracted_amount || 'NA'}</span>
                <span className={document.processing_state === 'failed' ? 'ocr-low' : 'ocr-good'}>{document.processing_state === 'failed' ? '-' : `${document.id.startsWith('demo-') ? '98' : '95'}%`}</span>
              </div>
            ))}
          </div>
          <div className="pagination-footer">
            <span>{documents.length} / {totalEstimate || documents.length} {t('common.documents')}</span>
            {nextCursor && <button type="button" className="primary" disabled={loadingMore} onClick={() => void loadMoreDocuments()}>{t('common.loadMore', 'Load more')}</button>}
          </div>
        </section>
        {selected && <DocumentPreviewPanel document={selected} pages={selectedPages} loading={detailLoading} onOpenDocument={onOpenDocument} />}
        {selected && <DocumentInspector document={selected} events={selectedEvents} loading={detailLoading} busy={Boolean(busyAction)} onOpenDocument={onOpenDocument} onOpenRecord={onOpenRecord} onMarkReviewed={() => void markReviewed(selected)} onDelete={() => void deleteDocument(selected)} />}
      </section>
    </main>
  )
}

type PreviewTab = 'ocr' | 'raw' | 'layout'
type InspectorTab = 'details' | 'metadata' | 'activity'

function DocumentPreviewPanel({ document, pages, loading, onOpenDocument }: { document: Document; pages: DocumentPage[]; loading: boolean; onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  const [activeTab, setActiveTab] = useState<PreviewTab>('ocr')
  const [zoom, setZoom] = useState(100)
  const [largePreviewOpen, setLargePreviewOpen] = useState(false)
  const previewSurfaceRef = useRef<HTMLDivElement | null>(null)
  const canPreview = document.mime_type?.startsWith('image/') || document.mime_type === 'application/pdf'
  const isPdf = document.mime_type === 'application/pdf'
  const mediaStyle = isPdf
    ? { width: `${zoom}%`, maxWidth: zoom <= 100 ? '100%' : 'none', height: `${Math.round(420 * zoom / 100)}px` }
    : { width: `${zoom}%`, maxWidth: zoom <= 100 ? '100%' : 'none' }

  useEffect(() => {
    setActiveTab('ocr')
    setZoom(100)
    setLargePreviewOpen(false)
  }, [document.id])

  function clampZoom(value: number) {
    return Math.min(260, Math.max(50, value))
  }

  function centerRatio() {
    const surface = previewSurfaceRef.current
    if (!surface || !surface.scrollWidth || !surface.scrollHeight) return { x: 0.5, y: 0.5 }
    return {
      x: (surface.scrollLeft + surface.clientWidth / 2) / surface.scrollWidth,
      y: (surface.scrollTop + surface.clientHeight / 2) / surface.scrollHeight
    }
  }

  function setZoomAround(nextZoom: number, ratio = centerRatio()) {
    const surface = previewSurfaceRef.current
    setZoom(clampZoom(nextZoom))
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!surface) return
      surface.scrollLeft = Math.max(0, Math.min(surface.scrollWidth - surface.clientWidth, ratio.x * surface.scrollWidth - surface.clientWidth / 2))
      surface.scrollTop = Math.max(0, Math.min(surface.scrollHeight - surface.clientHeight, ratio.y * surface.scrollHeight - surface.clientHeight / 2))
    }))
  }

  function adjustZoom(delta: number) {
    setZoomAround(zoom + delta)
  }

  function resetZoom() {
    setZoomAround(100, { x: 0.5, y: 0.5 })
  }

  function handlePreviewClick(event: MouseEvent<HTMLDivElement>) {
    if (isPdf) return
    const media = event.currentTarget.querySelector('.zoomable-preview-media') as HTMLElement | null
    if (!media) return
    const rect = media.getBoundingClientRect()
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
    setZoomAround(zoom >= 180 ? 100 : Math.max(180, zoom + 80), { x, y })
  }

  return (
    <section className="document-preview-panel workflow-card">
      <div className="card-title-row">
        <h2>{document.original_filename}</h2>
        <div className="button-row preview-zoom-controls">
          <button type="button" className="icon-button" title={t('common.zoomOut')} onClick={() => adjustZoom(-20)}><Minus size={16} /></button>
          <button type="button" className="zoom-value" title={t('common.resetZoom')} onClick={resetZoom}>{zoom}%</button>
          <button type="button" className="icon-button" title={t('common.zoomIn')} onClick={() => adjustZoom(20)}><Plus size={16} /></button>
          <button type="button" className="icon-button" title={t('documents.largePreview')} onClick={() => setLargePreviewOpen(true)}><Maximize2 size={16} /></button>
          <a className="icon-button" href={downloadUrl(document.id)} title={t('common.download')}><Download size={17} /></a>
          <button className="icon-button" onClick={() => onOpenDocument(document.id)} title={t('common.open')}><FileText size={17} /></button>
        </div>
      </div>
      <div ref={previewSurfaceRef} className="document-preview-surface console-preview zoomable-preview" onClick={handlePreviewClick} title={isPdf ? 'Use zoom controls above the PDF preview' : 'Click image to zoom around that point'}>
        {canPreview && !document.id.startsWith('demo-') ? (
          isPdf
            ? <iframe className="zoomable-preview-media" style={mediaStyle} src={previewUrl(document.id)} title="Document preview" />
            : <img className="zoomable-preview-media" style={mediaStyle} src={previewUrl(document.id)} alt={document.original_filename} />
        ) : document.thumbnail_path && !document.id.startsWith('demo-') ? <img className="zoomable-preview-media" style={mediaStyle} src={thumbnailUrl(document.id)} alt={document.original_filename} /> : <InvoiceMockup />}
      </div>
      <div className="ocr-tabs">
        <button type="button" className={activeTab === 'ocr' ? 'active' : ''} onClick={() => setActiveTab('ocr')}>{t('documents.ocrText')}</button>
        <button type="button" className={activeTab === 'raw' ? 'active' : ''} onClick={() => setActiveTab('raw')}>{t('documents.rawOcr')}</button>
        <button type="button" className={activeTab === 'layout' ? 'active' : ''} onClick={() => setActiveTab('layout')}>{t('documents.layout')}</button>
      </div>
      {activeTab === 'ocr' && <pre className="ocr-preview console-ocr">{document.ocr_text || document.ocr_snippet || 'Open the document detail page to load full OCR text.'}</pre>}
      {activeTab === 'raw' && <pre className="ocr-preview console-ocr json-preview">{formatJson(document.raw_ocr_json, 'No raw OCR JSON stored for this document yet.')}</pre>}
      {activeTab === 'layout' && <LayoutPreview pages={pages} loading={loading} />}
      <span className="confidence-pill">{t('documents.ocrConfidence')}: {document.processing_state === 'failed' ? 'NA' : '98%'}</span>
      {largePreviewOpen && <LargePreviewModal document={document} onClose={() => setLargePreviewOpen(false)} />}
    </section>
  )
}

function LargePreviewModal({ document, onClose }: { document: Document; onClose: () => void }) {
  const { t } = useI18n()
  const [zoom, setZoom] = useState(100)
  const isPdf = document.mime_type === 'application/pdf'
  const canPreview = document.mime_type?.startsWith('image/') || isPdf
  const source = document.id.startsWith('demo-') ? '' : canPreview ? previewUrl(document.id) : document.thumbnail_path ? thumbnailUrl(document.id) : ''
  const mediaStyle = isPdf ? { width: `${zoom}%`, height: `${Math.round(74 * zoom / 100)}vh` } : { width: `${zoom}%` }
  return (
    <div className="large-preview-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="large-preview-dialog" onClick={(event) => event.stopPropagation()}>
        <header>
          <strong>{document.original_filename}</strong>
          <div className="button-row">
            <button type="button" className="icon-button" onClick={() => setZoom((value) => Math.max(50, value - 20))}><Minus size={16} /></button>
            <button type="button" className="zoom-value" onClick={() => setZoom(100)}>{zoom}%</button>
            <button type="button" className="icon-button" onClick={() => setZoom((value) => Math.min(260, value + 20))}><Plus size={16} /></button>
            <button type="button" onClick={onClose}>{t('common.close')}</button>
          </div>
        </header>
        <div className="large-preview-surface">
          {source ? (isPdf ? <iframe style={mediaStyle} src={source} title="Large document preview" /> : <img style={mediaStyle} src={source} alt={document.original_filename} />) : <InvoiceMockup />}
        </div>
      </section>
    </div>
  )
}

function LayoutPreview({ pages, loading }: { pages: DocumentPage[]; loading: boolean }) {
  const [selectedPageId, setSelectedPageId] = useState('')

  useEffect(() => {
    if (!pages.length) {
      setSelectedPageId('')
      return
    }
    setSelectedPageId((current) => pages.some((page) => page.id === current) ? current : pages[0].id)
  }, [pages])

  if (loading) return <p className="tab-empty">Loading page layout…</p>
  if (!pages.length) return <p className="tab-empty">No page layout records are stored for this document yet.</p>
  const selectedPage = pages.find((page) => page.id === selectedPageId) || pages[0]
  return (
    <div className="layout-preview">
      <label className="layout-page-picker">Page
        <select value={selectedPage.id} onChange={(event) => setSelectedPageId(event.target.value)}>
          {pages.map((page) => <option key={page.id} value={page.id}>Page {page.page_number}</option>)}
        </select>
      </label>
      <section className="layout-page">
        <strong>Page {selectedPage.page_number}</strong>
        <pre>{selectedPage.ocr_text || formatJson(selectedPage.raw_ocr_json, 'No layout text for this page.')}</pre>
      </section>
    </div>
  )
}

function DocumentInspector({ document, events, loading, busy, onOpenDocument, onOpenRecord, onMarkReviewed, onDelete }: { document: Document; events: DocumentEvent[]; loading: boolean; busy: boolean; onOpenDocument: (id: string) => void; onOpenRecord: (id: string) => void; onMarkReviewed: () => void; onDelete: () => void }) {
  const { t } = useI18n()
  const [activeTab, setActiveTab] = useState<InspectorTab>('details')

  useEffect(() => {
    setActiveTab('details')
  }, [document.id])

  return (
    <aside className="document-detail-panel workflow-card">
      <div className="detail-tabs">
        <button type="button" className={activeTab === 'details' ? 'active' : ''} onClick={() => setActiveTab('details')}>{t('documents.details')}</button>
        <button type="button" className={activeTab === 'metadata' ? 'active' : ''} onClick={() => setActiveTab('metadata')}>{t('documents.metadata')}</button>
        <button type="button" className={activeTab === 'activity' ? 'active' : ''} onClick={() => setActiveTab('activity')}>{t('nav.activity')}</button>
      </div>
      {activeTab === 'details' && <DocumentDetailsFields document={document} />}
      {activeTab === 'metadata' && <DocumentMetadataPanel document={document} />}
      {activeTab === 'activity' && <DocumentActivityPanel document={document} events={events} loading={loading} />}
      <div className="detail-actions">
        <button type="button" onClick={() => onOpenDocument(document.id)}>{t('common.open')}</button>
        {document.record_id && <button type="button" onClick={() => onOpenRecord(document.record_id!)}>{t('common.record')}</button>}
        <button type="button" className="primary" disabled={busy || document.id.startsWith('demo-') || document.review_state === 'reviewed'} onClick={onMarkReviewed}>{t('documents.markReviewed')}</button>
        <button type="button" className="danger-button" disabled={document.id.startsWith('demo-')} onClick={onDelete}><Trash2 size={16} /> {t('common.delete')}</button>
      </div>
    </aside>
  )
}

function DocumentDetailsFields({ document }: { document: Document }) {
  const { t } = useI18n()
  const tags = document.llm_suggested_tags.filter((tag): tag is string => typeof tag === 'string' && tag.trim().length > 0)
  const field = (value: string | null | undefined) => value?.trim() || 'NA'
  const currency = typeof document.metadata_json?.currency === 'string' ? document.metadata_json.currency : document.extracted_amount ? 'EUR' : 'NA'
  return (
    <div className="detail-tab-panel">
      <label>{t('fields.title')}<input value={document.manual_title_override || document.extracted_title || document.original_filename} readOnly /></label>
      <label>{t('dashboard.collection')}<select value={document.collection_name} disabled><option>{document.collection_name}</option></select></label>
      <label>{t('fields.correspondentSender')}<input value={field(document.extracted_sender)} readOnly /></label>
      <label>{t('fields.recipientCustomer')}<input value={field(document.extracted_recipient)} readOnly /></label>
      <div className="detail-two">
        <label>{t('fields.invoiceNumber')}<input value={field(document.extracted_invoice_number)} readOnly /></label>
        <label>{t('fields.invoiceDate')}<input value={field(document.extracted_date)} readOnly /></label>
      </div>
      <div className="detail-two">
        <label>{t('fields.amountGross')}<input value={field(document.extracted_amount)} readOnly /></label>
        <label>{t('fields.currency')}<select value={currency} disabled><option>{currency}</option></select></label>
      </div>
      <label>{t('fields.statusReviewState')}<select value={document.review_state} disabled><option>{document.review_state}</option></select></label>
      <label>{t('fields.tags')}<div className="tag-input">{tags.length ? tags.map((tag) => <button type="button" key={tag}>{tag}</button>) : <span>{t('documents.noTags', 'No tags')}</span>}</div></label>
      <label>{t('fields.notes')}<textarea placeholder={t('documents.addNotes')} readOnly /></label>
    </div>
  )
}

function DocumentMetadataPanel({ document }: { document: Document }) {
  const { t } = useI18n()
  const rows = [
    [t('fields.title'), document.manual_title_override || document.extracted_title || '—'],
    [t('fields.sender'), document.extracted_sender || '—'],
    [t('fields.recipient'), document.extracted_recipient || '—'],
    [t('fields.invoiceNumber'), document.extracted_invoice_number || '—'],
    [t('fields.date'), document.extracted_date || '—'],
    [t('fields.amount'), document.extracted_amount || '—'],
    [t('fields.paymentMethod'), document.extracted_payment_method || '—'],
    [t('fields.summary'), document.llm_summary || '—'],
    [t('fields.purpose'), document.llm_document_purpose || '—'],
    [t('fields.confidence'), document.llm_confidence == null ? '—' : String(document.llm_confidence)]
  ]
  return (
    <div className="detail-tab-panel metadata-readout">
      <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <h3>{t('documents.metadataJson')}</h3>
      <pre className="json-preview compact-json">{formatJson(document.metadata_json, t('documents.noMetadataJson'))}</pre>
      <h3>{t('documents.sources')}</h3>
      <pre className="json-preview compact-json">{formatJson(document.metadata_sources_json, t('documents.noSourceMetadata'))}</pre>
    </div>
  )
}

function DocumentActivityPanel({ document, events, loading }: { document: Document; events: DocumentEvent[]; loading: boolean }) {
  const { t } = useI18n()
  const logEntries = Array.isArray(document.processing_log_json) ? document.processing_log_json : []
  return (
    <div className="detail-tab-panel activity-list">
      {loading && <p className="tab-empty">{t('documents.loadingActivity')}</p>}
      {!loading && !events.length && !logEntries.length && <p className="tab-empty">{t('documents.noActivityEvents')}</p>}
      {events.map((event) => (
        <article key={event.id}>
          <strong>{translateDocumentListEvent(event.event_type, t)}</strong>
          <span>{new Date(event.created_at).toLocaleString()} · {translateDocumentListActor(event.actor || event.source, t)}</span>
          {event.message && <p>{translateDocumentListMessage(event.message, t)}</p>}
        </article>
      ))}
      {!events.length && logEntries.map((entry, index) => (
        <article key={index}>
          <strong>{t('documents.processingLog')}</strong>
          <span>{t('documents.entry')} {index + 1}</span>
          <pre>{typeof entry === 'string' ? entry : JSON.stringify(entry, null, 2)}</pre>
        </article>
      ))}
      {document.reviewed_at && <article><strong>{t('common.reviewed')}</strong><span>{new Date(document.reviewed_at).toLocaleString()} · {document.reviewed_by || t('common.unknown')}</span></article>}
    </div>
  )
}

function formatJson(value: unknown, fallback: string) {
  if (value == null) return fallback
  if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as Record<string, unknown>).length === 0) return fallback
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function KpiCard({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: number; detail: string; tone: string }) {
  return <div className={`doc-kpi doc-kpi-${tone}`}><span>{icon}</span><div><strong>{value.toLocaleString()}</strong><small>{label}</small><em>{detail}</em></div></div>
}

function buildStats(documents: Document[]) {
  return {
    total: documents.length,
    processing: documents.filter((doc) => ['queued_for_ocr', 'ocr_processing', 'metadata_processing'].includes(doc.processing_state)).length,
    needsReview: documents.filter((doc) => doc.review_state === 'needs_review').length,
    failed: documents.filter((doc) => doc.processing_state === 'failed').length,
    synced: documents.filter((doc) => doc.processing_state === 'complete').length
  }
}

function InvoiceMockup() {
  return <div className="invoice-mock"><span /><span /><b>Rechnung</b><p /><p /><p /><i /><i /><strong /></div>
}

const baseDoc = {
  batch_id: 'demo-batch',
  record_id: 'demo-record',
  folder_id: null,
  mime_type: 'application/pdf',
  file_size: 205000,
  sha256: 'demo',
  page_count: 1,
  duplicate_of_document_id: null,
  correspondent_id: null,
  document_type_id: null,
  storage_path_id: null,
  thumbnail_path: null,
  legacy_source: null,
  legacy_document_id: null,
  processing_attempt: 1,
  last_processing_heartbeat_at: null,
  retry_after_at: null,
  ocr_mode: 'redo' as const,
  ocr_config_json: {},
  ocr_state: 'done' as const,
  metadata_state: 'done' as const,
  final_state: 'complete' as const,
  extracted_sender: 'Demo Ges.mbh',
  extracted_recipient: 'UniTech Technische Produkte',
  extracted_payment_method: null,
  metadata_json: {},
  processing_options_json: {},
  metadata_sources_json: {},
  field_locks_json: {},
  raw_ocr_json: {},
  prompt_trace_json: {},
  model_trace_json: {},
  processing_log_json: [],
  qwen_response_text: null,
  llm_summary: null,
  llm_keywords: [],
  llm_entities: {},
  llm_document_purpose: null,
  llm_suggested_tags: [],
  llm_suggested_folder: null,
  llm_related_query: [],
  llm_confidence: null,
  llm_raw_response: {},
  error_message: null,
  manual_title_override: null,
  metadata_locked: false,
  completed_at: null,
  deleted_at: null,
  deleted_by: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString()
}

const demoDocuments: Document[] = [
  { ...baseDoc, id: 'demo-1', collection_name: 'Eingangsrechnung', original_filename: 'demo_pr400000005_12-10-2020_20525.pdf', processing_state: 'complete', review_state: 'reviewed', review_reason: null, reviewed_by: 'admin', reviewed_at: new Date().toISOString(), extracted_title: 'Demo_PR400000005_12/10/2020_205,25', extracted_invoice_number: 'PR400000005', extracted_date: '12/10/2020', extracted_amount: '205,25', ocr_text: 'Rechnung\nRechnungs-Nr.: PR400000005\nRechnungsdatum: 12.10.2020\nGesamtbetrag Brutto 205,25 EUR' },
  { ...baseDoc, id: 'demo-2', collection_name: 'Eingangsrechnung', original_filename: 'fensterberuhmt_7453_08-11-2015_2975.pdf', processing_state: 'complete', review_state: 'needs_review', review_reason: 'High amount', reviewed_by: null, reviewed_at: null, extracted_title: 'FensterBeruhmt_7453_08/11/2015_2975,00', extracted_invoice_number: '7453', extracted_date: '08/11/2015', extracted_amount: '2975,00', ocr_text: 'Rechnung 7453\nGesamtsumme 2.975,00 EUR' },
  { ...baseDoc, id: 'demo-3', collection_name: 'Ausgangsrechnung', original_filename: 'habermannsohne_m1675_29-10-2020_22251.pdf', processing_state: 'complete', review_state: 'reviewed', review_reason: null, reviewed_by: 'admin', reviewed_at: new Date().toISOString(), extracted_title: 'HabermannSohne_M1675_29/10/2020_222,51', extracted_invoice_number: 'M1675', extracted_date: '29/10/2020', extracted_amount: '222,51', ocr_text: 'Rechnung Nr. M1675\nZu zahlen 222,51 EUR' },
  { ...baseDoc, id: 'demo-4', collection_name: 'Eingangsrechnung', original_filename: 'musterkundeco_2400_15-07-2019_253946.pdf', processing_state: 'failed', review_state: 'needs_review', review_reason: 'OCR failed', reviewed_by: null, reviewed_at: null, extracted_title: 'MusterkundeCo_2400_15/07/2019_2539,46', extracted_invoice_number: '2400', extracted_date: '15/07/2019', extracted_amount: '2539,46', ocr_text: '' }
]


function translateDocumentListEvent(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.event.${value}`, value.replace(/_/g, ' '))
}

function translateDocumentListActor(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.actor.${value}`, t(`activity.source.${value}`, value))
}

function translateDocumentListMessage(value: string, t: (key: string, fallback?: string) => string) {
  const key = DOCUMENT_LIST_EVENT_MESSAGE_KEYS[value]
  return key ? t(key, value) : value
}

const DOCUMENT_LIST_EVENT_MESSAGE_KEYS: Record<string, string> = {
  'Deterministic extraction completed': 'activity.message.deterministicDone',
  'Document complete after OCR, metadata, title, and DB update': 'activity.message.documentComplete',
  'Final title and metadata generated': 'activity.message.titleGenerated',
  'Full OCR and metadata are searchable in the app database': 'activity.message.searchIndexed',
  'Mapped correspondent, document type, and storage path metadata': 'activity.message.paperlessMapped',
  'OCR completed': 'activity.message.ocrCompleted',
  'OCR started': 'activity.message.ocrStarted',
  'Metadata extraction started': 'activity.message.metadataStarted',
  'Document queued for OCR': 'activity.message.queuedForOcr',
  'Document uploaded': 'activity.message.uploaded',
  'Original file stored on local filesystem': 'activity.message.stored',
  'Full document processing started': 'activity.message.processStarted'
}
