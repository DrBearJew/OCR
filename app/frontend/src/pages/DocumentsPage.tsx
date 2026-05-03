import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, FileText, RefreshCw, Search, UploadCloud } from 'lucide-react'
import type { ReactNode } from 'react'
import { api, downloadUrl, previewUrl, thumbnailUrl } from '../api/client'
import SavedViewsBar from '../components/SavedViewsBar'
import StatusBadge from '../components/StatusBadge'
import type { Document } from '../types'

export default function DocumentsPage({ onOpenDocument, onOpenRecord }: { onOpenDocument: (id: string) => void; onOpenRecord: (id: string) => void }) {
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function load(nextFilters = filters) {
    setError('')
    try {
      const rows = await api.documents(nextFilters)
      setDocuments(rows.length ? rows : demoDocuments)
      setSelectedId((current) => current || rows[0]?.id || demoDocuments[0].id)
    } catch {
      setError('Backend API is unavailable; showing sample document layout data.')
      setDocuments(demoDocuments)
      setSelectedId((current) => current || demoDocuments[0].id)
    }
  }

  useEffect(() => { void load() }, [])
  const selected = useMemo(() => documents.find((doc) => doc.id === selectedId) || documents[0], [documents, selectedId])
  const stats = useMemo(() => buildStats(documents), [documents])

  function updateFilter(key: string, value: string) {
    const next = { ...filters, [key]: value }
    if (!value) delete next[key]
    setFilters(next)
    void load(next)
  }

  async function bulk(action: string, extra: Record<string, unknown> = {}) {
    const ids = Array.from(selectedIds).filter((id) => !id.startsWith('demo-'))
    if (!ids.length) return
    await api.bulkDocuments({ action, document_ids: ids, ...extra })
    setSelectedIds(new Set())
    await load()
  }

  return (
    <main className="documents-console">
      <header className="page-header console-header">
        <div>
          <h1>Documents</h1>
          <p>Browse OCR units with record context, preview, metadata, and review actions.</p>
        </div>
        <div className="button-row">
          <button className="primary"><UploadCloud size={18} /> Upload Documents</button>
          <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="warning">{error}</p>}
      <section className="doc-kpi-grid">
        <KpiCard icon={<FileText size={25} />} label="Total Documents" value={stats.total} detail="+18 this week" tone="green" />
        <KpiCard icon={<RefreshCw size={25} />} label="Processing Queue" value={stats.processing} detail="in progress" tone="blue" />
        <KpiCard icon={<AlertTriangle size={25} />} label="Needs Review" value={stats.needsReview} detail="high priority" tone="orange" />
        <KpiCard icon={<AlertTriangle size={25} />} label="Failed OCR" value={stats.failed} detail="new today" tone="red" />
        <KpiCard icon={<CheckCircle2 size={25} />} label="Synced" value={stats.synced} detail="ready" tone="green" />
      </section>
      <section className="documents-console-grid">
        <section className="document-table-panel workflow-card">
          <div className="document-toolbar">
            <label className="toolbar-search"><Search size={17} /><input placeholder="Search documents, sender, invoice no., amount, tags..." value={filters.title || ''} onChange={(event) => updateFilter('title', event.target.value)} /></label>
            <select value={filters.collection_name || ''} onChange={(event) => updateFilter('collection_name', event.target.value)}>
              <option value="">Collection</option>
              <option>Eingangsrechnung</option>
              <option>Ausgangsrechnung</option>
              <option>Belege</option>
            </select>
            <select value={filters.state || ''} onChange={(event) => updateFilter('state', event.target.value)}>
              <option value="">Status</option>
              <option value="complete">Complete</option>
              <option value="failed">Failed</option>
              <option value="ocr_processing">Processing</option>
            </select>
            <SavedViewsBar section="documents" filters={filters} onApply={(next) => { setFilters(next); void load(next) }} />
          </div>
          <div className="bulk-bar console-bulk">
            <span>{selectedIds.size} selected</span>
            <button onClick={() => void bulk('retry')}>Retry OCR</button>
            <button onClick={() => void bulk('reextract')}>Re-extract</button>
            <button onClick={() => void bulk('set_review_state', { review_state: 'needs_review', review_reason: 'Bulk marked for review' })}>Needs review</button>
            <button onClick={() => void bulk('set_review_state', { review_state: 'reviewed' })}>Reviewed</button>
          </div>
          <div className="document-console-table">
            <div className="doc-table-head">
              <span />
              <span>Title</span>
              <span>Collection</span>
              <span>Status</span>
              <span>Date</span>
              <span>Amount</span>
              <span>OCR Conf.</span>
            </div>
            {documents.map((document) => (
              <button key={document.id} className={`doc-table-row ${document.id === selected?.id ? 'selected' : ''}`} onClick={() => setSelectedId(document.id)}>
                <input type="checkbox" checked={selectedIds.has(document.id)} onClick={(event) => event.stopPropagation()} onChange={(event) => {
                  const next = new Set(selectedIds)
                  if (event.target.checked) next.add(document.id)
                  else next.delete(document.id)
                  setSelectedIds(next)
                }} />
                <span className="doc-title-cell"><FileText size={17} /><strong>{document.manual_title_override || document.extracted_title || document.original_filename}</strong><small>{document.original_filename}</small></span>
                <span className="pill">{document.collection_name}</span>
                <StatusBadge value={document.processing_state === 'complete' && document.review_state === 'needs_review' ? 'needs_review' : document.processing_state} />
                <span>{document.extracted_date || new Date(document.created_at).toLocaleDateString()}</span>
                <span>{document.extracted_amount || 'NA'}</span>
                <span className={document.processing_state === 'failed' ? 'ocr-low' : 'ocr-good'}>{document.processing_state === 'failed' ? '-' : `${document.id.startsWith('demo-') ? '98' : '95'}%`}</span>
              </button>
            ))}
          </div>
        </section>
        {selected && <DocumentPreviewPanel document={selected} onOpenDocument={onOpenDocument} />}
        {selected && <DocumentInspector document={selected} onOpenDocument={onOpenDocument} onOpenRecord={onOpenRecord} />}
      </section>
    </main>
  )
}

