import { FormEvent, useEffect, useState } from 'react'
import { Download, RefreshCw, RotateCcw, Save, Sparkles, Trash2 } from 'lucide-react'
import { api, downloadUrl, previewUrl, thumbnailUrl } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { Document, DocumentCustomFieldValue, DocumentEvent, DocumentPage } from '../types'

export default function DocumentDetailPage({ id }: { id: string }) {
  const [document, setDocument] = useState<Document | null>(null)
  const [events, setEvents] = useState<DocumentEvent[]>([])
  const [pages, setPages] = useState<DocumentPage[]>([])
  const [customFields, setCustomFields] = useState<DocumentCustomFieldValue[]>([])
  const [pipeline, setPipeline] = useState<Record<string, unknown> | null>(null)
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)
  const [form, setForm] = useState<Partial<Document>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<'process' | 'delete' | null>(null)

  async function load() {
    setError('')
    try {
      const [row, eventRows, pageRows, customRows, pipelineRow, diagnosticRow] = await Promise.all([api.document(id), api.documentEvents(id), api.documentPages(id), api.documentCustomFields(id), api.documentPipeline(id), api.documentDiagnostics(id)])
      setDocument(row)
      setEvents(eventRows)
      setPages(pageRows)
      setCustomFields(customRows)
      setPipeline(pipelineRow)
      setDiagnostics(diagnosticRow)
      setForm(row)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load document')
    }
  }

  useEffect(() => { void load() }, [id])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!document) return
    const payload = {
      manual_title_override: form.manual_title_override || null,
      extracted_title: form.extracted_title || null,
      extracted_sender: form.extracted_sender || null,
      extracted_recipient: form.extracted_recipient || null,
      extracted_invoice_number: form.extracted_invoice_number || null,
      extracted_date: form.extracted_date || null,
      extracted_amount: form.extracted_amount || null,
      extracted_payment_method: form.extracted_payment_method || null,
      metadata_locked: Boolean(form.metadata_locked),
      review_state: form.review_state || 'unreviewed',
      review_reason: form.review_reason || null
    }
    setDocument(await api.patchDocument(document.id, payload))
  }

  async function retry() {
    if (!document) return
    setDocument(await api.retryDocument(document.id))
  }

  async function processDocument() {
    if (!document) return
    setBusy('process')
    try {
      setDocument(await api.processDocument(document.id))
      await load()
    } finally {
      setBusy(null)
    }
  }

  async function deleteDocument() {
    if (!document) return
    if (!confirm(`Delete "${document.original_filename}"? This soft-deletes the file, OCR text, and metadata until restored.`)) return
    setBusy('delete')
    try {
      setDocument(await api.deleteDocument(document.id))
      setError('Document deleted. It is hidden from default lists and search.')
    } finally {
      setBusy(null)
    }
  }

  async function reextract(force: boolean) {
    if (!document) return
    setDocument(await api.reextractDocument(document.id, force))
    await load()
  }

  async function runOcr(mode: 'skip' | 'redo' | 'force') {
    if (!document) return
    setDocument(await api.runDocumentOcr(document.id, mode))
    await load()
  }

  async function previewExtraction() {
    if (!document) return
    setPreview(await api.extractionPreview(document.id))
  }

  async function applyPreview() {
    if (!document) return
    setDocument(await api.applyExtractionPreview(document.id))
    setPreview(null)
    await load()
  }

  async function reindex() {
    if (!document) return
    setDocument(await api.reindexDocument(document.id))
    await load()
  }

  if (!document) return <main>{error || 'Loading document...'}</main>
  const canPreview = document.mime_type?.startsWith('image/') || document.mime_type === 'application/pdf'

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{document.manual_title_override || document.extracted_title || document.original_filename}</h1>
          <p><StatusBadge value={document.processing_state} /> {document.collection_name}</p>
        </div>
        <div className="button-row">
          <button className="primary" title="Process document" onClick={() => void processDocument()} disabled={busy === 'process'}><Sparkles size={18} /> {busy === 'process' ? 'Processing...' : 'Process Document'}</button>
          <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
          <a className="icon-button" title="Download" href={downloadUrl(document.id)}><Download size={18} /></a>
          <button className="icon-button danger-button" title="Delete" onClick={() => void deleteDocument()} disabled={busy === 'delete'}><Trash2 size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {document.error_message && <p className="error">{document.error_message}</p>}
      {document.duplicate_of_document_id && <p className="warning">Duplicate of document {document.duplicate_of_document_id}; it was linked and not reprocessed by default.</p>}

      <section className="split">
        <div className="preview-pane">
          {document.thumbnail_path && !canPreview ? (
            <img src={thumbnailUrl(document.id)} alt={document.original_filename} />
          ) : canPreview ? (
            document.mime_type === 'application/pdf'
              ? <iframe src={previewUrl(document.id)} title="Document preview" />
              : <img src={previewUrl(document.id)} alt={document.original_filename} />
          ) : (
            <a href={downloadUrl(document.id)}>Download {document.original_filename}</a>
          )}
        </div>
        <form className="metadata-form" onSubmit={save}>
          <label>Manual title override<input value={form.manual_title_override ?? ''} onChange={(e) => setForm({ ...form, manual_title_override: e.target.value })} /></label>
          <label>Extracted title<input value={form.extracted_title ?? ''} onChange={(e) => setForm({ ...form, extracted_title: e.target.value })} /></label>
          <label>Sender<input value={form.extracted_sender ?? ''} onChange={(e) => setForm({ ...form, extracted_sender: e.target.value })} /></label>
          <label>Recipient<input value={form.extracted_recipient ?? ''} onChange={(e) => setForm({ ...form, extracted_recipient: e.target.value })} /></label>
          <label>Invoice number<input value={form.extracted_invoice_number ?? ''} onChange={(e) => setForm({ ...form, extracted_invoice_number: e.target.value })} /></label>
          <label>Date<input value={form.extracted_date ?? ''} onChange={(e) => setForm({ ...form, extracted_date: e.target.value })} /></label>
          <label>Amount<input value={form.extracted_amount ?? ''} onChange={(e) => setForm({ ...form, extracted_amount: e.target.value })} /></label>
          <label>Payment method<input value={form.extracted_payment_method ?? ''} onChange={(e) => setForm({ ...form, extracted_payment_method: e.target.value })} /></label>
          <label>Review state<select value={form.review_state ?? 'unreviewed'} onChange={(e) => setForm({ ...form, review_state: e.target.value as Document['review_state'] })}>
            <option value="unreviewed">Unreviewed</option>
            <option value="needs_review">Needs review</option>
            <option value="reviewed">Reviewed</option>
          </select></label>
          <label>Review reason<input value={form.review_reason ?? ''} onChange={(e) => setForm({ ...form, review_reason: e.target.value })} /></label>
          <label className="check"><input type="checkbox" checked={Boolean(form.metadata_locked)} onChange={(e) => setForm({ ...form, metadata_locked: e.target.checked })} /> Metadata locked</label>
          <div className="button-row">
            <button className="primary"><Save size={18} /> Save</button>
            <details className="advanced-actions inline-advanced">
              <summary>Advanced actions</summary>
              <div>
                <button type="button" onClick={retry}><RotateCcw size={18} /> Retry OCR</button>
                <button type="button" onClick={() => void runOcr('skip')}>OCR skip</button>
                <button type="button" onClick={() => void runOcr('redo')}>OCR redo</button>
                <button type="button" onClick={() => void runOcr('force')}>OCR force</button>
                <button type="button" onClick={() => void reextract(false)}>Reextract</button>
                <button type="button" onClick={() => void reextract(true)}>Force reextract</button>
                <button type="button" onClick={() => void previewExtraction()}>Preview extraction</button>
                <button type="button" onClick={() => void reindex()}>Reindex</button>
              </div>
            </details>
          </div>
        </form>
      </section>

      <section className="text-section">
        <h2>Why is this not complete?</h2>
        <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
      </section>
      {preview && (
        <section className="text-section">
          <h2>Dry-run Extraction Preview</h2>
          <pre>{JSON.stringify(preview, null, 2)}</pre>
          <div className="button-row">
            <button type="button" className="primary" onClick={() => void applyPreview()}>Apply preview to unlocked fields</button>
            <button type="button" onClick={() => setPreview(null)}>Reject preview</button>
          </div>
        </section>
      )}
      <section className="text-section">
        <h2>Custom Fields</h2>
        <pre>{JSON.stringify(customFields, null, 2)}</pre>
      </section>
      <section className="text-section">
        <h2>Operational State</h2>
        <pre>{JSON.stringify({
          page_count: document.page_count,
          attempts: document.processing_attempt,
          heartbeat: document.last_processing_heartbeat_at,
          retry_after: document.retry_after_at,
          ocr_mode: document.ocr_mode,
          ocr_config: document.ocr_config_json,
          legacy_source: document.legacy_source,
          legacy_document_id: document.legacy_document_id,
          correspondent_id: document.correspondent_id,
          document_type_id: document.document_type_id,
          storage_path_id: document.storage_path_id,
          pipeline,
          prompt_trace: document.prompt_trace_json,
          model_trace: document.model_trace_json
        }, null, 2)}</pre>
      </section>
      <section className="timeline">
        <h2>Timeline</h2>
        {events.map((event) => (
          <div className="timeline-row" key={event.id}>
            <strong>{event.event_type}</strong>
            <span>{new Date(event.created_at).toLocaleString()} · {event.source}</span>
            <p>{event.message}</p>
          </div>
        ))}
      </section>
      <section className="text-section">
        <h2>Page OCR</h2>
        <pre>{JSON.stringify(pages.map((page) => ({ page: page.page_number, text: page.ocr_text })), null, 2)}</pre>
      </section>
      <section className="text-section">
        <h2>OCR Text</h2>
        <pre>{document.ocr_text || ''}</pre>
      </section>
      <section className="text-section">
        <h2>Debug</h2>
        <pre>{JSON.stringify({
          metadata: document.metadata_json,
          metadata_sources: document.metadata_sources_json,
          qwen_candidates: document.metadata_json?.qwen_candidates,
          qwen_response_text: document.qwen_response_text,
          llm_summary: document.llm_summary,
          llm_keywords: document.llm_keywords,
          llm_suggested_folder: document.llm_suggested_folder,
          llm_raw_response: document.llm_raw_response,
          raw_ocr: document.raw_ocr_json
        }, null, 2)}</pre>
      </section>
    </main>
  )
}
