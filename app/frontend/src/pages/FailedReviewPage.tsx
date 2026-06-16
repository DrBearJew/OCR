import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { Document, FailedReviewSummary } from '../types'
import { useI18n } from '../i18n'

export default function FailedReviewPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  const [data, setData] = useState<FailedReviewSummary | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setData(await api.failedReview())
    } catch (err) {
      setError(err instanceof Error ? err.message : t('failed.loadError'))
    }
  }

  useEffect(() => { void load() }, [])
  const docs = [...(data?.failed_documents || []), ...(data?.needs_review_documents || []), ...(data?.missing_required_documents || [])]
    .filter((doc, index, rows) => rows.findIndex((item) => item.id === doc.id) === index)
    .filter((doc) => !filters.collection_name || doc.collection_name === filters.collection_name)

  async function mark(document: Document, reviewState: string) {
    await api.patchDocument(document.id, { review_state: reviewState, review_reason: reviewState === 'reviewed' ? null : t('failed.manualReviewRequested') } as Partial<Document>)
    await load()
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{t('failed.title')}</h1>
          <p>{t('failed.subtitle')}</p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <SavedViewsBar section="failed" filters={filters} onApply={setFilters} />
      <div className="filter-row">
        <input placeholder={t('common.collection')} value={filters.collection_name || ''} onChange={(event) => setFilters({ ...filters, collection_name: event.target.value })} />
      </div>
      <section className="admin-list">
        {docs.map((document) => (
          <div className="admin-row" key={document.id}>
            <button onClick={() => onOpenDocument(document.id)}><strong>{document.extracted_title || document.original_filename}</strong><span>{document.error_message || document.review_reason || document.collection_name}</span></button>
            <StatusBadge value={document.processing_state === 'failed' ? 'failed' : document.review_state} />
            <span>{document.original_filename}</span>
            <div className="button-row">
              <button onClick={async () => { await api.retryDocument(document.id); await load() }}>{t('common.retry')}</button>
              <button onClick={async () => { await api.reextractDocument(document.id, false); await load() }}>{t('common.reextract')}</button>
              <button onClick={() => void mark(document, 'reviewed')}>{t('common.reviewed')}</button>
              <button onClick={() => void mark(document, 'needs_review')}>{t('common.flag')}</button>
            </div>
          </div>
        ))}
      </section>
    </main>
  )
}
