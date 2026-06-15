import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import type { MutableRefObject, ReactNode } from 'react'
import { Check, ChevronDown, ClipboardCheck, CloudUpload, Copy, FileImage, FileText, Maximize2, Minus, Plus, RefreshCw, RotateCcw, Save, Sparkles, Trash2, UploadCloud, XCircle } from 'lucide-react'
import { api, previewUrl as documentPreviewUrl, thumbnailUrl as documentThumbnailUrl } from '../api/client'
import type { Document } from '../types'

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
      setMessage('Add one or more files before uploading.')
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
      setMessage(`Uploaded ${batch.documents.length} file${batch.documents.length === 1 ? '' : 's'} into one record. Select a file to inspect OCR and metadata.`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  async function processAll() {
    if (!uploadedRecordId && !selected?.documentId) {
      setMessage('Upload files first, or use Upload & Process All Documents.')
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
        setFiles((current) => current.map((file) => file.documentId ? { ...file, ocrStatus: 'running', ocrSnippet: 'Full pipeline queued: OCR, deterministic extraction, Qwen enrichment, title generation, and folder assignment.' } : file))
        setMessage(`Processing queued for ${result.queued} document${result.queued === 1 ? '' : 's'}.`)
      } else if (selected?.documentId) {
        const document = await api.processDocument(selected.documentId, {
          qwenEnabled: qwenRequested,
          overwriteManualValues: processingOptions.overwriteManualValues
        })
        updateDraftFromDocument(document)
        setMessage('Processing queued for the selected document.')
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Processing failed')
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
    if (!confirm(`Delete "${selected.filename}"? This hides the original file, OCR text, metadata, and page fragments until restored.`)) return
    setActionBusy('delete')
    try {
      await api.deleteDocument(selected.documentId)
      setFiles((current) => {
        const remaining = current.filter((file) => file.documentId !== selected.documentId)
        if (remaining[0]) setSelectedId(remaining[0].id)
        return remaining.length ? remaining : seededFiles
      })
      setMessage('Document deleted. Sibling files remain untouched.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Delete failed')
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
          <h1>Upload Document</h1>
          <p>Upload documents, run OCR, and extract metadata</p>
        </div>
        <div className="upload-header-actions">
          <button type="button" disabled={!uploadedRecordId} onClick={() => uploadedRecordId && onOpenRecord(uploadedRecordId)}>Open record</button>
          <button type="button" disabled={!selected?.documentId} onClick={() => selected?.documentId && onOpenDocument(selected.documentId)}>Open selected document</button>
          <button type="button" disabled={actionBusy === 'delete'} onClick={() => void deleteSelected()}><Trash2 size={15} /> Delete selected</button>
        </div>
      </header>
      {message && <p className={message.toLowerCase().includes('failed') || message.toLowerCase().includes('add one') ? 'error' : 'success-message'}>{message}</p>}
      <form className="upload-dashboard-grid" onSubmit={submit}>
        <section className="workflow-main">
          <UploadDropzone inputRef={inputRef} files={files} busy={busy} onFiles={addFiles} />
          <RecordSetupCard collectionName={collectionName} setCollectionName={setCollectionName} value={sharedTitle} setValue={setSharedTitle} folderPath={folderPath} setFolderPath={setFolderPath} />
          <section className="workflow-two-col">
            <MetadataForm metadata={metadata} setMetadata={updateSelectedMetadata} busy={busy} selected={selected} collectionName={collectionName} setCollectionName={setCollectionName} />
            <FilePreviewCard selected={selected} files={files} selectedId={selectedId} setSelectedId={setSelectedId} onAddMore={() => inputRef.current?.click()} />
          </section>
          <ProcessingOptionsPanel options={processingOptions} setOptions={setProcessingOptions} qwenStatus={qwenStatus} />
          <NextActionsBar
            disabled={Boolean(actionBusy) || busy}
            hasUploadedRecord={Boolean(uploadedRecordId)}
            actionBusy={actionBusy}
            onProcessAll={() => void processAll()}
            onRunOcr={() => void runSelected('ocr')}
            onExtract={() => void runSelected('metadata')}
            onReview={() => void runSelected('review')}
          />
        </section>
        <aside className="workflow-inspector">
          <OCRStatusCard selected={selected} onRunAgain={() => void runSelected('ocr')} />
          <MetadataExtractionCard selected={selected} qwenStatus={qwenStatus} qwenEnabled={(processingOptions.qwenAutofill || processingOptions.qwenEnrichment) && qwenAvailable} onRunAgain={() => void runSelected('metadata')} />
          <ExtractedMetadataPreview metadata={metadata} sources={selected?.metadataSources || {}} />
          <OCRTextPreview selected={selected} />
        </aside>
      </form>
    </main>
  )
}

function UploadDropzone({ inputRef, files, busy, onFiles }: { inputRef: MutableRefObject<HTMLInputElement | null>; files: UploadDraftFile[]; busy: boolean; onFiles: (files: FileList | File[]) => void }) {
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    onFiles(event.dataTransfer.files)
  }
  return (
    <section className="workflow-card upload-card">
      <h2>1. Upload File</h2>
      <div className="upload-card-grid">
        <div className="dropzone" onDrop={drop} onDragOver={(event) => event.preventDefault()}>
          <CloudUpload size={54} />
          <strong>Drag & drop a file here</strong>
          <span>or</span>
          <button type="button" className="primary split-button" onClick={() => inputRef.current?.click()} disabled={busy}>
            Upload file <ChevronDown size={16} />
          </button>
          <small>PDF, JPG, PNG, TIFF up to 50MB · multiple files supported</small>
          <input ref={inputRef} hidden type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,application/pdf,image/jpeg,image/png,image/webp,image/tiff" onChange={(event: ChangeEvent<HTMLInputElement>) => event.target.files && onFiles(event.target.files)} />
        </div>
        <div className="recent-uploads">
          <div className="mini-heading">
            <strong>Recent uploads</strong>
            <span>{files.length} file{files.length === 1 ? '' : 's'}</span>
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
  const active = value.applySharedTitleToDocuments && value.sharedTitleBase.trim()
  const example = collectionName === 'Belege'
    ? `${value.sharedTitleBase || 'Telekom'}_B_10/24_90,74_Karte`
    : `${value.sharedTitleBase || 'Telekom'}_12345_12/10/2024_90,74`
  return (
    <section className="workflow-card shared-title-card">
      <div>
        <h2>Record setup</h2>
        <p>Choose one collection for this record, then optionally use a shared base name for every uploaded document title.</p>
      </div>
      <div className="shared-title-controls">
        <label>
          Collection
          <select value={collectionName} onChange={(event) => setCollectionName(event.target.value)}>
            <option>Dokumente</option>
            <option>Eingangsrechnung</option>
            <option>Ausgangsrechnung</option>
            <option>Belege</option>
          </select>
        </label>
        <label>
          Shared title base
          <input
            value={value.sharedTitleBase}
            onChange={(event) => setValue({ ...value, sharedTitleBase: event.target.value })}
            placeholder="Telekom"
          />
        </label>
        <Toggle
          label="Apply shared title to all documents in this upload"
          checked={value.applySharedTitleToDocuments}
          onChange={(checked) => setValue({ ...value, applySharedTitleToDocuments: checked })}
        />
        <label>
          Folder path
          <input value={folderPath} onChange={(event) => setFolderPath(event.target.value)} placeholder={`${collectionName}/2024/10`} />
          <small>Optional. Leave blank to let rules or Qwen suggest a folder after processing.</small>
        </label>
      </div>
      <div className={`shared-title-preview ${active ? 'active' : ''}`}>
        <span>{active ? 'Will generate titles like' : 'Preview when enabled'}</span>
        <strong>{example}</strong>
      </div>
      {value.sharedTitleBase.trim() && !value.applySharedTitleToDocuments && (
        <small className="shared-title-hint">Turn on the toggle to apply this base title. Otherwise normal sender/recipient extraction is used.</small>
      )}
    </section>
  )
}

function MetadataForm({ metadata, setMetadata, busy, selected, collectionName, setCollectionName }: { metadata: MetadataFormState; setMetadata: (value: MetadataFormState) => void; busy: boolean; selected?: UploadDraftFile; collectionName: string; setCollectionName: (value: string) => void }) {
  const set = (key: keyof MetadataFormState, value: string | string[]) => setMetadata({ ...metadata, [key]: value })
  return (
    <section className="workflow-card metadata-card">
      <h2>2. Document Information</h2>
      <div className="metadata-grid">
        <FormField label="Record collection" source={selected?.metadataSources.collection}><select value={collectionName} onChange={(event) => setCollectionName(event.target.value)}><option>Dokumente</option><option>Eingangsrechnung</option><option>Ausgangsrechnung</option><option>Belege</option></select></FormField>
        <FormField label="Document Type" source={selected?.metadataSources.documentType}><select value={metadata.documentType} onChange={(event) => set('documentType', event.target.value)}><option value="">None</option><option>Rechnung</option><option>Beleg</option><option>Vertrag</option><option>Dokument</option></select></FormField>
        <FormField label="Status" source={selected?.metadataSources.status}><select value={metadata.status} onChange={(event) => set('status', event.target.value)}><option>New</option><option>OCR Running</option><option>Needs Review</option><option>Synced</option></select></FormField>
        <FormField label="Title" source={selected?.metadataSources.title} wide><input value={metadata.title} onChange={(event) => set('title', event.target.value)} placeholder="Optional; can be generated later" /></FormField>
        <FormField label="Correspondent / Sender" source={selected?.metadataSources.correspondent}><input value={metadata.correspondent} onChange={(event) => set('correspondent', event.target.value)} placeholder="Optional" /></FormField>
        <FormField label="Date" source={selected?.metadataSources.date}><input value={metadata.date} onChange={(event) => set('date', event.target.value)} placeholder="Optional" /></FormField>
        <FormField label="Invoice No." source={selected?.metadataSources.invoiceNo}><input value={metadata.invoiceNo} onChange={(event) => set('invoiceNo', event.target.value)} placeholder="Optional" /></FormField>
        <FormField label="Recipient / Customer"><input value={metadata.recipient} onChange={(event) => set('recipient', event.target.value)} /></FormField>
        <FormField label="Amount (Gross)" source={selected?.metadataSources.amount}><div className="input-combo"><input value={metadata.amount} onChange={(event) => set('amount', event.target.value)} placeholder="Optional" /><span>{metadata.currency}</span></div></FormField>
        <FormField label="Tax Amount" source={selected?.metadataSources.taxAmount}><input value={metadata.taxAmount} onChange={(event) => set('taxAmount', event.target.value)} placeholder="Optional" /></FormField>
        <FormField label="Currency"><select value={metadata.currency} onChange={(event) => set('currency', event.target.value)}><option>EUR</option><option>USD</option><option>CHF</option></select></FormField>
        <FormField label="Tags"><TagInput tags={metadata.tags} onChange={(tags) => set('tags', tags)} /></FormField>
        <FormField label="Notes / Description"><textarea value={metadata.notes} onChange={(event) => set('notes', event.target.value)} placeholder="Add notes or description..." /></FormField>
      </div>
      <div className="button-row form-actions">
        <button className="primary" disabled={busy}><Save size={17} /> Save Record</button>
        <button type="button">Save Draft</button>
        <button type="button"><RotateCcw size={17} /> Reset</button>
      </div>
    </section>
  )
}

function ProcessingOptionsPanel({ options, setOptions, qwenStatus }: { options: ProcessingOptionsState; setOptions: (value: ProcessingOptionsState) => void; qwenStatus: QwenStatus }) {
  const set = (patch: Partial<ProcessingOptionsState>) => setOptions({ ...options, ...patch })
  const qwenAvailable = qwenStatus === 'available'
  return (
    <section className="workflow-card processing-options-card">
      <div className="card-title-row">
        <h2>Processing Options</h2>
        {qwenStatus !== 'available' && <span className="option-warning">{qwenStatus === 'checking' ? 'Checking Qwen' : 'Qwen unavailable'}</span>}
      </div>
      <p>Qwen fills missing metadata, tags, folders, and search hints from OCR. Locked manual fields are preserved.</p>
      <div className="processing-options-grid">
        <Toggle label="Auto process full pipeline after upload" checked={options.autoProcess} onChange={(checked) => set({ autoProcess: checked })} />
        <Toggle label="Run OCR automatically after upload" checked={options.autoOcr} onChange={(checked) => set({ autoOcr: checked })} />
        <Toggle label="Auto-fill metadata with Qwen" checked={options.qwenAutofill && qwenAvailable} disabled={!qwenAvailable} onChange={(checked) => set({ qwenAutofill: checked })} />
        <Toggle label="Include Qwen tags, folders, and search hints" checked={options.qwenEnrichment && qwenAvailable} disabled={!qwenAvailable} onChange={(checked) => set({ qwenEnrichment: checked, qwenAutofill: checked || options.qwenAutofill })} />
        <Toggle label="Overwrite manual values" checked={options.overwriteManualValues} onChange={(checked) => set({ overwriteManualValues: checked })} />
        <Toggle label="Preserve manual edits / locked fields" checked={options.preserveLockedFields} onChange={(checked) => set({ preserveLockedFields: checked })} />
        <label>OCR engine<select value={options.ocrEngine} onChange={(event) => set({ ocrEngine: event.target.value as ProcessingOptionsState['ocrEngine'] })}><option value="paddle_vl">Smart parser · PaddleOCR-VL</option><option value="ppocrv6">Fast OCR · PP-OCRv6 medium</option></select></label>
        <label>OCR language<select value={options.ocrLanguage} onChange={(event) => set({ ocrLanguage: event.target.value })}><option value="deu+eng">German + English</option><option value="auto">Auto-detect</option><option value="deu">German</option><option value="eng">English</option></select></label>
        <label>OCR pages<select value={options.ocrPageMode} onChange={(event) => set({ ocrPageMode: event.target.value as ProcessingOptionsState['ocrPageMode'] })}><option value="all">All pages</option><option value="first_n">First N pages</option></select></label>
        <label>Page limit<input type="number" min="1" max="100" value={options.ocrPageLimit} onChange={(event) => set({ ocrPageLimit: Number(event.target.value) || 1 })} /></label>
        <Toggle label="Extract tables" checked={options.extractTables} onChange={(checked) => set({ extractTables: checked })} />
        <Toggle label="Use collection-specific rules" checked={options.collectionRules} onChange={(checked) => set({ collectionRules: checked })} />
      </div>
    </section>
  )
}

function FilePreviewCard({ selected, files, selectedId, setSelectedId, onAddMore }: { selected?: UploadDraftFile; files: UploadDraftFile[]; selectedId: string; setSelectedId: (id: string) => void; onAddMore: () => void }) {
  return (
    <section className="workflow-card file-preview-card">
      <div className="card-title-row"><h2>3. File Preview</h2><div className="zoom-controls"><button type="button"><Maximize2 size={16} /></button><button type="button"><Minus size={16} /></button><span>50%</span><button type="button"><Plus size={16} /></button></div></div>
      <div className="document-preview-surface">
        {selected?.serverPreviewUrl && selected.kind === 'pdf' ? (
          <iframe src={selected.serverPreviewUrl} title={selected.filename} />
        ) : selected?.serverPreviewUrl && selected.kind === 'image' ? (
          <img src={selected.serverPreviewUrl} alt={selected.filename} />
        ) : selected?.previewUrl ? (
          <img src={selected.previewUrl} alt={selected.filename} />
        ) : selected?.kind === 'pdf' ? (
          <PdfMockup />
        ) : (
          <InvoiceMockup />
        )}
      </div>
      <AttachmentStrip files={files} selectedId={selectedId} onSelect={setSelectedId} onAddMore={onAddMore} />
    </section>
  )
}

function AttachmentStrip({ files, selectedId, onSelect, onAddMore }: { files: UploadDraftFile[]; selectedId: string; onSelect: (id: string) => void; onAddMore: () => void }) {
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
              <dt>Collection</dt><dd>{file.metadata.collection || 'Dokumente'}</dd>
              <dt>Invoice</dt><dd>{file.metadata.invoiceNo || 'NA'}</dd>
              <dt>Date</dt><dd>{file.metadata.date || 'NA'}</dd>
              <dt>Amount</dt><dd>{file.metadata.amount ? `${file.metadata.amount} ${file.metadata.currency}` : 'NA'}</dd>
            </dl>
            <p>{file.ocrSnippet}</p>
            <em>Confidence {file.confidence || 0}%</em>
          </span>
        </button>
      ))}
      <button type="button" className="attachment-tile add-more" onClick={onAddMore}><Plus size={30} /><span>Add more</span></button>
    </div>
  )
}

