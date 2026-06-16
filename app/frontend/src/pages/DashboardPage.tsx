import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent, MutableRefObject, ReactNode } from 'react'
import { Check, ChevronDown, ClipboardCheck, CloudUpload, Copy, FileImage, FileText, Maximize2, Minus, Plus, RefreshCw, RotateCcw, Save, Sparkles, Trash2, UploadCloud, XCircle } from 'lucide-react'
import { api, previewUrl as documentPreviewUrl, thumbnailUrl as documentThumbnailUrl } from '../api/client'
import type { Document } from '../types'
import { useI18n } from '../i18n'

interface DashboardPageProps {
  onOpenRecord: (id: string) => void
  onOpenDocument: (id: string) => void
  onSearch: () => void
}

interface UploadDraftFile {
  id: string
  documentId: string | null
  recordId: string | null
  file: File | null
  filename: string
  sizeLabel: string
  previewUrl: string | null
  thumbnailUrl: string | null
  serverPreviewUrl: string | null
  mimeType: string | null
  kind: 'pdf' | 'image' | 'text'
  ocrStatus: 'completed' | 'running' | 'failed' | 'queued'
  extractedTitle: string
  ocrSnippet: string
  confidence: number
  metadata: MetadataFormState
  metadataSources: Record<string, FieldSourceInfo>
  qwenRunStatus: 'not_run' | 'disabled' | 'succeeded' | 'failed'
  qwenMessage: string
  qwenSuggestedFolder: string
}

interface MetadataFormState {
  collection: string
  documentType: string
  status: string
  title: string
  correspondent: string
  recipient: string
  date: string
  invoiceNo: string
  amount: string
  taxAmount: string
  currency: string
  tags: string[]
  notes: string
}

interface FieldSourceInfo {
  source: 'manual' | 'deterministic' | 'qwen' | 'imported'
  confidence?: number
  evidence?: string
}

interface ProcessingOptionsState {
  autoProcess: boolean
  autoOcr: boolean
  qwenAutofill: boolean
  qwenEnrichment: boolean
  overwriteManualValues: boolean
  preserveLockedFields: boolean
  ocrEngine: 'paddle_vl' | 'ppocrv6'
  ocrLanguage: string
  ocrPageMode: 'all' | 'first_n'
  ocrPageLimit: number
  extractTables: boolean
  collectionRules: boolean
}

interface SharedTitleState {
  sharedTitleBase: string
  applySharedTitleToDocuments: boolean
}

type QwenStatus = 'checking' | 'available' | 'unavailable'

const sampleMetadata: MetadataFormState = {
  collection: 'Eingangsrechnung',
  documentType: 'Rechnung',
  status: 'New',
  title: 'Demo_PR400000005_12/10/2020_205,25',
  correspondent: 'Demo Ges.mbh',
  recipient: 'UniTech Technische Produkte',
  date: '12/10/2020',
  invoiceNo: 'PR400000005',
  amount: '205,25',
  taxAmount: '28,05',
  currency: 'EUR',
  tags: ['invoice', '2020', 'supplier:demo'],
  notes: ''
}

const seededFiles: UploadDraftFile[] = [
  {
    id: 'seed-1',
    documentId: null,
    recordId: null,
    file: null,
    filename: 'Rechnung_PR400000005_12-10-2020_20525.pdf',
    sizeLabel: '205 KB',
    previewUrl: null,
    thumbnailUrl: null,
    serverPreviewUrl: null,
    mimeType: 'application/pdf',
    kind: 'pdf',
    ocrStatus: 'completed',
    extractedTitle: 'Demo_PR400000005_12/10/2020_205,25',
    ocrSnippet: 'Rechnung\nRechnungs-Nr.: PR400000005\nRechnungsdatum: 12.10.2020\nGesamtbetrag Brutto 205,25 EUR',
    confidence: 98,
    metadata: sampleMetadata,
    qwenRunStatus: 'succeeded',
    qwenMessage: 'Qwen suggested recipient and amount with evidence.',
    qwenSuggestedFolder: 'Eingangsrechnung/Demo/2020',
    metadataSources: {
      title: { source: 'deterministic', confidence: 98 },
      invoiceNo: { source: 'deterministic', confidence: 97 },
      date: { source: 'deterministic', confidence: 96 },
      amount: { source: 'qwen', confidence: 92 },
      correspondent: { source: 'deterministic', confidence: 91 },
      recipient: { source: 'qwen', confidence: 88 }
    }
  },
  {
    id: 'seed-2',
    documentId: null,
    recordId: null,
    file: null,
    filename: 'Beleg_Reise_Muc_2020-10-05_45,30.jpg',
    sizeLabel: '120 KB',
    previewUrl: null,
    thumbnailUrl: null,
    serverPreviewUrl: null,
    mimeType: 'image/jpeg',
    kind: 'image',
    ocrStatus: 'completed',
    extractedTitle: 'CommerceBank_B_04/26_NA_NA',
    ocrSnippet: 'Beleg Reise München\nDatum 05.10.2020\nBetrag 45,30 EUR',
    confidence: 96,
    metadata: { ...sampleMetadata, collection: 'Belege', documentType: 'Beleg', title: 'CommerceBank_B_04/26_NA_NA', correspondent: 'CommerceBank', recipient: '', invoiceNo: '', amount: '', taxAmount: '' },
    qwenRunStatus: 'not_run',
    qwenMessage: 'Qwen has not run for this sample.',
    qwenSuggestedFolder: '',
    metadataSources: {
      title: { source: 'deterministic', confidence: 93 },
      correspondent: { source: 'deterministic', confidence: 90 }
    }
  }
]

const defaultProcessingOptions: ProcessingOptionsState = {
  autoProcess: true,
  autoOcr: true,
  qwenAutofill: false,
  qwenEnrichment: false,
  overwriteManualValues: false,
  preserveLockedFields: true,
  ocrEngine: 'paddle_vl',
  ocrLanguage: 'deu+eng',
  ocrPageMode: 'all',
  ocrPageLimit: 10,
  extractTables: false,
  collectionRules: true
}

