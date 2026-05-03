"""initial schema

Revision ID: 0001_init
Revises:
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


batch_status = postgresql.ENUM("pending", "processing", "partially_failed", "complete", name="batch_status")
document_state = postgresql.ENUM(
    "uploaded",
    "queued_for_ocr",
    "ocr_processing",
    "ocr_done",
    "metadata_processing",
    "complete",
    "failed",
    name="document_state",
)
stage_state = postgresql.ENUM("pending", "processing", "done", "failed", name="stage_state")


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_name", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("status", batch_status, nullable=False, server_default="pending"),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_batches_collection_name", "batches", ["collection_name"])
    op.create_index("ix_batches_status", "batches", ["status"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_name", sa.String(length=80), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("processing_state", document_state, nullable=False, server_default="uploaded"),
        sa.Column("ocr_state", stage_state, nullable=False, server_default="pending"),
        sa.Column("metadata_state", stage_state, nullable=False, server_default="pending"),
        sa.Column("final_state", document_state, nullable=False, server_default="uploaded"),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column(
            "ocr_search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(ocr_text, ''))", persisted=True),
        ),
        sa.Column("extracted_title", sa.String(length=512), nullable=True),
        sa.Column("extracted_sender", sa.String(length=255), nullable=True),
        sa.Column("extracted_recipient", sa.String(length=255), nullable=True),
        sa.Column("extracted_invoice_number", sa.String(length=80), nullable=True),
        sa.Column("extracted_date", sa.String(length=40), nullable=True),
        sa.Column("extracted_amount", sa.String(length=40), nullable=True),
        sa.Column("extracted_payment_method", sa.String(length=40), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_ocr_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("manual_title_override", sa.String(length=512), nullable=True),
        sa.Column("metadata_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_batch_id", "documents", ["batch_id"])
    op.create_index("ix_documents_collection_name", "documents", ["collection_name"])
    op.create_index("ix_documents_collection_state", "documents", ["collection_name", "processing_state"])
    op.create_index("ix_documents_final_state", "documents", ["final_state"])
    op.create_index("ix_documents_metadata_state", "documents", ["metadata_state"])
    op.create_index("ix_documents_ocr_state", "documents", ["ocr_state"])
    op.create_index("ix_documents_processing_state", "documents", ["processing_state"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_ocr_search", "documents", ["ocr_search"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_documents_ocr_search", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_batches_status", table_name="batches")
    op.drop_index("ix_batches_collection_name", table_name="batches")
    op.drop_table("batches")
    bind = op.get_bind()
    stage_state.drop(bind, checkfirst=True)
    document_state.drop(bind, checkfirst=True)
    batch_status.drop(bind, checkfirst=True)
