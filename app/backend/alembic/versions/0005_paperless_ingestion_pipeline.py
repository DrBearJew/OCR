"""paperless ingestion and ocr pipeline

Revision ID: 0005_paperless_ingestion_pipeline
Revises: 0004_collections_records_custom_fields
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_paperless_ingestion_pipeline"
down_revision = "0004_collections_records_custom_fields"
branch_labels = None
depends_on = None


ingestion_source_type = postgresql.ENUM("upload", "consume_folder", name="ingestion_source_type")
record_grouping = postgresql.ENUM("one_record_per_batch", "one_record_per_file", name="record_grouping")
ingestion_job_status = postgresql.ENUM("pending", "processing", "imported", "skipped", "failed", name="ingestion_job_status")
ocr_mode = postgresql.ENUM("skip", "redo", "force", name="ocr_mode")
hook_stage = postgresql.ENUM("pre_consume", "post_consume", name="hook_stage")
hook_kind = postgresql.ENUM("command", "webhook", name="hook_kind")


def upgrade() -> None:
    bind = op.get_bind()
    ingestion_source_type.create(bind, checkfirst=True)
    record_grouping.create(bind, checkfirst=True)
    ingestion_job_status.create(bind, checkfirst=True)
    ocr_mode.create(bind, checkfirst=True)
    hook_stage.create(bind, checkfirst=True)
    hook_kind.create(bind, checkfirst=True)

    op.add_column(
        "collections",
        sa.Column("ocr_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "correspondents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("match_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "slug", name="uq_correspondents_collection_slug"),
    )
    op.create_index("ix_correspondents_collection_id", "correspondents", ["collection_id"])
    op.create_index("ix_correspondents_slug", "correspondents", ["slug"])

    op.create_table(
        "document_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("match_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "slug", name="uq_document_types_collection_slug"),
    )
    op.create_index("ix_document_types_collection_id", "document_types", ["collection_id"])
    op.create_index("ix_document_types_slug", "document_types", ["slug"])

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("match_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "slug", name="uq_tags_collection_slug"),
    )
    op.create_index("ix_tags_collection_id", "tags", ["collection_id"])
    op.create_index("ix_tags_slug", "tags", ["slug"])

    op.create_table(
        "storage_path_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("path_template", sa.String(length=1024), nullable=False, server_default="{collection}/{year}"),
        sa.Column("match_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "slug", name="uq_storage_path_rules_collection_slug"),
    )
    op.create_index("ix_storage_path_rules_collection_id", "storage_path_rules", ["collection_id"])
    op.create_index("ix_storage_path_rules_slug", "storage_path_rules", ["slug"])

    op.add_column("documents", sa.Column("correspondent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("documents", sa.Column("document_type_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("documents", sa.Column("storage_path_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("documents", sa.Column("ocr_mode", ocr_mode, nullable=False, server_default="redo"))
    op.add_column("documents", sa.Column("ocr_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_foreign_key("fk_documents_correspondent_id_correspondents", "documents", "correspondents", ["correspondent_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_documents_document_type_id_document_types", "documents", "document_types", ["document_type_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_documents_storage_path_id_storage_path_rules", "documents", "storage_path_rules", ["storage_path_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_documents_correspondent_id", "documents", ["correspondent_id"])
    op.create_index("ix_documents_document_type_id", "documents", ["document_type_id"])
    op.create_index("ix_documents_storage_path_id", "documents", ["storage_path_id"])
    op.create_index("ix_documents_ocr_mode", "documents", ["ocr_mode"])

    op.create_table(
        "document_tags",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "ingestion_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", ingestion_source_type, nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_grouping", record_grouping, nullable=False, server_default="one_record_per_file"),
        sa.Column("polling_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("ignore_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recursive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ocr_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ingestion_sources_enabled", "ingestion_sources", ["enabled"])
    op.create_index("ix_ingestion_sources_collection_id", "ingestion_sources", ["collection_id"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingestion_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", ingestion_job_status, nullable=False, server_default="pending"),
        sa.Column("discovered_path", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source_id", "discovered_path", name="uq_ingestion_jobs_source_path"),
    )
    op.create_index("ix_ingestion_jobs_source_id", "ingestion_jobs", ["source_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_sha256", "ingestion_jobs", ["sha256"])
    op.create_index("ix_ingestion_jobs_batch_id", "ingestion_jobs", ["batch_id"])
    op.create_index("ix_ingestion_jobs_record_id", "ingestion_jobs", ["record_id"])
    op.create_index("ix_ingestion_jobs_document_id", "ingestion_jobs", ["document_id"])

    op.create_table(
        "processing_hooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("stage", hook_stage, nullable=False),
        sa.Column("hook_kind", hook_kind, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("webhook_url", sa.String(length=1024), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("env_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_processing_hooks_stage", "processing_hooks", ["stage"])
    op.create_index("ix_processing_hooks_enabled", "processing_hooks", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_processing_hooks_enabled", table_name="processing_hooks")
    op.drop_index("ix_processing_hooks_stage", table_name="processing_hooks")
    op.drop_table("processing_hooks")
    op.drop_index("ix_ingestion_jobs_document_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_record_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_batch_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_sha256", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_source_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_ingestion_sources_collection_id", table_name="ingestion_sources")
    op.drop_index("ix_ingestion_sources_enabled", table_name="ingestion_sources")
    op.drop_table("ingestion_sources")
    op.drop_table("document_tags")
    op.drop_index("ix_documents_ocr_mode", table_name="documents")
    op.drop_index("ix_documents_storage_path_id", table_name="documents")
    op.drop_index("ix_documents_document_type_id", table_name="documents")
    op.drop_index("ix_documents_correspondent_id", table_name="documents")
    op.drop_constraint("fk_documents_storage_path_id_storage_path_rules", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_document_type_id_document_types", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_correspondent_id_correspondents", "documents", type_="foreignkey")
    op.drop_column("documents", "ocr_config_json")
    op.drop_column("documents", "ocr_mode")
    op.drop_column("documents", "storage_path_id")
    op.drop_column("documents", "document_type_id")
    op.drop_column("documents", "correspondent_id")
    op.drop_index("ix_storage_path_rules_slug", table_name="storage_path_rules")
    op.drop_index("ix_storage_path_rules_collection_id", table_name="storage_path_rules")
    op.drop_table("storage_path_rules")
    op.drop_index("ix_tags_slug", table_name="tags")
    op.drop_index("ix_tags_collection_id", table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_document_types_slug", table_name="document_types")
    op.drop_index("ix_document_types_collection_id", table_name="document_types")
    op.drop_table("document_types")
    op.drop_index("ix_correspondents_slug", table_name="correspondents")
    op.drop_index("ix_correspondents_collection_id", table_name="correspondents")
    op.drop_table("correspondents")
    op.drop_column("collections", "ocr_config_json")
    bind = op.get_bind()
    hook_kind.drop(bind, checkfirst=True)
    hook_stage.drop(bind, checkfirst=True)
    ocr_mode.drop(bind, checkfirst=True)
    ingestion_job_status.drop(bind, checkfirst=True)
    record_grouping.drop(bind, checkfirst=True)
    ingestion_source_type.drop(bind, checkfirst=True)