export default function DashboardPage({ onOpenRecord, onOpenDocument }: DashboardPageProps) {
  const { t } = useI18n()
  const [files, setFiles] = useState<UploadDraftFile[]>(seededFiles)
  const [selectedId, setSelectedId] = useState(seededFiles[0].id)
  const [collectionName, setCollectionNameState] = useState(sampleMetadata.collection)
  const [processingOptions, setProcessingOptions] = useState<ProcessingOptionsState>(defaultProcessingOptions)
  const [sharedTitle, setSharedTitle] = useState<SharedTitleState>({ sharedTitleBase: '', applySharedTitleToDocuments: false })
  const [folderPath, setFolderPath] = useState('')
  const [qwenStatus, setQwenStatus] = useState<QwenStatus>('checking')
  const [uploadedRecordId, setUploadedRecordId] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<'process' | 'ocr' | 'metadata' | 'review' | 'delete' | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)
  const selected = useMemo(() => files.find((file) => file.id === selectedId) || files[0], [files, selectedId])
  const metadata = selected?.metadata || sampleMetadata
  const qwenAvailable = qwenStatus === 'available'

  useEffect(() => {
    void api.integrations().then((summary) => {
      const qwen = summary.integrations.find((item) => item.name.toLowerCase().includes('qwen'))
      const ok = Boolean(qwen?.ok)
      setQwenStatus(ok ? 'available' : 'unavailable')
      if (ok) setProcessingOptions((current) => ({ ...current, qwenAutofill: true, qwenEnrichment: true }))
    }).catch(() => setQwenStatus('unavailable'))
  }, [])

  function setCollectionName(value: string) {
    const next = value || 'Dokumente'
    setCollectionNameState(next)
    setFiles((current) => current.map((file) => ({ ...file, metadata: { ...file.metadata, collection: next } })))
  }

  function updateSelectedMetadata(value: MetadataFormState) {
    setFiles((current) => current.map((file) => file.id === selectedId ? {
      ...file,
      extractedTitle: value.title || file.extractedTitle,
      metadata: value,
      metadataSources: markChangedSources(file.metadata, value, file.metadataSources)
    } : file))
  }

  function addFiles(list: FileList | File[]) {
    const next: UploadDraftFile[] = Array.from(list).map((file, index) => {
      const kind = kindFromFile(file)
      return {
        id: `${file.name}-${file.lastModified}-${index}`,
        documentId: null,
        recordId: null,
        file,
        filename: file.name,
        sizeLabel: formatBytes(file.size),
        previewUrl: kind === 'image' ? URL.createObjectURL(file) : null,
        thumbnailUrl: null,
        serverPreviewUrl: null,
        mimeType: file.type || null,
        kind,
        ocrStatus: 'queued' as const,
        extractedTitle: file.name.replace(/\.[^.]+$/, ''),
        ocrSnippet: 'Queued for OCR. Select Run OCR after saving the record.',
        confidence: 0,
        metadata: { ...sampleMetadata, collection: collectionName, title: '', correspondent: '', recipient: '', date: '', invoiceNo: '', amount: '', taxAmount: '', notes: '' },
        qwenRunStatus: 'not_run' as const,
        qwenMessage: 'Qwen will fill missing metadata after OCR when enabled.',
        qwenSuggestedFolder: '',
        metadataSources: {}
      }
    })
    if (!next.length) return
    setFiles((current) => [...current.filter((file) => !file.id.startsWith('seed-')), ...next])
    setUploadedRecordId(null)
    setSelectedId(next[0].id)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const realItems = files.filter((item) => Boolean(item.file))
    if (!realItems.length) {
      setMessage(t('dashboard.message.addFiles'))
      return
    }
    setBusy(true)
    setMessage('')
    const form = new FormData()
    form.set('collection_name', collectionName || 'Dokumente')
    form.set('label', sharedTitle.sharedTitleBase || `${collectionName || 'Dokumente'} upload`)
    form.set('processing_options_json', JSON.stringify(toProcessingPayload(processingOptions, qwenAvailable)))
    form.set('record_metadata_json', JSON.stringify({
      shared_title_base: sharedTitle.sharedTitleBase,
      apply_shared_title_to_documents: sharedTitle.applySharedTitleToDocuments,
      folder_path: folderPath
    }))
    form.set('document_metadata_json', JSON.stringify(realItems.map((item) => toDocumentMetadataPayload(item.metadata, item.metadataSources, processingOptions))))
    realItems.forEach((item) => item.file && form.append('files', item.file))
    try {
      const batch = await api.uploadBatch(form)
      const first = batch.documents[0]
      setFiles(batch.documents.map((document, index) => draftFromDocument(document, index)))
      setUploadedRecordId(first?.record_id || null)
      if (first?.collection_name) setCollectionNameState(first.collection_name)
      if (first) setSelectedId(first.id)
      setMessage(`${t('dashboard.message.uploadedPrefix')} ${batch.documents.length} ${batch.documents.length === 1 ? t('dashboard.message.fileSingular') : t('dashboard.message.filePlural')} ${t('dashboard.message.uploadedSuffix')}`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('dashboard.message.uploadFailed'))
    } finally {
      setBusy(false)
    }
  }

  async function processAll() {
    if (!uploadedRecordId && !selected?.documentId) {
      setMessage(t('dashboard.message.uploadFirst'))
      return
    }
    setActionBusy('process')
    setMessage('')
    const qwenRequested = (processingOptions.qwenAutofill || processingOptions.qwenEnrichment) && qwenAvailable
    try {
      if (uploadedRecordId) {
        const result = await api.processRecord(uploadedRecordId, {
          qwenEnabled: qwenRequested,
          overwriteManualValues: processingOptions.overwriteManualValues
        })
        setFiles((current) => current.map((file) => file.documentId ? { ...file, ocrStatus: 'running', ocrSnippet: t('dashboard.message.pipelineQueuedDetail') } : file))
        setMessage(`${t('dashboard.message.processingQueuedPrefix')} ${result.queued} ${result.queued === 1 ? t('dashboard.message.documentSingular') : t('dashboard.message.documentPlural')}.`)
      } else if (selected?.documentId) {
        const document = await api.processDocument(selected.documentId, {
          qwenEnabled: qwenRequested,
          overwriteManualValues: processingOptions.overwriteManualValues
        })
        updateDraftFromDocument(document)
        setMessage(t('dashboard.message.processingSelected'))
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('dashboard.message.processingFailed'))
    } finally {
      setActionBusy(null)
    }
  }

  async function deleteSelected() {
    if (!selected?.documentId) {
      setFiles((current) => {
        const remaining = current.filter((file) => file.id !== selectedId)
        if (remaining[0]) setSelectedId(remaining[0].id)
        return remaining.length ? remaining : seededFiles
      })
      return
    }
    if (!confirm(`${t('dashboard.confirmDeletePrefix')} "${selected.filename}"? ${t('dashboard.confirmDeleteSuffix')}`)) return
    setActionBusy('delete')
    try {
      await api.deleteDocument(selected.documentId)
      setFiles((current) => {
        const remaining = current.filter((file) => file.documentId !== selected.documentId)
        if (remaining[0]) setSelectedId(remaining[0].id)
        return remaining.length ? remaining : seededFiles
      })
      setMessage(t('dashboard.message.documentDeleted'))
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('dashboard.message.deleteFailed'))
    } finally {
      setActionBusy(null)
    }
  }

  async function runSelected(action: 'ocr' | 'metadata' | 'review') {
    if (!selected?.documentId) {
      setMessage('Save the record before running actions on a real document.')
      return
    }
    setActionBusy(action)
    setMessage('')
    try {
      let document: Document
      if (action === 'ocr') {
        document = await api.runDocumentOcr(selected.documentId, 'redo')
      } else if (action === 'metadata') {
        document = await api.reextractDocument(selected.documentId, {
          qwenEnabled: (processingOptions.qwenAutofill || processingOptions.qwenEnrichment) && qwenAvailable,
          overwriteManualValues: processingOptions.overwriteManualValues
        })
      } else {
        document = await api.patchDocument(selected.documentId, { review_state: 'needs_review', review_reason: 'Sent from upload dashboard' })
      }
      updateDraftFromDocument(document)
      setMessage(action === 'ocr' ? 'OCR finished or queued for the selected document.' : action === 'metadata' ? 'Metadata extraction finished for the selected document.' : 'Selected document sent to review.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setActionBusy(null)
    }
  }

  function updateDraftFromDocument(document: Document) {
    setFiles((current) => current.map((file, index) => file.documentId === document.id ? draftFromDocument(document, index, file) : file))
    setSelectedId(document.id)
    if (document.record_id) setUploadedRecordId(document.record_id)
  }

  return (
    <main className="upload-dashboard">
      <header className="upload-header">
        <div>
          <h1>{t('dashboard.title')}</h1>
          <p>{t('dashboard.subtitle')}</p>
        </div>
        <div className="upload-header-actions">
          <button type="button" disabled={!uploadedRecordId} onClick={() => uploadedRecordId && onOpenRecord(uploadedRecordId)}>{t('dashboard.openRecord')}</button>
          <button type="button" disabled={!selected?.documentId} onClick={() => selected?.documentId && onOpenDocument(selected.documentId)}>{t('dashboard.openSelectedDocument')}</button>
          <button type="button" disabled={actionBusy === 'delete'} onClick={() => void deleteSelected()}><Trash2 size={15} /> {t('dashboard.deleteSelected')}</button>
        </div>
      </header>
      {message && <p className={message.toLowerCase().includes('failed') || message.toLowerCase().includes(t('dashboard.message.addFiles').toLowerCase().slice(0, 8)) ? 'error' : 'success-message'}>{message}</p>}
      <form className="upload-dashboard-grid upload-redesign-grid" onSubmit={submit}>
        <section className="upload-left-workspace">
          <aside className="upload-queue-rail">
            <UploadDropzone inputRef={inputRef} files={files} busy={busy} onFiles={addFiles} />
          </aside>

          <section className="upload-review-workspace">
            <section className="workflow-card review-combo-card document-preview-shell">
              <FilePreviewCard selected={selected} files={files} selectedId={selectedId} setSelectedId={setSelectedId} onAddMore={() => inputRef.current?.click()} />
            </section>
          </section>

          <ProcessingProfilePanel options={processingOptions} setOptions={setProcessingOptions} qwenStatus={qwenStatus} />
        </section>

        <aside className="metadata-redesign-rail">
          <NextActionsBar
            disabled={Boolean(actionBusy) || busy}
            hasUploadedRecord={Boolean(uploadedRecordId)}
            actionBusy={actionBusy}
            onProcessAll={() => void processAll()}
            onRunOcr={() => void runSelected('ocr')}
            onExtract={() => void runSelected('metadata')}
            onReview={() => void runSelected('review')}
          />
          <RecordSetupCard collectionName={collectionName} setCollectionName={setCollectionName} value={sharedTitle} setValue={setSharedTitle} folderPath={folderPath} setFolderPath={setFolderPath} />
          <MetadataForm metadata={metadata} setMetadata={updateSelectedMetadata} busy={busy} selected={selected} collectionName={collectionName} setCollectionName={setCollectionName} />
          <OCRTextPreview selected={selected} />
          <ProcessingOptionsPanel options={processingOptions} setOptions={setProcessingOptions} qwenStatus={qwenStatus} />
        </aside>
      </form>
    </main>
  )
}

