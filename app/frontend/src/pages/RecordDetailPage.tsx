import { useEffect, useState } from 'react'
import { Download, RefreshCw, Save, Sparkles, Trash2 } from 'lucide-react'
import { api, downloadUrl, previewUrl, thumbnailUrl } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { Document, RecordRow } from '../types'
import { useI18n } from '../i18n'

export default function RecordDetailPage({ id, onOpenDocument }: { id: string; onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
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
      setError(err instanceof Error ? err.message : t('recordDetail.loadError'))
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
    <main className="record-detail-console">
      <header className="page-header">
        <div>
          <h1>{record.title}</h1>
          <p>{record.collection?.name} · {record.document_count} documents · <StatusBadge value={record.status} /></p>
        </div>
        <div className="button-row">
          <button className="primary" onClick={() => void processAll()} disabled={busy === 'process'}><Sparkles size={18} /> {busy === 'process' ? t('common.processing') + '...' : t('recordDetail.processAll')}</button>
          <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
          <button className="icon-button danger-button" title={t('recordDetail.deleteRecord')} onClick={() => void deleteRecord()} disabled={busy === 'delete'}><Trash2 size={18} /></button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {message && <p className="success-message">{message}</p>}
      <section className="workflow-card record-shared-title-card">
        <div>
          <h2>{t('recordDetail.sharedTitleBase')}</h2>
          <p>{t('recordDetail.sharedTitleCopy')}</p>
        </div>
        <div className="shared-title-controls">
          <label>
            {t('recordDetail.baseTitleName')}
            <input value={sharedTitleBase} onChange={(event) => setSharedTitleBase(event.target.value)} placeholder="Telekom" />
          </label>
          <label className="toggle-row">
            <input type="checkbox" checked={applySharedTitle} onChange={(event) => setApplySharedTitle(event.target.checked)} />
            <span>{t('recordDetail.applySharedTitle')}</span>
          </label>
        </div>
        <div className="button-row">
          <button type="button" onClick={() => void saveSharedTitle(false)}><Save size={17} /> {t('recordDetail.saveSettings')}</button>
          <button type="button" className="primary" disabled={!sharedTitleBase.trim() || !applySharedTitle} onClick={() => void saveSharedTitle(true)}>
            <Sparkles size={17} /> {t('recordDetail.applyUnlocked')}
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
        {selected ? <SelectedDocument document={selected} onOpenDocument={onOpenDocument} /> : <p>{t('recordDetail.noDocuments')}</p>}
      </section>
    </main>
  )
}

function SelectedDocument({ document, onOpenDocument }: { document: Document; onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  const canPreview = document.mime_type?.startsWith('image/') || document.mime_type === 'application/pdf'
  return (
    <section className="selected-document">
      <div className="selected-toolbar">
        <button onClick={() => onOpenDocument(document.id)}>{t('recordDetail.openDocument')}</button>
        <a className="icon-button" href={downloadUrl(document.id)} title={t('common.download')}><Download size={18} /></a>
      </div>
      <div className="preview-pane">
        {canPreview ? (
          document.mime_type === 'application/pdf'
            ? <iframe src={previewUrl(document.id)} title={t('documents.preview')} />
            : <img src={previewUrl(document.id)} alt={document.original_filename} />
        ) : document.thumbnail_path ? (
          <img src={thumbnailUrl(document.id)} alt={document.original_filename} />
        ) : (
          <a href={downloadUrl(document.id)}>{t('common.download')} {document.original_filename}</a>
        )}
      </div>
      <div className="record-document-meta">
        <h2>{t('recordDetail.documentMetadata')}</h2>
        <dl>
          <dt>{t('fields.title')}</dt><dd>{document.manual_title_override || document.extracted_title || 'NA'}</dd>
          <dt>{t('fields.sender')}</dt><dd>{document.extracted_sender || 'NA'}</dd>
          <dt>{t('fields.recipient')}</dt><dd>{document.extracted_recipient || 'NA'}</dd>
          <dt>{t('fields.invoice')}</dt><dd>{document.extracted_invoice_number || 'NA'}</dd>
          <dt>{t('fields.date')}</dt><dd>{document.extracted_date || 'NA'}</dd>
          <dt>{t('fields.amount')}</dt><dd>{document.extracted_amount || 'NA'}</dd>
        </dl>
      </div>
      <div className="text-section">
        <h2>{t('documents.ocrText')}</h2>
        <pre>{document.ocr_text || ''}</pre>
      </div>
    </section>
  )
}
