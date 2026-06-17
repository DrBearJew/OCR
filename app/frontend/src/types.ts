export type BatchStatus = 'pending' | 'processing' | 'partially_failed' | 'failed' | 'complete' | 'needs_review'
export type DocumentState = 'uploaded' | 'queued_for_ocr' | 'ocr_processing' | 'ocr_done' | 'metadata_processing' | 'metadata_done' | 'complete' | 'needs_review' | 'failed' | 'duplicate'
export type StageState = 'pending' | 'processing' | 'done' | 'skipped' | 'failed'
export type CustomFieldType = 'string' | 'text' | 'number' | 'date' | 'boolean' | 'select'
export type FieldValueSource = 'manual' | 'deterministic' | 'qwen' | 'imported'
export type OCRMode = 'skip' | 'redo' | 'force'
export type IngestionSourceType = 'upload' | 'consume_folder'
export type RecordGrouping = 'one_record_per_batch' | 'one_record_per_file'
export type IngestionJobStatus = 'pending' | 'processing' | 'imported' | 'skipped' | 'failed'
export type HookStage = 'pre_consume' | 'post_consume'
export type HookKind = 'command' | 'webhook'
export type ReviewState = 'unreviewed' | 'needs_review' | 'reviewed'

export interface Batch {
  id: string
  collection_name: string
  label: string | null
  status: BatchStatus
  document_count: number
  created_at: string
  updated_at: string
}

export interface Document {
  id: string
  batch_id: string
  record_id: string | null
  folder_id: string | null
  collection_name: string
  original_filename: string
  mime_type: string | null
  file_size: number
  sha256: string
  page_count: number | null
  duplicate_of_document_id: string | null
  correspondent_id: string | null
  document_type_id: string | null
  storage_path_id: string | null
  thumbnail_path: string | null
  legacy_source: string | null
  legacy_document_id: string | null
  processing_attempt: number
  last_processing_heartbeat_at: string | null
  retry_after_at: string | null
  ocr_mode: OCRMode
  ocr_config_json: Record<string, unknown>
  review_state: ReviewState
  review_reason: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  processing_state: DocumentState
  ocr_state: StageState
  metadata_state: StageState
  final_state: DocumentState
  ocr_text: string | null
  ocr_snippet?: string
  extracted_title: string | null
  extracted_sender: string | null
  extracted_recipient: string | null
  extracted_invoice_number: string | null
  extracted_date: string | null
  extracted_amount: string | null
  extracted_payment_method: string | null
  metadata_json: Record<string, unknown>
  processing_options_json: Record<string, unknown>
  metadata_sources_json: Record<string, unknown>
  field_locks_json: Record<string, unknown>
  raw_ocr_json: Record<string, unknown>
  prompt_trace_json: Record<string, unknown>
  model_trace_json: Record<string, unknown>
  processing_log_json: unknown[]
  qwen_response_text: string | null
  llm_summary: string | null
  llm_keywords: unknown[]
  llm_entities: Record<string, unknown>
  llm_document_purpose: string | null
  llm_suggested_tags: unknown[]
  llm_suggested_folder: string | null
  llm_related_query: unknown[]
  llm_confidence: number | null
  llm_raw_response: Record<string, unknown>
  error_message: string | null
  manual_title_override: string | null
  metadata_locked: boolean
  created_at: string
  updated_at: string
  completed_at: string | null
  deleted_at: string | null
  deleted_by: string | null
}

export interface BatchDetail extends Batch {
  documents: Document[]
}

export interface SearchResult {
  document_id: string
  batch_id: string
  record_id: string | null
  record_title: string | null
  folder_id: string | null
  folder_path: string | null
  collection_name: string
  extracted_title: string | null
  original_filename: string
  status: DocumentState
  correspondent_id: string | null
  document_type_id: string | null
  storage_path_id: string | null
  ocr_mode: OCRMode | null
  review_state: ReviewState | null
  snippet: string
  created_at: string
  rank: number
}

export interface SearchResultPage {
  items: SearchResult[]
  limit: number
  next_cursor: string | null
  total_estimate: number
}

