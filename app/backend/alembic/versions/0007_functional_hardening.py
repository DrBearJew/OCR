from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_functional_hardening"
down_revision = "0006_app_shell_review_saved_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_postgres else sa.JSON()

    if is_postgres:
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE document_state ADD VALUE IF NOT EXISTS 'metadata_done'")
            op.execute("ALTER TYPE document_state ADD VALUE IF NOT EXISTS 'needs_review'")
            op.execute("ALTER TYPE stage_state ADD VALUE IF NOT EXISTS 'skipped'")
            op.execute("ALTER TYPE field_value_source ADD VALUE IF NOT EXISTS 'deterministic'")
            op.execute("ALTER TYPE field_value_source ADD VALUE IF NOT EXISTS 'qwen'")
        op.execute("UPDATE document_custom_field_values SET source='deterministic' WHERE source='auto'")
    else:
        op.execute("UPDATE document_custom_field_values SET source='deterministic' WHERE source='auto'")

    op.add_column("documents", sa.Column("processing_options_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")))
    op.add_column("documents", sa.Column("metadata_sources_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")))
    op.add_column("documents", sa.Column("field_locks_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")))


def downgrade() -> None:
    op.drop_column("documents", "field_locks_json")
    op.drop_column("documents", "metadata_sources_json")
    op.drop_column("documents", "processing_options_json")
    # PostgreSQL enum values are intentionally left in place.