function UploadDropzone({ inputRef, files, busy, onFiles }: { inputRef: MutableRefObject<HTMLInputElement | null>; files: UploadDraftFile[]; busy: boolean; onFiles: (files: FileList | File[]) => void }) {
  const { t } = useI18n()
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    onFiles(event.dataTransfer.files)
  }
  return (
    <section className="workflow-card upload-card">
      <h2>{t('dashboard.uploadFile')}</h2>
      <div className="upload-card-grid">
        <div className="dropzone" onDrop={drop} onDragOver={(event) => event.preventDefault()}>
          <CloudUpload size={54} />
          <strong>{t('dashboard.dropFile')}</strong>
          <span>{t('common.or', 'or')}</span>
          <button type="button" className="primary split-button" onClick={() => inputRef.current?.click()} disabled={busy}>
            {t('dashboard.uploadFileButton')} <ChevronDown size={16} />
          </button>
          <small>{t('dashboard.fileSupport')}</small>
          <input ref={inputRef} hidden type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,application/pdf,image/jpeg,image/png,image/webp,image/tiff" onChange={(event: ChangeEvent<HTMLInputElement>) => event.target.files && onFiles(event.target.files)} />
        </div>
        <div className="recent-uploads">
          <div className="mini-heading">
            <strong>{t('dashboard.recentUploads')}</strong>
            <span>{files.length} {files.length === 1 ? t('dashboard.file') : t('dashboard.files')}</span>
          </div>
          {files.slice(0, 3).map((file) => (
            <div className="recent-upload-row" key={file.id}>
              <FileKindIcon kind={file.kind} />
              <span><strong>{file.filename}</strong><small>{file.sizeLabel} · {file.extractedTitle}</small></span>
              <Check size={18} />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function RecordSetupCard({ collectionName, setCollectionName, value, setValue, folderPath, setFolderPath }: { collectionName: string; setCollectionName: (value: string) => void; value: SharedTitleState; setValue: (value: SharedTitleState) => void; folderPath: string; setFolderPath: (value: string) => void }) {
  const { t } = useI18n()
  const active = value.applySharedTitleToDocuments && value.sharedTitleBase.trim()
  const example = collectionName === 'Belege'
    ? `${value.sharedTitleBase || 'Telekom'}_B_10/24_90,74_Karte`
    : `${value.sharedTitleBase || 'Telekom'}_12345_12/10/2024_90,74`
  return (
    <details className="workflow-card shared-title-card record-setup-panel">
      <summary><span><ChevronDown size={16} /> {t('dashboard.recordSetup')}</span></summary>
      <p>{t('dashboard.recordSetupCopy')}</p>
      <div className="shared-title-controls">
        <label>
          {t('dashboard.collection')}
          <select value={collectionName} onChange={(event) => setCollectionName(event.target.value)}>
            <option>Dokumente</option>
            <option>Eingangsrechnung</option>
            <option>Ausgangsrechnung</option>
            <option>Belege</option>
          </select>
        </label>
        <label>
          {t('dashboard.sharedTitleBase')}
          <input
            value={value.sharedTitleBase}
            onChange={(event) => setValue({ ...value, sharedTitleBase: event.target.value })}
            placeholder="Telekom"
          />
        </label>
        <Toggle
          label={t('dashboard.applySharedTitle')}
          checked={value.applySharedTitleToDocuments}
          onChange={(checked) => setValue({ ...value, applySharedTitleToDocuments: checked })}
        />
        <label>
          {t('dashboard.folderPath')}
          <input value={folderPath} onChange={(event) => setFolderPath(event.target.value)} placeholder={`${collectionName}/2024/10`} />
          <small>{t('dashboard.folderPathHelp')}</small>
        </label>
      </div>
      <div className={`shared-title-preview ${active ? 'active' : ''}`}>
        <span>{active ? t('dashboard.willGenerateTitles') : t('dashboard.previewWhenEnabled')}</span>
        <strong>{example}</strong>
      </div>
      {value.sharedTitleBase.trim() && !value.applySharedTitleToDocuments && (
        <small className="shared-title-hint">{t('dashboard.sharedTitleHint')}</small>
      )}
    </details>
  )
}

function MetadataForm({ metadata, setMetadata, busy, selected, collectionName, setCollectionName }: { metadata: MetadataFormState; setMetadata: (value: MetadataFormState) => void; busy: boolean; selected?: UploadDraftFile; collectionName: string; setCollectionName: (value: string) => void }) {
  const { t } = useI18n()
  const set = (key: keyof MetadataFormState, value: string | string[]) => setMetadata({ ...metadata, [key]: value })
  return (
    <details className="workflow-card metadata-card metadata-collapsible-panel">
      <summary><span><ChevronDown size={16} /> {t('dashboard.documentInformation')}</span></summary>
      <div className="metadata-grid">
        <FormField label={t('dashboard.recordCollection')} source={selected?.metadataSources.collection}><select value={collectionName} onChange={(event) => setCollectionName(event.target.value)}><option>Dokumente</option><option>Eingangsrechnung</option><option>Ausgangsrechnung</option><option>Belege</option></select></FormField>
        <FormField label={t('fields.documentType')} source={selected?.metadataSources.documentType}><select value={metadata.documentType} onChange={(event) => set('documentType', event.target.value)}><option value="">{t('common.none')}</option><option>Rechnung</option><option>Beleg</option><option>Vertrag</option><option>Dokument</option></select></FormField>
        <FormField label={t('fields.status')} source={selected?.metadataSources.status}><select value={metadata.status} onChange={(event) => set('status', event.target.value)}><option>{t('status.new')}</option><option>{t('status.ocrRunning')}</option><option>{t('status.needsReview')}</option><option>{t('status.synced')}</option></select></FormField>
        <FormField label={t('fields.title')} source={selected?.metadataSources.title} wide><input value={metadata.title} onChange={(event) => set('title', event.target.value)} placeholder={t('dashboard.optionalGeneratedLater')} /></FormField>
        <FormField label={t('fields.correspondentSender')} source={selected?.metadataSources.correspondent}><input value={metadata.correspondent} onChange={(event) => set('correspondent', event.target.value)} placeholder={t('common.optional')} /></FormField>
        <FormField label={t('fields.date')} source={selected?.metadataSources.date}><input value={metadata.date} onChange={(event) => set('date', event.target.value)} placeholder={t('common.optional')} /></FormField>
        <FormField label={t('fields.invoiceNumber')} source={selected?.metadataSources.invoiceNo}><input value={metadata.invoiceNo} onChange={(event) => set('invoiceNo', event.target.value)} placeholder={t('common.optional')} /></FormField>
        <FormField label={t('fields.recipientCustomer')}><input value={metadata.recipient} onChange={(event) => set('recipient', event.target.value)} /></FormField>
        <FormField label={t('fields.amountGross')} source={selected?.metadataSources.amount}><div className="input-combo"><input value={metadata.amount} onChange={(event) => set('amount', event.target.value)} placeholder={t('common.optional')} /><span>{metadata.currency}</span></div></FormField>
        <FormField label={t('fields.taxAmount')} source={selected?.metadataSources.taxAmount}><input value={metadata.taxAmount} onChange={(event) => set('taxAmount', event.target.value)} placeholder={t('common.optional')} /></FormField>
        <FormField label={t('fields.currency')}><select value={metadata.currency} onChange={(event) => set('currency', event.target.value)}><option>EUR</option><option>USD</option><option>CHF</option></select></FormField>
        <FormField label={t('fields.tags')}><TagInput tags={metadata.tags} onChange={(tags) => set('tags', tags)} /></FormField>
        <FormField label={t('fields.notesDescription')}><textarea value={metadata.notes} onChange={(event) => set('notes', event.target.value)} placeholder={t('dashboard.notesPlaceholder')} /></FormField>
      </div>
      <div className="button-row form-actions">
        <button className="primary" disabled={busy}><Save size={17} /> {t('dashboard.saveRecord')}</button>
        <button type="button">{t('dashboard.saveDraft')}</button>
        <button type="button"><RotateCcw size={17} /> {t('common.reset')}</button>
      </div>
    </details>
  )
}

function ProcessingProfilePanel({ options, setOptions, qwenStatus }: { options: ProcessingOptionsState; setOptions: (value: ProcessingOptionsState) => void; qwenStatus: QwenStatus }) {
  const { t } = useI18n()
  const qwenAvailable = qwenStatus === 'available'
  const profiles = [
    {
      key: 'quick',
      title: t('dashboard.profileQuick'),
      copy: t('dashboard.profileQuickCopy'),
      tag: t('dashboard.profileQuickTag'),
      icon: <RefreshCw size={24} />,
      active: options.ocrEngine === 'ppocrv6' && options.ocrPageMode === 'first_n',
      patch: { ocrEngine: 'ppocrv6' as const, ocrPageMode: 'first_n' as const, ocrPageLimit: 3, qwenAutofill: false, qwenEnrichment: false, extractTables: false }
    },
    {
      key: 'standard',
      title: t('dashboard.profileStandard'),
      copy: t('dashboard.profileStandardCopy'),
      tag: t('dashboard.profileStandardTag'),
      icon: <FileText size={24} />,
      active: options.ocrEngine === 'paddle_vl' && options.qwenAutofill && !options.qwenEnrichment,
      patch: { ocrEngine: 'paddle_vl' as const, ocrPageMode: 'all' as const, ocrPageLimit: 100, qwenAutofill: qwenAvailable, qwenEnrichment: false, extractTables: true, collectionRules: true }
    },
    {
      key: 'accuracy',
      title: t('dashboard.profileAccuracy'),
      copy: t('dashboard.profileAccuracyCopy'),
      tag: t('dashboard.profileAccuracyTag'),
      icon: <Sparkles size={24} />,
      active: options.ocrEngine === 'paddle_vl' && options.qwenAutofill && options.qwenEnrichment,
      patch: { ocrEngine: 'paddle_vl' as const, ocrPageMode: 'all' as const, ocrPageLimit: 100, qwenAutofill: qwenAvailable, qwenEnrichment: qwenAvailable, extractTables: true, collectionRules: true, preserveLockedFields: true }
    },
    {
      key: 'archive',
      title: t('dashboard.profileArchive'),
      copy: t('dashboard.profileArchiveCopy'),
      tag: t('dashboard.profileArchiveTag'),
      icon: <ClipboardCheck size={24} />,
      active: options.collectionRules && options.preserveLockedFields && !options.overwriteManualValues,
      patch: { collectionRules: true, preserveLockedFields: true, overwriteManualValues: false, extractTables: true }
    }
  ]
  return (
    <section className="workflow-card processing-profile-card">
      <div className="card-title-row"><h2>{t('dashboard.processingProfiles')}</h2><span>{t('dashboard.processingProfilesCopy')}</span></div>
      <div className="processing-profile-grid">
        {profiles.map((profile) => (
          <button type="button" key={profile.key} className={`processing-profile-tile ${profile.active ? 'active' : ''}`} onClick={() => setOptions({ ...options, ...profile.patch })}>
            <span className="profile-icon">{profile.icon}</span>
            <strong>{profile.title}</strong>
            <small>{profile.copy}</small>
            <em>{profile.tag}</em>
            {profile.active && <b><Check size={15} /></b>}
          </button>
        ))}
      </div>
    </section>
  )
}

function ProcessingOptionsPanel({ options, setOptions, qwenStatus }: { options: ProcessingOptionsState; setOptions: (value: ProcessingOptionsState) => void; qwenStatus: QwenStatus }) {
  const { t } = useI18n()
  const set = (patch: Partial<ProcessingOptionsState>) => setOptions({ ...options, ...patch })
  const qwenAvailable = qwenStatus === 'available'
  return (
    <details className="workflow-card processing-options-card collapsed-ocr-options">
      <summary>
        <span><ChevronDown size={17} /> {t('dashboard.processingOptions')}</span>
        <small>{t('dashboard.processingOptionsCollapsed')}</small>
        {qwenStatus !== 'available' && <span className="option-warning">{qwenStatus === 'checking' ? t('dashboard.checkingQwen') : t('dashboard.qwenUnavailable')}</span>}
      </summary>
      <p>{t('dashboard.qwenProcessingCopy')}</p>
      <div className="processing-options-grid">
        <Toggle label={t('dashboard.autoProcess')} checked={options.autoProcess} onChange={(checked) => set({ autoProcess: checked })} />
        <Toggle label={t('dashboard.autoOcr')} checked={options.autoOcr} onChange={(checked) => set({ autoOcr: checked })} />
        <Toggle label={t('dashboard.qwenAutofill')} checked={options.qwenAutofill && qwenAvailable} disabled={!qwenAvailable} onChange={(checked) => set({ qwenAutofill: checked })} />
        <Toggle label={t('dashboard.qwenEnrichment')} checked={options.qwenEnrichment && qwenAvailable} disabled={!qwenAvailable} onChange={(checked) => set({ qwenEnrichment: checked, qwenAutofill: checked || options.qwenAutofill })} />
        <Toggle label={t('dashboard.overwriteManual')} checked={options.overwriteManualValues} onChange={(checked) => set({ overwriteManualValues: checked })} />
        <Toggle label={t('dashboard.preserveManual')} checked={options.preserveLockedFields} onChange={(checked) => set({ preserveLockedFields: checked })} />
        <label>{t('dashboard.ocrEngine')}<select value={options.ocrEngine} onChange={(event) => set({ ocrEngine: event.target.value as ProcessingOptionsState['ocrEngine'] })}><option value="paddle_vl">{t('dashboard.smartParser')} · PaddleOCR-VL</option><option value="ppocrv6">{t('dashboard.fastOcr')} · PP-OCRv6 medium</option></select></label>
        <label>{t('dashboard.ocrLanguage')}<select value={options.ocrLanguage} onChange={(event) => set({ ocrLanguage: event.target.value })}><option value="deu+eng">{t('dashboard.germanEnglish')}</option><option value="auto">{t('dashboard.autoDetect')}</option><option value="deu">{t('language.de')}</option><option value="eng">{t('language.en')}</option></select></label>
        <label>{t('dashboard.ocrPages')}<select value={options.ocrPageMode} onChange={(event) => set({ ocrPageMode: event.target.value as ProcessingOptionsState['ocrPageMode'] })}><option value="all">{t('dashboard.allPages')}</option><option value="first_n">{t('dashboard.firstNPages')}</option></select></label>
        <label>{t('dashboard.pageLimit')}<input type="number" min="1" max="100" value={options.ocrPageLimit} onChange={(event) => set({ ocrPageLimit: Number(event.target.value) || 1 })} /></label>
        <Toggle label={t('dashboard.extractTables')} checked={options.extractTables} onChange={(checked) => set({ extractTables: checked })} />
        <Toggle label={t('dashboard.collectionRules')} checked={options.collectionRules} onChange={(checked) => set({ collectionRules: checked })} />
      </div>
    </details>
  )
}

function FilePreviewCard({ selected, files, selectedId, setSelectedId, onAddMore }: { selected?: UploadDraftFile; files: UploadDraftFile[]; selectedId: string; setSelectedId: (id: string) => void; onAddMore: () => void }) {
  const { t } = useI18n()
  const [zoom, setZoom] = useState(100)
  const [rotation, setRotation] = useState(0)
  const [showOcr, setShowOcr] = useState(true)
  const previewSurfaceRef = useRef<HTMLDivElement | null>(null)
  const isPdf = selected?.kind === 'pdf'
  const mediaStyle = isPdf
    ? { width: `${zoom}%`, maxWidth: zoom <= 100 ? '100%' : 'none', height: `${Math.round(620 * zoom / 100)}px` }
    : { width: `${zoom}%`, maxWidth: zoom <= 100 ? '100%' : 'none' }

  useEffect(() => {
    setZoom(100)
    setRotation(0)
  }, [selected?.id])

  function clampZoom(value: number) {
    return Math.min(400, Math.max(50, value))
  }

  function centerRatio() {
    const surface = previewSurfaceRef.current
    if (!surface || !surface.scrollWidth || !surface.scrollHeight) return { x: 0.5, y: 0.5 }
    return {
      x: (surface.scrollLeft + surface.clientWidth / 2) / surface.scrollWidth,
      y: (surface.scrollTop + surface.clientHeight / 2) / surface.scrollHeight
    }
  }

  function setZoomAround(nextZoom: number, ratio = centerRatio()) {
    const surface = previewSurfaceRef.current
    setZoom(clampZoom(nextZoom))
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!surface) return
      surface.scrollLeft = Math.max(0, Math.min(surface.scrollWidth - surface.clientWidth, ratio.x * surface.scrollWidth - surface.clientWidth / 2))
      surface.scrollTop = Math.max(0, Math.min(surface.scrollHeight - surface.clientHeight, ratio.y * surface.scrollHeight - surface.clientHeight / 2))
    }))
  }

  function handlePreviewClick(event: MouseEvent<HTMLDivElement>) {
    if (isPdf) return
    const media = event.currentTarget.querySelector('.upload-zoomable-preview-media') as HTMLElement | null
    if (!media) return
    const rect = media.getBoundingClientRect()
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
    setZoomAround(zoom >= 220 ? 100 : Math.max(220, zoom + 80), { x, y })
  }

  const preview = selected?.serverPreviewUrl && selected.kind === 'pdf' ? (
    <iframe className="upload-zoomable-preview-media" style={mediaStyle} src={selected.serverPreviewUrl} title={selected.filename} />
  ) : selected?.serverPreviewUrl && selected.kind === 'image' ? (
    <img className="upload-zoomable-preview-media" style={mediaStyle} src={selected.serverPreviewUrl} alt={selected.filename} />
  ) : selected?.previewUrl ? (
    <img className="upload-zoomable-preview-media" style={mediaStyle} src={selected.previewUrl} alt={selected.filename} />
  ) : selected?.kind === 'pdf' ? (
    <PdfMockup />
  ) : (
    <InvoiceMockup />
  )

  return (
    <section className="file-preview-card document-preview-card">
      <div className="document-preview-heading">
        <h2>{t('dashboard.filePreview')}</h2>
        <span>{selected?.filename || t('dashboard.noFileSelected')}</span>
      </div>
      <div className="document-preview-toolbar upload-preview-toolbar">
        <span><Maximize2 size={16} /> Zoom</span>
        <button type="button" onClick={() => setZoomAround(zoom - 25)} aria-label={t('common.zoomOut')}><Minus size={15} /></button>
        <button type="button" className="zoom-value" onClick={() => setZoomAround(100, { x: 0.5, y: 0.5 })} aria-label={t('common.resetZoom')}>{zoom}%</button>
        <button type="button" onClick={() => setZoomAround(zoom + 25)} aria-label={t('common.zoomIn')}><Plus size={15} /></button>
        <i />
        <button type="button" onClick={() => setRotation((value) => (value + 90) % 360)}><RefreshCw size={16} /> {t('dashboard.rotate')}</button>
        <i />
        <label>{t('dashboard.showOcr')}<input type="checkbox" checked={showOcr} onChange={(event) => setShowOcr(event.target.checked)} /></label>
      </div>
      <div className="document-preview-layout">
        <AttachmentStrip files={files} selectedId={selectedId} onSelect={setSelectedId} onAddMore={onAddMore} />
        <div ref={previewSurfaceRef} className={`document-preview-surface upload-zoomable-preview ${showOcr ? 'show-ocr-overlay' : ''}`} onClick={handlePreviewClick}>
          <div className="document-preview-stage">
            <div className="document-preview-object" style={{ transform: `rotate(${rotation}deg)` }}>
              {preview}
            </div>
          </div>
          {showOcr && selected?.ocrSnippet && <pre className="document-preview-ocr-overlay">{selected.ocrSnippet}</pre>}
        </div>
      </div>
    </section>
  )
}

