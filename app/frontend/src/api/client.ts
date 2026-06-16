import type { ActivityItem, AdminActionResult, Batch, BatchDetail, Collection, CollectionPageData, CollectionSummary, CustomFieldDefinition, DashboardSummary, Document, DocumentCustomFieldValue, DocumentEvent, DocumentPage, FailedReviewSummary, Folder, FolderContentsPage, IngestionJob, IngestionSource, IntegrationSummary, ModelEndpointTestResult, ModelSetup, JobInfo, PaperlessMetadata, ProcessingHook, ProcessingSummary, RecordRow, SavedView, SearchResult } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const TOKEN_KEY = 'dokocr_token'
const TOKEN_EXPIRY_SKEW_SECONDS = 10
export const AUTH_EXPIRED_EVENT = 'dokocr:auth-expired'

interface ProcessOptions {
  force?: boolean
  qwenEnabled?: boolean
  overwriteManualValues?: boolean
}

export function getToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY)
  if (!token) return null
  if (isStoredTokenExpired(token)) {
    setToken(null)
    return null
  }
  return token
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function expireClientSession() {
  setToken(null)
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}

function isStoredTokenExpired(token: string): boolean {
  if (token === 'dev-preview-token' && import.meta.env.DEV) return false
  const parts = token.split('.')
  if (parts.length !== 3) return true
  try {
    const payload = JSON.parse(decodeBase64Url(parts[1])) as { exp?: unknown }
    if (typeof payload.exp !== 'number') return true
    return payload.exp <= Math.floor(Date.now() / 1000) + TOKEN_EXPIRY_SKEW_SECONDS
  } catch {
    return true
  }
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
  return atob(padded)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    const text = await response.text()
    if (response.status === 401 && path !== '/api/auth/login') {
      expireClientSession()
      throw new Error('Session expired. Please sign in again.')
    }
    if (response.status === 413) {
      throw new Error('Upload too large. Check the configured max file size and max batch size.')
    }
    throw new Error(text || response.statusText)
  }
  return response.json() as Promise<T>
}

export async function login(username: string, password: string): Promise<void> {
  try {
    const data = await request<{ access_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    })
    setToken(data.access_token)
  } catch (err) {
    if (canUseDevPreviewLogin(username, password, err)) {
      setToken('dev-preview-token')
      return
    }
    throw err
  }
}

function canUseDevPreviewLogin(username: string, password: string, err: unknown): boolean {
  if (import.meta.env.PROD) return false
  if (!import.meta.env.DEV || import.meta.env.VITE_ALLOW_DEMO_LOGIN !== 'true') return false
  if (username !== 'admin' || password !== 'admin') return false
  const message = err instanceof Error ? err.message.toLowerCase() : String(err).toLowerCase()
  return ['bad gateway', 'failed to fetch', 'proxy', 'gateway', 'connect', 'econnrefused'].some((needle) => message.includes(needle))
}

