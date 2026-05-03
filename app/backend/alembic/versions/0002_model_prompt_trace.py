"""add model and prompt tracing

Revision ID: 0002_model_prompt_trace
Revises: 0001_init
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_model_prompt_trace"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("prompt_trace_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "documents",
        sa.Column("model_trace_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "documents",
        sa.Column("processing_log_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("documents", sa.Column("qwen_response_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "qwen_response_text")
    op.drop_column("documents", "processing_log_json")
    op.drop_column("documents", "model_trace_json")
    op.drop_column("documents", "prompt_trace_json")

