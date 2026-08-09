"""Add searchable pricing pipeline v2 operational fields.

Revision ID: 20260804_0006
Revises: 20260730_0005
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260804_0006"
down_revision: str | None = "20260730_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competitor_price_research_runs",
        sa.Column("status", sa.String(length=24), server_default="legacy", nullable=False),
    )
    op.add_column(
        "competitor_price_research_runs",
        sa.Column("pipeline_version", sa.String(length=16), server_default="v1", nullable=False),
    )
    op.add_column(
        "competitor_price_research_runs",
        sa.Column(
            "provider_cost_usd",
            sa.Numeric(precision=10, scale=4),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "competitor_price_research_runs",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "competitor_price_research_runs",
        sa.Column("failure_code", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_competitor_price_research_runs_status",
        "competitor_price_research_runs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_competitor_price_research_runs_status",
        table_name="competitor_price_research_runs",
    )
    op.drop_column("competitor_price_research_runs", "failure_code")
    op.drop_column("competitor_price_research_runs", "duration_ms")
    op.drop_column("competitor_price_research_runs", "provider_cost_usd")
    op.drop_column("competitor_price_research_runs", "pipeline_version")
    op.drop_column("competitor_price_research_runs", "status")
