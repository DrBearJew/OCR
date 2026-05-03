import { useEffect, useState } from 'react'
import { FileText, RefreshCw, Search, Settings2 } from 'lucide-react'
import { api } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { CollectionPageData, Document, RecordRow } from '../types'

export default function CollectionDetailPage({ slug, onOpenRecord }: { slug: string; onOpenRecord: (id: string) => void }) {
  const [data, setData] = useState<CollectionPageData | null>(null)
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setData(await api.collectionPage(slug))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load collection')
    }
  }

  useEffect(() => { void load() }, [slug])

  const records = (data?.records || []).filter((record) => {
    const matchesStatus = !status || record.status === status
    const needle = query.trim().toLowerCase()
    const matchesQuery = !needle || record.title.toLowerCase().includes(needle) || record.documents.some((document) =>
      document.original_filename.toLowerCase().includes(needle) || (document.extracted_title || '').toLowerCase().includes(needle)
    )
    return matchesStatus && matchesQuery
  })
  const totalDocs = records.reduce((sum, record) => sum + record.document_count, 0)

  return (
    <main className="collection-detail-console">
      <header className="page-header console-header">
        <div>
          <h1>{data?.collection.name || slug}</h1>
          <p>Records, status counts, and document strips for this collection.</p>
        </div>
        <div className="button-row">
          <button><Settings2 size={17} /> Schema</button>
          <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="collection-detail-hero workflow-card">
        <div>
          <span className="eyebrow">Collection</span>
          <h2>{data?.collection.name || slug}</h2>
          <p>{records.length} visible records, {totalDocs} searchable document OCR units.</p>
        </div>
        <div className="collection-detail-stats">
          <span><strong>{data?.records.length || 0}</strong> Records</span>
          <span><strong>{totalDocs}</strong> Documents</span>
          <span><strong>{data?.status_counts.needs_review || 0}</strong> Needs review</span>
          <span><strong>{data?.status_counts.complete || 0}</strong> Complete</span>
        </div>
      </section>
      <section className="workflow-card collection-record-panel">
        <div className="document-toolbar collection-detail-toolbar">
          <label className="toolbar-search">
            <Search size={17} />
            <input placeholder="Search records, filenames, titles..." value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="processing">Processing</option>
            <option value="partially_failed">Partially failed</option>
            <option value="complete">Complete</option>
            <option value="needs_review">Needs review</option>
          </select>
          <SavedViewsBar section="collections" filters={{ status, query }} onApply={(filters) => { setStatus(filters.status || ''); setQuery(filters.query || '') }} />
        </div>
        <div className="collection-record-list">
          {records.map((record) => <CollectionRecordCard key={record.id} record={record} onOpenRecord={onOpenRecord} />)}
          {!records.length && <p className="muted-empty">No records match the current filters.</p>}
        </div>
      </section>
    </main>
  )
}

function CollectionRecordCard({ record, onOpenRecord }: { record: RecordRow; onOpenRecord: (id: string) => void }) {
  const firstDoc = record.documents[0]
  return (
    <button className="collection-record-card" onClick={() => onOpenRecord(record.id)}>
      <div className="record-main-meta">
        <span className="record-type-icon"><FileText size={18} /></span>
        <div>
          <strong>{record.title}</strong>
          <span>{record.document_count} documents · updated {new Date(record.updated_at).toLocaleString()}</span>
          <small>{firstDoc?.extracted_invoice_number || firstDoc?.extracted_amount || firstDoc?.original_filename || 'No document metadata yet'}</small>
        </div>
      </div>
      <div className="thumb-strip" onClick={(event) => event.stopPropagation()}>
        {record.documents.slice(0, 6).map((document) => <CollectionDocThumb key={document.id} document={document} />)}
        {record.documents.length > 6 && <span className="count-badge">+{record.documents.length - 6}</span>}
      </div>
      <StatusBadge value={record.status} />
    </button>
  )
}

function CollectionDocThumb({ document }: { document: Document }) {
  return (
    <span className="record-thumb compact-record-thumb">
      <span className="file-icon">{document.original_filename.split('.').pop()?.toUpperCase() || 'DOC'}</span>
      <span className={`status-dot dot-${document.processing_state}`} />
      <span className="hover-preview">
        <strong>{document.original_filename}</strong>
        <em>{document.processing_state}</em>
        <span>{document.extracted_title || 'No title yet'}</span>
        <small>{document.extracted_invoice_number || document.extracted_payment_method || ''} {document.extracted_amount || ''}</small>
        <p>{(document.ocr_text || '').slice(0, 220)}</p>
      </span>
    </span>
  )
}
