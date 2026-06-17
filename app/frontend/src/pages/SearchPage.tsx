import { FormEvent, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { SearchResult } from '../types'
import { useI18n } from '../i18n'

const SEARCH_PAGE_LIMIT = 25

export default function SearchPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
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
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  function currentSearchParams(cursor: string | null = null) {
    return {
      q: query,
      collection,
      status,
      filename,
      title,
      dateFrom,
      dateTo,
      customField,
      customValue,
      correspondentId,
      documentTypeId,
      tagId,
      storagePathId,
      ocrMode,
      reviewState,
      limit: String(SEARCH_PAGE_LIMIT),
      ...(cursor ? { cursor } : {}),
    }
  }

  async function runSearch(append = false, cursor: string | null = null) {
    setError('')
    if (append) setLoadingMore(true)
    try {
      const page = await api.searchPage(currentSearchParams(cursor))
      setResults((current) => append ? [...current, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('search.failed'))
    } finally {
      if (append) setLoadingMore(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    await runSearch(false, null)
  }

  function loadMoreSearchResults() {
    if (!nextCursor || loadingMore) return
    void runSearch(true, nextCursor)
  }

  return (
    <main className="search-console">
      <header className="page-header">
        <div>
          <h1>{t('search.title')}</h1>
          <p>{t('search.subtitle')}</p>
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
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('search.ocrPlaceholder')} />
        <select value={collection} onChange={(event) => setCollection(event.target.value)}>
          <option value="">{t('search.allCollections')}</option>
          <option>Belege</option>
          <option>Eingangsrechnung</option>
          <option>Ausgangsrechnung</option>
        </select>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">{t('search.anyStatus')}</option>
          <option value="complete">{t('common.complete')}</option>
          <option value="failed">{t('common.failed')}</option>
          <option value="duplicate">{t('common.duplicate')}</option>
          <option value="ocr_done">{t('common.ocrDone')}</option>
        </select>
        <input value={filename} onChange={(event) => setFilename(event.target.value)} placeholder={t('search.filenameFilter')} />
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('search.titleFilter')} />
        <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
        <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
        <input value={customField} onChange={(event) => setCustomField(event.target.value)} placeholder={t('search.customField')} />
        <input value={customValue} onChange={(event) => setCustomValue(event.target.value)} placeholder={t('search.customValue')} />
        <input value={correspondentId} onChange={(event) => setCorrespondentId(event.target.value)} placeholder={t('search.correspondentId')} />
        <input value={documentTypeId} onChange={(event) => setDocumentTypeId(event.target.value)} placeholder={t('search.documentTypeId')} />
        <input value={tagId} onChange={(event) => setTagId(event.target.value)} placeholder={t('search.tagId')} />
        <input value={storagePathId} onChange={(event) => setStoragePathId(event.target.value)} placeholder={t('search.storagePathId')} />
        <select value={ocrMode} onChange={(event) => setOcrMode(event.target.value)}>
          <option value="">{t('search.anyOcrMode')}</option>
          <option value="skip">{t('search.ocrSkip')}</option>
          <option value="redo">{t('search.ocrRedo')}</option>
          <option value="force">{t('search.ocrForce')}</option>
        </select>
        <select value={reviewState} onChange={(event) => setReviewState(event.target.value)}>
          <option value="">{t('search.anyReview')}</option>
          <option value="unreviewed">{t('search.unreviewed')}</option>
          <option value="needs_review">{t('search.needsReview')}</option>
          <option value="reviewed">{t('search.reviewed')}</option>
        </select>
        <button className="primary"><Search size={18} /> {t('common.search')}</button>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="results">
        {results.map((result) => (
          <button key={result.document_id} onClick={() => onOpenDocument(result.document_id)}>
            <div>
              <strong>{result.extracted_title || result.original_filename}</strong>
              <span>{result.collection_name} · {result.record_title || t('common.record')} · {new Date(result.created_at).toLocaleDateString()}</span>
            </div>
            <StatusBadge value={result.status} />
            <p><HighlightedSnippet snippet={result.snippet} /></p>
          </button>
        ))}
      </div>
      {nextCursor && (
        <div className="pagination-footer">
          <span>{results.length} / {totalEstimate} {t('common.documents')}</span>
          <button onClick={loadMoreSearchResults} disabled={loadingMore}>{loadingMore ? t('common.loading') : t('common.loadMore')}</button>
        </div>
      )}
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
