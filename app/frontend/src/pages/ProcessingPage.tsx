import { useEffect, useState } from 'react'
import { RefreshCw, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { ProcessingSummary } from '../types'

export default function ProcessingPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const [data, setData] = useState<ProcessingSummary | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setData(await api.processing())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load processing queue')
    }
  }

  useEffect(() => { void load() }, [])
  const docs = (data?.documents || []).filter((doc) => !filters.state || doc.processing_state === filters.state)

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>Processing</h1>
          <p>Queue, worker state, stuck documents, ingestion jobs, and retry controls.</p>
        </div>
        <div className="button-row">
          <button onClick={async () => { await api.reconcile(); await load() }}><RotateCcw size={18} /> Reconcile</button>
          <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      <SavedViewsBar section="processing" filters={filters} onApply={setFilters} />
      <section className="stats-grid">
        {Object.entries(data?.summary || {}).map(([key, value]) => <div className="metric" key={key}><strong>{value}</strong><span>{key.replace(/_/g, ' ')}</span></div>)}
        <div className="metric"><strong>{data?.stuck_documents.length || 0}</strong><span>stuck</span></div>
      </section>
      <div className="filter-row">
        <select value={filters.state || ''} onChange={(event) => setFilters({ ...filters, state: event.target.value })}>
          <option value="">All active states</option>
          <option value="uploaded">Uploaded</option>
          <option value="queued_for_ocr">Queued</option>
          <option value="ocr_processing">OCR running</option>
          <option value="ocr_done">OCR done</option>
          <option value="metadata_processing">Metadata running</option>
        </select>
      </div>
      <section className="admin-list">
        {docs.map((document) => (
          <div className="admin-row" key={document.id}>
            <button onClick={() => onOpenDocument(document.id)}><strong>{document.extracted_title || document.original_filename}</strong><span>{document.collection_name}</span></button>
            <StatusBadge value={document.processing_state} />
            <span>{document.updated_at ? new Date(document.updated_at).toLocaleString() : ''}</span>
            <button onClick={async () => { await api.retryDocument(document.id); await load() }}>Retry</button>
          </div>
        ))}
      </section>
      <h2>Ingestion Jobs</h2>
      <section className="admin-list">
        {(data?.ingestion_jobs || []).map((job) => <div className="admin-row" key={job.id}><strong>{job.discovered_path}</strong><StatusBadge value={job.status} /><span>{job.error_message || job.sha256 || ''}</span><button onClick={async () => { await api.retryIngestionJob(job.id); await load() }}>Retry</button></div>)}
      </section>
    </main>
  )
}
