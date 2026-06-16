from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    BatchStatus,
    CustomFieldType,
    DocumentState,
    FieldValueSource,
    HookKind,
    HookStage,
    IngestionJobStatus,
    IngestionSourceType,
    OCRMode,
    RecordGrouping,
    ReviewState,
    StageState,
)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class BatchRead(BaseModel):
    id: uuid.UUID
    collection_name: str
    label: str | None
    status: BatchStatus
    document_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CollectionRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    icon: str | None = None
    color: str | None = None
    title_generation_rule: dict[str, Any] = Field(default_factory=dict)
    extraction_rules: dict[str, Any] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    display_config: dict[str, Any] = Field(default_factory=dict)
    search_defaults: dict[str, Any] = Field(default_factory=dict)
    ocr_config_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CollectionCreate(BaseModel):
    name: str
    slug: str | None = None
    icon: str | None = None
    color: str | None = None
    title_generation_rule: dict[str, Any] = Field(default_factory=dict)
    extraction_rules: dict[str, Any] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    display_config: dict[str, Any] = Field(default_factory=dict)
    search_defaults: dict[str, Any] = Field(default_factory=dict)
    ocr_config_json: dict[str, Any] = Field(default_factory=dict)


class CollectionUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    icon: str | None = None
    color: str | None = None
    title_generation_rule: dict[str, Any] | None = None
    extraction_rules: dict[str, Any] | None = None
    validation_rules: dict[str, Any] | None = None
    display_config: dict[str, Any] | None = None
    search_defaults: dict[str, Any] | None = None
    ocr_config_json: dict[str, Any] | None = None