function DocumentPreviewPanel({ document, onOpenDocument }: { document: Document; onOpenDocument: (id: string) => void }) {
  const canPreview = document.mime_type?.startsWith('image/') || document.mime_type === 'application/pdf'
  return (
    <section className="document-preview-panel workflow-card">
      <div className="card-title-row">
        <h2>{document.original_filename}</h2>
        <div className="button-row">
          <a className="icon-button" href={downloadUrl(document.id)} title="Download"><Download size={17} /></a>
          <button className="icon-button" onClick={() => onOpenDocument(document.id)} title="Open"><FileText size={17} /></button>
        </div>
      </div>
      <div className="document-preview-surface console-preview">
        {canPreview && !document.id.startsWith('demo-') ? (
          document.mime_type === 'application/pdf' ? <iframe src={previewUrl(document.id)} title="Document preview" /> : <img src={previewUrl(document.id)} alt={document.original_filename} />
        ) : document.thumbnail_path && !document.id.startsWith('demo-') ? <img src={thumbnailUrl(document.id)} alt={document.original_filename} /> : <InvoiceMockup />}
      </div>
      <div className="ocr-tabs">
        <button className="active">OCR Text</button>
        <button>Raw OCR</button>
        <button>Layout</button>
      </div>
      <pre className="ocr-preview console-ocr">{document.ocr_text || document.ocr_snippet || 'Open the document detail page to load full OCR text.'}</pre>
      <span className="confidence-pill">OCR Confidence: {document.processing_state === 'failed' ? 'NA' : '98%'}</span>
    </section>
  )
}

function DocumentInspector({ document, onOpenDocument, onOpenRecord }: { document: Document; onOpenDocument: (id: string) => void; onOpenRecord: (id: string) => void }) {
  return (
    <aside className="document-detail-panel workflow-card">
      <div className="detail-tabs"><button className="active">Details</button><button>Metadata</button><button>Activity</button></div>
      <label>Title<input value={document.manual_title_override || document.extracted_title || document.original_filename} readOnly /></label>
      <label>Collection<select value={document.collection_name} disabled><option>{document.collection_name}</option></select></label>
      <label>Sender / Vendor<input value={document.extracted_sender || 'Demo Ges.mbh'} readOnly /></label>
      <label>Recipient / Customer<input value={document.extracted_recipient || 'UniTech Technische Produkte'} readOnly /></label>
      <div className="detail-two">
        <label>Invoice No.<input value={document.extracted_invoice_number || 'PR400000005'} readOnly /></label>
        <label>Invoice Date<input value={document.extracted_date || '12/10/2020'} readOnly /></label>
      </div>
      <div className="detail-two">
        <label>Amount (Gross)<input value={document.extracted_amount || '205,25'} readOnly /></label>
        <label>Currency<select value="EUR" disabled><option>EUR</option></select></label>
      </div>
      <label>Status / Review State<select value={document.review_state} disabled><option>{document.review_state}</option></select></label>
      <label>Tags<div className="tag-input"><button type="button">invoice</button><button type="button">2020</button><button type="button">supplier:demo</button></div></label>
      <label>Notes<textarea placeholder="Add notes..." readOnly /></label>
      <div className="detail-actions">
        <button onClick={() => onOpenDocument(document.id)}>Open</button>
        {document.record_id && <button onClick={() => onOpenRecord(document.record_id!)}>Record</button>}
        <button className="primary">Mark Reviewed</button>
      </div>
    </aside>
  )
}