export const api = {
  batches: () => request<Batch[]>('/api/batches'),
  batch: (id: string) => request<BatchDetail>(`/api/batches/${id}`),
  uploadBatch: (form: FormData) => request<BatchDetail>('/api/batches/upload', { method: 'POST', body: form }),
  collections: () => request<Collection[]>('/api/collections'),
  createCollection: (payload: Partial<Collection>) => request<Collection>('/api/collections', { method: 'POST', body: JSON.stringify(payload) }),
  patchCollection: (id: string, payload: Partial<Collection>) => request<Collection>(`/api/collections/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  dashboard: () => request<DashboardSummary>('/api/dashboard'),
  activity: (params: Record<string, string> = {}) => request<ActivityItem[]>(`/api/activity?${new URLSearchParams(params).toString()}`),
  processing: () => request<ProcessingSummary>('/api/processing'),
  failedReview: () => request<FailedReviewSummary>('/api/failed'),
  collectionSummaries: () => request<CollectionSummary[]>('/api/collection-summaries'),
  collectionPage: (slug: string) => request<CollectionPageData>(`/api/collection-pages/${encodeURIComponent(slug)}`),
  customFields: (collectionId: string) => request<CustomFieldDefinition[]>(`/api/collections/${collectionId}/fields`),
  createCustomField: (collectionId: string, payload: Partial<CustomFieldDefinition>) =>
    request<CustomFieldDefinition>(`/api/collections/${collectionId}/fields`, { method: 'POST', body: JSON.stringify(payload) }),
  records: () => request<RecordRow[]>('/api/records'),
  record: (id: string) => request<RecordRow>(`/api/records/${id}`),
  patchRecord: (id: string, payload: Partial<RecordRow>) =>
    request<RecordRow>(`/api/records/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  applySharedTitle: (id: string, onlyUnlocked = true) =>
    request<RecordRow>(`/api/records/${id}/apply-shared-title?only_unlocked=${onlyUnlocked}`, { method: 'POST' }),
  processRecord: (id: string, options: boolean | ProcessOptions = false) => {
    const normalized = typeof options === 'boolean' ? { force: options } : options
    const query = new URLSearchParams()
    query.set('force', String(Boolean(normalized.force)))
    if (normalized.qwenEnabled !== undefined) query.set('qwen_enabled', String(normalized.qwenEnabled))
    if (normalized.overwriteManualValues !== undefined) query.set('overwrite_manual_values', String(normalized.overwriteManualValues))
    return request<AdminActionResult>(`/api/records/${id}/process-all?${query.toString()}`, { method: 'POST' })
  },
  deleteRecord: (id: string) => request<RecordRow>(`/api/records/${id}`, { method: 'DELETE' }),
  restoreRecord: (id: string) => request<RecordRow>(`/api/records/${id}/restore`, { method: 'POST' }),
  purgeRecord: (id: string) => request<AdminActionResult>(`/api/records/${id}/purge`, { method: 'POST' }),
  documents: (params: Record<string, string> = {}) => {
    const query = new URLSearchParams(params)
    return request<Document[]>(`/api/documents${query.toString() ? `?${query.toString()}` : ''}`)
  },
  duplicates: () => request<Document[]>('/api/documents/duplicates'),
  document: (id: string) => request<Document>(`/api/documents/${id}`),
  documentEvents: (id: string) => request<DocumentEvent[]>(`/api/documents/${id}/events`),
  documentPages: (id: string) => request<DocumentPage[]>(`/api/documents/${id}/pages`),
  documentCustomFields: (id: string) => request<DocumentCustomFieldValue[]>(`/api/documents/${id}/custom-fields`),
  upsertDocumentCustomField: (id: string, payload: Partial<DocumentCustomFieldValue> & { force?: boolean }) =>
    request<DocumentCustomFieldValue>(`/api/documents/${id}/custom-fields`, { method: 'PUT', body: JSON.stringify(payload) }),
  patchDocument: (id: string, payload: Partial<Document>) =>
    request<Document>(`/api/documents/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  retryDocument: (id: string) => request<Document>(`/api/documents/${id}/retry`, { method: 'POST' }),
  processDocument: (id: string, options: boolean | ProcessOptions = false) => {
    const normalized = typeof options === 'boolean' ? { force: options } : options
    const query = new URLSearchParams()
    query.set('force', String(Boolean(normalized.force)))
    if (normalized.qwenEnabled !== undefined) query.set('qwen_enabled', String(normalized.qwenEnabled))
    if (normalized.overwriteManualValues !== undefined) query.set('overwrite_manual_values', String(normalized.overwriteManualValues))
    return request<Document>(`/api/documents/${id}/process?${query.toString()}`, { method: 'POST' })
  },
  deleteDocument: (id: string) => request<Document>(`/api/documents/${id}`, { method: 'DELETE' }),
  restoreDocument: (id: string) => request<Document>(`/api/documents/${id}/restore`, { method: 'POST' }),
  purgeDocument: (id: string) => request<AdminActionResult>(`/api/documents/${id}/purge`, { method: 'POST' }),
  runDocumentOcr: (id: string, ocrMode = '') =>
    request<Document>(`/api/documents/${id}/ocr${ocrMode ? `?ocr_mode=${encodeURIComponent(ocrMode)}` : ''}`, { method: 'POST' }),
  patchOcrSettings: (id: string, payload: { ocr_mode?: string; ocr_config_json?: Record<string, unknown> }) =>
    request<Document>(`/api/documents/${id}/ocr-settings`, { method: 'PATCH', body: JSON.stringify(payload) }),
  documentPipeline: (id: string) => request<Record<string, unknown>>(`/api/documents/${id}/pipeline`),
  documentDiagnostics: (id: string) => request<Record<string, unknown>>(`/api/documents/${id}/diagnostics`),
  extractionPreview: (id: string) => request<Record<string, unknown>>(`/api/documents/${id}/extraction-preview`, { method: 'POST' }),
  applyExtractionPreview: (id: string, force = false) =>
    request<Document>(`/api/documents/${id}/extraction-preview/apply?force=${force}`, { method: 'POST' }),
  reindexDocument: (id: string) => request<Document>(`/api/documents/${id}/reindex`, { method: 'POST' }),
  reextractDocument: (id: string, options: boolean | { force?: boolean; qwenEnabled?: boolean; overwriteManualValues?: boolean; skipMetadata?: boolean } = false) => {
    const normalized = typeof options === 'boolean' ? { force: options } : options
    const query = new URLSearchParams()
    query.set('force', String(Boolean(normalized.force)))
    if (normalized.qwenEnabled !== undefined) query.set('qwen_enabled', String(normalized.qwenEnabled))
    if (normalized.overwriteManualValues !== undefined) query.set('overwrite_manual_values', String(normalized.overwriteManualValues))
    if (normalized.skipMetadata !== undefined) query.set('skip_metadata', String(normalized.skipMetadata))
    return request<Document>(`/api/documents/${id}/reextract?${query.toString()}`, { method: 'POST' })
  },
  bulkDocuments: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/documents/bulk', { method: 'POST', body: JSON.stringify(payload) }),
  search: (params: { q: string; collection?: string; status?: string; filename?: string; title?: string; dateFrom?: string; dateTo?: string; customField?: string; customValue?: string; correspondentId?: string; documentTypeId?: string; tagId?: string; storagePathId?: string; folderId?: string; ocrMode?: string; reviewState?: string }) => {
    const query = new URLSearchParams({ q: params.q })
    if (params.collection) query.set('collection_name', params.collection)
    if (params.status) query.set('status', params.status)
    if (params.filename) query.set('filename', params.filename)
    if (params.title) query.set('title', params.title)
    if (params.dateFrom) query.set('date_from', params.dateFrom)
    if (params.dateTo) query.set('date_to', params.dateTo)
    if (params.customField) query.set('custom_field', params.customField)
    if (params.customValue) query.set('custom_value', params.customValue)
    if (params.correspondentId) query.set('correspondent_id', params.correspondentId)
    if (params.documentTypeId) query.set('document_type_id', params.documentTypeId)
    if (params.tagId) query.set('tag_id', params.tagId)
    if (params.storagePathId) query.set('storage_path_id', params.storagePathId)
    if (params.folderId) query.set('folder_id', params.folderId)
    if (params.ocrMode) query.set('ocr_mode', params.ocrMode)
    if (params.reviewState) query.set('review_state', params.reviewState)
    return request<SearchResult[]>(`/api/search?${query.toString()}`)
  },
  savedViews: (section = '') => request<SavedView[]>(`/api/saved-views${section ? `?section=${encodeURIComponent(section)}` : ''}`),
  createSavedView: (payload: Partial<SavedView>) => request<SavedView>('/api/saved-views', { method: 'POST', body: JSON.stringify(payload) }),
  updateSavedView: (id: string, payload: Partial<SavedView>) => request<SavedView>(`/api/saved-views/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteSavedView: (id: string) => request<{ ok: boolean }>(`/api/saved-views/${id}`, { method: 'DELETE' }),
  jobs: () => request<JobInfo[]>('/api/admin/jobs'),
  failed: () => request<JobInfo[]>('/api/admin/failed'),
  integrations: () => request<IntegrationSummary>('/api/admin/integrations'),
  modelSetup: () => request<ModelSetup>('/api/admin/model-setup'),
  saveModelSetup: (payload: ModelSetup) => request<ModelSetup>('/api/admin/model-setup', { method: 'PATCH', body: JSON.stringify(payload) }),
  testModelEndpoint: (payload: { base_url: string; model?: string; timeout_seconds?: number }) =>
    request<ModelEndpointTestResult>('/api/admin/model-setup/test', { method: 'POST', body: JSON.stringify(payload) }),
  reconcile: () => request<AdminActionResult>('/api/admin/reconcile', { method: 'POST' }),
  retryFailed: () => request<AdminActionResult>('/api/admin/retry-failed', { method: 'POST' }),
  reextractCollection: (collectionName: string, force = false) =>
    request<AdminActionResult>(`/api/admin/reextract-collection?collection_name=${encodeURIComponent(collectionName)}&force=${force}`, { method: 'POST' }),
  ingestionSources: () => request<IngestionSource[]>('/api/admin/ingestion-sources'),
  createIngestionSource: (payload: Partial<IngestionSource>) =>
    request<IngestionSource>('/api/admin/ingestion-sources', { method: 'POST', body: JSON.stringify(payload) }),
  scanIngestionSource: (id: string) => request<Record<string, unknown>>(`/api/admin/ingestion-sources/${id}/scan`, { method: 'POST' }),
  scanAllIngestionSources: () => request<Record<string, unknown>>('/api/admin/ingestion-sources/scan-all', { method: 'POST' }),
  ingestionJobs: () => request<IngestionJob[]>('/api/admin/ingestion-jobs'),
  retryIngestionJob: (id: string) => request<IngestionJob>(`/api/admin/ingestion-jobs/${id}/retry`, { method: 'POST' }),
  hooks: () => request<ProcessingHook[]>('/api/admin/hooks'),
  createHook: (payload: Partial<ProcessingHook>) => request<ProcessingHook>('/api/admin/hooks', { method: 'POST', body: JSON.stringify(payload) }),
  testHook: (id: string) => request<Record<string, unknown>>(`/api/admin/hooks/${id}/test`, { method: 'POST' }),
  paperlessMetadata: (kind: 'correspondents' | 'document-types' | 'tags' | 'storage-paths') =>
    request<PaperlessMetadata[]>(`/api/admin/metadata/${kind}`),
  createPaperlessMetadata: (kind: 'correspondents' | 'document-types' | 'tags' | 'storage-paths', payload: Partial<PaperlessMetadata>) =>
    request<PaperlessMetadata>(`/api/admin/metadata/${kind}`, { method: 'POST', body: JSON.stringify(payload) }),
  folders: (params: Record<string, string> = {}) => {
    const query = new URLSearchParams(params)
    return request<Folder[]>(`/api/folders${query.toString() ? `?${query.toString()}` : ''}`)
  },
  folderContents: (params: { kind: 'records' | 'documents'; scope?: 'all' | 'direct' | 'subtree' | 'unfiled'; folderId?: string | null; q?: string; limit?: number; cursor?: string | null }) => {
    const query = new URLSearchParams({ kind: params.kind })
    if (params.scope) query.set('scope', params.scope)
    if (params.folderId) query.set('folder_id', params.folderId)
    if (params.q) query.set('q', params.q)
    if (params.limit) query.set('limit', String(params.limit))
    if (params.cursor) query.set('cursor', params.cursor)
    return request<FolderContentsPage>(`/api/folders/contents?${query.toString()}`)
  },
  createFolder: (payload: Partial<Folder>) => request<Folder>('/api/folders', { method: 'POST', body: JSON.stringify(payload) }),
  updateFolder: (id: string, payload: Partial<Folder>) => request<Folder>(`/api/folders/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteFolder: (id: string, deleteContents = false) => request<Folder>(`/api/folders/${id}${deleteContents ? '?delete_contents=true' : ''}`, { method: 'DELETE' }),
  restoreFolder: (id: string) => request<Folder>(`/api/folders/${id}/restore`, { method: 'POST' }),
  moveDocumentToFolder: (documentId: string, folderId: string | null) =>
    request<Document>(`/api/folders/move-document/${documentId}`, { method: 'POST', body: JSON.stringify({ folder_id: folderId }) }),
  moveRecordToFolder: (recordId: string, folderId: string | null) =>
    request<RecordRow>(`/api/folders/move-record/${recordId}`, { method: 'POST', body: JSON.stringify({ folder_id: folderId }) })
}

export function previewUrl(id: string): string {
  return `${API_BASE}/api/documents/${id}/preview`
}

export function downloadUrl(id: string): string {
  return `${API_BASE}/api/documents/${id}/download`
}

export function thumbnailUrl(id: string): string {
  return `${API_BASE}/api/documents/${id}/thumbnail`
}