function OCRStatusCard({ selected, onRunAgain }: { selected?: UploadDraftFile; onRunAgain: () => void }) {
  const done = selected?.ocrStatus === 'completed'
  return <InspectorCard title="4. OCR Status"><div className="status-card-row"><span className={done ? 'round-icon success' : 'round-icon warning'}>{done ? <Check size={18} /> : <RefreshCw size={18} />}</span><span><strong>{done ? 'OCR Completed' : 'OCR Queued'}</strong><small>{done ? 'Completed in 2.4s' : 'Waiting for worker'}</small></span><button type="button" onClick={onRunAgain}><RefreshCw size={16} /> Run OCR Again</button></div></InspectorCard>
}

function MetadataExtractionCard({ selected, qwenStatus, qwenEnabled, onRunAgain }: { selected?: UploadDraftFile; qwenStatus: QwenStatus; qwenEnabled: boolean; onRunAgain: () => void }) {
  const label = qwenStatus === 'checking' ? 'Checking' : qwenEnabled ? 'Enabled' : qwenStatus === 'available' ? 'Disabled' : 'Unavailable'
  const runLabel = selected?.qwenRunStatus === 'succeeded' ? 'Qwen filled/suggested fields' : selected?.qwenRunStatus === 'failed' ? 'Qwen failed' : selected?.qwenRunStatus === 'disabled' ? 'Qwen did not run' : 'Qwen pending'
  return (
    <InspectorCard title="5. AI Metadata Extraction">
      <p className="model-line">Model: <strong>Qwen Metadata</strong> <span className={qwenEnabled ? '' : 'muted-chip'}>{label}</span></p>
      <div className={`qwen-run-state qwen-${selected?.qwenRunStatus || 'not_run'}`}>
        <strong>{runLabel}</strong>
        <small>{selected?.qwenMessage || 'Qwen fills missing metadata, tags, folders, and search hints from OCR.'}</small>
        {selected?.qwenSuggestedFolder && <small>Suggested folder: {selected.qwenSuggestedFolder}</small>}
      </div>
      <button type="button" onClick={onRunAgain}><Sparkles size={16} /> Extract Metadata Again</button>
    </InspectorCard>
  )
}