export interface Collection {
  id: string
  name: string
  slug: string
  icon: string | null
  color: string | null
  title_generation_rule: Record<string, unknown>
  extraction_rules: Record<string, unknown>
  validation_rules: Record<string, unknown>
  display_config: Record<string, unknown>
  search_defaults: Record<string, unknown>
  ocr_config_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RecordRow {
  id: string
  collection_id: string
  folder_id: string | null
  title: string
  shared_title_base: string | null
  apply_shared_title_to_documents: boolean
  status: BatchStatus
  document_count: number
  summary_metadata: Record<string, unknown>
  custom_metadata: Record<string, unknown>
  manual_override_flags: Record<string, unknown>
  created_at: string
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
  collection: Collection | null
  documents: Document[]
}

export interface DocumentListPage {
  items: Document[]
  limit: number
  next_cursor: string | null
  total_estimate: number
}

export interface RecordListPage {
  items: RecordRow[]
  limit: number
  next_cursor: string | null
  total_estimate: number
}


export interface Folder {
  id: string
  parent_id: string | null
  collection_id: string | null
  name: string
  path: string
  document_count: number
  record_count: number
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface FolderContentsItem {
  kind: 'record' | 'document'
  id: string
  folder_id: string | null
  folder_path: string | null
  collection_id: string | null
  collection_name: string | null
  record_id: string | null
  title: string
  subtitle: string | null
  status: string | null
  review_state: string | null
  document_count: number | null
  original_filename: string | null
  mime_type: string | null
  thumbnail_path: string | null
  ocr_snippet: string | null
  created_at: string
  updated_at: string
}

export interface FolderContentsPage {
  kind: 'records' | 'documents'
  scope: 'all' | 'direct' | 'subtree' | 'unfiled'
  folder_id: string | null
  limit: number
  next_cursor: string | null
  total_estimate: number
  items: FolderContentsItem[]
}

export interface CustomFieldDefinition {
  id: string
  collection_id: string
  name: string
  slug: string
  field_type: CustomFieldType
  required: boolean
  searchable: boolean
  default_value: string | null
  enum_options: unknown[]
  extraction_binding: Record<string, unknown>
  validation_rules: Record<string, unknown>
  display_order: number
  created_at: string
  updated_at: string
}

export interface DocumentCustomFieldValue {
  id: string
  document_id: string
  custom_field_definition_id: string
  raw_value: string | null
  normalized_value: string | null
  source: FieldValueSource
  confidence: number | null
  locked: boolean
  created_at: string
  updated_at: string
}

export interface JobInfo {
  document_id: string
  batch_id: string
  state: DocumentState
  ocr_state: StageState
  metadata_state: StageState
  filename: string
  title: string | null
  updated_at: string
  error_message: string | null
}

export interface IntegrationStatus {
  name: string
  ok: boolean
  detail: string
  latency_ms: number | null
  metadata: Record<string, unknown>
}

export interface ModelSetup {
  mode: string
  ocr_provider: string
  paddle_vl_base_url: string
  paddle_vl_model: string
  glm_base_url: string
  glm_model: string
  qwen_enabled: boolean
  qwen_base_url: string
  qwen_model: string
  timeout_seconds: number
}

export interface ModelEndpointTestResult {
  ok: boolean
  detail: string
  available_models: string[]
  base_url?: string | null
  model?: string | null
}

export interface IntegrationSummary {
  ok: boolean
  integrations: IntegrationStatus[]
}

export interface DocumentEvent {
  id: string
  document_id: string
  event_type: string
  actor: string
  source: string
  message: string | null
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  event_metadata: Record<string, unknown>
  created_at: string
}

export interface DocumentPage {
  id: string
  document_id: string
  page_number: number
  ocr_text: string | null
  raw_ocr_json: Record<string, unknown>
  rendered_image_path: string | null
  created_at: string
  updated_at: string
}

export interface AdminActionResult {
  ok: boolean
  queued: number
  updated: number
  skipped: number
  details: Record<string, unknown>
}

export interface IngestionSource {
  id: string
  name: string
  source_type: IngestionSourceType
  path: string | null
  enabled: boolean
  collection_id: string
  record_grouping: RecordGrouping
  polling_interval_seconds: number
  ignore_patterns: unknown[]
  recursive: boolean
  ocr_config_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface IngestionJob {
  id: string
  source_id: string
  status: IngestionJobStatus
  discovered_path: string
  sha256: string | null
  batch_id: string | null
  record_id: string | null
  document_id: string | null
  attempts: number
  error_message: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface ProcessingHook {
  id: string
  name: string
  stage: HookStage
  hook_kind: HookKind
  enabled: boolean
  blocking: boolean
  command: string | null
  webhook_url: string | null
  timeout_seconds: number
  env_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface PaperlessMetadata {
  id: string
  collection_id: string | null
  name: string
  slug: string
  color: string | null
  path_template: string | null
  match_rules: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface SavedView {
  id: string
  name: string
  slug: string
  section: string
  filters_json: Record<string, unknown>
  sort_json: Record<string, unknown>
  display_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface DashboardSummary {
  status_counts: Record<string, number>
  review_counts: Record<string, number>
  collection_counts: Array<{ collection: string; documents: number }>
  recent_records: RecordRow[]
  failed_documents: Document[]
  completed_documents: Document[]
}

export interface ActivityItem extends DocumentEvent {
  record_id: string | null
  document_title: string
  original_filename: string
  collection_name: string
}

export interface ProcessingSummary {
  documents: Document[]
  stuck_documents: Document[]
  ingestion_jobs: IngestionJob[]
  summary: Record<string, number>
}

export interface FailedReviewSummary {
  failed_documents: Document[]
  needs_review_documents: Document[]
  missing_required_documents: Document[]
}

export interface CollectionSummary {
  collection: Pick<Collection, 'id' | 'name' | 'slug' | 'icon' | 'color'>
  record_count: number
  document_count: number
  status_counts: Record<string, number>
}

export interface CollectionPageData {
  collection: Pick<Collection, 'id' | 'name' | 'slug' | 'icon' | 'color' | 'display_config'>
  records: RecordRow[]
  status_counts: Record<string, number>
  limit?: number
  next_cursor?: string | null
  total_estimate?: number
}
