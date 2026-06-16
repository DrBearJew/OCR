from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


JSONVariant = JSON().with_variant(JSONB, "postgresql")


class BatchStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    partially_failed = "partially_failed"
    failed = "failed"
    complete = "complete"
    needs_review = "needs_review"


class DocumentState(str, enum.Enum):
    uploaded = "uploaded"
    queued_for_ocr = "queued_for_ocr"
    ocr_processing = "ocr_processing"
    ocr_done = "ocr_done"
    metadata_processing = "metadata_processing"
    metadata_done = "metadata_done"
    complete = "complete"
    needs_review = "needs_review"
    failed = "failed"
    duplicate = "duplicate"


class StageState(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    skipped = "skipped"
    failed = "failed"


class CustomFieldType(str, enum.Enum):
    string = "string"
    text = "text"
    number = "number"
    date = "date"
    boolean = "boolean"
    select = "select"


class FieldValueSource(str, enum.Enum):
    manual = "manual"
    deterministic = "deterministic"
    qwen = "qwen"
    imported = "imported"


class IngestionSourceType(str, enum.Enum):
    upload = "upload"
    consume_folder = "consume_folder"


class RecordGrouping(str, enum.Enum):
    one_record_per_batch = "one_record_per_batch"
    one_record_per_file = "one_record_per_file"


class IngestionJobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    imported = "imported"
    skipped = "skipped"
    failed = "failed"


class OCRMode(str, enum.Enum):
    skip = "skip"
    redo = "redo"
    force = "force"


class HookStage(str, enum.Enum):
    pre_consume = "pre_consume"
    post_consume = "post_consume"


class HookKind(str, enum.Enum):
    command = "command"
    webhook = "webhook"


class ReviewState(str, enum.Enum):
    unreviewed = "unreviewed"
    needs_review = "needs_review"
    reviewed = "reviewed"


document_tags = Table(
    "document_tags",
    Base.metadata,
    Column("document_id", Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    icon: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    title_generation_rule: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    extraction_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    validation_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    display_config: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    search_defaults: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    ocr_config_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    records: Mapped[list["Record"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    custom_fields: Mapped[list["CustomFieldDefinition"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", order_by="CustomFieldDefinition.display_order"
    )
    correspondents: Mapped[list["Correspondent"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    document_types: Mapped[list["DocumentType"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    tags: Mapped[list["Tag"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    storage_paths: Mapped[list["StoragePathRule"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    ingestion_sources: Mapped[list["IngestionSource"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    folders: Mapped[list["Folder"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class Record(Base):
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="Untitled")
    shared_title_base: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    apply_shared_title_to_documents: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status", create_type=False),
        default=BatchStatus.pending,
        nullable=False,
        index=True,
    )
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_metadata: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    custom_metadata: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    manual_override_flags: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    collection: Mapped[Collection] = relationship(back_populates="records")
    folder: Mapped[Optional["Folder"]] = relationship(back_populates="records")
    documents: Mapped[list["Document"]] = relationship(back_populates="record")

    __table_args__ = (
        Index("ix_records_collection_status", "collection_id", "status"),
        Index("ix_records_deleted_updated_id", "deleted_at", "updated_at", "id"),
        Index("ix_records_deleted_folder_updated_id", "deleted_at", "folder_id", "updated_at", "id"),
    )


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_name: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status"),
        default=BatchStatus.pending,
        nullable=False,
        index=True,
    )
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("records.id", ondelete="CASCADE"), nullable=True, index=True
    )
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collection_name: Mapped[str] = mapped_column(String(80), index=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duplicate_of_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    correspondent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("correspondents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    storage_path_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("storage_path_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    legacy_source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    legacy_document_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    processing_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_processing_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_after_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    current_stage: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    ocr_mode: Mapped[OCRMode] = mapped_column(
        Enum(OCRMode, name="ocr_mode"),
        default=OCRMode.redo,
        nullable=False,
        index=True,
    )
    ocr_config_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    review_state: Mapped[ReviewState] = mapped_column(
        Enum(ReviewState, name="review_state"),
        default=ReviewState.unreviewed,
        nullable=False,
        index=True,
    )
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    processing_state: Mapped[DocumentState] = mapped_column(
        Enum(DocumentState, name="document_state"),
        default=DocumentState.uploaded,
        nullable=False,
        index=True,
    )
    ocr_state: Mapped[StageState] = mapped_column(
        Enum(StageState, name="stage_state"),
        default=StageState.pending,
        nullable=False,
        index=True,
    )
    metadata_state: Mapped[StageState] = mapped_column(
        Enum(StageState, name="stage_state", create_type=False),
        default=StageState.pending,
        nullable=False,
        index=True,
    )
    final_state: Mapped[DocumentState] = mapped_column(
        Enum(DocumentState, name="document_state", create_type=False),
        default=DocumentState.uploaded,
        nullable=False,
        index=True,
    )

    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    extracted_sender: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extracted_recipient: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extracted_invoice_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    extracted_date: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    extracted_amount: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    extracted_payment_method: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    processing_options_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    metadata_sources_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    field_locks_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    raw_ocr_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    prompt_trace_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    model_trace_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    processing_log_json: Mapped[list] = mapped_column(JSONVariant, default=list, nullable=False)
    qwen_response_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_keywords: Mapped[list] = mapped_column(JSONVariant, default=list, nullable=False)
    llm_entities: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    llm_document_purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_suggested_tags: Mapped[list] = mapped_column(JSONVariant, default=list, nullable=False)
    llm_suggested_folder: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    llm_related_query: Mapped[list] = mapped_column(JSONVariant, default=list, nullable=False)
    llm_confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_raw_response: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manual_title_override: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    metadata_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    batch: Mapped[Batch] = relationship(back_populates="documents")
    record: Mapped[Optional[Record]] = relationship(back_populates="documents")
    folder: Mapped[Optional["Folder"]] = relationship(back_populates="documents")
    correspondent: Mapped[Optional["Correspondent"]] = relationship(back_populates="documents")
    document_type: Mapped[Optional["DocumentType"]] = relationship(back_populates="documents")
    storage_path_rule: Mapped[Optional["StoragePathRule"]] = relationship(back_populates="documents")
    duplicate_of: Mapped[Optional["Document"]] = relationship(remote_side=[id], uselist=False)
    events: Mapped[list["DocumentEvent"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentEvent.created_at"
    )
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )
    custom_field_values: Mapped[list["DocumentCustomFieldValue"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=document_tags, back_populates="documents")

    __table_args__ = (
        Index("ix_documents_collection_state", "collection_name", "processing_state"),
        Index("ix_documents_deleted_updated_id", "deleted_at", "updated_at", "id"),
        Index("ix_documents_deleted_folder_updated_id", "deleted_at", "folder_id", "updated_at", "id"),
    )

    @property
    def display_title(self) -> str:
        return self.manual_title_override or self.extracted_title or self.original_filename


class DocumentEvent(Base):
    __tablename__ = "document_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="automatic", nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_value: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    new_value: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="events")


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_ocr_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    rendered_image_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),
    )


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    field_type: Mapped[CustomFieldType] = mapped_column(
        Enum(CustomFieldType, name="custom_field_type"), nullable=False
    )
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    searchable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enum_options: Mapped[list] = mapped_column(JSONVariant, default=list, nullable=False)
    extraction_binding: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    validation_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    collection: Mapped[Collection] = relationship(back_populates="custom_fields")
    values: Mapped[list["DocumentCustomFieldValue"]] = relationship(
        back_populates="field_definition", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("collection_id", "slug", name="uq_custom_field_definitions_collection_slug"),
    )


class DocumentCustomFieldValue(Base):
    __tablename__ = "document_custom_field_values"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    custom_field_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("custom_field_definitions.id", ondelete="CASCADE"), index=True
    )
    raw_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[FieldValueSource] = mapped_column(
        Enum(FieldValueSource, name="field_value_source"),
        default=FieldValueSource.deterministic,
        nullable=False,
    )
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship(back_populates="custom_field_values")
    field_definition: Mapped[CustomFieldDefinition] = relationship(back_populates="values")

    __table_args__ = (
        UniqueConstraint("document_id", "custom_field_definition_id", name="uq_document_custom_field_values_document_field"),
    )


class Correspondent(Base):
    __tablename__ = "correspondents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    match_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    collection: Mapped[Optional[Collection]] = relationship(back_populates="correspondents")
    documents: Mapped[list[Document]] = relationship(back_populates="correspondent")

    __table_args__ = (UniqueConstraint("collection_id", "slug", name="uq_correspondents_collection_slug"),)


class DocumentType(Base):
    __tablename__ = "document_types"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    match_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    collection: Mapped[Optional[Collection]] = relationship(back_populates="document_types")
    documents: Mapped[list[Document]] = relationship(back_populates="document_type")

    __table_args__ = (UniqueConstraint("collection_id", "slug", name="uq_document_types_collection_slug"),)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    match_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    collection: Mapped[Optional[Collection]] = relationship(back_populates="tags")
    documents: Mapped[list[Document]] = relationship(secondary=document_tags, back_populates="tags")

    __table_args__ = (UniqueConstraint("collection_id", "slug", name="uq_tags_collection_slug"),)


class StoragePathRule(Base):
    __tablename__ = "storage_path_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    path_template: Mapped[str] = mapped_column(String(1024), nullable=False, default="{collection}/{year}")
    match_rules: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    collection: Mapped[Optional[Collection]] = relationship(back_populates="storage_paths")
    documents: Mapped[list[Document]] = relationship(back_populates="storage_path_rule")

    __table_args__ = (UniqueConstraint("collection_id", "slug", name="uq_storage_path_rules_collection_slug"),)


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    parent: Mapped[Optional["Folder"]] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Folder"]] = relationship(back_populates="parent")
    collection: Mapped[Optional[Collection]] = relationship(back_populates="folders")
    records: Mapped[list[Record]] = relationship(back_populates="folder")
    documents: Mapped[list[Document]] = relationship(back_populates="folder")

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_folders_parent_name"),
    )


class IngestionSource(Base):
    __tablename__ = "ingestion_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[IngestionSourceType] = mapped_column(Enum(IngestionSourceType, name="ingestion_source_type"), nullable=False)
    path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    collection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    record_grouping: Mapped[RecordGrouping] = mapped_column(
        Enum(RecordGrouping, name="record_grouping"),
        default=RecordGrouping.one_record_per_file,
        nullable=False,
    )
    polling_interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    ignore_patterns: Mapped[list] = mapped_column(JSONVariant, default=list, nullable=False)
    recursive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ocr_config_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    collection: Mapped[Collection] = relationship(back_populates="ingestion_sources")
    jobs: Mapped[list["IngestionJob"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("ingestion_sources.id", ondelete="CASCADE"), index=True)
    status: Mapped[IngestionJobStatus] = mapped_column(
        Enum(IngestionJobStatus, name="ingestion_job_status"),
        default=IngestionJobStatus.pending,
        nullable=False,
        index=True,
    )
    discovered_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True)
    record_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("records.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[IngestionSource] = relationship(back_populates="jobs")

    __table_args__ = (UniqueConstraint("source_id", "discovered_path", name="uq_ingestion_jobs_source_path"),)


class ProcessingHook(Base):
    __tablename__ = "processing_hooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[HookStage] = mapped_column(Enum(HookStage, name="hook_stage"), nullable=False, index=True)
    hook_kind: Mapped[HookKind] = mapped_column(Enum(HookKind, name="hook_kind"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    env_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    section: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    filters_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    sort_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    display_json: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
