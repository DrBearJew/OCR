from __future__ import annotations

from alembic import op


revision = "0013_folder_contents_keyset_indexes"
down_revision = "0012_app_settings_model_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_documents_deleted_updated_id", "documents", ["deleted_at", "updated_at", "id"])
    op.create_index("ix_documents_deleted_folder_updated_id", "documents", ["deleted_at", "folder_id", "updated_at", "id"])
    op.create_index("ix_records_deleted_updated_id", "records", ["deleted_at", "updated_at", "id"])
    op.create_index("ix_records_deleted_folder_updated_id", "records", ["deleted_at", "folder_id", "updated_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_records_deleted_folder_updated_id", table_name="records")
    op.drop_index("ix_records_deleted_updated_id", table_name="records")
    op.drop_index("ix_documents_deleted_folder_updated_id", table_name="documents")
    op.drop_index("ix_documents_deleted_updated_id", table_name="documents")