function AttachmentStrip({ files, selectedId, onSelect, onAddMore }: { files: UploadDraftFile[]; selectedId: string; onSelect: (id: string) => void; onAddMore: () => void }) {
  const { t } = useI18n()
  return (
    <div className="attachment-strip">
      {files.map((file, index) => (
        <button type="button" key={file.id} className={`attachment-tile ${file.id === selectedId ? 'selected' : ''}`} onClick={() => onSelect(file.id)}>
          <span className="attachment-thumb"><DocumentThumb file={file} /></span>
          <span className={`status-dot dot-${file.ocrStatus}`} />
          <strong>{index + 1}</strong>
          <span className="attachment-popover">
            <b>{file.filename}</b>
            <small>{file.sizeLabel} · OCR {file.ocrStatus}</small>
            <small>{file.extractedTitle}</small>
            <dl>
              <dt>{t('dashboard.collection')}</dt><dd>{file.metadata.collection || 'Dokumente'}</dd>
              <dt>{t('fields.invoice')}</dt><dd>{file.metadata.invoiceNo || 'NA'}</dd>
              <dt>{t('fields.date')}</dt><dd>{file.metadata.date || 'NA'}</dd>
              <dt>{t('fields.amount')}</dt><dd>{file.metadata.amount ? `${file.metadata.amount} ${file.metadata.currency}` : 'NA'}</dd>
            </dl>
            <p>{file.ocrSnippet}</p>
            <em>{t('fields.confidence')} {file.confidence || 0}%</em>
          </span>
        </button>
      ))}
      <button type="button" className="attachment-tile add-more" onClick={onAddMore}><Plus size={30} /><span>{t('dashboard.addMore')}</span></button>
    </div>
  )
}

