import { FormEvent, useEffect, useState } from 'react'
import { Download, Maximize2, Minus, Plus, RefreshCw, RotateCcw, Save, Sparkles, Trash2 } from 'lucide-react'
import { api, downloadUrl, previewUrl, thumbnailUrl } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { Document, DocumentCustomFieldValue, DocumentEvent, DocumentPage } from '../types'
import { useI18n } from '../i18n'

export default function DocumentDetailPage({ id }: { id: string }) {
  const { t, language } = useI18n()
  const [document, setDocument] = useState<Document | null>(null)
  const [events, setEvents] = useState<DocumentEvent[]>([])
  const [pages, setPages] = useState<DocumentPage[]>([])
  const [customFields, setCustomFields] = useState<DocumentCustomFieldValue[]>([])
  const [pipeline, setPipeline] = useState<Record<string, unknown> | null>(null)
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)
  const [form, setForm] = useState<Partial<Document>>({})
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [previewZoom, setPreviewZoom] = useState(100)

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
      setError(err instanceof Error ? err.message : t('documentDetail.loadError'))
    }
  }

  useEffect(() => { void load(); setPreviewZoom(100) }, [id])

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
    setError('')
    setMessage('')
    try {
      setDocument(await api.patchDocument(document.id, payload))
      setMessage(t('activity.message.reviewUpdated'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  async function retry() {
    if (!document) return
    setError('')
    setMessage('')
    setBusy('retry')
    try {
      setDocument(await api.retryDocument(document.id))
      setMessage(t('processing.queued'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retry failed')
    } finally {
      setBusy(null)
    }
  }

  async function processDocument() {
    if (!document) return
    setError('')
    setMessage('')
    setBusy('process')
    try {
      setDocument(await api.processDocument(document.id))
      setMessage(t('processing.queued'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Process failed')
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
    setError('')
    setMessage('')
    setBusy(force ? 'reextract_force' : 'reextract')
    try {
      setDocument(await api.reextractDocument(document.id, force))
      setMessage(t('processing.queued'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Re-extract failed')
    } finally {
      setBusy(null)
    }
  }

  async function runOcr(mode: 'skip' | 'redo' | 'force') {
    if (!document) return
    setError('')
    setMessage('')
    setBusy(`ocr_${mode}`)
    try {
      setDocument(await api.runDocumentOcr(document.id, mode))
      setMessage(t('processing.queued'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'OCR action failed')
    } finally {
      setBusy(null)
    }
  }

  async function previewExtraction() {
    if (!document) return
    setError('')
    setMessage('')
    setBusy('preview_extraction')
    try {
      setPreview(await api.extractionPreview(document.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview extraction failed')
    } finally {
      setBusy(null)
    }
  }

  async function applyPreview() {
    if (!document) return
    setError('')
    setMessage('')
    setBusy('apply_preview')
    try {
      setDocument(await api.applyExtractionPreview(document.id))
      setPreview(null)
      setMessage(t('activity.message.reviewUpdated'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Apply preview failed')
    } finally {
      setBusy(null)
    }
  }

  async function reindex() {
    if (!document) return
    setError('')
    setMessage('')
    setBusy('reindex')
    try {
      setDocument(await api.reindexDocument(document.id))
      setMessage(t('activity.message.ocrSettingsUpdated'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reindex failed')
    } finally {
      setBusy(null)
    }
  }

  if (!document) return <main className="document-detail-console">{error || t('documentDetail.loading')}</main>
  const canPreview = document.mime_type?.startsWith('image/') || document.mime_type === 'application/pdf'
  const isPdf = document.mime_type === 'application/pdf'
  const previewMediaStyle = isPdf
    ? { width: '100%', maxWidth: '1100px', height: 'min(78vh, 900px)' }
    : { width: `${previewZoom}%`, maxWidth: previewZoom <= 100 ? '100%' : 'none' }

  function adjustPreviewZoom(delta: number) {
    setPreviewZoom((current) => Math.min(260, Math.max(50, current + delta)))
  }

  return (
    <main className="document-detail-console">
      <header className="page-header">
        <div>
          <h1>{document.manual_title_override || document.extracted_title || document.original_filename}</h1>
          <p><StatusBadge value={document.processing_state} /> {document.collection_name}</p>
        </div>
        <div className="button-row">
          <button className="primary" title={t('documentDetail.processDocument')} onClick={() => void processDocument()} disabled={busy === 'process'}><Sparkles size={18} /> {busy === 'process' ? t('common.processing') + '...' : t('documentDetail.processDocument')}</button>
          <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
          <a className="icon-button" title={t('common.download')} href={downloadUrl(document.id)}><Download size={18} /></a>
          <button className="icon-button danger-button" title={t('common.delete')} onClick={() => void deleteDocument()} disabled={busy === 'delete'}><Trash2 size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {message && <p className="success-message">{message}</p>}
      {document.error_message && <p className="error">{document.error_message}</p>}
      {document.duplicate_of_document_id && <p className="warning">{t('documentDetail.duplicateOf')} {document.duplicate_of_document_id}; {t('documentDetail.duplicateLinked')}</p>}

      <section className="split document-detail-split">
        <section className="document-detail-preview-card">
          <div className="preview-toolbar">
            <strong>{t('documents.preview')}</strong>
            <div className="button-row">
              {isPdf ? (
                <small className="native-pdf-toolbar-note">Use the PDF toolbar for pages and zoom.</small>
              ) : (
                <>
                  <button type="button" className="icon-button" title={t('common.zoomOut')} onClick={() => adjustPreviewZoom(-20)}><Minus size={16} /></button>
                  <button type="button" className="zoom-value" title={t('common.resetZoom')} onClick={() => setPreviewZoom(100)}>{previewZoom}%</button>
                  <button type="button" className="icon-button" title={t('common.zoomIn')} onClick={() => adjustPreviewZoom(20)}><Plus size={16} /></button>
                  <button type="button" className="icon-button" title={t('documentDetail.readableSize')} onClick={() => setPreviewZoom((current) => current >= 160 ? 100 : 160)}><Maximize2 size={16} /></button>
                </>
              )}
            </div>
          </div>
          <div className="preview-pane document-detail-preview-pane">
            {document.thumbnail_path && !canPreview ? (
              <img className="document-detail-preview-media" style={previewMediaStyle} src={thumbnailUrl(document.id)} alt={document.original_filename} />
            ) : canPreview ? (
              isPdf
                ? <iframe className="document-detail-preview-media document-native-pdf-preview" style={previewMediaStyle} src={previewUrl(document.id)} title={t('documents.preview')} />
                : <img className="document-detail-preview-media" style={previewMediaStyle} src={previewUrl(document.id)} alt={document.original_filename} />
            ) : (
              <a href={downloadUrl(document.id)}>{t('common.download')} {document.original_filename}</a>
            )}
          </div>
        </section>
        <form className="metadata-form" onSubmit={save}>
          <label>{t('documentDetail.manualTitleOverride')}<input value={form.manual_title_override ?? ''} onChange={(e) => setForm({ ...form, manual_title_override: e.target.value })} /></label>
          <label>{t('documentDetail.extractedTitle')}<input value={form.extracted_title ?? ''} onChange={(e) => setForm({ ...form, extracted_title: e.target.value })} /></label>
          <label>{t('fields.sender')}<input value={form.extracted_sender ?? ''} onChange={(e) => setForm({ ...form, extracted_sender: e.target.value })} /></label>
          <label>{t('fields.recipient')}<input value={form.extracted_recipient ?? ''} onChange={(e) => setForm({ ...form, extracted_recipient: e.target.value })} /></label>
          <label>{t('fields.invoiceNumber')}<input value={form.extracted_invoice_number ?? ''} onChange={(e) => setForm({ ...form, extracted_invoice_number: e.target.value })} /></label>
          <label>{t('fields.date')}<input value={form.extracted_date ?? ''} onChange={(e) => setForm({ ...form, extracted_date: e.target.value })} /></label>
          <label>{t('fields.amount')}<input value={form.extracted_amount ?? ''} onChange={(e) => setForm({ ...form, extracted_amount: e.target.value })} /></label>
          <label>{t('fields.paymentMethod')}<input value={form.extracted_payment_method ?? ''} onChange={(e) => setForm({ ...form, extracted_payment_method: e.target.value })} /></label>
          <label>{t('fields.reviewState')}<select value={form.review_state ?? 'unreviewed'} onChange={(e) => setForm({ ...form, review_state: e.target.value as Document['review_state'] })}>
            <option value="unreviewed">{t('common.unreviewed')}</option>
            <option value="needs_review">{t('common.needsReview')}</option>
            <option value="reviewed">{t('common.reviewed')}</option>
          </select></label>
          <label>{t('fields.reviewReason')}<input value={form.review_reason ?? ''} onChange={(e) => setForm({ ...form, review_reason: e.target.value })} /></label>
          <label className="check"><input type="checkbox" checked={Boolean(form.metadata_locked)} onChange={(e) => setForm({ ...form, metadata_locked: e.target.checked })} /> {t('documentDetail.metadataLocked')}</label>
          <div className="button-row">
            <button className="primary"><Save size={18} /> {t('common.save')}</button>
            <details className="advanced-actions inline-advanced">
              <summary>{t('documentDetail.advancedActions')}</summary>
              <div>
                <button type="button" disabled={Boolean(busy)} onClick={() => void retry()}><RotateCcw size={18} /> {t('common.retryOcr')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void runOcr('skip')}>{t('documentDetail.ocrSkip')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void runOcr('redo')}>{t('documentDetail.ocrRedo')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void runOcr('force')}>{t('documentDetail.ocrForce')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void reextract(false)}>{t('common.reextract')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void reextract(true)}>{t('documentDetail.forceReextract')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void previewExtraction()}>{t('documentDetail.previewExtraction')}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void reindex()}>{t('documentDetail.reindex')}</button>
              </div>
            </details>
          </div>
        </form>
      </section>

      <section className="text-section">
        <h2>{t('documentDetail.whyIncomplete')}</h2>
        <DiagnosticsSummary diagnostics={diagnostics} t={t} />
      </section>
      {preview && (
        <section className="text-section">
          <h2>{t('documentDetail.dryRunPreview')}</h2>
          <pre>{JSON.stringify(preview, null, 2)}</pre>
          <div className="button-row">
            <button type="button" className="primary" onClick={() => void applyPreview()}>{t('documentDetail.applyPreview')}</button>
            <button type="button" onClick={() => setPreview(null)}>{t('documentDetail.rejectPreview')}</button>
          </div>
        </section>
      )}
      <section className="text-section">
        <h2>{t('schemas.customFields')}</h2>
        <pre>{JSON.stringify(customFields, null, 2)}</pre>
      </section>
      <section className="text-section">
        <h2>{t('documentDetail.operationalState')}</h2>
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
        <h2>{t('documentDetail.timeline')}</h2>
        {events.map((event) => (
          <div className="timeline-row" key={event.id}>
            <strong>{translateDocumentEvent(event.event_type, t)}</strong>
            <span>{new Date(event.created_at).toLocaleString(language === 'de' ? 'de-DE' : undefined)} · {translateDocumentSource(event.source, t)}</span>
            <p>{translateDocumentMessage(event.message || '', t)}</p>
          </div>
        ))}
      </section>
      <section className="text-section">
        <h2>{t('documentDetail.pageOcr')}</h2>
        <pre>{JSON.stringify(pages.map((page) => ({ page: page.page_number, text: page.ocr_text })), null, 2)}</pre>
      </section>
      <section className="text-section">
        <h2>{t('documents.ocrText')}</h2>
        <pre>{document.ocr_text || ''}</pre>
      </section>
      <section className="text-section">
        <h2>{t('documentDetail.debug')}</h2>
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


function translateDocumentEvent(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.event.${value}`, value.replace(/_/g, ' '))
}

function translateDocumentSource(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.source.${value}`, value)
}

function translateDocumentMessage(value: string, t: (key: string, fallback?: string) => string) {
  const key = DOCUMENT_EVENT_MESSAGE_KEYS[value]
  return key ? t(key, value) : value
}

const DOCUMENT_EVENT_MESSAGE_KEYS: Record<string, string> = {
  'Deterministic extraction completed': 'activity.message.deterministicDone',
  'Document complete after OCR, metadata, title, and DB update': 'activity.message.documentComplete',
  'Final title and metadata generated': 'activity.message.titleGenerated',
  'Full OCR and metadata are searchable in the app database': 'activity.message.searchIndexed',
  'Mapped correspondent, document type, and storage path metadata': 'activity.message.paperlessMapped',
  'OCR completed': 'activity.message.ocrCompleted',
  'OCR started': 'activity.message.ocrStarted',
  'Metadata extraction started': 'activity.message.metadataStarted',
  'Document queued for OCR': 'activity.message.queuedForOcr',
  'Document uploaded': 'activity.message.uploaded',
  'Original file stored on local filesystem': 'activity.message.stored',
  'Full document processing started': 'activity.message.processStarted'
}

function DiagnosticsSummary({ diagnostics, t }: { diagnostics: Record<string, unknown> | null; t: (key: string, fallback?: string) => string }) {
  if (!diagnostics) return <p className="muted">{t('documentDetail.diagnosticsLoading')}</p>
  const blockers = Array.isArray(diagnostics.blockers) ? diagnostics.blockers.map(String) : []
  const task = isRecord(diagnostics.task) ? diagnostics.task : null
  const taskActive = Boolean(task?.active)
  const totalAttempts = typeof task?.total_attempts === 'number' ? task.total_attempts : typeof task?.attempt === 'number' ? task.attempt : null
  const qwen = isRecord(diagnostics.qwen) ? diagnostics.qwen : null
  const qwenStatus = typeof qwen?.status === 'string' ? qwen.status : null
  const complete = Boolean(diagnostics.complete)
  return (
    <div className="diagnostics-summary">
      <ul>
        {blockers.length ? blockers.map((blocker) => <li key={blocker}>{blocker}</li>) : <li className="ok">{complete ? t('documentDetail.noCompletionBlockers') : t('documentDetail.noDiagnosticBlockers')}</li>}
        {qwenStatus && <li>{t('documentDetail.qwenStatus')}: {qwenStatus}</li>}
        {taskActive && <li>{t('documentDetail.activeTask')}: {String(task?.current_stage || 'processing')}</li>}
        {!taskActive && totalAttempts !== null && totalAttempts > 0 && <li>{t('documentDetail.totalAttempts')}: {totalAttempts}</li>}
      </ul>
      <details className="diagnostics-raw">
        <summary>{t('documentDetail.rawDiagnostics')}</summary>
        <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
      </details>
    </div>
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
