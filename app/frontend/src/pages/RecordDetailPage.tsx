import { useEffect, useState } from 'react'
import { Download, RefreshCw, Save, Sparkles, Trash2 } from 'lucide-react'
import { api, downloadUrl, previewUrl, thumbnailUrl } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { Document, RecordRow } from '../types'

export default function RecordDetailPage({ id, onOpenDocument }: { id: string; onOpenDocument: (id: string) => void }) {
  const [record, setRecord] = useState<RecordRow | null>(null)
  const [selectedId, setSelectedId] = useState<string>('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<'process' | 'delete' | null>(null)
  const [sharedTitleBase, setSharedTitleBase] = useState('')
  const [applySharedTitle, setApplySharedTitle] = useState(false)

  async function load() {
    setError('')
    try {
      const row = await api.record(id)
      setRecord(row)
      setSharedTitleBase(row.shared_title_base || '')
      setApplySharedTitle(row.apply_shared_title_to_documents)
      setSelectedId((current) => current || row.documents[0]?.id || '')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load record')
    }
  }

  useEffect(() => { void load() }, [id])

  if (!record) return <main>{error || 'Loading record...'}</main>
  const selected = record.documents.find((doc) => doc.id === selectedId) || record.documents[0]

  async function saveSharedTitle(applyNow = false) {
    if (!record) return
    setError('')
    setMessage('')
    try {
      const updated = await api.patchRecord(record.id, {
        shared_title_base: sharedTitleBase,
        apply_shared_title_to_documents: applySharedTitle
      })
      const next = applyNow ? await api.applySharedTitle(updated.id, true) : updated
      setRecord(next)
      setSharedTitleBase(next.shared_title_base || '')
      setApplySharedTitle(next.apply_shared_title_to_documents)
      setMessage(applyNow ? 'Shared title applied to unlocked documents.' : 'Shared title settings saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save shared title')
    }
  }

  async function processAll() {
    if (!record) return
    setBusy('process')
    try {
      const result = await api.processRecord(record.id)
      setMessage(`Processing queued for ${result.queued} document${result.queued === 1 ? '' : 's'}.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not process record')
    } finally {
      setBusy(null)
    }
  }

  async function deleteRecord() {
    if (!record) return
    if (!confirm(`Delete record "${record.title}" and all ${record.document_count} child document${record.document_count === 1 ? '' : 's'}? This is a soft delete.`)) return
    setBusy('delete')
    try {
      await api.deleteRecord(record.id)
      setMessage('Record and child documents deleted. They are hidden from default lists and search.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete record')
    } finally {
      setBusy(null)
    }
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{record.title}</h1>
          <p>{record.collection?.name} · {record.document_count} documents · <StatusBadge value={record.status} /></p>
        </div>
        <div className="button-row">
          <button className="primary" onClick={() => void processAll()} disabled={busy === 'process'}><Sparkles size={18} /> {busy === 'process' ? 'Processing...' : 'Process All'}</button>
          <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
          <button className="icon-button danger-button" title="Delete record" onClick={() => void deleteRecord()} disabled={busy === 'delete'}><Trash2 size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {message && <p className="success-message">{message}</p>}
      <section className="workflow-card record-shared-title-card">
        <div>
          <h2>Shared title base</h2>
          <p>Optional. Applies only to unlocked document title base segments; invoice number, date, amount, OCR, and metadata remain per document.</p>
        </div>
        <div className="shared-title-controls">
          <label>
            Base title/name
            <input value={sharedTitleBase} onChange={(event) => setSharedTitleBase(event.target.value)} placeholder="Telekom" />
          </label>
          <label className="toggle-row">
            <input type="checkbox" checked={applySharedTitle} onChange={(event) => setApplySharedTitle(event.target.checked)} />
            <span>Apply shared title to documents in this record</span>
          </label>
        </div>
        <div className="button-row">
          <button type="button" onClick={() => void saveSharedTitle(false)}><Save size={17} /> Save settings</button>
          <button type="button" className="primary" disabled={!sharedTitleBase.trim() || !applySharedTitle} onClick={() => void saveSharedTitle(true)}>
            <Sparkles size={17} /> Apply to unlocked documents
          </button>
        </div>
      </section>
      <section className="record-detail-grid">
        <aside className="document-selector">
          {record.documents.map((document) => (
            <button key={document.id} className={document.id === selected?.id ? 'active' : ''} onClick={() => setSelectedId(document.id)}>
              {document.thumbnail_path && <img src={thumbnailUrl(document.id)} alt="" />}
              <span>
                <strong>{document.extracted_title || document.original_filename}</strong>
                <small>{document.original_filename}</small>
              </span>
              <StatusBadge value={document.processing_state} />
            </button>
          ))}
        </aside>
        {selected ? <SelectedDocument document={selected} onOpenDocument={onOpenDocument} /> : <p>No documents in this record.</p>}
      </section>
    </main>
  )
}

function SelectedDocument({ document, onOpenDocument }: { document: Document; onOpenDocument: (id: string) => void }) {
  const canPreview = document.mime_type?.startsWith('image/') || document.mime_type === 'application/pdf'
  return (
    <section className="selected-document">
      <div className="selected-toolbar">
        <button onClick={() => onOpenDocument(document.id)}>Open document</button>
        <a className="icon-button" href={downloadUrl(document.id)} title="Download"><Download size={18} /></a>
      </div>
      <div className="preview-pane">
        {canPreview ? (
          document.mime_type === 'application/pdf'
            ? <iframe src={previewUrl(document.id)} title="Document preview" />
            : <img src={previewUrl(document.id)} alt={document.original_filename} />
        ) : document.thumbnail_path ? (
          <img src={thumbnailUrl(document.id)} alt={document.original_filename} />
        ) : (
          <a href={downloadUrl(document.id)}>Download {document.original_filename}</a>
        )}
      </div>
      <div className="record-document-meta">
        <h2>Document Metadata</h2>
        <dl>
          <dt>Title</dt><dd>{document.manual_title_override || document.extracted_title || 'NA'}</dd>
          <dt>Sender</dt><dd>{document.extracted_sender || 'NA'}</dd>
          <dt>Recipient</dt><dd>{document.extracted_recipient || 'NA'}</dd>
          <dt>Invoice</dt><dd>{document.extracted_invoice_number || 'NA'}</dd>
          <dt>Date</dt><dd>{document.extracted_date || 'NA'}</dd>
          <dt>Amount</dt><dd>{document.extracted_amount || 'NA'}</dd>
        </dl>
      </div>
      <div className="text-section">
        <h2>OCR Text</h2>
        <pre>{document.ocr_text || ''}</pre>
      </div>
    </section>
  )
}