function OCRStatusCard({ selected, onRunAgain }: { selected?: UploadDraftFile; onRunAgain: () => void }) {
  const { t } = useI18n()
  const done = selected?.ocrStatus === 'completed'
  return <InspectorCard title={t('dashboard.ocrStatus')}><div className="status-card-row"><span className={done ? 'round-icon success' : 'round-icon warning'}>{done ? <Check size={18} /> : <RefreshCw size={18} />}</span><span><strong>{done ? t('dashboard.ocrCompleted') : t('dashboard.ocrQueued')}</strong><small>{done ? t('dashboard.completedExample') : t('dashboard.waitingWorker')}</small></span><button type="button" onClick={onRunAgain}><RefreshCw size={16} /> {t('dashboard.runOcrAgain')}</button></div></InspectorCard>
}

function MetadataExtractionCard({ selected, qwenStatus, qwenEnabled, onRunAgain }: { selected?: UploadDraftFile; qwenStatus: QwenStatus; qwenEnabled: boolean; onRunAgain: () => void }) {
  const { t } = useI18n()
  const label = qwenStatus === 'checking' ? t('status.checking') : qwenEnabled ? t('status.enabled') : qwenStatus === 'available' ? t('status.disabled') : t('status.unavailable')
  const runLabel = selected?.qwenRunStatus === 'succeeded' ? t('dashboard.qwenFilled') : selected?.qwenRunStatus === 'failed' ? t('dashboard.qwenFailed') : selected?.qwenRunStatus === 'disabled' ? t('dashboard.qwenDidNotRun') : t('dashboard.qwenPending')
  return (
    <InspectorCard title={t('dashboard.aiMetadataExtraction')}>
      <p className="model-line">{t('dashboard.model')}: <strong>Qwen Metadata</strong> <span className={qwenEnabled ? '' : 'muted-chip'}>{label}</span></p>
      <div className={`qwen-run-state qwen-${selected?.qwenRunStatus || 'not_run'}`}>
        <strong>{runLabel}</strong>
        <small>{selected?.qwenMessage || t('dashboard.qwenProcessingCopy')}</small>
        {selected?.qwenSuggestedFolder && <small>{t('dashboard.suggestedFolder')}: {selected.qwenSuggestedFolder}</small>}
      </div>
      <button type="button" onClick={onRunAgain}><Sparkles size={16} /> {t('dashboard.extractMetadataAgain')}</button>
    </InspectorCard>
  )
}

