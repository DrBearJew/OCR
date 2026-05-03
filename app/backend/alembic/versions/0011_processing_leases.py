from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_processing_leases"
down_revision = "0010_one_click_folders_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("processing_task_id", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("current_stage", sa.String(length=80), nullable=True))
    op.create_index("ix_documents_processing_task_id", "documents", ["processing_task_id"])
    op.create_index("ix_documents_processing_lease_until", "documents", ["processing_lease_until"])
    op.create_index("ix_documents_current_stage", "documents", ["current_stage"])


def downgrade() -> None:
    op.drop_index("ix_documents_current_stage", table_name="documents")
    op.drop_index("ix_documents_processing_lease_until", table_name="documents")
    op.drop_index("ix_documents_processing_task_id", table_name="documents")
    op.drop_column("documents", "current_stage")
    op.drop_column("documents", "processing_lease_until")
    op.drop_column("documents", "processing_started_at")
    op.drop_column("documents", "processing_task_id")
