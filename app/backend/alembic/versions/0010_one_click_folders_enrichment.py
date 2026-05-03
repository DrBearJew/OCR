from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_one_click_folders_enrichment"
down_revision = "0009_bugfix_status_security"
branch_labels = None
depends_on = None


def _json_default(bind, value: str):
    if bind.dialect.name == "postgresql":
        return sa.text(f"'{value}'::jsonb")
    return sa.text(f"'{value}'")


def upgrade() -> None:
    bind = op.get_bind()
    uuid_type = postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.Uuid()
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()

    op.create_table(
        "folders",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("parent_id", uuid_type, sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("collection_id", uuid_type, sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("parent_id", "name", name="uq_folders_parent_name"),
        sa.UniqueConstraint("path", name="uq_folders_path"),
    )
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])
    op.create_index("ix_folders_collection_id", "folders", ["collection_id"])
    op.create_index("ix_folders_path", "folders", ["path"])
    op.create_index("ix_folders_deleted_at", "folders", ["deleted_at"])

    op.add_column("records", sa.Column("folder_id", uuid_type, nullable=True))
    op.add_column("records", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("records", sa.Column("deleted_by", sa.String(length=80), nullable=True))
    op.create_foreign_key("fk_records_folder_id_folders", "records", "folders", ["folder_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_records_folder_id", "records", ["folder_id"])
    op.create_index("ix_records_deleted_at", "records", ["deleted_at"])

    op.add_column("documents", sa.Column("folder_id", uuid_type, nullable=True))
    op.add_column("documents", sa.Column("llm_summary", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("llm_keywords", json_type, nullable=False, server_default=_json_default(bind, "[]")))
    op.add_column("documents", sa.Column("llm_entities", json_type, nullable=False, server_default=_json_default(bind, "{}")))
    op.add_column("documents", sa.Column("llm_document_purpose", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("llm_suggested_tags", json_type, nullable=False, server_default=_json_default(bind, "[]")))
    op.add_column("documents", sa.Column("llm_suggested_folder", sa.String(length=1024), nullable=True))
    op.add_column("documents", sa.Column("llm_related_query", json_type, nullable=False, server_default=_json_default(bind, "[]")))
    op.add_column("documents", sa.Column("llm_confidence", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("llm_raw_response", json_type, nullable=False, server_default=_json_default(bind, "{}")))
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("deleted_by", sa.String(length=80), nullable=True))
    op.create_foreign_key("fk_documents_folder_id_folders", "documents", "folders", ["folder_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_documents_folder_id", "documents", ["folder_id"])
    op.create_index("ix_documents_deleted_at", "documents", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_deleted_at", table_name="documents")
    op.drop_index("ix_documents_folder_id", table_name="documents")
    op.drop_constraint("fk_documents_folder_id_folders", "documents", type_="foreignkey")
    for column in (
        "deleted_by",
        "deleted_at",
        "llm_raw_response",
        "llm_confidence",
        "llm_related_query",
        "llm_suggested_folder",
        "llm_suggested_tags",
        "llm_document_purpose",
        "llm_entities",
        "llm_keywords",
        "llm_summary",
        "folder_id",
    ):
        op.drop_column("documents", column)

    op.drop_index("ix_records_deleted_at", table_name="records")
    op.drop_index("ix_records_folder_id", table_name="records")
    op.drop_constraint("fk_records_folder_id_folders", "records", type_="foreignkey")
    op.drop_column("records", "deleted_by")
    op.drop_column("records", "deleted_at")
    op.drop_column("records", "folder_id")

    op.drop_index("ix_folders_deleted_at", table_name="folders")
    op.drop_index("ix_folders_path", table_name="folders")
    op.drop_index("ix_folders_collection_id", table_name="folders")
    op.drop_index("ix_folders_parent_id", table_name="folders")
    op.drop_table("folders")