function ExtractedMetadataPreview({ metadata, sources }: { metadata: MetadataFormState; sources: Record<string, FieldSourceInfo> }) {
  const { t } = useI18n()
  const fields: Array<[string, string, FieldSourceInfo | undefined]> = [
    [t('fields.invoiceNumber'), metadata.invoiceNo, sources.invoiceNo],
    [t('fields.date'), metadata.date, sources.date],
    [t('fields.correspondent'), metadata.correspondent, sources.correspondent],
    [t('fields.recipient'), metadata.recipient, sources.recipient],
    [t('fields.amountGross'), `${metadata.amount} ${metadata.currency}`, sources.amount],
    [t('fields.taxAmount'), `${metadata.taxAmount} ${metadata.currency}`, sources.taxAmount],
    [t('fields.currency'), metadata.currency, sources.currency],
    [t('fields.dueDate'), '26/10/2020', undefined]
  ]
  return <InspectorCard title={t('dashboard.extractedMetadataPreview')}><div className="extracted-list">{fields.map(([label, value, source]) => <div key={label}><span>{label}</span><strong>{value || 'NA'}{source && <SourceBadge info={source} />}</strong><Check size={15} /></div>)}</div><button type="button" className="link-button">{t('dashboard.showMoreFields')}</button></InspectorCard>
}

