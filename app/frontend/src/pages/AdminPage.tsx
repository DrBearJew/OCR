import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, RotateCcw, Save, Wrench } from 'lucide-react'
import { api } from '../api/client'
import type { Collection, Document, IngestionJob, IngestionSource, IntegrationSummary, JobInfo, ModelEndpointTestResult, ModelSetup, ProcessingHook } from '../types'
import { useI18n } from '../i18n'

interface ModelFormState {
  ocr_engine: string
  ocr_mode: string
  language: string
  page_limit: string
  image_dpi: string
  output_type: string
  max_image_pixels: string
}

const defaultModelForm: ModelFormState = {
  ocr_engine: 'paddle_vl',
  ocr_mode: 'redo',
  language: 'deu+eng',
  page_limit: '100',
  image_dpi: '220',
  output_type: 'markdown',
  max_image_pixels: '40000000'
}

const engineLabels: Record<string, { title: string; detail: string }> = {
  paddle_vl: { title: 'PaddleOCR-VL', detail: 'Smart document parser, default for invoices and mixed layouts.' },
  ppocrv6: { title: 'PP-OCRv6', detail: 'Fast/simple OCR through ONNX Runtime.' },
  glm: { title: 'GLM OCR', detail: 'Legacy multimodal fallback.' },
  fake: { title: 'Fake OCR', detail: 'Development/test stub only.' }
}

const defaultRuntimeSetup: ModelSetup = {
  mode: 'fake',
  ocr_provider: 'fake',
  paddle_vl_base_url: 'http://host.docker.internal:1234/v1',
  paddle_vl_model: 'paddleocr-vl',
  glm_base_url: 'http://host.docker.internal:1234/v1',
  glm_model: 'glm',
  qwen_enabled: false,
  qwen_base_url: 'http://host.docker.internal:1234/v1',
  qwen_model: 'qwen',
  timeout_seconds: 120
}

