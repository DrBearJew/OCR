from __future__ import annotations

from alembic import op


revision = "0015_collection_records_page_index"
down_revision = "0014_document_page_keyset_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_records_deleted_collection_updated_id", "records", ["deleted_at", "collection_id", "updated_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_records_deleted_collection_updated_id", table_name="records")
