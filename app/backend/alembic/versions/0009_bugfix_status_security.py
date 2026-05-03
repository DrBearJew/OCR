from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_bugfix_status_security"
down_revision = "0008_shared_title_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE batch_status ADD VALUE IF NOT EXISTS 'failed'")
    op.alter_column("documents", "page_count", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("documents", "page_count", existing_type=sa.Integer(), nullable=False, server_default="0")
    # PostgreSQL enum values are intentionally left in place.