function OCRTextPreview({ selected }: { selected?: UploadDraftFile }) {
  const { t } = useI18n()
  return (
    <details className="workflow-card inspector-card collapsed-side-panel ocr-side-panel">
      <summary><span><ChevronDown size={16} /> {t('dashboard.ocrTextPreview')}</span><small>{t('fields.confidence')}: {selected?.confidence || 0}%</small></summary>
      <pre className="ocr-preview">{selected?.ocrSnippet || ''}</pre>
      <div className="ocr-footer"><strong>{t('fields.confidence')}: {selected?.confidence || 0}%</strong><button type="button" onClick={() => navigator.clipboard?.writeText(selected?.ocrSnippet || '')}><Copy size={16} /> {t('common.copyText')}</button></div>
    </details>
  )
}

function NextActionsBar({ disabled, hasUploadedRecord, actionBusy, onProcessAll, onRunOcr, onExtract, onReview }: { disabled: boolean; hasUploadedRecord: boolean; actionBusy: 'process' | 'ocr' | 'metadata' | 'review' | 'delete' | null; onProcessAll: () => void; onRunOcr: () => void; onExtract: () => void; onReview: () => void }) {
  const { t } = useI18n()
  return (
    <section className="workflow-card next-actions">
      <h2>{t('dashboard.nextActions')}</h2>
      <div className="primary-process-row">
        {hasUploadedRecord ? (
          <button type="button" className="primary process-button" disabled={disabled} onClick={onProcessAll}>
            <Sparkles size={18} /> {actionBusy === 'process' ? t('common.processingEllipsis') : t('dashboard.processAllDocuments')}
          </button>
        ) : (
          <button type="submit" className="primary process-button" disabled={disabled}>
            <Sparkles size={18} /> {t('dashboard.uploadProcessAll')}
          </button>
        )}
        <span>{t('dashboard.pipelineDescription')}</span>
      </div>
      <details className="advanced-actions">
        <summary>{t('dashboard.advancedActions')}</summary>
        <div>
          <button type="button" disabled={disabled} onClick={onRunOcr}><RefreshCw size={17} /> {actionBusy === 'ocr' ? t('dashboard.runningOcr') : t('dashboard.runOcrOnly')}</button>
          <button type="button" disabled={disabled} onClick={onExtract}><Sparkles size={17} /> {actionBusy === 'metadata' ? t('dashboard.extracting') : t('dashboard.extractMetadataOnly')}</button>
          <button type="button" disabled={disabled}><ClipboardCheck size={17} /> {t('dashboard.validateData')}</button>
          <button type="button" disabled={disabled}><UploadCloud size={17} /> {t('dashboard.rebuildSearchSync')}</button>
          <button type="button" disabled={disabled} onClick={onReview}><XCircle size={17} /> {actionBusy === 'review' ? t('dashboard.sending') : t('dashboard.sendToReview')}</button>
        </div>
      </details>
    </section>
  )
}

function InspectorCard({ title, children }: { title: string; children: ReactNode }) {
  return <section className="workflow-card inspector-card"><h2>{title}</h2>{children}</section>
}

