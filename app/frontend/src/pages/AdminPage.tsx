import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw, RotateCcw, Save, Wrench } from 'lucide-react'
import { api, changeCredentials, createAuthAccount, deleteAuthAccount, getAuthAccounts, setAllowRegistration } from '../api/client'
import type { AuthAccountsState } from '../api/client'
import type { Collection, Document, IngestionJob, IngestionSource, IntegrationSummary, JobInfo, ModelEndpointTestResult, ModelSetup, ProcessingHook } from '../types'
import { useI18n } from '../i18n'

type AdminTab = 'models' | 'system' | 'automation' | 'queues'

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

const DOKOCR_LLAMA_SWAP_URL = 'http://model-runtime:8092/v1'
const ENGINE_PRESETS = [
  { id: 'lmstudio', label: 'LM Studio (:1234)', url: 'http://host.docker.internal:1234/v1', provider: 'openai_vision' as const, model: 'auto' },
  { id: 'llamacpp', label: 'llama.cpp (:8080)', url: 'http://host.docker.internal:8080/v1', provider: 'openai_vision' as const, model: 'auto' },
  { id: 'ollama', label: 'Ollama (:11434)', url: 'http://host.docker.internal:11434/v1', provider: 'openai_vision' as const, model: 'auto' },
  { id: 'internal', label: 'Internal (:8092)', url: DOKOCR_LLAMA_SWAP_URL, provider: 'paddle_vl' as const, model: 'paddleocr-vl' },
]

const defaultRuntimeSetup: ModelSetup = {
  mode: 'smart',
  ocr_provider: 'paddle_vl',
  paddle_vl_base_url: DOKOCR_LLAMA_SWAP_URL,
  paddle_vl_model: 'paddleocr-vl',
  glm_base_url: DOKOCR_LLAMA_SWAP_URL,
  glm_model: 'glm',
  openai_vision_base_url: 'http://host.docker.internal:1234/v1',
  openai_vision_model: 'auto',
  ocr_api_key_configured: false,
  qwen_enabled: true,
  qwen_base_url: DOKOCR_LLAMA_SWAP_URL,
  qwen_model: 'metadata',
  qwen_api_key_configured: false,
  timeout_seconds: 120,
  ocr_task_soft_time_limit: 600,
  ocr_task_time_limit: 660,
  ocr_task_hard_time_limit_grace_seconds: 120,
  ocr_task_lease_grace_seconds: 300,
  ocr_task_base_overhead_seconds: 300,
  ocr_task_paddle_vl_seconds_per_chunk: 180,
  ocr_task_glm_seconds_per_page: 180,
  ocr_task_openai_vision_seconds_per_page: 120,
  ocr_task_ppocrv6_seconds_per_page: 30,
  ocr_pdf_text_layer_auto_enabled: true,
  ocr_pdf_text_layer_min_chars: 80,
  ocr_pdf_text_layer_min_chars_per_page: 20
}

