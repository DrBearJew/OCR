import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { Document, FailedReviewSummary } from '../types'

export default function FailedReviewPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const [data, setData] = useState<FailedReviewSummary | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setData(await api.failedReview())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load failed/review queue')
    }
  }

  useEffect(() => { void load() }, [])
  const docs = [...(data?.failed_documents || []), ...(data?.needs_review_documents || []), ...(data?.missing_required_documents || [])]
    .filter((doc, index, rows) => rows.findIndex((item) => item.id === doc.id) === index)
    .filter((doc) => !filters.collection_name || doc.collection_name === filters.collection_name)

  async function mark(document: Document, reviewState: string) {
    await api.patchDocument(document.id, { review_state: reviewState, review_reason: reviewState === 'reviewed' ? null : 'Manual review requested' } as Partial<Document>)
    await load()
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>Failed / Needs Review</h1>
          <p>Documents that need operator attention before they disappear into the archive.</p>
        </div>
        <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <SavedViewsBar section="failed" filters={filters} onApply={setFilters} />
      <div className="filter-row">
        <input placeholder="Collection" value={filters.collection_name || ''} onChange={(event) => setFilters({ ...filters, collection_name: event.target.value })} />
      </div>
      <section className="admin-list">
        {docs.map((document) => (
          <div className="admin-row" key={document.id}>
            <button onClick={() => onOpenDocument(document.id)}><strong>{document.extracted_title || document.original_filename}</strong><span>{document.error_message || document.review_reason || document.collection_name}</span></button>
            <StatusBadge value={document.processing_state === 'failed' ? 'failed' : document.review_state} />
            <span>{document.original_filename}</span>
            <div className="button-row">
              <button onClick={async () => { await api.retryDocument(document.id); await load() }}>Retry</button>
              <button onClick={async () => { await api.reextractDocument(document.id, false); await load() }}>Re-extract</button>
              <button onClick={() => void mark(document, 'reviewed')}>Reviewed</button>
              <button onClick={() => void mark(document, 'needs_review')}>Flag</button>
            </div>
          </div>
        ))}
      </section>
    </main>
  )
}
