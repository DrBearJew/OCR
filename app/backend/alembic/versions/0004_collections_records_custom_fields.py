"""collections records and custom fields

Revision ID: 0004_collections_records_custom_fields
Revises: 0003_operational_hardening
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_collections_records_custom_fields"
down_revision = "0003_operational_hardening"
branch_labels = None
depends_on = None


custom_field_type = postgresql.ENUM("string", "text", "number", "date", "boolean", "select", name="custom_field_type")
field_value_source = postgresql.ENUM("auto", "manual", "imported", name="field_value_source")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE batch_status ADD VALUE IF NOT EXISTS 'needs_review'")

    op.create_table(
        "collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("icon", sa.String(length=80), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("title_generation_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("extraction_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("display_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("search_defaults", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_collections_name"),
        sa.UniqueConstraint("slug", name="uq_collections_slug"),
    )
    op.create_index("ix_collections_slug", "collections", ["slug"])

    op.create_table(
        "records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False, server_default="Untitled"),
        sa.Column("status", postgresql.ENUM(name="batch_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("custom_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("manual_override_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_records_collection_id", "records", ["collection_id"])
    op.create_index("ix_records_collection_status", "records", ["collection_id", "status"])
    op.create_index("ix_records_status", "records", ["status"])

    op.add_column("documents", sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_documents_record_id_records", "documents", "records", ["record_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_documents_record_id", "documents", ["record_id"])

    op.create_table(
        "custom_field_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("field_type", custom_field_type, nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("searchable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("enum_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extraction_binding", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "slug", name="uq_custom_field_definitions_collection_slug"),
    )
    op.create_index("ix_custom_field_definitions_collection_id", "custom_field_definitions", ["collection_id"])

    op.create_table(
        "document_custom_field_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("custom_field_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("custom_field_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("source", field_value_source, nullable=False, server_default="auto"),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "custom_field_definition_id", name="uq_document_custom_field_values_document_field"),
    )
    op.create_index("ix_document_custom_field_values_document_id", "document_custom_field_values", ["document_id"])
    op.create_index("ix_document_custom_field_values_custom_field_definition_id", "document_custom_field_values", ["custom_field_definition_id"])


def downgrade() -> None:
    op.drop_index("ix_document_custom_field_values_custom_field_definition_id", table_name="document_custom_field_values")
    op.drop_index("ix_document_custom_field_values_document_id", table_name="document_custom_field_values")
    op.drop_table("document_custom_field_values")
    op.drop_index("ix_custom_field_definitions_collection_id", table_name="custom_field_definitions")
    op.drop_table("custom_field_definitions")
    op.drop_index("ix_documents_record_id", table_name="documents")
    op.drop_constraint("fk_documents_record_id_records", "documents", type_="foreignkey")
    op.drop_column("documents", "record_id")
    op.drop_index("ix_records_status", table_name="records")
    op.drop_index("ix_records_collection_status", table_name="records")
    op.drop_index("ix_records_collection_id", table_name="records")
    op.drop_table("records")
    op.drop_index("ix_collections_slug", table_name="collections")
    op.drop_table("collections")
    bind = op.get_bind()
    field_value_source.drop(bind, checkfirst=True)
    custom_field_type.drop(bind, checkfirst=True)
