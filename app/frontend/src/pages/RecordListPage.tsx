import { FormEvent, useEffect, useState } from 'react'
import { FileText, Layers3, RefreshCw, Search, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { api, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { Document, RecordRow } from '../types'
import { useI18n } from '../i18n'

const collections = ['Belege', 'Eingangsrechnung', 'Ausgangsrechnung', 'Dokumente']

function Thumb({ document }: { document: Document }) {
  const { t } = useI18n()
  return (
    <span className="record-thumb">
      {document.thumbnail_path ? <img src={thumbnailUrl(document.id)} alt="" /> : <span className="file-icon">{document.original_filename.split('.').pop()?.toUpperCase() || 'DOC'}</span>}
      <span className={`status-dot dot-${document.processing_state}`} />
      <span className="hover-preview">
        {document.thumbnail_path && <img src={document.mime_type?.startsWith('image/') ? previewUrl(document.id) : thumbnailUrl(document.id)} alt="" />}
        <strong>{document.original_filename}</strong>
        <em>{document.processing_state}</em>
        <span>{document.extracted_title || t('records.noTitleYet')}</span>
        <small>{document.extracted_invoice_number || document.extracted_payment_method || ''} {document.extracted_amount || ''}</small>
        <p>{(document.ocr_text || '').slice(0, 220)}</p>
      </span>
    </span>
  )
}

export default function RecordListPage({ onOpenRecord }: { onOpenRecord: (id: string) => void }) {
  const { t } = useI18n()
  const [records, setRecords] = useState<RecordRow[]>([])
  const [collection, setCollection] = useState(collections[0])
  const [label, setLabel] = useState('')
  const [files, setFiles] = useState<FileList | null>(null)
  const [busy, setBusy] = useState(false)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const visibleRecords = records.filter((record) =>
    (!filters.collection || record.collection?.name.toLowerCase().includes(filters.collection.toLowerCase())) &&
    (!filters.status || record.status === filters.status) &&
    (!filters.query || record.title.toLowerCase().includes(filters.query.toLowerCase()) || record.documents.some((document) =>
      document.original_filename.toLowerCase().includes(filters.query.toLowerCase()) || (document.extracted_title || '').toLowerCase().includes(filters.query.toLowerCase())
    ))
  )
  const stats = {
    total: records.length,
    documents: records.reduce((sum, record) => sum + record.document_count, 0),
    processing: records.filter((record) => record.status === 'processing').length,
    needsReview: records.filter((record) => record.status === 'needs_review' || record.status === 'partially_failed').length
  }

  async function load() {
    setError('')
    try {
      setRecords(await api.records())
    } catch (err) {
      setError(err instanceof Error ? err.message : t('records.loadError'))
    }
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
      await load()
      const newest = (await api.records()).find((record) => record.documents.some((doc) => doc.batch_id === created.id))
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
            <input placeholder={t('records.searchPlaceholder')} value={filters.query || ''} onChange={(event) => setFilters({ ...filters, query: event.target.value })} />
          </label>
          <input placeholder={t('common.collection')} value={filters.collection || ''} onChange={(event) => setFilters({ ...filters, collection: event.target.value })} />
          <select value={filters.status || ''} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
            <option value="">Any status</option>
            <option value="pending">Pending</option>
            <option value="processing">Processing</option>
            <option value="partially_failed">Partially failed</option>
            <option value="complete">Complete</option>
            <option value="needs_review">Needs review</option>
          </select>
          <SavedViewsBar section="records" filters={filters} onApply={setFilters} />
        </div>
        <div className="record-list dark-record-list">
          {visibleRecords.map((record) => (
            <button className="collection-record-card record-console-row" key={record.id} onClick={() => onOpenRecord(record.id)}>
              <div className="record-main-meta">
                <span className="record-type-icon"><Layers3 size={18} /></span>
                <div>
                  <strong>{record.title}</strong>
                  <span>{record.collection?.name || record.collection_id} · {record.document_count} documents · updated {new Date(record.updated_at).toLocaleString()}</span>
                  <small>{String(record.summary_metadata?.invoice_number || record.summary_metadata?.amount || 'Document metadata stays per file')}</small>
                </div>
              </div>
              <div className="thumb-strip" onClick={(event) => event.stopPropagation()}>
                {record.documents.slice(0, 8).map((document) => <Thumb key={document.id} document={document} />)}
                {record.documents.length > 8 && <span className="count-badge">+{record.documents.length - 8}</span>}
              </div>
              <StatusBadge value={record.status} />
            </button>
          ))}
          {!visibleRecords.length && <p className="muted-empty">No records match the current filters.</p>}
        </div>
      </section>
    </main>
  )
}

function RecordSummary({ icon, label, value, detail, tone = 'green' }: { icon: ReactNode; label: string; value: number; detail: string; tone?: string }) {
  return <div className={`collection-summary-card collection-summary-${tone}`}><span>{icon}</span><div><strong>{value.toLocaleString()}</strong><small>{label}</small><em>{detail}</em></div></div>
}