class CustomFieldDefinitionRead(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    name: str
    slug: str
    field_type: CustomFieldType
    required: bool
    searchable: bool
    default_value: str | None = None
    enum_options: list[Any] = Field(default_factory=list)
    extraction_binding: dict[str, Any] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomFieldDefinitionWrite(BaseModel):
    name: str
    slug: str
    field_type: CustomFieldType
    required: bool = False
    searchable: bool = False
    default_value: str | None = None
    enum_options: list[Any] = Field(default_factory=list)
    extraction_binding: dict[str, Any] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    display_order: int = 0


class DocumentRead(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    record_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    collection_name: str
    original_filename: str
    mime_type: str | None
    file_size: int
    sha256: str
    page_count: int | None = None
    duplicate_of_document_id: uuid.UUID | None = None
    correspondent_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    storage_path_id: uuid.UUID | None = None
    thumbnail_path: str | None = None
    legacy_source: str | None = None
    legacy_document_id: str | None = None
    processing_attempt: int = 0
    last_processing_heartbeat_at: datetime | None = None
    retry_after_at: datetime | None = None
    processing_task_id: str | None = None
    processing_started_at: datetime | None = None
    processing_lease_until: datetime | None = None
    current_stage: str | None = None
    ocr_mode: OCRMode = OCRMode.redo
    ocr_config_json: dict[str, Any] = Field(default_factory=dict)
    review_state: ReviewState = ReviewState.unreviewed
    review_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    processing_state: DocumentState
    ocr_state: StageState
    metadata_state: StageState
    final_state: DocumentState
    ocr_text: str | None = None
    extracted_title: str | None = None
    extracted_sender: str | None = None
    extracted_recipient: str | None = None
    extracted_invoice_number: str | None = None
    extracted_date: str | None = None
    extracted_amount: str | None = None
    extracted_payment_method: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    processing_options_json: dict[str, Any] = Field(default_factory=dict)
    metadata_sources_json: dict[str, Any] = Field(default_factory=dict)
    field_locks_json: dict[str, Any] = Field(default_factory=dict)
    raw_ocr_json: dict[str, Any] = Field(default_factory=dict)
    prompt_trace_json: dict[str, Any] = Field(default_factory=dict)
    model_trace_json: dict[str, Any] = Field(default_factory=dict)
    processing_log_json: list[Any] = Field(default_factory=list)
    qwen_response_text: str | None = None
    llm_summary: str | None = None
    llm_keywords: list[Any] = Field(default_factory=list)
    llm_entities: dict[str, Any] = Field(default_factory=dict)
    llm_document_purpose: str | None = None
    llm_suggested_tags: list[Any] = Field(default_factory=list)
    llm_suggested_folder: str | None = None
    llm_related_query: list[Any] = Field(default_factory=list)
    llm_confidence: int | None = None
    llm_raw_response: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    manual_title_override: str | None = None
    metadata_locked: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentCustomFieldValueRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    custom_field_definition_id: uuid.UUID
    raw_value: str | None = None
    normalized_value: str | None = None
    source: FieldValueSource
    confidence: int | None = None
    locked: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentCustomFieldValueWrite(BaseModel):
    custom_field_definition_id: uuid.UUID
    raw_value: Any = None
    source: FieldValueSource = FieldValueSource.manual
    confidence: int | None = None
    locked: bool | None = None
    force: bool = False


class BatchDetail(BatchRead):
    documents: list[DocumentRead] = Field(default_factory=list)


class RecordRead(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str
    shared_title_base: str | None = None
    apply_shared_title_to_documents: bool = False
    status: BatchStatus
    document_count: int
    summary_metadata: dict[str, Any] = Field(default_factory=dict)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)
    manual_override_flags: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    collection: CollectionRead | None = None
    documents: list[DocumentRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DocumentPatch(BaseModel):
    manual_title_override: str | None = None
    extracted_title: str | None = None
    extracted_sender: str | None = None
    extracted_recipient: str | None = None
    extracted_invoice_number: str | None = None
    extracted_date: str | None = None
    extracted_amount: str | None = None
    extracted_payment_method: str | None = None
    metadata_locked: bool | None = None
    correspondent_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    storage_path_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    ocr_mode: OCRMode | None = None
    ocr_config_json: dict[str, Any] | None = None
    review_state: ReviewState | None = None
    review_reason: str | None = None


class RecordPatch(BaseModel):
    title: str | None = None
    custom_metadata: dict[str, Any] | None = None
    manual_override_flags: dict[str, Any] | None = None
    shared_title_base: str | None = None
    apply_shared_title_to_documents: bool | None = None
    folder_id: uuid.UUID | None = None


class OCRSettingsPatch(BaseModel):
    ocr_mode: OCRMode | None = None
    ocr_config_json: dict[str, Any] = Field(default_factory=dict)


class DocumentBulkAction(BaseModel):
    document_ids: list[uuid.UUID]
    action: str
    force: bool = False
    review_state: ReviewState | None = None
    review_reason: str | None = None
    tag_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    collection_name: str | None = None


class SavedViewRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    section: str
    filters_json: dict[str, Any] = Field(default_factory=dict)
    sort_json: dict[str, Any] = Field(default_factory=dict)
    display_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SavedViewWrite(BaseModel):
    name: str
    slug: str | None = None
    section: str
    filters_json: dict[str, Any] = Field(default_factory=dict)
    sort_json: dict[str, Any] = Field(default_factory=dict)
    display_json: dict[str, Any] = Field(default_factory=dict)


class PaperlessMetadataRead(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID | None = None
    name: str
    slug: str
    color: str | None = None
    path_template: str | None = None
    match_rules: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaperlessMetadataWrite(BaseModel):
    collection_id: uuid.UUID | None = None
    name: str
    slug: str | None = None
    color: str | None = None
    path_template: str | None = None
    match_rules: dict[str, Any] = Field(default_factory=dict)


class IngestionSourceRead(BaseModel):
    id: uuid.UUID
    name: str
    source_type: IngestionSourceType
    path: str | None = None
    enabled: bool
    collection_id: uuid.UUID
    record_grouping: RecordGrouping
    polling_interval_seconds: int
    ignore_patterns: list[Any] = Field(default_factory=list)
    recursive: bool
    ocr_config_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IngestionSourceWrite(BaseModel):
    name: str
    source_type: IngestionSourceType = IngestionSourceType.consume_folder
    path: str | None = None
    enabled: bool = True
    collection_id: uuid.UUID
    record_grouping: RecordGrouping = RecordGrouping.one_record_per_file
    polling_interval_seconds: int = 300
    ignore_patterns: list[Any] = Field(default_factory=list)
    recursive: bool = False
    ocr_config_json: dict[str, Any] = Field(default_factory=dict)


class IngestionJobRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    status: IngestionJobStatus
    discovered_path: str
    sha256: str | None = None
    batch_id: uuid.UUID | None = None
    record_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    attempts: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProcessingHookRead(BaseModel):
    id: uuid.UUID
    name: str
    stage: HookStage
    hook_kind: HookKind
    enabled: bool
    blocking: bool
    command: str | None = None
    webhook_url: str | None = None
    timeout_seconds: int
    env_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProcessingHookWrite(BaseModel):
    name: str
    stage: HookStage
    hook_kind: HookKind
    enabled: bool = True
    blocking: bool = True
    command: str | None = None
    webhook_url: str | None = None
    timeout_seconds: int = 30
    env_json: dict[str, Any] = Field(default_factory=dict)


class DocumentEventRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    event_type: str
    actor: str
    source: str
    message: str | None = None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentPageRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    ocr_text: str | None = None
    raw_ocr_json: dict[str, Any] = Field(default_factory=dict)
    rendered_image_path: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SearchResult(BaseModel):
    document_id: uuid.UUID
    batch_id: uuid.UUID
    record_id: uuid.UUID | None = None
    record_title: str | None = None
    folder_id: uuid.UUID | None = None
    folder_path: str | None = None
    collection_name: str
    extracted_title: str | None
    original_filename: str
    status: DocumentState
    correspondent_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    storage_path_id: uuid.UUID | None = None
    ocr_mode: OCRMode | None = None
    review_state: ReviewState | None = None
    snippet: str
    created_at: datetime
    rank: float = 0.0


class JobInfo(BaseModel):
    document_id: uuid.UUID
    batch_id: uuid.UUID
    state: DocumentState
    ocr_state: StageState
    metadata_state: StageState
    filename: str
    title: str | None
    updated_at: datetime
    error_message: str | None = None


class AdminActionResult(BaseModel):
    ok: bool = True
    queued: int = 0
    updated: int = 0
    skipped: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class ModelSetupRead(BaseModel):
    mode: str = "fake"
    ocr_provider: str = "fake"
    paddle_vl_base_url: str = ""
    paddle_vl_model: str = "paddleocr-vl"
    glm_base_url: str = ""
    glm_model: str = "glm"
    qwen_enabled: bool = False
    qwen_base_url: str = ""
    qwen_model: str = "qwen"
    timeout_seconds: float = 120.0


class ModelSetupWrite(ModelSetupRead):
    pass


class ModelEndpointTestPayload(BaseModel):
    base_url: str
    model: str = ""
    timeout_seconds: float | None = None


class ModelEndpointTestResult(BaseModel):
    ok: bool
    detail: str
    available_models: list[str] = Field(default_factory=list)
    base_url: str | None = None
    model: str | None = None


class FolderRead(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    name: str
    path: str
    document_count: int = 0
    record_count: int = 0
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FolderWrite(BaseModel):
    parent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    name: str


class FolderMovePayload(BaseModel):
    folder_id: uuid.UUID | None = None
