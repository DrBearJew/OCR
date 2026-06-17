import { useEffect, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'
import { FileText, RefreshCw, Search, Settings2 } from 'lucide-react'
import { api, previewPageUrl, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { CollectionPageData, Document } from '../types'
import { useI18n } from '../i18n'

const COLLECTION_DOCUMENT_PAGE_LIMIT = 50

export default function CollectionDetailPage({ slug, onOpenDocument }: { slug: string; onOpenDocument: (id: string) => void }) {
  const { t, language } = useI18n()
  const [data, setData] = useState<CollectionPageData | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  async function loadCollection(): Promise<CollectionPageData | null> {
    setError('')
    try {
      const page = await api.collectionPage(slug)
      setData(page)
      return page
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load collection')
      return null
    }
  }

  async function loadDocuments(append = false, cursor: string | null = null, nextStatus = status, nextQuery = query, collectionName = data?.collection.name) {
    if (!collectionName) return
    setError('')
    if (append) setLoadingMore(true)
    try {
      const params: Record<string, string> = { collection_name: collectionName, limit: String(COLLECTION_DOCUMENT_PAGE_LIMIT) }
      if (nextStatus === 'needs_review') params.review_state = 'needs_review'
      else if (nextStatus) params.state = nextStatus
      if (nextQuery.trim()) params.title = nextQuery.trim()
      if (cursor) params.cursor = cursor
      const page = await api.documentsPage(params)
      setDocuments((current) => append ? [...current, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load collection documents')
    } finally {
      if (append) setLoadingMore(false)
    }
  }

  async function refresh() {
    const page = await loadCollection()
    await loadDocuments(false, null, status, query, page?.collection.name)
  }

  function loadMoreCollectionDocuments() {
    if (!nextCursor || loadingMore) return
    void loadDocuments(true, nextCursor)
  }

  useEffect(() => {
    setDocuments([])
    setNextCursor(null)
    setTotalEstimate(0)
    void refresh()
  }, [slug])

  useEffect(() => {
    if (data?.collection.name) void loadDocuments(false, null, status, query, data.collection.name)
  }, [status, query])

  const needsReview = documents.filter((document) => document.review_state === 'needs_review').length || data?.status_counts.needs_review || 0
  const complete = documents.filter((document) => document.processing_state === 'complete').length || data?.status_counts.complete || 0

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
          <p>{documents.length} / {totalEstimate || documents.length} {t('common.documents')}</p>
        </div>
        <div className="collection-detail-stats">
          <span><strong>{totalEstimate || documents.length}</strong> {t('common.documents')}</span>
          <span><strong>{needsReview}</strong> {t('common.needsReview')}</span>
          <span><strong>{complete}</strong> {t('common.complete')}</span>
        </div>
      </section>
      <section className="workflow-card collection-record-panel collection-document-panel">
        <div className="document-toolbar collection-detail-toolbar">
          <label className="toolbar-search">
            <Search size={17} />
            <input placeholder={t('collectionDetail.searchPlaceholder')} value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">{t('search.anyStatus')}</option>
            <option value="complete">{t('common.complete')}</option>
            <option value="failed">{t('common.failed')}</option>
            <option value="ocr_processing">{t('common.processing')}</option>
            <option value="needs_review">{t('common.needsReview')}</option>
          </select>
          <SavedViewsBar section="collections" filters={{ status, query }} onApply={(filters) => { setStatus(filters.status || ''); setQuery(filters.query || '') }} />
        </div>
        <div className="collection-record-list collection-document-list">
          {documents.map((document) => <CollectionDocumentCard key={document.id} document={document} onOpenDocument={onOpenDocument} />)}
          {!documents.length && <p className="muted-empty">{t('documents.noMatches')}</p>}
        </div>
        {nextCursor && (
          <div className="pagination-footer">
            <span>{documents.length} / {totalEstimate} {t('common.documents')}</span>
            <button onClick={loadMoreCollectionDocuments} disabled={loadingMore}>{loadingMore ? t('common.loading') : t('common.loadMore')}</button>
          </div>
        )}
      </section>
    </main>
  )
}

function collectionDocumentHoverPreviewUrl(document: Document): string | null {
  if (document.mime_type === 'application/pdf') return previewPageUrl(document.id, 1)
  if (document.mime_type?.startsWith('image/')) return previewUrl(document.id)
  return document.thumbnail_path ? thumbnailUrl(document.id) : null
}

function CollectionDocumentCard({ document, onOpenDocument }: { document: Document; onOpenDocument: (id: string) => void }) {
  const { t, language } = useI18n()
  const previewSource = collectionDocumentHoverPreviewUrl(document)
  function open(event: MouseEvent | KeyboardEvent) {
    event.stopPropagation()
    onOpenDocument(document.id)
  }

  return (
    <div
      className="collection-record-card collection-document-card"
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          open(event)
        }
      }}
    >
      <div className="record-main-meta">
        <span className="record-type-icon"><FileText size={18} /></span>
        <div>
          <strong>{document.manual_title_override || document.extracted_title || document.original_filename}</strong>
          <span>{document.original_filename} · {new Date(document.updated_at).toLocaleString(language === 'de' ? 'de-DE' : undefined)}</span>
          <small>{document.extracted_invoice_number || document.extracted_amount || document.extracted_sender || t('documents.noMetadataYet')}</small>
        </div>
      </div>
      <span className="record-thumb collection-document-thumb" title={`${t('common.open')} ${document.original_filename}`}>
        {document.thumbnail_path ? <img src={thumbnailUrl(document.id)} alt="" /> : <span className="file-icon">{document.original_filename.split('.').pop()?.toUpperCase() || 'DOC'}</span>}
        <span className={`status-dot dot-${document.processing_state}`} />
        <span className="hover-preview high-res-document-preview">
          {previewSource && <img src={previewSource} alt="" />}
          <strong>{document.original_filename}</strong>
          <em>{t(`status.${document.processing_state}`, document.processing_state)}</em>
          <span>{document.extracted_title || t('documents.noTitleYet')}</span>
          <small>{document.extracted_invoice_number || document.extracted_payment_method || ''} {document.extracted_amount || ''}</small>
          <p>{(document.ocr_text || '').slice(0, 220)}</p>
        </span>
      </span>
      <StatusBadge value={document.review_state === 'needs_review' ? 'needs_review' : document.processing_state} />
    </div>
  )
}