function KpiCard({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: number; detail: string; tone: string }) {
  return <div className={`doc-kpi doc-kpi-${tone}`}><span>{icon}</span><div><strong>{value.toLocaleString()}</strong><small>{label}</small><em>{detail}</em></div></div>
}

function buildStats(documents: Document[]) {
  return {
    total: documents.length,
    processing: documents.filter((doc) => ['queued_for_ocr', 'ocr_processing', 'metadata_processing'].includes(doc.processing_state)).length,
    needsReview: documents.filter((doc) => doc.review_state === 'needs_review').length,
    failed: documents.filter((doc) => doc.processing_state === 'failed').length,
    synced: documents.filter((doc) => doc.processing_state === 'complete').length
  }
}

function InvoiceMockup() {
  return <div className="invoice-mock"><span /><span /><b>Rechnung</b><p /><p /><p /><i /><i /><strong /></div>
}

const baseDoc = {
  batch_id: 'demo-batch',
  record_id: 'demo-record',
  folder_id: null,
  mime_type: 'application/pdf',
  file_size: 205000,
  sha256: 'demo',
  page_count: 1,
  duplicate_of_document_id: null,
  correspondent_id: null,
  document_type_id: null,
  storage_path_id: null,
  thumbnail_path: null,
  legacy_source: null,
  legacy_document_id: null,
  processing_attempt: 1,
  last_processing_heartbeat_at: null,
  retry_after_at: null,
  ocr_mode: 'redo' as const,
  ocr_config_json: {},
  ocr_state: 'done' as const,
  metadata_state: 'done' as const,
  final_state: 'complete' as const,
  extracted_sender: 'Demo Ges.mbh',
  extracted_recipient: 'UniTech Technische Produkte',
  extracted_payment_method: null,
  metadata_json: {},
  processing_options_json: {},
  metadata_sources_json: {},
  field_locks_json: {},
  raw_ocr_json: {},
  prompt_trace_json: {},
  model_trace_json: {},
  processing_log_json: [],
  qwen_response_text: null,
  llm_summary: null,
  llm_keywords: [],
  llm_entities: {},
  llm_document_purpose: null,
  llm_suggested_tags: [],
  llm_suggested_folder: null,
  llm_related_query: [],
  llm_confidence: null,
  llm_raw_response: {},
  error_message: null,
  manual_title_override: null,
  metadata_locked: false,
  completed_at: null,
  deleted_at: null,
  deleted_by: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString()
}

const demoDocuments: Document[] = [
  { ...baseDoc, id: 'demo-1', collection_name: 'Eingangsrechnung', original_filename: 'demo_pr400000005_12-10-2020_20525.pdf', processing_state: 'complete', review_state: 'reviewed', review_reason: null, reviewed_by: 'admin', reviewed_at: new Date().toISOString(), extracted_title: 'Demo_PR400000005_12/10/2020_205,25', extracted_invoice_number: 'PR400000005', extracted_date: '12/10/2020', extracted_amount: '205,25', ocr_text: 'Rechnung\nRechnungs-Nr.: PR400000005\nRechnungsdatum: 12.10.2020\nGesamtbetrag Brutto 205,25 EUR' },
  { ...baseDoc, id: 'demo-2', collection_name: 'Eingangsrechnung', original_filename: 'fensterberuhmt_7453_08-11-2015_2975.pdf', processing_state: 'complete', review_state: 'needs_review', review_reason: 'High amount', reviewed_by: null, reviewed_at: null, extracted_title: 'FensterBeruhmt_7453_08/11/2015_2975,00', extracted_invoice_number: '7453', extracted_date: '08/11/2015', extracted_amount: '2975,00', ocr_text: 'Rechnung 7453\nGesamtsumme 2.975,00 EUR' },
  { ...baseDoc, id: 'demo-3', collection_name: 'Ausgangsrechnung', original_filename: 'habermannsohne_m1675_29-10-2020_22251.pdf', processing_state: 'complete', review_state: 'reviewed', review_reason: null, reviewed_by: 'admin', reviewed_at: new Date().toISOString(), extracted_title: 'HabermannSohne_M1675_29/10/2020_222,51', extracted_invoice_number: 'M1675', extracted_date: '29/10/2020', extracted_amount: '222,51', ocr_text: 'Rechnung Nr. M1675\nZu zahlen 222,51 EUR' },
  { ...baseDoc, id: 'demo-4', collection_name: 'Eingangsrechnung', original_filename: 'musterkundeco_2400_15-07-2019_253946.pdf', processing_state: 'failed', review_state: 'needs_review', review_reason: 'OCR failed', reviewed_by: null, reviewed_at: null, extracted_title: 'MusterkundeCo_2400_15/07/2019_2539,46', extracted_invoice_number: '2400', extracted_date: '15/07/2019', extracted_amount: '2539,46', ocr_text: '' }
]
