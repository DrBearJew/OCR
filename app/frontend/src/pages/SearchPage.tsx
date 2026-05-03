import { FormEvent, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { SearchResult } from '../types'

export default function SearchPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [collection, setCollection] = useState('')
  const [status, setStatus] = useState('')
  const [filename, setFilename] = useState('')
  const [title, setTitle] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [customField, setCustomField] = useState('')
  const [customValue, setCustomValue] = useState('')
  const [correspondentId, setCorrespondentId] = useState('')
  const [documentTypeId, setDocumentTypeId] = useState('')
  const [tagId, setTagId] = useState('')
  const [storagePathId, setStoragePathId] = useState('')
  const [ocrMode, setOcrMode] = useState('')
  const [reviewState, setReviewState] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      setResults(await api.search({ q: query, collection, status, filename, title, dateFrom, dateTo, customField, customValue, correspondentId, documentTypeId, tagId, storagePathId, ocrMode, reviewState }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed')
    }
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>Search</h1>
          <p>Full-text search across OCR text stored in PostgreSQL.</p>
        </div>
      </header>
      <SavedViewsBar section="search" filters={{ query, collection, status, filename, title, dateFrom, dateTo, customField, customValue, correspondentId, documentTypeId, tagId, storagePathId, ocrMode, reviewState }} onApply={(filters) => {
        setQuery(filters.query || '')
        setCollection(filters.collection || '')
        setStatus(filters.status || '')
        setFilename(filters.filename || '')
        setTitle(filters.title || '')
        setDateFrom(filters.dateFrom || '')
        setDateTo(filters.dateTo || '')
        setCustomField(filters.customField || '')
        setCustomValue(filters.customValue || '')
        setCorrespondentId(filters.correspondentId || '')
        setDocumentTypeId(filters.documentTypeId || '')
        setTagId(filters.tagId || '')
        setStoragePathId(filters.storagePathId || '')
        setOcrMode(filters.ocrMode || '')
        setReviewState(filters.reviewState || '')
      }} />
      <form className="search-band" onSubmit={submit}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search OCR text" />
        <select value={collection} onChange={(event) => setCollection(event.target.value)}>
          <option value="">All collections</option>
          <option>Belege</option>
          <option>Eingangsrechnung</option>
          <option>Ausgangsrechnung</option>
        </select>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">Any status</option>
          <option value="complete">Complete</option>
          <option value="failed">Failed</option>
          <option value="duplicate">Duplicate</option>
          <option value="ocr_done">OCR done</option>
        </select>
        <input value={filename} onChange={(event) => setFilename(event.target.value)} placeholder="Filename filter" />
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title filter" />
        <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
        <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
        <input value={customField} onChange={(event) => setCustomField(event.target.value)} placeholder="Custom field slug" />
        <input value={customValue} onChange={(event) => setCustomValue(event.target.value)} placeholder="Custom value" />
        <input value={correspondentId} onChange={(event) => setCorrespondentId(event.target.value)} placeholder="Correspondent ID" />
        <input value={documentTypeId} onChange={(event) => setDocumentTypeId(event.target.value)} placeholder="Document type ID" />
        <input value={tagId} onChange={(event) => setTagId(event.target.value)} placeholder="Tag ID" />
        <input value={storagePathId} onChange={(event) => setStoragePathId(event.target.value)} placeholder="Storage path ID" />
        <select value={ocrMode} onChange={(event) => setOcrMode(event.target.value)}>
          <option value="">Any OCR mode</option>
          <option value="skip">skip</option>
          <option value="redo">redo</option>
          <option value="force">force</option>
        </select>
        <select value={reviewState} onChange={(event) => setReviewState(event.target.value)}>
          <option value="">Any review</option>
          <option value="unreviewed">unreviewed</option>
          <option value="needs_review">needs review</option>
          <option value="reviewed">reviewed</option>
        </select>
        <button className="primary"><Search size={18} /> Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="results">
        {results.map((result) => (
          <button key={result.document_id} onClick={() => onOpenDocument(result.document_id)}>
            <div>
              <strong>{result.extracted_title || result.original_filename}</strong>
              <span>{result.collection_name} · {result.record_title || 'Record'} · {new Date(result.created_at).toLocaleDateString()}</span>
            </div>
            <StatusBadge value={result.status} />
            <p><HighlightedSnippet snippet={result.snippet} /></p>
          </button>
        ))}
      </div>
    </main>
  )
}

function HighlightedSnippet({ snippet }: { snippet: string }) {
  const parts = snippet.split(/(<mark>|<\/mark>)/g)
  let highlighted = false
  return (
    <>
      {parts.map((part, index) => {
        if (part === '<mark>') {
          highlighted = true
          return null
        }
        if (part === '</mark>') {
          highlighted = false
          return null
        }
        return highlighted ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>
      })}
    </>
  )
}
