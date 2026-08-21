"""business knowledge (RAG for campaign generation)

Revision ID: 20260712_0003
Revises: 20260709_0002
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import context, op

revision: str = "20260712_0003"
down_revision: str | None = "20260709_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match app.core.config.Settings.embedding_dimensions (Cohere Embed v4 on
# Bedrock). Changing embedding models later needs a new migration + backfill.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    # Adopt databases that already got this table via create_all() (see
    # 20260709_0001's comment for the same pattern) — just ensure the
    # extension it needs is there and let later revisions add anything else.
    if not context.is_offline_mode():
        if "business_knowledge" in set(sa.inspect(op.get_bind()).get_table_names()):
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
            return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "business_knowledge",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="note"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_business_knowledge_business_id"), "business_knowledge", ["business_id"]
    )
    # No vector index (ivfflat/hnsw): expected volume is a few dozen snippets per
    # business, so a business_id-filtered sequential scan is fast and avoids
    # tuning index params for a near-empty table. Revisit if per-tenant snippet
    # counts grow into the thousands.


def downgrade() -> None:
    op.drop_index(op.f("ix_business_knowledge_business_id"), table_name="business_knowledge")
    op.drop_table("business_knowledge")
