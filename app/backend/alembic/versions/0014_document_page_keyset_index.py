from __future__ import annotations

from alembic import op


revision = "0014_document_page_keyset_index"
down_revision = "0013_folder_contents_keyset_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_documents_deleted_created_id", "documents", ["deleted_at", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_documents_deleted_created_id", table_name="documents")
