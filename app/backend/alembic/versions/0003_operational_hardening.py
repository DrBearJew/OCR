"""operational hardening

Revision ID: 0003_operational_hardening
Revises: 0002_model_prompt_trace
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_operational_hardening"
down_revision = "0002_model_prompt_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE document_state ADD VALUE IF NOT EXISTS 'duplicate'")

    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("documents", sa.Column("duplicate_of_document_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("documents", sa.Column("thumbnail_path", sa.String(length=1024), nullable=True))
    op.add_column("documents", sa.Column("legacy_source", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("legacy_document_id", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("processing_attempt", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("documents", sa.Column("last_processing_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("retry_after_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_duplicate_of_document_id_documents",
        "documents",
        "documents",
        ["duplicate_of_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_duplicate_of_document_id", "documents", ["duplicate_of_document_id"])
    op.create_index("ix_documents_legacy_source", "documents", ["legacy_source"])
    op.create_index("ix_documents_legacy_document_id", "documents", ["legacy_document_id"])

    op.create_table(
        "document_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False, server_default="system"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="automatic"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_events_document_id", "document_events", ["document_id"])
    op.create_index("ix_document_events_event_type", "document_events", ["event_type"])

    op.create_table(
        "document_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("raw_ocr_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rendered_image_path", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_document_pages_document_id", table_name="document_pages")
    op.drop_table("document_pages")
    op.drop_index("ix_document_events_event_type", table_name="document_events")
    op.drop_index("ix_document_events_document_id", table_name="document_events")
    op.drop_table("document_events")
    op.drop_index("ix_documents_legacy_document_id", table_name="documents")
    op.drop_index("ix_documents_legacy_source", table_name="documents")
    op.drop_index("ix_documents_duplicate_of_document_id", table_name="documents")
    op.drop_constraint("fk_documents_duplicate_of_document_id_documents", "documents", type_="foreignkey")
    op.drop_column("documents", "retry_after_at")
    op.drop_column("documents", "last_processing_heartbeat_at")
    op.drop_column("documents", "processing_attempt")
    op.drop_column("documents", "legacy_document_id")
    op.drop_column("documents", "legacy_source")
    op.drop_column("documents", "thumbnail_path")
    op.drop_column("documents", "duplicate_of_document_id")
    op.drop_column("documents", "page_count")
