"""add pricing research audit fields

Revision ID: 20260709_0002
Revises: 20260709_0001
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260709_0002"
down_revision: str | None = "20260709_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing(
        "competitor_price_sources",
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "competitor_price_sources",
        sa.Column(
            "attempt_status", sa.String(length=32), nullable=False, server_default="discovered"
        ),
    )
    _add_column_if_missing(
        "competitor_price_sources", sa.Column("failure_reason", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "competitor_price_observations",
        sa.Column("price_channel", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    _add_column_if_missing(
        "competitor_price_observations",
        sa.Column("match_quality", sa.String(length=16), nullable=False, server_default="weak"),
    )
    _add_column_if_missing(
        "competitor_price_observations",
        sa.Column("corroborated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "competitor_price_observations",
        sa.Column("included_in_summary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if context.is_offline_mode():
        op.add_column(table_name, column)
        return
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def downgrade() -> None:
    op.drop_column("competitor_price_observations", "included_in_summary")
    op.drop_column("competitor_price_observations", "corroborated")
    op.drop_column("competitor_price_observations", "match_quality")
    op.drop_column("competitor_price_observations", "price_channel")
    op.drop_column("competitor_price_sources", "failure_reason")
    op.drop_column("competitor_price_sources", "attempt_status")
    op.drop_column("competitor_price_sources", "attempted_at")