export default function AdminPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  const [jobs, setJobs] = useState<JobInfo[]>([])
  const [failed, setFailed] = useState<JobInfo[]>([])
  const [duplicates, setDuplicates] = useState<Document[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [sources, setSources] = useState<IngestionSource[]>([])
  const [ingestionJobs, setIngestionJobs] = useState<IngestionJob[]>([])
  const [hooks, setHooks] = useState<ProcessingHook[]>([])
  const [integrations, setIntegrations] = useState<IntegrationSummary | null>(null)
  const [collection, setCollection] = useState('Belege')
  const [selectedCollectionId, setSelectedCollectionId] = useState('')
  const [modelForm, setModelForm] = useState<ModelFormState>(defaultModelForm)
  const [runtimeSetup, setRuntimeSetup] = useState<ModelSetup>(defaultRuntimeSetup)
  const [endpointTest, setEndpointTest] = useState<ModelEndpointTestResult | null>(null)
  const [setupBusy, setSetupBusy] = useState(false)
  const [sourceForm, setSourceForm] = useState({ name: '', path: '', collection_id: '', recursive: false })
  const [hookForm, setHookForm] = useState({ name: '', stage: 'pre_consume', hook_kind: 'command', command: '', webhook_url: '', blocking: true })
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function load() {
    setError('')
    try {
      const [recentJobs, failedDocs, duplicateDocs, integrationStatus, modelSetup, collectionRows, sourceRows, ingestionRows, hookRows] = await Promise.all([
        api.jobs(),
        api.failed(),
        api.duplicates(),
        api.integrations(),
        api.modelSetup(),
        api.collections(),
        api.ingestionSources(),
        api.ingestionJobs(),
        api.hooks()
      ])
      setJobs(recentJobs)
      setFailed(failedDocs)
      setDuplicates(duplicateDocs)
      setIntegrations(integrationStatus)
      setRuntimeSetup(modelSetup)
      setCollections(collectionRows)
      setSources(sourceRows)
      setIngestionJobs(ingestionRows)
      setHooks(hookRows)
      if (!selectedCollectionId && collectionRows[0]) setSelectedCollectionId(collectionRows[0].id)
      if (!sourceForm.collection_id && collectionRows[0]) setSourceForm((form) => ({ ...form, collection_id: collectionRows[0].id }))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('admin.loadError'))
    }
  }

  useEffect(() => { void load() }, [])

  const selectedCollection = useMemo(
    () => collections.find((item) => item.id === selectedCollectionId) || collections[0],
    [collections, selectedCollectionId]
  )

  useEffect(() => {
    if (!selectedCollection) return
    setModelForm(formFromCollection(selectedCollection))
  }, [selectedCollection?.id, selectedCollection?.updated_at])

  const integrationByName = useMemo(() => {
    const rows = integrations?.integrations || []
    return new Map(rows.map((item) => [item.name, item]))
  }, [integrations])

  async function retry(id: string) {
    await api.retryDocument(id)
    await load()
  }

  async function runAction(action: () => Promise<unknown>, success = 'Action queued.') {
    setMessage('')
    await action()
    setMessage(success)
    await load()
  }

  async function saveRuntimeSetup() {
    setSetupBusy(true)
    setMessage('')
    try {
      const saved = await api.saveModelSetup(runtimeSetup)
      setRuntimeSetup(saved)
      setMessage(t('admin.modelSetupSaved'))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('admin.modelSetupSaveFailed'))
    } finally {
      setSetupBusy(false)
    }
  }

  async function testRuntimeEndpoint(kind: 'paddle' | 'glm' | 'qwen') {
    const base_url = kind === 'glm' ? runtimeSetup.glm_base_url : kind === 'qwen' ? runtimeSetup.qwen_base_url : runtimeSetup.paddle_vl_base_url
    const model = kind === 'glm' ? runtimeSetup.glm_model : kind === 'qwen' ? runtimeSetup.qwen_model : runtimeSetup.paddle_vl_model
    setSetupBusy(true)
    setEndpointTest(null)
    try {
      setEndpointTest(await api.testModelEndpoint({ base_url, model, timeout_seconds: runtimeSetup.timeout_seconds }))
    } catch (err) {
      setEndpointTest({ ok: false, detail: err instanceof Error ? err.message : t('admin.endpointTestFailed'), available_models: [] })
    } finally {
      setSetupBusy(false)
    }
  }

  async function saveModelConfig() {
    if (!selectedCollection) return
    const nextConfig = {
      ...(selectedCollection.ocr_config_json || {}),
      ocr_engine: modelForm.ocr_engine,
      ocr_mode: modelForm.ocr_mode,
      language: modelForm.language,
      page_limit: toNumber(modelForm.page_limit, defaultModelForm.page_limit),
      image_dpi: toNumber(modelForm.image_dpi, defaultModelForm.image_dpi),
      output_type: modelForm.output_type,
      max_image_pixels: toNumber(modelForm.max_image_pixels, defaultModelForm.max_image_pixels)
    }
    await api.patchCollection(selectedCollection.id, { ocr_config_json: nextConfig })
    setMessage(`Saved model config for ${selectedCollection.name}. New documents in this collection inherit it.`)
    await load()
  }

  async function addSource() {
    await api.createIngestionSource({
      name: sourceForm.name,
      source_type: 'consume_folder',
      path: sourceForm.path,
      enabled: true,
      collection_id: sourceForm.collection_id || collections[0]?.id,
      record_grouping: 'one_record_per_file',
      polling_interval_seconds: 300,
      ignore_patterns: ['.*', '*.tmp'],
      recursive: sourceForm.recursive,
      ocr_config_json: { ocr_mode: 'redo', language: 'deu+eng' }
    })
    setSourceForm({ name: '', path: '', collection_id: collections[0]?.id || '', recursive: false })
    await load()
  }

  async function addHook() {
    await api.createHook({
      name: hookForm.name,
      stage: hookForm.stage as 'pre_consume' | 'post_consume',
      hook_kind: hookForm.hook_kind as 'command' | 'webhook',
      enabled: true,
      blocking: hookForm.blocking,
      command: hookForm.command || null,
      webhook_url: hookForm.webhook_url || null,
      timeout_seconds: 30,
      env_json: {}
    })
    setHookForm({ name: '', stage: 'pre_consume', hook_kind: 'command', command: '', webhook_url: '', blocking: true })
    await load()
  }

  return (
    <main className="admin-page admin-console">
      <header className="page-header">
        <div>
          <h1>{t('admin.title')}</h1>
          <p>{t('admin.subtitle')}</p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      {message && <p className="success-message">{message}</p>}

      <section className="admin-card runtime-model-setup-card">
        <div className="section-heading-row">
          <div>
            <h2>{t('admin.modelSetup')}</h2>
            <p>{t('admin.modelSetupCopy')}</p>
          </div>
          <TechnicalPill state={runtimeSetup.ocr_provider === 'fake' ? 'info' : 'ok'} label={runtimeSetup.ocr_provider} />
        </div>
        <div className="model-config-form runtime-model-form">
          <label>{t('admin.setupMode')}
            <select value={runtimeSetup.mode} onChange={(event) => {
              const mode = event.target.value
              const provider = mode === 'local' ? 'ppocrv6' : mode === 'smart' ? 'paddle_vl' : 'fake'
              setRuntimeSetup({ ...runtimeSetup, mode, ocr_provider: provider })
            }}>
              <option value="fake">{t('admin.modeFake')}</option>
              <option value="local">{t('admin.modeLocal')}</option>
              <option value="smart">{t('admin.modeSmart')}</option>
            </select>
          </label>
          <label>{t('admin.defaultOcrProvider')}
            <select value={runtimeSetup.ocr_provider} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_provider: event.target.value })}>
              <option value="fake">fake</option>
              <option value="ppocrv6">ppocrv6</option>
              <option value="paddle_vl">paddle_vl</option>
              <option value="glm">glm</option>
            </select>
          </label>
          <label>{t('admin.paddleBaseUrl')}
            <input value={runtimeSetup.paddle_vl_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, paddle_vl_base_url: event.target.value })} placeholder="http://host.docker.internal:1234/v1" />
          </label>
          <label>{t('admin.paddleModel')}
            <input value={runtimeSetup.paddle_vl_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, paddle_vl_model: event.target.value })} placeholder="paddleocr-vl" />
          </label>
          <label>{t('admin.glmBaseUrl')}
            <input value={runtimeSetup.glm_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, glm_base_url: event.target.value })} placeholder="http://host.docker.internal:1234/v1" />
          </label>
          <label>{t('admin.glmModel')}
            <input value={runtimeSetup.glm_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, glm_model: event.target.value })} placeholder="glm" />
          </label>
          <label className="check runtime-check"><input type="checkbox" checked={runtimeSetup.qwen_enabled} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, qwen_enabled: event.target.checked })} /> {t('admin.enableQwenMetadata')}</label>
          <label>{t('admin.qwenBaseUrl')}
            <input value={runtimeSetup.qwen_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, qwen_base_url: event.target.value })} placeholder="http://host.docker.internal:1234/v1" />
          </label>
          <label>{t('admin.qwenModel')}
            <input value={runtimeSetup.qwen_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, qwen_model: event.target.value })} placeholder="qwen" />
          </label>
          <label>{t('admin.timeoutSeconds')}
            <input type="number" min="5" value={runtimeSetup.timeout_seconds} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, timeout_seconds: Number(event.target.value) || 120 })} />
          </label>
        </div>
        <div className="button-row form-actions runtime-setup-actions">
          <button type="button" onClick={() => void testRuntimeEndpoint('paddle')} disabled={setupBusy}>{t('admin.testPaddle')}</button>
          <button type="button" onClick={() => void testRuntimeEndpoint('glm')} disabled={setupBusy}>{t('admin.testGlm')}</button>
          <button type="button" onClick={() => void testRuntimeEndpoint('qwen')} disabled={setupBusy}>{t('admin.testQwen')}</button>
          <button type="button" className="primary" onClick={() => void saveRuntimeSetup()} disabled={setupBusy}><Save size={17} /> {t('admin.saveModelSetup')}</button>
        </div>
        {endpointTest && <p className={endpointTest.ok ? 'success-message' : 'error'}>{endpointTest.detail}{endpointTest.available_models.length ? ` · ${t('admin.models')}: ${endpointTest.available_models.join(', ')}` : ''}</p>}
      </section>

      <section className="admin-card model-config-card">
        <div className="section-heading-row">
          <div>
            <h2>{t('admin.modelConfig')}</h2>
            <p>{t('admin.modelConfigCopy')}</p>
          </div>
          <TechnicalPill state="info" label="Collection default" />
        </div>
        <div className="model-engine-grid">
          <EngineCard engine="paddle_vl" item={integrationByName.get('paddle_vl_multimodal_ocr') || integrationByName.get('paddle_vl_llama')} />
          <EngineCard engine="ppocrv6" item={undefined} note="Local ONNX runtime, loaded on demand." />
          <EngineCard engine="glm" item={integrationByName.get('glm_multimodal_ocr') || integrationByName.get('glm_llama')} />
          <EngineCard engine="qwen" item={integrationByName.get('qwen_llama')} title={t('admin.qwenMetadata')} detail={t('admin.qwenMetadataDetail')} />
        </div>
        <div className="model-config-form">
          <label>Collection
            <select value={selectedCollection?.id || ''} onChange={(event) => setSelectedCollectionId(event.target.value)}>
              {collections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <label>OCR engine
            <select value={modelForm.ocr_engine} onChange={(event) => setModelForm({ ...modelForm, ocr_engine: event.target.value })}>
              <option value="paddle_vl">PaddleOCR-VL, smart parser</option>
              <option value="ppocrv6">PP-OCRv6, fast/simple</option>
              <option value="glm">GLM OCR fallback</option>
              <option value="fake">Fake/test</option>
            </select>
          </label>
          <label>OCR mode
            <select value={modelForm.ocr_mode} onChange={(event) => setModelForm({ ...modelForm, ocr_mode: event.target.value })}>
              <option value="redo">{t('admin.ocrModeRedo')}</option>
              <option value="force">{t('admin.ocrModeForce')}</option>
              <option value="skip">{t('admin.ocrModeSkip')}</option>
            </select>
          </label>
          <label>Language
            <input value={modelForm.language} onChange={(event) => setModelForm({ ...modelForm, language: event.target.value })} />
          </label>
          <label>Page limit
            <input type="number" min="1" value={modelForm.page_limit} onChange={(event) => setModelForm({ ...modelForm, page_limit: event.target.value })} />
          </label>
          <label>DPI
            <input type="number" min="72" value={modelForm.image_dpi} onChange={(event) => setModelForm({ ...modelForm, image_dpi: event.target.value })} />
          </label>
          <label>Output
            <select value={modelForm.output_type} onChange={(event) => setModelForm({ ...modelForm, output_type: event.target.value })}>
              <option value="markdown">markdown</option>
              <option value="text">text</option>
            </select>
          </label>
          <label>Max image pixels
            <input type="number" min="1000000" value={modelForm.max_image_pixels} onChange={(event) => setModelForm({ ...modelForm, max_image_pixels: event.target.value })} />
          </label>
          <button type="button" className="primary" onClick={() => void saveModelConfig()}><Save size={17} /> {t('admin.saveConfig')}</button>
        </div>
      </section>

      <section className="admin-card">
        <div className="section-heading-row">
          <div>
            <h2>{t('admin.maintenance')}</h2>
            <p>{t('admin.maintenanceCopy')}</p>
          </div>
        </div>
        <div className="admin-actions technical-actions">
          <button onClick={() => void runAction(api.reconcile, t('admin.reconciliationQueued'))}><Wrench size={18} /> {t('admin.reconcileStuck')}</button>
          <button onClick={() => void runAction(api.retryFailed, t('admin.failedDocsRetried'))}><RotateCcw size={18} /> {t('admin.retryFailed')}</button>
          <select value={collection} onChange={(event) => setCollection(event.target.value)}>
            <option>Belege</option>
            <option>Eingangsrechnung</option>
            <option>Ausgangsrechnung</option>
          </select>
          <button onClick={() => void runAction(() => api.reextractCollection(collection, false), `${t('admin.reextractQueuedFor')} ${collection}.`)}>{t('admin.reextractCollection')}</button>
        </div>
      </section>

      <section className="admin-card">
        <div className="section-heading-row"><h2>{t('admin.integrations')}</h2><TechnicalPill state={integrations?.ok ? 'ok' : 'down'} label={integrations?.ok ? t('admin.allReachable') : t('admin.needsAttention')} /></div>
        <div className="admin-list technical-list">
          {integrations?.integrations.map((item) => (
            <div key={item.name} className="admin-row technical-row">
              <strong>{item.name}</strong>
              <TechnicalPill state={item.ok ? 'ok' : 'down'} label={item.ok ? t('admin.up') : t('admin.down')} />
              <span>{translateIntegrationDetail(item.detail, t)}</span>
              <small>{item.latency_ms ?? ''}{item.latency_ms !== null ? ' ms' : ''}</small>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-card">
        <div className="section-heading-row"><h2>{t('admin.ingestionSources')}</h2><TechnicalPill state="info" label={`${sources.length} ${t('admin.configured')}`} /></div>
        <div className="admin-actions technical-actions">
          <input placeholder={t('admin.sourceName')} value={sourceForm.name} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })} />
          <input placeholder={t('admin.consumeFolderPath')} value={sourceForm.path} onChange={(event) => setSourceForm({ ...sourceForm, path: event.target.value })} />
          <select value={sourceForm.collection_id} onChange={(event) => setSourceForm({ ...sourceForm, collection_id: event.target.value })}>
            {collections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <label className="check"><input type="checkbox" checked={sourceForm.recursive} onChange={(event) => setSourceForm({ ...sourceForm, recursive: event.target.checked })} /> {t('admin.recursive')}</label>
          <button onClick={() => void addSource()}>{t('admin.addSource')}</button>
          <button onClick={() => void runAction(api.scanAllIngestionSources, t('admin.ingestionScanStarted'))}>{t('admin.scanAll')}</button>
        </div>
        <div className="admin-list technical-list">
          {sources.map((source) => (
            <div key={source.id} className="admin-row technical-row">
              <strong>{source.name}</strong>
              <TechnicalPill state={source.enabled ? 'ok' : 'down'} label={source.enabled ? t('status.enabled') : t('status.disabled')} />
              <span>{source.path} · {source.record_grouping}</span>
              <button onClick={() => void runAction(() => api.scanIngestionSource(source.id), `${t('admin.scanStartedFor')} ${source.name}.`)}>{t('admin.scan')}</button>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-card">
        <div className="section-heading-row"><h2>{t('admin.processingHooks')}</h2><TechnicalPill state="info" label={`${hooks.length} ${t('admin.configured')}`} /></div>
        <div className="admin-actions technical-actions">
          <input placeholder={t('admin.hookName')} value={hookForm.name} onChange={(event) => setHookForm({ ...hookForm, name: event.target.value })} />
          <select value={hookForm.stage} onChange={(event) => setHookForm({ ...hookForm, stage: event.target.value })}>
            <option value="pre_consume">pre_consume</option>
            <option value="post_consume">post_consume</option>
          </select>
          <select value={hookForm.hook_kind} onChange={(event) => setHookForm({ ...hookForm, hook_kind: event.target.value })}>
            <option value="command">command</option>
            <option value="webhook">webhook</option>
          </select>
          <input placeholder={t('admin.command')} value={hookForm.command} onChange={(event) => setHookForm({ ...hookForm, command: event.target.value })} />
          <input placeholder={t('admin.webhookUrl')} value={hookForm.webhook_url} onChange={(event) => setHookForm({ ...hookForm, webhook_url: event.target.value })} />
          <label className="check"><input type="checkbox" checked={hookForm.blocking} onChange={(event) => setHookForm({ ...hookForm, blocking: event.target.checked })} /> {t('admin.blocking')}</label>
          <button onClick={() => void addHook()}>{t('admin.addHook')}</button>
        </div>
        <div className="admin-list technical-list">
          {hooks.map((hook) => (
            <div key={hook.id} className="admin-row technical-row">
              <strong>{hook.name}</strong>
              <TechnicalPill state={hook.enabled ? 'ok' : 'down'} label={hook.enabled ? t('status.enabled') : t('status.disabled')} />
              <span>{hook.stage} · {hook.hook_kind}</span>
              <button onClick={() => void runAction(() => api.testHook(hook.id), `${t('admin.hookTestQueuedFor')} ${hook.name}.`)}>{t('admin.testHook')}</button>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-card operational-card">
        <div className="section-heading-row"><h2>{t('admin.operationalQueues')}</h2><p>{t('admin.operationalQueuesCopy')}</p></div>
        <details>
          <summary>{t('admin.ingestionJobs')} ({ingestionJobs.length})</summary>
          <div className="admin-list technical-list compact-list">
            {ingestionJobs.slice(0, 20).map((job) => (
              <div key={job.id} className="admin-row technical-row">
                <button disabled={!job.document_id} onClick={() => job.document_id && onOpenDocument(job.document_id)}>{job.discovered_path}</button>
                <TechnicalPill state={job.status === 'failed' ? 'down' : job.status === 'imported' || job.status === 'skipped' ? 'ok' : 'info'} label={job.status} />
                <span>{job.error_message || job.sha256 || ''}</span>
                <button onClick={() => void runAction(() => api.retryIngestionJob(job.id), t('admin.ingestionJobRetried'))}>{t('common.retry')}</button>
              </div>
            ))}
          </div>
        </details>
        <details>
          <summary>{t('admin.failedDocuments')} ({failed.length})</summary>
          <div className="admin-list technical-list compact-list">
            {failed.map((job) => (
              <div key={job.document_id} className="admin-row technical-row">
                <button onClick={() => onOpenDocument(job.document_id)}>{job.title || job.filename}</button>
                <TechnicalPill state="down" label={job.state} />
                <span>{job.error_message}</span>
                <button className="icon-button" title={t('common.retry')} onClick={() => void retry(job.document_id)}><RotateCcw size={18} /></button>
              </div>
            ))}
          </div>
        </details>
        <details>
          <summary>{t('admin.duplicates')} ({duplicates.length})</summary>
          <div className="admin-list technical-list compact-list">
            {duplicates.map((doc) => (
              <div key={doc.id} className="admin-row technical-row">
                <button onClick={() => onOpenDocument(doc.id)}>{doc.manual_title_override || doc.extracted_title || doc.original_filename}</button>
                <TechnicalPill state="info" label={t('admin.duplicate')} />
                <span>{t('admin.duplicateOf')} {doc.duplicate_of_document_id}</span>
                <button className="icon-button" title={t('admin.forceRetryOcr')} onClick={() => void retry(doc.id)}><RotateCcw size={18} /></button>
              </div>
            ))}
          </div>
        </details>
        <details>
          <summary>{t('admin.recentJobs')} ({jobs.length})</summary>
          <div className="admin-list technical-list compact-list">
            {jobs.map((job) => (
              <div key={job.document_id} className="admin-row technical-row">
                <button onClick={() => onOpenDocument(job.document_id)}>{job.title || job.filename}</button>
                <TechnicalPill state={job.state === 'failed' ? 'down' : 'info'} label={job.state} />
                <span>{new Date(job.updated_at).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </details>
      </section>
    </main>
  )
}

function formFromCollection(collection: Collection): ModelFormState {
  const config = collection.ocr_config_json || {}
  return {
    ocr_engine: String(config.ocr_engine || defaultModelForm.ocr_engine),
    ocr_mode: String(config.ocr_mode || defaultModelForm.ocr_mode),
    language: String(config.language || defaultModelForm.language),
    page_limit: String(config.page_limit || defaultModelForm.page_limit),
    image_dpi: String(config.image_dpi || defaultModelForm.image_dpi),
    output_type: String(config.output_type || defaultModelForm.output_type),
    max_image_pixels: String(config.max_image_pixels || defaultModelForm.max_image_pixels)
  }
}

function toNumber(value: string, fallback: string) {
  const parsed = Number(value || fallback)
  return Number.isFinite(parsed) ? parsed : Number(fallback)
}

function EngineCard({ engine, item, note, title, detail }: { engine: string; item: IntegrationSummary['integrations'][number] | undefined; note?: string; title?: string; detail?: string }) {
  const { t } = useI18n()
  const meta = engineLabels[engine] || { title: title || engine, detail: detail || '' }
  return (
    <article className="engine-card">
      <div><strong>{title || meta.title}</strong><p>{detail || meta.detail}</p></div>
      <TechnicalPill state={item ? item.ok ? 'ok' : 'down' : 'info'} label={item ? item.ok ? t('admin.up') : t('admin.down') : t('admin.configuredStandalone')} />
      {item?.detail && <small>{translateIntegrationDetail(item.detail, t)}</small>}
      {note && <small>{note}</small>}
    </article>
  )
}

function translateIntegrationDetail(detail: string, t: (key: string, fallback?: string) => string) {
  if (detail === 'reachable') return t('admin.detailReachable')
  if (detail === 'workers reachable') return t('admin.detailWorkersReachable')
  if (detail === 'PaddleOCR-VL multimodal parser config looks usable') return t('admin.detailPaddleUsable')
  if (detail === 'multimodal OCR config looks usable') return t('admin.detailMultimodalUsable')
  if (detail.startsWith('reachable via ')) return `${t('admin.detailReachableVia')} ${detail.replace('reachable via ', '')}`
  return detail
}

function TechnicalPill({ state, label }: { state: 'ok' | 'down' | 'info'; label: string }) {
  return <span className={`technical-pill technical-pill-${state}`}>{label}</span>
}