export default function AdminPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  const [tab, setTab] = useState<AdminTab>('models')
  const [loading, setLoading] = useState(false)

  const [runtimeSetup, setRuntimeSetup] = useState<ModelSetup>(defaultRuntimeSetup)
  const [ocrApiKeyInput, setOcrApiKeyInput] = useState('')
  const [qwenApiKeyInput, setQwenApiKeyInput] = useState('')
  const [clearOcrApiKey, setClearOcrApiKey] = useState(false)
  const [clearQwenApiKey, setClearQwenApiKey] = useState(false)
  const [endpointTestTarget, setEndpointTestTarget] = useState<'paddle' | 'glm' | 'openai_vision' | 'qwen' | null>(null)
  const [collections, setCollections] = useState<Collection[]>([])
  const [selectedCollectionId, setSelectedCollectionId] = useState('')
  const [modelForm, setModelForm] = useState<ModelFormState>(defaultModelForm)
  const [endpointTest, setEndpointTest] = useState<ModelEndpointTestResult | null>(null)
  const [setupBusy, setSetupBusy] = useState(false)

  const [integrations, setIntegrations] = useState<IntegrationSummary | null>(null)
  const [collection, setCollection] = useState('Belege')
  const [accountsState, setAccountsState] = useState<AuthAccountsState | null>(null)
  const [newAccountForm, setNewAccountForm] = useState({ username: '', password: '' })
  const [accountForm, setAccountForm] = useState({ username: 'admin', currentPassword: '', newPassword: '', confirmPassword: '' })
  const [accountBusy, setAccountBusy] = useState(false)
  const [accountNotice, setAccountNotice] = useState<{ ok: boolean; text: string } | null>(null)

  const [sources, setSources] = useState<IngestionSource[]>([])
  const [hooks, setHooks] = useState<ProcessingHook[]>([])
  const [sourceForm, setSourceForm] = useState({ name: '', path: '', collection_id: '', recursive: false })
  const [hookForm, setHookForm] = useState({ name: '', stage: 'pre_consume', hook_kind: 'command', command: '', webhook_url: '', blocking: true })

  const [jobs, setJobs] = useState<JobInfo[]>([])
  const [failed, setFailed] = useState<JobInfo[]>([])
  const [duplicates, setDuplicates] = useState<Document[]>([])
  const [ingestionJobs, setIngestionJobs] = useState<IngestionJob[]>([])

  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const loadTab = useCallback(async (target: AdminTab, force = false) => {
    setError('')
    setLoading(true)
    try {
      if (target === 'models') {
        const [modelSetup, collectionRows] = await Promise.all([api.modelSetup(), api.collections()])
        setRuntimeSetup(modelSetup)
        setCollections(collectionRows)
        setSelectedCollectionId((prev) => prev || collectionRows[0]?.id || '')
        setSourceForm((form) => (form.collection_id || !collectionRows[0] ? form : { ...form, collection_id: collectionRows[0].id }))
      } else if (target === 'system') {
        const [integrationStatus, collectionRows, authAccounts] = await Promise.all([
          api.integrations(force),
          collections.length ? Promise.resolve(collections) : api.collections(),
          getAuthAccounts().catch(() => null),
        ])
        setIntegrations(integrationStatus)
        if (!collections.length) setCollections(collectionRows)
        if (authAccounts) {
          setAccountsState(authAccounts)
          setAccountForm((prev) => ({ ...prev, username: authAccounts.current_username }))
        }
      } else if (target === 'automation') {
        const [sourceRows, hookRows, collectionRows] = await Promise.all([
          api.ingestionSources(),
          api.hooks(),
          collections.length ? Promise.resolve(collections) : api.collections()
        ])
        setSources(sourceRows)
        setHooks(hookRows)
        if (!collections.length) setCollections(collectionRows)
        setSourceForm((form) => (form.collection_id || !collectionRows[0] ? form : { ...form, collection_id: collectionRows[0].id }))
      } else if (target === 'queues') {
        const [recentJobs, failedDocs, duplicateDocs, ingestionRows] = await Promise.all([
          api.jobs(),
          api.failed(),
          api.duplicates(),
          api.ingestionJobs()
        ])
        setJobs(recentJobs)
        setFailed(failedDocs)
        setDuplicates(duplicateDocs)
        setIngestionJobs(ingestionRows)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('admin.loadError'))
    } finally {
      setLoading(false)
    }
  }, [collections, t])

  useEffect(() => {
    void loadTab(tab)
  }, [tab])

  const selectedCollection = useMemo(
    () => collections.find((item) => item.id === selectedCollectionId) || collections[0],
    [collections, selectedCollectionId]
  )

  useEffect(() => {
    if (!selectedCollection) return
    setModelForm(formFromCollection(selectedCollection))
  }, [selectedCollection?.id, selectedCollection?.updated_at])

  async function saveAccountCredentials() {
    setAccountNotice(null)
    if (!accountForm.username.trim()) {
      setAccountNotice({ ok: false, text: t('admin.accountUsernameRequired') })
      return
    }
    if (!accountForm.currentPassword) {
      setAccountNotice({ ok: false, text: t('admin.accountCurrentPasswordRequired') })
      return
    }
    if (accountForm.newPassword.length < 8) {
      setAccountNotice({ ok: false, text: t('login.setupPasswordTooShort') })
      return
    }
    if (accountForm.newPassword !== accountForm.confirmPassword) {
      setAccountNotice({ ok: false, text: t('login.setupPasswordMismatch') })
      return
    }
    setAccountBusy(true)
    try {
      const updated = await changeCredentials(
        accountForm.currentPassword,
        accountForm.username.trim(),
        accountForm.newPassword
      )
      setAccountForm({ username: updated.username, currentPassword: '', newPassword: '', confirmPassword: '' })
      const refreshed = await getAuthAccounts().catch(() => null)
      if (refreshed) setAccountsState(refreshed)
      setAccountNotice({ ok: true, text: t('admin.accountSaved') })
    } catch (err) {
      setAccountNotice({ ok: false, text: err instanceof Error ? err.message : t('admin.accountSaveFailed') })
    } finally {
      setAccountBusy(false)
    }
  }

  async function addAccount() {
    setAccountNotice(null)
    if (!newAccountForm.username.trim()) {
      setAccountNotice({ ok: false, text: t('admin.accountUsernameRequired') })
      return
    }
    if (newAccountForm.password.length < 8) {
      setAccountNotice({ ok: false, text: t('login.setupPasswordTooShort') })
      return
    }
    setAccountBusy(true)
    try {
      const updated = await createAuthAccount(newAccountForm.username.trim(), newAccountForm.password)
      setAccountsState(updated)
      setNewAccountForm({ username: '', password: '' })
      setAccountNotice({ ok: true, text: t('admin.accountAdded') })
    } catch (err) {
      setAccountNotice({ ok: false, text: err instanceof Error ? err.message : t('admin.accountSaveFailed') })
    } finally {
      setAccountBusy(false)
    }
  }

  async function removeAccount(username: string) {
    setAccountNotice(null)
    setAccountBusy(true)
    try {
      const updated = await deleteAuthAccount(username)
      setAccountsState(updated)
      setAccountNotice({ ok: true, text: t('admin.accountRemoved') })
    } catch (err) {
      setAccountNotice({ ok: false, text: err instanceof Error ? err.message : t('admin.accountSaveFailed') })
    } finally {
      setAccountBusy(false)
    }
  }

  async function toggleSelfRegistration(enabled: boolean) {
    setAccountNotice(null)
    setAccountBusy(true)
    try {
      const updated = await setAllowRegistration(enabled)
      setAccountsState(updated)
      setAccountNotice({ ok: true, text: enabled ? t('admin.registrationEnabledNotice') : t('admin.registrationDisabledNotice') })
    } catch (err) {
      setAccountNotice({ ok: false, text: err instanceof Error ? err.message : t('admin.accountSaveFailed') })
    } finally {
      setAccountBusy(false)
    }
  }

  async function runAction(action: () => Promise<unknown>, success: string) {
    setError('')
    setMessage('')
    try {
      await action()
      setMessage(success)
      await loadTab(tab, true)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('admin.loadError'))
    }
  }

  async function saveRuntimeSetup() {
    setSetupBusy(true)
    setError('')
    setMessage('')
    try {
      const saved = await api.saveModelSetup({
        ...runtimeSetup,
        qwen_enabled: Boolean(runtimeSetup.qwen_base_url.trim() && runtimeSetup.qwen_model.trim()),
        ocr_api_key: ocrApiKeyInput.trim() || undefined,
        qwen_api_key: qwenApiKeyInput.trim() || undefined,
        clear_ocr_api_key: clearOcrApiKey,
        clear_qwen_api_key: clearQwenApiKey
      })
      setRuntimeSetup(saved)
      setOcrApiKeyInput('')
      setQwenApiKeyInput('')
      setClearOcrApiKey(false)
      setClearQwenApiKey(false)
      setMessage(t('admin.modelSetupSaved'))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('admin.modelSetupSaveFailed'))
    } finally {
      setSetupBusy(false)
    }
  }

  function applyEnginePreset(preset: typeof ENGINE_PRESETS[number]) {
    if (preset.id === 'internal') {
      setRuntimeSetup({
        ...runtimeSetup,
        mode: 'smart',
        ocr_provider: runtimeSetup.ocr_provider === 'fake' || runtimeSetup.ocr_provider === 'openai_vision' ? 'paddle_vl' : runtimeSetup.ocr_provider,
        paddle_vl_base_url: DOKOCR_LLAMA_SWAP_URL,
        glm_base_url: DOKOCR_LLAMA_SWAP_URL,
        qwen_base_url: DOKOCR_LLAMA_SWAP_URL,
        qwen_model: 'metadata'
      })
    } else {
      setRuntimeSetup({
        ...runtimeSetup,
        mode: 'smart',
        ocr_provider: 'openai_vision',
        openai_vision_base_url: preset.url,
        openai_vision_model: preset.model,
        qwen_enabled: true,
        qwen_base_url: preset.url,
        qwen_model: preset.model
      })
    }
    setEndpointTest(null)
    setEndpointTestTarget(null)
  }

  function useInternalGatewayPreset() {
    applyEnginePreset(ENGINE_PRESETS[3])
  }

  async function testRuntimeEndpoint(kind: 'paddle' | 'glm' | 'openai_vision' | 'qwen') {
    const base_url = kind === 'glm'
      ? runtimeSetup.glm_base_url
      : kind === 'qwen'
        ? runtimeSetup.qwen_base_url
        : kind === 'openai_vision'
          ? runtimeSetup.openai_vision_base_url
          : runtimeSetup.paddle_vl_base_url
    const model = kind === 'glm'
      ? runtimeSetup.glm_model
      : kind === 'qwen'
        ? runtimeSetup.qwen_model
        : kind === 'openai_vision'
          ? runtimeSetup.openai_vision_model
          : runtimeSetup.paddle_vl_model
    const api_key = kind === 'qwen' ? qwenApiKeyInput.trim() : ocrApiKeyInput.trim()
    const use_saved_key_for = !api_key ? (kind === 'qwen' ? 'qwen' : 'ocr') : undefined
    setSetupBusy(true)
    setEndpointTest(null)
    setEndpointTestTarget(kind)
    try {
      setEndpointTest(await api.testModelEndpoint({
        base_url,
        model,
        timeout_seconds: runtimeSetup.timeout_seconds,
        api_key: api_key || undefined,
        use_saved_key_for
      }))
    } catch (err) {
      setEndpointTest({ ok: false, detail: err instanceof Error ? err.message : t('admin.endpointTestFailed'), available_models: [] })
    } finally {
      setSetupBusy(false)
    }
  }

  function selectDetectedModel(modelId: string) {
    if (endpointTestTarget === 'qwen') {
      setRuntimeSetup({ ...runtimeSetup, qwen_model: modelId, qwen_enabled: true })
    } else if (endpointTestTarget === 'openai_vision') {
      setRuntimeSetup({ ...runtimeSetup, openai_vision_model: modelId })
    } else if (endpointTestTarget === 'glm') {
      setRuntimeSetup({ ...runtimeSetup, glm_model: modelId })
    } else {
      setRuntimeSetup({ ...runtimeSetup, paddle_vl_model: modelId })
    }
  }

  async function saveModelConfig() {
    if (!selectedCollection) return
    setError('')
    setMessage('')
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
    setMessage(`${t('admin.saveConfig')}: ${selectedCollection.name}`)
    await loadTab('models')
  }

  async function addSource() {
    if (!sourceForm.name.trim() || !sourceForm.path.trim()) return
    await runAction(
      () => api.createIngestionSource({
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
      }),
      sourceForm.name
    )
    setSourceForm({ name: '', path: '', collection_id: collections[0]?.id || '', recursive: false })
  }

  async function addHook() {
    if (!hookForm.name.trim()) return
    await runAction(
      () => api.createHook({
        name: hookForm.name,
        stage: hookForm.stage as 'pre_consume' | 'post_consume',
        hook_kind: hookForm.hook_kind as 'command' | 'webhook',
        enabled: true,
        blocking: hookForm.blocking,
        command: hookForm.command || null,
        webhook_url: hookForm.webhook_url || null,
        timeout_seconds: 30,
        env_json: {}
      }),
      hookForm.name
    )
    setHookForm({ name: '', stage: 'pre_consume', hook_kind: 'command', command: '', webhook_url: '', blocking: true })
  }

  const tabs: { id: AdminTab; label: string }[] = [
    { id: 'models', label: t('admin.tabModels', 'Models') },
    { id: 'system', label: t('admin.tabSystem', 'System') },
    { id: 'automation', label: t('admin.tabAutomation', 'Automation') },
    { id: 'queues', label: t('admin.tabQueues', 'Queues') }
  ]

  return (
    <main className="admin-page admin-console">
      <header className="page-header admin-header-row">
        <h1>{t('admin.title')}</h1>
        <nav className="admin-tabs" role="tablist" aria-label={t('admin.title')}>
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              className={tab === item.id ? 'active' : ''}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <button className="icon-button" title={t('common.refresh')} disabled={loading} onClick={() => void loadTab(tab, true)}>
          <RefreshCw size={17} />
        </button>
      </header>

      {error && <p className="error">{error}</p>}
      {message && <p className="success-message">{message}</p>}

      {tab === 'models' && (
        <>
          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.modelSetup')}</h2>
              <TechnicalPill state={runtimeSetup.ocr_provider === 'fake' ? 'info' : 'ok'} label={providerLabel(runtimeSetup.ocr_provider, t)} />
            </div>

            <div className="admin-preset-row">
              <span className="admin-preset-label">{t('admin.enginePresets', 'Quick setup')}:</span>
              {ENGINE_PRESETS.map((preset) => (
                <button key={preset.id} type="button" className="preset-chip" disabled={setupBusy} onClick={() => applyEnginePreset(preset)}>
                  {preset.label}
                </button>
              ))}
            </div>

            <div className="admin-form-grid">
              <label>{t('admin.setupMode')}
                <select value={runtimeSetup.mode} onChange={(event) => {
                  const mode = event.target.value
                  const provider = mode === 'local' ? 'ppocrv6' : mode === 'smart' ? (runtimeSetup.ocr_provider === 'openai_vision' ? 'openai_vision' : 'paddle_vl') : 'fake'
                  setRuntimeSetup({ ...runtimeSetup, mode, ocr_provider: provider })
                }}>
                  <option value="fake">{t('admin.modeFake')}</option>
                  <option value="local">{t('admin.modeLocal')}</option>
                  <option value="smart">{t('admin.modeSmart')}</option>
                </select>
              </label>
              <label>{t('admin.defaultOcrProvider')}
                <select value={runtimeSetup.ocr_provider} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_provider: event.target.value })}>
                  <option value="paddle_vl">{t('admin.providerOptionSmart')}</option>
                  <option value="openai_vision">{t('admin.providerOptionOpenAIVision', 'External Vision (LM Studio / llama.cpp / Ollama)')}</option>
                  <option value="ppocrv6">{t('admin.providerOptionLocal')}</option>
                  <option value="glm">{t('admin.providerOptionSecondary')}</option>
                  <option value="fake">{t('admin.providerOptionFake')}</option>
                </select>
              </label>
              {runtimeSetup.ocr_provider === 'openai_vision' ? (
                <>
                  <label>{t('admin.openaiVisionBaseUrl', 'External vision OCR endpoint')}
                    <input value={runtimeSetup.openai_vision_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, openai_vision_base_url: event.target.value })} placeholder="http://host.docker.internal:1234/v1" />
                  </label>
                  <label>{t('admin.openaiVisionModel', 'External vision model ID')}
                    <input value={runtimeSetup.openai_vision_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, openai_vision_model: event.target.value })} placeholder="auto" />
                  </label>
                </>
              ) : (
                <>
                  <label>{t('admin.paddleBaseUrl')}
                    <input value={runtimeSetup.paddle_vl_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, paddle_vl_base_url: event.target.value })} placeholder={DOKOCR_LLAMA_SWAP_URL} />
                  </label>
                  <label>{t('admin.paddleModel')}
                    <input value={runtimeSetup.paddle_vl_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, paddle_vl_model: event.target.value })} placeholder="paddleocr-vl" />
                  </label>
                </>
              )}
              <label>{t('admin.qwenBaseUrl')}
                <input value={runtimeSetup.qwen_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, qwen_base_url: event.target.value })} placeholder={DOKOCR_LLAMA_SWAP_URL} />
              </label>
              <label>{t('admin.qwenModel')}
                <input value={runtimeSetup.qwen_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, qwen_model: event.target.value })} placeholder="auto" />
              </label>
              <label>{t('admin.timeoutSeconds')}
                <input type="number" min="5" value={runtimeSetup.timeout_seconds} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, timeout_seconds: Number(event.target.value) || 120 })} />
              </label>
            </div>

            <details className="admin-advanced">
              <summary>{t('admin.advanced', 'Advanced')}</summary>
              <div className="admin-advanced-body">
                <div className="admin-form-grid">
                  <label>{t('admin.ocrApiKey', 'OCR Bearer API key (optional)')}
                    <div className="api-key-input-row">
                      <input
                        type="password"
                        autoComplete="off"
                        value={ocrApiKeyInput}
                        onChange={(event) => { setOcrApiKeyInput(event.target.value); setClearOcrApiKey(false) }}
                        placeholder={runtimeSetup.ocr_api_key_configured && !clearOcrApiKey ? t('admin.apiKeySavedPlaceholder', 'Saved — leave blank to keep') : t('admin.apiKeyOptionalPlaceholder', 'Optional Bearer token')}
                      />
                      {runtimeSetup.ocr_api_key_configured && !clearOcrApiKey && (
                        <button type="button" onClick={() => { setClearOcrApiKey(true); setOcrApiKeyInput('') }}>{t('admin.clearApiKey', 'Clear')}</button>
                      )}
                    </div>
                  </label>
                  <label>{t('admin.qwenApiKey', 'Metadata Bearer API key (optional)')}
                    <div className="api-key-input-row">
                      <input
                        type="password"
                        autoComplete="off"
                        value={qwenApiKeyInput}
                        onChange={(event) => { setQwenApiKeyInput(event.target.value); setClearQwenApiKey(false) }}
                        placeholder={runtimeSetup.qwen_api_key_configured && !clearQwenApiKey ? t('admin.apiKeySavedPlaceholder', 'Saved — leave blank to keep') : t('admin.apiKeyOptionalPlaceholder', 'Optional Bearer token')}
                      />
                      {runtimeSetup.qwen_api_key_configured && !clearQwenApiKey && (
                        <button type="button" onClick={() => { setClearQwenApiKey(true); setQwenApiKeyInput('') }}>{t('admin.clearApiKey', 'Clear')}</button>
                      )}
                    </div>
                  </label>
                  <label>{t('admin.glmBaseUrl')}
                    <input value={runtimeSetup.glm_base_url} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, glm_base_url: event.target.value })} placeholder={DOKOCR_LLAMA_SWAP_URL} />
                  </label>
                  <label>{t('admin.glmModel')}
                    <input value={runtimeSetup.glm_model} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, glm_model: event.target.value })} placeholder="glm" />
                  </label>
                  <label>{t('admin.ocrSoftLimit')}
                    <input type="number" min="60" value={runtimeSetup.ocr_task_soft_time_limit} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_soft_time_limit: Number(event.target.value) || 600 })} />
                  </label>
                  <label>{t('admin.ocrHardLimit')}
                    <input type="number" min="60" value={runtimeSetup.ocr_task_time_limit} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_time_limit: Number(event.target.value) || 660 })} />
                  </label>
                  <label>{t('admin.ocrHardGrace')}
                    <input type="number" min="1" value={runtimeSetup.ocr_task_hard_time_limit_grace_seconds} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_hard_time_limit_grace_seconds: Number(event.target.value) || 120 })} />
                  </label>
                  <label>{t('admin.ocrLeaseGrace')}
                    <input type="number" min="1" value={runtimeSetup.ocr_task_lease_grace_seconds} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_lease_grace_seconds: Number(event.target.value) || 300 })} />
                  </label>
                  <label>{t('admin.ocrBaseOverhead')}
                    <input type="number" min="1" value={runtimeSetup.ocr_task_base_overhead_seconds} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_base_overhead_seconds: Number(event.target.value) || 300 })} />
                  </label>
                  <label>{t('admin.paddleChunkBudget')}
                    <input type="number" min="1" value={runtimeSetup.ocr_task_paddle_vl_seconds_per_chunk} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_paddle_vl_seconds_per_chunk: Number(event.target.value) || 180 })} />
                  </label>
                  <label>{t('admin.glmPageBudget')}
                    <input type="number" min="1" value={runtimeSetup.ocr_task_glm_seconds_per_page} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_glm_seconds_per_page: Number(event.target.value) || 180 })} />
                  </label>
                  <label>{t('admin.ppocrPageBudget')}
                    <input type="number" min="1" value={runtimeSetup.ocr_task_ppocrv6_seconds_per_page} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_task_ppocrv6_seconds_per_page: Number(event.target.value) || 30 })} />
                  </label>
                  <label>{t('admin.pdfTextLayerMinChars')}
                    <input type="number" min="1" value={runtimeSetup.ocr_pdf_text_layer_min_chars} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_pdf_text_layer_min_chars: Number(event.target.value) || 80 })} />
                  </label>
                  <label>{t('admin.pdfTextLayerMinCharsPerPage')}
                    <input type="number" min="1" value={runtimeSetup.ocr_pdf_text_layer_min_chars_per_page} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_pdf_text_layer_min_chars_per_page: Number(event.target.value) || 20 })} />
                  </label>
                </div>
                <div className="admin-advanced-footer">
                  <label className="check">
                    <input type="checkbox" checked={runtimeSetup.ocr_pdf_text_layer_auto_enabled} onChange={(event) => setRuntimeSetup({ ...runtimeSetup, ocr_pdf_text_layer_auto_enabled: event.target.checked })} />
                    {t('admin.pdfTextLayerFastPath')}
                  </label>
                  <div className="button-row">
                    <button type="button" onClick={useInternalGatewayPreset} disabled={setupBusy}>{t('admin.useInternalGateway')}</button>
                    <button type="button" onClick={() => void testRuntimeEndpoint('glm')} disabled={setupBusy}>{t('admin.testGlm')}</button>
                  </div>
                </div>
              </div>
            </details>

            <div className="button-row form-actions runtime-setup-actions">
              <button
                type="button"
                onClick={() => void testRuntimeEndpoint(runtimeSetup.ocr_provider === 'openai_vision' ? 'openai_vision' : 'paddle')}
                disabled={setupBusy}
              >
                {t('admin.testPaddle')}
              </button>
              <button type="button" onClick={() => void testRuntimeEndpoint('qwen')} disabled={setupBusy}>{t('admin.testQwen')}</button>
              <button type="button" className="primary" onClick={() => void saveRuntimeSetup()} disabled={setupBusy}><Save size={16} /> {t('admin.saveModelSetup')}</button>
            </div>
            {endpointTest && (
              <div className="endpoint-test-result">
                <p className={endpointTest.ok ? 'success-message' : 'error'}>
                  {translateEndpointDetail(endpointTest.detail, t)}
                </p>
                {endpointTest.available_models.length > 0 && (
                  <div className="detected-models-row">
                    <span>{t('admin.clickModelToSelect', 'Detected models (click to select)')}:</span>
                    {endpointTest.available_models.map((modelId) => (
                      <button key={modelId} type="button" className="preset-chip" onClick={() => selectDetectedModel(modelId)}>
                        {modelId}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.modelConfig')}</h2>
              <TechnicalPill state="info" label={t('admin.collectionDefault')} />
            </div>
            <div className="model-config-form">
              <label>{t('dashboard.collection')}
                <select value={selectedCollection?.id || ''} onChange={(event) => setSelectedCollectionId(event.target.value)}>
                  {collections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <label>{t('admin.ocrEngine')}
                <select value={modelForm.ocr_engine} onChange={(event) => setModelForm({ ...modelForm, ocr_engine: event.target.value })}>
                  <option value="paddle_vl">{t('admin.engineOptionPaddle')}</option>
                  <option value="openai_vision">{t('admin.providerOptionOpenAIVision', 'External Vision (LM Studio / llama.cpp / Ollama)')}</option>
                  <option value="ppocrv6">{t('admin.engineOptionPpocr')}</option>
                  <option value="glm">{t('admin.engineOptionGlm')}</option>
                  <option value="fake">{t('admin.engineOptionFake')}</option>
                </select>
              </label>
              <label>{t('admin.ocrMode')}
                <select value={modelForm.ocr_mode} onChange={(event) => setModelForm({ ...modelForm, ocr_mode: event.target.value })}>
                  <option value="redo">{t('admin.ocrModeRedo')}</option>
                  <option value="force">{t('admin.ocrModeForce')}</option>
                  <option value="skip">{t('admin.ocrModeSkip')}</option>
                </select>
              </label>
              <label>{t('fields.language')}
                <input value={modelForm.language} onChange={(event) => setModelForm({ ...modelForm, language: event.target.value })} />
              </label>
              <label>{t('admin.pageLimit')}
                <input type="number" min="1" value={modelForm.page_limit} onChange={(event) => setModelForm({ ...modelForm, page_limit: event.target.value })} />
              </label>
              <label>{t('admin.dpi')}
                <input type="number" min="72" value={modelForm.image_dpi} onChange={(event) => setModelForm({ ...modelForm, image_dpi: event.target.value })} />
              </label>
              <label>{t('admin.output')}
                <select value={modelForm.output_type} onChange={(event) => setModelForm({ ...modelForm, output_type: event.target.value })}>
                  <option value="markdown">markdown</option>
                  <option value="text">text</option>
                </select>
              </label>
              <label>{t('admin.maxImagePixels')}
                <input type="number" min="1000000" value={modelForm.max_image_pixels} onChange={(event) => setModelForm({ ...modelForm, max_image_pixels: event.target.value })} />
              </label>
              <button type="button" className="primary" onClick={() => void saveModelConfig()}><Save size={16} /> {t('admin.saveConfig')}</button>
            </div>
          </section>
        </>
      )}

      {tab === 'system' && (
        <>
          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.integrations')}</h2>
              <TechnicalPill state={integrations?.ok ? 'ok' : 'down'} label={integrations?.ok ? t('admin.allReachable') : t('admin.needsAttention')} />
            </div>
            <div className="admin-list technical-list">
              {integrations?.integrations.map((item) => (
                <div key={item.name} className="admin-row technical-row">
                  <strong>{translateIntegrationName(item.name, t)}</strong>
                  <TechnicalPill state={item.ok ? 'ok' : 'down'} label={item.ok ? t('admin.up') : t('admin.down')} />
                  <span>{translateIntegrationDetail(item.detail, t)}</span>
                  <small>{item.latency_ms !== null ? `${item.latency_ms} ms` : ''}</small>
                </div>
              ))}
            </div>
          </section>

          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.accountTitle')}</h2>
              <TechnicalPill state="info" label={`${accountsState?.accounts.length ?? 1}`} />
            </div>
            <p className="muted">{t('admin.accountHint')}</p>

            {accountsState && (
              <div className="admin-list technical-list" style={{ marginBottom: '1rem' }}>
                {accountsState.accounts.map((item) => {
                  const isCurrent = item.username.toLowerCase() === accountsState.current_username.toLowerCase()
                  return (
                    <div key={item.username} className="admin-row technical-row">
                      <strong>{item.username}</strong>
                      <TechnicalPill state={isCurrent ? 'ok' : 'info'} label={isCurrent ? t('admin.accountCurrentBadge') : t('admin.accountMemberBadge')} />
                      <span />
                      {!isCurrent && (
                        <button type="button" disabled={accountBusy} onClick={() => void removeAccount(item.username)}>
                          {t('admin.accountRemove')}
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            <div className="admin-actions technical-actions" style={{ marginBottom: '1rem' }}>
              <input
                placeholder={t('admin.accountAddUsernamePlaceholder')}
                value={newAccountForm.username}
                onChange={(event) => setNewAccountForm({ ...newAccountForm, username: event.target.value })}
              />
              <input
                type="password"
                autoComplete="new-password"
                placeholder={t('login.setupPasswordPlaceholder')}
                value={newAccountForm.password}
                onChange={(event) => setNewAccountForm({ ...newAccountForm, password: event.target.value })}
              />
              <button type="button" disabled={accountBusy} onClick={() => void addAccount()}>
                {t('admin.accountAdd')}
              </button>
            </div>

            <label className="check" style={{ marginBottom: '1.15rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={Boolean(accountsState?.allow_registration)}
                disabled={accountBusy}
                onChange={(event) => void toggleSelfRegistration(event.target.checked)}
              />
              <span>{t('admin.allowRegistrationToggle')}</span>
            </label>

            <div className="model-config-form">
              <label>{t('admin.accountMyUsername')}
                <input
                  autoComplete="username"
                  value={accountForm.username}
                  onChange={(event) => setAccountForm({ ...accountForm, username: event.target.value })}
                />
              </label>
              <label>{t('admin.accountCurrentPassword')}
                <input
                  type="password"
                  autoComplete="current-password"
                  value={accountForm.currentPassword}
                  onChange={(event) => setAccountForm({ ...accountForm, currentPassword: event.target.value })}
                />
              </label>
              <label>{t('admin.accountNewPassword')}
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder={t('login.setupPasswordPlaceholder')}
                  value={accountForm.newPassword}
                  onChange={(event) => setAccountForm({ ...accountForm, newPassword: event.target.value })}
                />
              </label>
              <label>{t('login.setupConfirmPassword')}
                <input
                  type="password"
                  autoComplete="new-password"
                  value={accountForm.confirmPassword}
                  onChange={(event) => setAccountForm({ ...accountForm, confirmPassword: event.target.value })}
                />
              </label>
              <button type="button" className="primary" disabled={accountBusy} onClick={() => void saveAccountCredentials()}>
                <Save size={16} /> {accountBusy ? '…' : t('admin.accountSave')}
              </button>
            </div>
            {accountNotice && (
              <p className={accountNotice.ok ? 'success-message' : 'error'} role={accountNotice.ok ? 'status' : 'alert'}>
                {accountNotice.text}
              </p>
            )}
          </section>

          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.maintenance')}</h2>
            </div>
            <div className="admin-actions technical-actions">
              <button onClick={() => void runAction(api.reconcile, t('admin.reconciliationQueued'))}><Wrench size={16} /> {t('admin.reconcileStuck')}</button>
              <button onClick={() => void runAction(api.retryFailed, t('admin.failedDocsRetried'))}><RotateCcw size={16} /> {t('admin.retryFailed')}</button>
              <select value={collection} onChange={(event) => setCollection(event.target.value)}>
                {(collections.length ? collections.map((c) => c.name) : ['Belege', 'Eingangsrechnung', 'Ausgangsrechnung']).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
              <button onClick={() => void runAction(() => api.reextractCollection(collection, false), `${t('admin.reextractQueuedFor')} ${collection}.`)}>{t('admin.reextractCollection')}</button>
            </div>
          </section>
        </>
      )}

      {tab === 'automation' && (
        <>
          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.ingestionSources')}</h2>
              <TechnicalPill state="info" label={`${sources.length}`} />
            </div>
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
            {sources.length > 0 && (
              <div className="admin-list technical-list">
                {sources.map((source) => (
                  <div key={source.id} className="admin-row technical-row">
                    <strong>{source.name}</strong>
                    <TechnicalPill state={source.enabled ? 'ok' : 'down'} label={source.enabled ? t('status.enabled') : t('status.disabled')} />
                    <span>{source.path}</span>
                    <button onClick={() => void runAction(() => api.scanIngestionSource(source.id), `${t('admin.scanStartedFor')} ${source.name}.`)}>{t('admin.scan')}</button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="admin-card">
            <div className="section-heading-row">
              <h2>{t('admin.processingHooks')}</h2>
              <TechnicalPill state="info" label={`${hooks.length}`} />
            </div>
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
              {hookForm.hook_kind === 'command'
                ? <input placeholder={t('admin.command')} value={hookForm.command} onChange={(event) => setHookForm({ ...hookForm, command: event.target.value })} />
                : <input placeholder={t('admin.webhookUrl')} value={hookForm.webhook_url} onChange={(event) => setHookForm({ ...hookForm, webhook_url: event.target.value })} />}
              <label className="check"><input type="checkbox" checked={hookForm.blocking} onChange={(event) => setHookForm({ ...hookForm, blocking: event.target.checked })} /> {t('admin.blocking')}</label>
              <button onClick={() => void addHook()}>{t('admin.addHook')}</button>
            </div>
            {hooks.length > 0 && (
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
            )}
          </section>
        </>
      )}

      {tab === 'queues' && (
        <section className="admin-card operational-card">
          <details open={failed.length > 0}>
            <summary>{t('admin.failedDocuments')} ({failed.length})</summary>
            <div className="admin-list technical-list compact-list">
              {failed.map((job) => (
                <div key={job.document_id} className="admin-row technical-row">
                  <button onClick={() => onOpenDocument(job.document_id)}>{job.title || job.filename}</button>
                  <TechnicalPill state="down" label={job.state} />
                  <span>{job.error_message}</span>
                  <button className="icon-button" title={t('common.retry')} onClick={() => void runAction(() => api.retryDocument(job.document_id), t('admin.failedDocsRetried'))}><RotateCcw size={16} /></button>
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
                  <button className="icon-button" title={t('admin.forceRetryOcr')} onClick={() => void runAction(() => api.retryDocument(doc.id), t('admin.failedDocsRetried'))}><RotateCcw size={16} /></button>
                </div>
              ))}
            </div>
          </details>
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
          <details open={failed.length === 0}>
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
      )}
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

function providerLabel(provider: string, t: (key: string, fallback?: string) => string) {
  if (provider === 'fake') return t('admin.providerOptionFake')
  if (provider === 'ppocrv6') return t('admin.providerOptionLocal')
  if (provider === 'paddle_vl') return t('admin.providerOptionSmart')
  if (provider === 'openai_vision') return t('admin.providerOptionOpenAIVision', 'External Vision')
  if (provider === 'glm') return t('admin.providerOptionSecondary')
  return provider
}

function translateIntegrationName(name: string, t: (key: string, fallback?: string) => string) {
  return t(`admin.integrationName.${name}`, name.replace(/_/g, ' '))
}

function translateIntegrationDetail(detail: string, t: (key: string, fallback?: string) => string) {
  if (detail === 'reachable') return t('admin.detailReachable')
  if (detail === 'workers reachable') return t('admin.detailWorkersReachable')
  if (detail.endsWith('multimodal parser config looks usable')) return t('admin.detailPaddleUsable')
  if (detail === 'multimodal OCR config looks usable') return t('admin.detailMultimodalUsable')
  if (/^Configured .* model .* not found in \/v1\/models$/.test(detail)) return t('admin.detailEndpointModelMissing')
  if (detail.startsWith('reachable via ')) return translateEndpointDetail(detail, t)
  return detail
}

function translateEndpointDetail(detail: string, t: (key: string, fallback?: string) => string) {
  if (detail === 'reachable') return t('admin.detailReachable')
  if (detail.startsWith('reachable via ')) {
    const url = detail.replace('reachable via ', '')
    if (url.includes('smart-proxy') || url.includes('model-runtime:8092') || url.includes('172.19.0.1:8092') || url.includes('127.0.0.1:8092') || url.includes('localhost:8092')) return t('admin.detailInternalGatewayReachable')
    return `${t('admin.detailReachableVia')} ${url}`
  }
  return detail
}

function TechnicalPill({ state, label }: { state: 'ok' | 'down' | 'info'; label: string }) {
  return <span className={`technical-pill technical-pill-${state}`}>{label}</span>
}
