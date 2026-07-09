"""add pricing research audit fields

Revision ID: 20260709_0002
Revises: 20260709_0001
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260709_0002"
down_revision: str | None = "20260709_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competitor_price_sources",
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "competitor_price_sources",
        sa.Column(
            "attempt_status", sa.String(length=32), nullable=False, server_default="discovered"
        ),
    )
    op.add_column("competitor_price_sources", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column(
        "competitor_price_observations",
        sa.Column("price_channel", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "competitor_price_observations",
        sa.Column("match_quality", sa.String(length=16), nullable=False, server_default="weak"),
    )
    op.add_column(
        "competitor_price_observations",
        sa.Column("corroborated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "competitor_price_observations",
        sa.Column("included_in_summary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("competitor_price_observations", "included_in_summary")
    op.drop_column("competitor_price_observations", "corroborated")
    op.drop_column("competitor_price_observations", "match_quality")
    op.drop_column("competitor_price_observations", "price_channel")
    op.drop_column("competitor_price_sources", "failure_reason")
    op.drop_column("competitor_price_sources", "attempt_status")
    op.drop_column("competitor_price_sources", "attempted_at")
