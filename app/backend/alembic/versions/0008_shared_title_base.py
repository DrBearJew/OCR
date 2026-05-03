from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_shared_title_base"
down_revision = "0007_functional_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("records", sa.Column("shared_title_base", sa.String(length=255), nullable=True))
    op.add_column(
        "records",
        sa.Column(
            "apply_shared_title_to_documents",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("records", "apply_shared_title_to_documents")
    op.drop_column("records", "shared_title_base")
