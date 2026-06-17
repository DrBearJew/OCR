import { useEffect, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'
import { FileText, RefreshCw, Search, Settings2 } from 'lucide-react'
import { api, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { CollectionPageData, Document, RecordRow } from '../types'
import { useI18n } from '../i18n'

const COLLECTION_RECORD_PAGE_LIMIT = 50

export default function CollectionDetailPage({ slug, onOpenRecord, onOpenDocument }: { slug: string; onOpenRecord: (id: string) => void; onOpenDocument: (id: string) => void }) {
  const { t, language } = useI18n()
  const [data, setData] = useState<CollectionPageData | null>(null)
  const [records, setRecords] = useState<RecordRow[]>([])
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  async function loadCollection() {
    setError('')
    try {
      setData(await api.collectionPage(slug))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load collection')
    }
  }

  async function loadRecords(append = false, cursor: string | null = null, nextStatus = status, nextQuery = query) {
    setError('')
    if (append) setLoadingMore(true)
    try {
      const params: Record<string, string> = { collection_slug: slug, limit: String(COLLECTION_RECORD_PAGE_LIMIT) }
      if (nextStatus) params.status_filter = nextStatus
      if (nextQuery.trim()) params.q = nextQuery.trim()
      if (cursor) params.cursor = cursor
      const page = await api.recordsPage(params)
      setRecords((current) => append ? [...current, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load collection records')
    } finally {
      if (append) setLoadingMore(false)
    }
  }

  async function refresh() {
    await Promise.all([loadCollection(), loadRecords(false, null)])
  }

  function loadMoreCollectionRecords() {
    if (!nextCursor || loadingMore) return
    void loadRecords(true, nextCursor)
  }

  useEffect(() => {
    setRecords([])
    setNextCursor(null)
    setTotalEstimate(0)
    void refresh()
  }, [slug])

  useEffect(() => {
    void loadRecords(false, null, status, query)
  }, [status, query])

  const totalDocs = records.reduce((sum, record) => sum + record.document_count, 0)

  return (
    <main className="collection-detail-console">
      <header className="page-header console-header">
        <div>
          <h1>{data?.collection.name || slug}</h1>
          <p>{t('collectionDetail.subtitle')}</p>
        </div>
        <div className="button-row">
          <button><Settings2 size={17} /> Schema</button>
          <button className="icon-button" title={t('common.refresh')} onClick={() => void refresh()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="collection-detail-hero workflow-card">
        <div>
          <span className="eyebrow">{t('dashboard.collection')}</span>
          <h2>{data?.collection.name || slug}</h2>
          <p>{records.length} / {totalEstimate} {t('common.records')} · {totalDocs} {t('common.documents')}</p>
        </div>
        <div className="collection-detail-stats">
          <span><strong>{totalEstimate}</strong> {t('common.records')}</span>
          <span><strong>{totalDocs}</strong> {t('common.documents')}</span>
          <span><strong>{data?.status_counts.needs_review || 0}</strong> {t('common.needsReview')}</span>
          <span><strong>{data?.status_counts.complete || 0}</strong> {t('common.complete')}</span>
        </div>
      </section>
      <section className="workflow-card collection-record-panel">
        <div className="document-toolbar collection-detail-toolbar">
          <label className="toolbar-search">
            <Search size={17} />
            <input placeholder={t('collectionDetail.searchPlaceholder')} value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">{t('search.anyStatus')}</option>
            <option value="pending">{t('status.pending')}</option>
            <option value="processing">{t('status.processing')}</option>
            <option value="partially_failed">{t('status.partially_failed')}</option>
            <option value="complete">{t('status.complete')}</option>
            <option value="needs_review">{t('status.needs_review')}</option>
          </select>
          <SavedViewsBar section="collections" filters={{ status, query }} onApply={(filters) => { setStatus(filters.status || ''); setQuery(filters.query || '') }} />
        </div>
        <div className="collection-record-list">
          {records.map((record) => <CollectionRecordCard key={record.id} record={record} onOpenRecord={onOpenRecord} onOpenDocument={onOpenDocument} />)}
          {!records.length && <p className="muted-empty">{t('records.noMatches')}</p>}
        </div>
        {nextCursor && (
          <div className="pagination-footer">
            <span>{records.length} / {totalEstimate} {t('common.records')}</span>
            <button onClick={loadMoreCollectionRecords} disabled={loadingMore}>{loadingMore ? t('common.loading') : t('common.loadMore')}</button>
          </div>
        )}
      </section>
    </main>
  )
}

function CollectionRecordCard({ record, onOpenRecord, onOpenDocument }: { record: RecordRow; onOpenRecord: (id: string) => void; onOpenDocument: (id: string) => void }) {
  const { t, language } = useI18n()
  const firstDoc = record.documents[0]
  return (
    <div
      className="collection-record-card"
      role="button"
      tabIndex={0}
      onClick={() => onOpenRecord(record.id)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpenRecord(record.id)
        }
      }}
    >
      <div className="record-main-meta">
        <span className="record-type-icon"><FileText size={18} /></span>
        <div>
          <strong>{record.title}</strong>
          <span>{record.document_count} {record.document_count === 1 ? t('records.documentSingular') : t('records.documentPlural')} · {t('records.updated')} {new Date(record.updated_at).toLocaleString(language === 'de' ? 'de-DE' : undefined)}</span>
          <small>{firstDoc?.extracted_invoice_number || firstDoc?.extracted_amount || firstDoc?.original_filename || t('records.noMetadataYet')}</small>
        </div>
      </div>
      <div className="thumb-strip" onClick={(event) => event.stopPropagation()}>
        {record.documents.slice(0, 6).map((document) => <CollectionDocThumb key={document.id} document={document} onOpenDocument={onOpenDocument} />)}
        {record.documents.length > 6 && <span className="count-badge">+{record.documents.length - 6}</span>}
      </div>
      <StatusBadge value={record.status} />
    </div>
  )
}

function CollectionDocThumb({ document, onOpenDocument }: { document: Document; onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  function open(event: MouseEvent | KeyboardEvent) {
    event.stopPropagation()
    onOpenDocument(document.id)
  }

  return (
    <span
      className="record-thumb"
      role="button"
      tabIndex={0}
      title={`${t('common.open')} ${document.original_filename}`}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          open(event)
        }
      }}
    >
      {document.thumbnail_path ? <img src={thumbnailUrl(document.id)} alt="" /> : <span className="file-icon">{document.original_filename.split('.').pop()?.toUpperCase() || 'DOC'}</span>}
      <span className={`status-dot dot-${document.processing_state}`} />
      <span className="hover-preview">
        {document.thumbnail_path && <img src={document.mime_type?.startsWith('image/') ? previewUrl(document.id) : thumbnailUrl(document.id)} alt="" />}
        <strong>{document.original_filename}</strong>
        <em>{t(`status.${document.processing_state}`, document.processing_state)}</em>
        <span>{document.extracted_title || t('records.noTitleYet')}</span>
        <small>{document.extracted_invoice_number || document.extracted_payment_method || ''} {document.extracted_amount || ''}</small>
        <p>{(document.ocr_text || '').slice(0, 220)}</p>
      </span>
    </span>
  )
}
