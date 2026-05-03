from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_app_shell_review_saved_views"
down_revision = "0005_paperless_ingestion_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    review_state = sa.Enum("unreviewed", "needs_review", "reviewed", name="review_state")
    if is_postgres:
        review_state.create(bind, checkfirst=True)

    op.add_column("documents", sa.Column("review_state", review_state, nullable=False, server_default="unreviewed"))
    op.add_column("documents", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("reviewed_by", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_documents_review_state", "documents", ["review_state"])

    json_type = postgresql.JSONB() if is_postgres else sa.JSON()
    op.create_table(
        "saved_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("section", sa.String(length=80), nullable=False),
        sa.Column("filters_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")),
        sa.Column("sort_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")),
        sa.Column("display_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_saved_views_slug"),
    )
    op.create_index("ix_saved_views_slug", "saved_views", ["slug"])
    op.create_index("ix_saved_views_section", "saved_views", ["section"])


def downgrade() -> None:
    op.drop_index("ix_saved_views_section", table_name="saved_views")
    op.drop_index("ix_saved_views_slug", table_name="saved_views")
    op.drop_table("saved_views")
    op.drop_index("ix_documents_review_state", table_name="documents")
    op.drop_column("documents", "reviewed_at")
    op.drop_column("documents", "reviewed_by")
    op.drop_column("documents", "review_reason")
    op.drop_column("documents", "review_state")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="review_state").drop(bind, checkfirst=True)