function Toggle({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  return <label className={`toggle-row ${disabled ? 'disabled' : ''}`}><input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /><span>{label}</span></label>
}

function FormField({ label, wide, source, children }: { label: string; wide?: boolean; source?: FieldSourceInfo; children: ReactNode }) {
  return <label className={wide ? 'wide-field' : ''}><span>{label}{source && <SourceBadge info={source} />}</span>{children}</label>
}

function SourceBadge({ info }: { info: FieldSourceInfo }) {
  return <b className={`source-badge source-${info.source}`} title={info.evidence || undefined}>{info.source}{info.confidence ? ` ${info.confidence}%` : ''}</b>
}

function TagInput({ tags, onChange }: { tags: string[]; onChange: (tags: string[]) => void }) {
  return <div className="tag-input">{tags.map((tag) => <button type="button" key={tag} onClick={() => onChange(tags.filter((item) => item !== tag))}>{tag} <XCircle size={13} /></button>)}<button type="button" onClick={() => onChange([...tags, 'reviewed'])}><Plus size={15} /></button></div>
}

function FileKindIcon({ kind }: { kind: UploadDraftFile['kind'] }) {
  return <span className={`file-kind file-kind-${kind}`}>{kind === 'image' ? <FileImage size={22} /> : <FileText size={22} />}</span>
}

function DocumentThumb({ file }: { file: UploadDraftFile }) {
  const image = file.thumbnailUrl || file.previewUrl
  if (image) return <img src={image} alt="" />
  if (file.kind === 'pdf') return <PdfMockup tiny />
  if (file.kind === 'image') return <FileImage size={26} />
  return <FileText size={26} />
}

function PdfMockup({ tiny = false }: { tiny?: boolean }) {
  return <div className={tiny ? 'pdf-mock tiny' : 'pdf-mock'}><FileText size={tiny ? 22 : 48} /><strong>PDF</strong><span>First page preview after upload</span></div>
}

function InvoiceMockup({ tiny = false }: { tiny?: boolean }) {
  return <div className={tiny ? 'invoice-mock tiny' : 'invoice-mock'}><span /><span /><b>Rechnung</b><p /><p /><p /><i /><i /><strong /></div>
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function kindFromFile(file: File): UploadDraftFile['kind'] {
  const name = file.name.toLowerCase()
  if (file.type === 'application/pdf' || name.endsWith('.pdf')) return 'pdf'
  if (file.type.startsWith('image/') || /\.(jpe?g|png|webp|tiff?|tif)$/.test(name)) return 'image'
  return 'text'
}

function kindFromDocument(document: Document): UploadDraftFile['kind'] {
  const mime = document.mime_type || ''
  const name = document.original_filename.toLowerCase()
  if (mime === 'application/pdf' || name.endsWith('.pdf')) return 'pdf'
  if (mime.startsWith('image/') || /\.(jpe?g|png|webp|tiff?|tif)$/.test(name)) return 'image'
  return 'text'
}

function draftFromDocument(document: Document, index: number, previous?: UploadDraftFile): UploadDraftFile {
  const kind = kindFromDocument(document)
  const sources = fromDocumentSources(document.metadata_sources_json)
  return {
    id: document.id,
    documentId: document.id,
    recordId: document.record_id,
    file: null,
    filename: document.original_filename,
    sizeLabel: formatBytes(document.file_size),
    previewUrl: previous?.previewUrl || null,
    thumbnailUrl: document.thumbnail_path ? documentThumbnailUrl(document.id) : null,
    serverPreviewUrl: documentPreviewUrl(document.id),
    mimeType: document.mime_type,
    kind,
    ocrStatus: document.processing_state === 'failed' ? 'failed' : document.ocr_state === 'done' || document.ocr_state === 'skipped' ? 'completed' : document.processing_state === 'queued_for_ocr' ? 'queued' : 'running',
    extractedTitle: document.manual_title_override || document.extracted_title || document.original_filename,
    ocrSnippet: document.ocr_text || document.error_message || 'OCR has been queued for this file.',
    confidence: confidenceFromSources(sources, index),
    metadata: fromDocumentMetadata(document),
    metadataSources: sources,
    qwenRunStatus: qwenRunStatusFromDocument(document),
    qwenMessage: qwenMessageFromDocument(document),
    qwenSuggestedFolder: document.llm_suggested_folder || ''
  }
}

function confidenceFromSources(sources: Record<string, FieldSourceInfo>, index: number) {
  const values = Object.values(sources).map((source) => source.confidence).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  if (!values.length) return index === 0 ? 98 : 94
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
}

function markChangedSources(previous: MetadataFormState, next: MetadataFormState, sources: Record<string, FieldSourceInfo>) {
  const updated = { ...sources }
  for (const key of Object.keys(next) as Array<keyof MetadataFormState>) {
    if (JSON.stringify(previous[key]) !== JSON.stringify(next[key])) {
      updated[key] = { source: 'manual', confidence: 100 }
    }
  }
  return updated
}

function toProcessingPayload(options: ProcessingOptionsState, qwenAvailable: boolean) {
  const qwenEnabled = (options.qwenAutofill || options.qwenEnrichment) && qwenAvailable
  return {
    auto_ocr: options.autoOcr,
    auto_process: options.autoProcess,
    qwen_enabled: qwenEnabled,
    qwen_enrichment_enabled: qwenEnabled,
    overwrite_manual_values: options.overwriteManualValues,
    preserve_locked_fields: options.preserveLockedFields,
    skip_metadata: false,
    extract_tables: options.extractTables,
    collection_rules_enabled: options.collectionRules,
    ocr_engine: options.ocrEngine,
    language: options.ocrLanguage,
    page_limit: options.ocrPageMode === 'all' ? 100 : options.ocrPageLimit,
  }
}

function qwenRunStatusFromDocument(document: Document): UploadDraftFile['qwenRunStatus'] {
  const refinement = document.metadata_json.qwen_refinement as Record<string, unknown> | undefined
  const candidates = document.metadata_json.qwen_candidates as Record<string, unknown> | undefined
  if (refinement?.disabled === true) return 'disabled'
  if (refinement?.error || document.llm_raw_response?.metadata_brain_error) return 'failed'
  if (candidates && Object.keys(candidates).length > 0) return 'succeeded'
  return 'not_run'
}

function qwenMessageFromDocument(document: Document): string {
  const refinement = document.metadata_json.qwen_refinement as Record<string, unknown> | undefined
  const sourceValues = Object.values(fromDocumentSources(document.metadata_sources_json)).filter((item) => item.source === 'qwen')
  if (sourceValues.length) return `Qwen filled ${sourceValues.length} field${sourceValues.length === 1 ? '' : 's'}; hover badges for evidence.`
  if (refinement?.disabled === true) return 'Qwen did not run for this document.'
  if (refinement?.error) return String(refinement.error)
  if (document.llm_summary) return document.llm_summary
  return 'Qwen has not produced metadata candidates yet.'
}

function toDocumentMetadataPayload(metadata: MetadataFormState, sources: Record<string, FieldSourceInfo>, options: ProcessingOptionsState) {
  return {
    title: metadata.title,
    sender: metadata.correspondent,
    recipient: metadata.recipient,
    invoice_number: metadata.invoiceNo,
    date: metadata.date,
    amount: metadata.amount,
    tax_amount: metadata.taxAmount,
    currency: metadata.currency,
    document_type: metadata.documentType,
    tags: metadata.tags,
    notes: metadata.notes,
    field_locks: Object.fromEntries(Object.entries(sources).filter(([, info]) => info.source === 'manual' && options.preserveLockedFields).map(([field]) => [metadataFieldToCoreKey(field), true])),
  }
}

function metadataFieldToCoreKey(field: string) {
  const mapping: Record<string, string> = {
    invoiceNo: 'invoice_number',
    correspondent: 'sender',
    paymentMethod: 'payment_method'
  }
  return mapping[field] || field
}

function fromDocumentMetadata(document: { collection_name: string; extracted_title: string | null; manual_title_override: string | null; extracted_sender: string | null; extracted_recipient: string | null; extracted_date: string | null; extracted_invoice_number: string | null; extracted_amount: string | null; extracted_payment_method: string | null; metadata_json: Record<string, unknown> }): MetadataFormState {
  return {
    collection: document.collection_name,
    documentType: String(document.metadata_json.document_type || ''),
    status: 'New',
    title: document.manual_title_override || document.extracted_title || '',
    correspondent: document.extracted_sender || '',
    recipient: document.extracted_recipient || '',
    date: document.extracted_date || '',
    invoiceNo: document.extracted_invoice_number || '',
    amount: document.extracted_amount || '',
    taxAmount: String(document.metadata_json.tax_amount || ''),
    currency: String(document.metadata_json.currency || 'EUR'),
    tags: Array.isArray(document.metadata_json.tags) ? document.metadata_json.tags.map(String) : [],
    notes: String(document.metadata_json.notes || '')
  }
}

function fromDocumentSources(value: Record<string, unknown>): Record<string, FieldSourceInfo> {
  const sources: Record<string, FieldSourceInfo> = {}
  const mapping: Record<string, string> = { sender: 'correspondent', invoice_number: 'invoiceNo', payment_method: 'paymentMethod' }
  for (const [key, raw] of Object.entries(value || {})) {
    if (!raw || typeof raw !== 'object') continue
    const source = (raw as Record<string, unknown>).source
    if (source === 'manual' || source === 'deterministic' || source === 'qwen' || source === 'imported') {
      const confidence = Number((raw as Record<string, unknown>).confidence)
      const evidence = (raw as Record<string, unknown>).evidence
      sources[mapping[key] || key] = {
        source,
        confidence: Number.isFinite(confidence) ? confidence : undefined,
        evidence: typeof evidence === 'string' ? evidence : undefined
      }
    }
  }
  return sources
}
