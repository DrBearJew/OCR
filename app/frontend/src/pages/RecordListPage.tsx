import { FormEvent, useEffect, useState } from 'react'
import { FileText, Layers3, RefreshCw, Search, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { api, previewPageUrl, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { Document, RecordRow } from '../types'
import { useI18n } from '../i18n'

const RECORD_PAGE_LIMIT = 50

const collections = ['Belege', 'Eingangsrechnung', 'Ausgangsrechnung', 'Dokumente']

function documentHoverPreviewUrl(document: Document): string | null {
  if (document.mime_type === 'application/pdf') return previewPageUrl(document.id, 1)
  if (document.mime_type?.startsWith('image/')) return previewUrl(document.id)
  return document.thumbnail_path ? thumbnailUrl(document.id) : null
}

function Thumb({ document }: { document: Document }) {
  const { t } = useI18n()
  const previewSource = documentHoverPreviewUrl(document)
  return (
    <span className="record-thumb" aria-label={`${t('records.childDocument')}: ${document.original_filename}`}>
      {document.thumbnail_path ? <img src={thumbnailUrl(document.id)} alt="" /> : <span className="file-icon">{document.original_filename.split('.').pop()?.toUpperCase() || 'DOC'}</span>}
      <span className={`status-dot dot-${document.processing_state}`} />
      <span className="hover-preview high-res-document-preview">
        {previewSource && <img src={previewSource} alt="" />}
        <strong>{document.original_filename}</strong>
        <em>{t('records.childDocument')} · {document.processing_state}</em>
        <span>{document.extracted_title || t('records.noTitleYet')}</span>
        <small>{document.extracted_invoice_number || document.extracted_payment_method || ''} {document.extracted_amount || ''}</small>
        <p>{(document.ocr_text || '').slice(0, 220)}</p>
      </span>
    </span>
  )
}

export default function RecordListPage({ onOpenRecord }: { onOpenRecord: (id: string) => void }) {
  const { t, language } = useI18n()
  const [records, setRecords] = useState<RecordRow[]>([])
  const [collection, setCollection] = useState(collections[0])
  const [label, setLabel] = useState('')
  const [files, setFiles] = useState<FileList | null>(null)
  const [busy, setBusy] = useState(false)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const visibleRecords = records
  const stats = {
    total: totalEstimate || records.length,
    documents: records.reduce((sum, record) => sum + record.document_count, 0),
    processing: records.filter((record) => record.status === 'processing').length,
    needsReview: records.filter((record) => record.status === 'needs_review' || record.status === 'partially_failed').length
  }

  function pageParams(nextFilters = filters, cursor: string | null = null) {
    const params: Record<string, string> = { limit: String(RECORD_PAGE_LIMIT) }
    if (nextFilters.query) params.q = nextFilters.query
    if (nextFilters.collection) params.collection = nextFilters.collection
    if (nextFilters.status) params.status_filter = nextFilters.status
    if (cursor) params.cursor = cursor
    return params
  }

  async function load(nextFilters = filters, append = false, cursor: string | null = null) {
    setError('')
    try {
      const page = await api.recordsPage(pageParams(nextFilters, cursor))
      setRecords((current) => append ? [...current, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('records.loadError'))
    }
  }

  async function loadMoreRecords() {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      await load(filters, true, nextCursor)
    } finally {
      setLoadingMore(false)
    }
  }

  function updateFilter(key: string, value: string) {
    const next = { ...filters, [key]: value }
    if (!value) delete next[key]
    setFilters(next)
    void load(next, false, null)
  }

  useEffect(() => { void load() }, [])

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!files?.length) return
    setBusy(true)
    setError('')
    const form = new FormData()
    form.set('collection_name', collection)
    if (label.trim()) form.set('label', label.trim())
    Array.from(files).forEach((file) => form.append('files', file))
    try {
      const created = await api.uploadBatch(form)
      setLabel('')
      setFiles(null)
      const page = await api.recordsPage({ limit: String(RECORD_PAGE_LIMIT) })
      setRecords(page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
      const newest = page.items.find((record) => record.documents.some((doc) => doc.batch_id === created.id))
      if (newest) onOpenRecord(newest.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.uploadFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="records-console">
      <header className="page-header console-header">
        <div>
          <h1>{t('records.title')}</h1>
          <p>{t('records.subtitle')}</p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      <section className="records-summary-grid">
        <RecordSummary icon={<Layers3 size={23} />} label={t('nav.records')} value={stats.total} detail={t('records.parentObjects')} />
        <RecordSummary icon={<FileText size={23} />} label={t('nav.documents')} value={stats.documents} detail={t('records.attachedOcrUnits')} />
        <RecordSummary icon={<RefreshCw size={23} />} label={t('nav.processing')} value={stats.processing} detail={t('records.activeRecords')} tone="blue" />
        <RecordSummary icon={<FileText size={23} />} label={t('common.review')} value={stats.needsReview} detail={t('records.needsAttention')} tone="orange" />
      </section>
      <section className="workflow-card record-workflow-panel">
        <form className="upload-band record-upload-band" onSubmit={upload}>
          <select value={collection} onChange={(event) => setCollection(event.target.value)}>
            {collections.map((item) => <option key={item}>{item}</option>)}
          </select>
          <input placeholder={t('records.titlePlaceholder')} value={label} onChange={(event) => setLabel(event.target.value)} />
          <input type="file" multiple onChange={(event) => setFiles(event.target.files)} />
          <button className="primary" disabled={busy || !files?.length}><Upload size={18} /> {t('common.upload')}</button>
        </form>
      </section>
      {error && <p className="error">{error}</p>}
      <section className="workflow-card record-browser-panel">
        <div className="document-toolbar record-toolbar">
          <label className="toolbar-search">
            <Search size={17} />
            <input placeholder={t('records.searchPlaceholder')} value={filters.query || ''} onChange={(event) => updateFilter('query', event.target.value)} />
          </label>
          <input placeholder={t('common.collection')} value={filters.collection || ''} onChange={(event) => updateFilter('collection', event.target.value)} />
          <select value={filters.status || ''} onChange={(event) => updateFilter('status', event.target.value)}>
            <option value="">{t('search.anyStatus')}</option>
            <option value="pending">{t('status.pending')}</option>
            <option value="processing">{t('status.processing')}</option>
            <option value="partially_failed">{t('status.partially_failed')}</option>
            <option value="complete">{t('status.complete')}</option>
            <option value="needs_review">{t('status.needs_review')}</option>
          </select>
          <SavedViewsBar section="records" filters={filters} onApply={(next) => { setFilters(next); void load(next, false, null) }} />
        </div>
        <div className="record-list dark-record-list">
          {visibleRecords.map((record) => (
            <button className="collection-record-card record-console-row" key={record.id} onClick={() => onOpenRecord(record.id)}>
              <div className="record-main-meta">
                <span className="record-type-icon"><Layers3 size={18} /></span>
                <div>
                  <span className="record-object-label">{t('records.envelopeLabel')}</span>
                  <strong>{record.title}</strong>
                  <span>{record.collection?.name || record.collection_id} · {record.document_count} {record.document_count === 1 ? t('records.documentSingular') : t('records.documentPlural')} · {t('records.updated')} {new Date(record.updated_at).toLocaleString(language === 'de' ? 'de-DE' : undefined)}</span>
                  <small>{String(record.summary_metadata?.invoice_number || record.summary_metadata?.amount || t('records.metadataPerFile'))}</small>
                </div>
              </div>
              <div className="record-documents-cluster" onClick={(event) => event.stopPropagation()}>
                <span className="record-documents-label">{t('records.childDocuments')}</span>
                <div className="thumb-strip">
                  {record.documents.slice(0, 8).map((document) => <Thumb key={document.id} document={document} />)}
                  {record.documents.length > 8 && <span className="count-badge">+{record.documents.length - 8}</span>}
                </div>
              </div>
              <StatusBadge value={record.status} />
            </button>
          ))}
          {!visibleRecords.length && <p className="muted-empty">{t('records.noMatches')}</p>}
        </div>
        <div className="pagination-footer">
          <span>{records.length} / {totalEstimate || records.length} {t('common.records')}</span>
          {nextCursor && <button type="button" className="primary" disabled={loadingMore} onClick={() => void loadMoreRecords()}>{t('common.loadMore', 'Load more')}</button>}
        </div>
      </section>
    </main>
  )
}

function RecordSummary({ icon, label, value, detail, tone = 'green' }: { icon: ReactNode; label: string; value: number; detail: string; tone?: string }) {
  return <div className={`collection-summary-card collection-summary-${tone}`}><span>{icon}</span><div><strong>{value.toLocaleString()}</strong><small>{label}</small><em>{detail}</em></div></div>
}