function ExtractedMetadataPreview({ metadata, sources }: { metadata: MetadataFormState; sources: Record<string, FieldSourceInfo> }) {
  const fields: Array<[string, string, FieldSourceInfo | undefined]> = [
    ['Invoice No.', metadata.invoiceNo, sources.invoiceNo],
    ['Date', metadata.date, sources.date],
    ['Correspondent', metadata.correspondent, sources.correspondent],
    ['Recipient', metadata.recipient, sources.recipient],
    ['Amount (Gross)', `${metadata.amount} ${metadata.currency}`, sources.amount],
    ['Tax Amount', `${metadata.taxAmount} ${metadata.currency}`, sources.taxAmount],
    ['Currency', metadata.currency, sources.currency],
    ['Due Date', '26/10/2020', undefined]
  ]
  return <InspectorCard title="6. Extracted Metadata (Preview)"><div className="extracted-list">{fields.map(([label, value, source]) => <div key={label}><span>{label}</span><strong>{value || 'NA'}{source && <SourceBadge info={source} />}</strong><Check size={15} /></div>)}</div><button type="button" className="link-button">Show more fields (6)</button></InspectorCard>
}

function OCRTextPreview({ selected }: { selected?: UploadDraftFile }) {
  return <InspectorCard title="7. OCR Text Preview"><pre className="ocr-preview">{selected?.ocrSnippet || ''}</pre><div className="ocr-footer"><strong>Confidence: {selected?.confidence || 0}%</strong><button type="button" onClick={() => navigator.clipboard?.writeText(selected?.ocrSnippet || '')}><Copy size={16} /> Copy Text</button></div></InspectorCard>
}

function NextActionsBar({ disabled, hasUploadedRecord, actionBusy, onProcessAll, onRunOcr, onExtract, onReview }: { disabled: boolean; hasUploadedRecord: boolean; actionBusy: 'process' | 'ocr' | 'metadata' | 'review' | 'delete' | null; onProcessAll: () => void; onRunOcr: () => void; onExtract: () => void; onReview: () => void }) {
  return (
    <section className="workflow-card next-actions">
      <h2>8. Next Actions</h2>
      <div className="primary-process-row">
        {hasUploadedRecord ? (
          <button type="button" className="primary process-button" disabled={disabled} onClick={onProcessAll}>
            <Sparkles size={18} /> {actionBusy === 'process' ? 'Processing...' : 'Process All Documents'}
          </button>
        ) : (
          <button type="submit" className="primary process-button" disabled={disabled}>
            <Sparkles size={18} /> Upload & Process All Documents
          </button>
        )}
        <span>Runs OCR, deterministic extraction, Qwen enrichment, title generation, folder assignment, and final save.</span>
      </div>
      <details className="advanced-actions">
        <summary>Advanced stage-only actions</summary>
        <div>
          <button type="button" disabled={disabled} onClick={onRunOcr}><RefreshCw size={17} /> {actionBusy === 'ocr' ? 'Running OCR...' : 'Run OCR only'}</button>
          <button type="button" disabled={disabled} onClick={onExtract}><Sparkles size={17} /> {actionBusy === 'metadata' ? 'Extracting...' : 'Extract metadata only'}</button>
          <button type="button" disabled={disabled}><ClipboardCheck size={17} /> Validate Data</button>
          <button type="button" disabled={disabled}><UploadCloud size={17} /> Rebuild Search / Sync</button>
          <button type="button" disabled={disabled} onClick={onReview}><XCircle size={17} /> {actionBusy === 'review' ? 'Sending...' : 'Send to Review'}</button>
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
