"""add scheduled pricing watches

Revision ID: 20260712_0004
Revises: 20260710_0003
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260712_0004"
down_revision: str | None = "20260710_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not context.is_offline_mode():
        tables = set(sa.inspect(op.get_bind()).get_table_names())
        if "competitor_price_watches" in tables:
            return
    op.create_table(
        "competitor_price_watches",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
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
        "ix_comp_price_watches_business",
        "competitor_price_watches",
        ["business_id"],
        unique=True,
    )
    op.create_index(
        "ix_comp_price_watches_due",
        "competitor_price_watches",
        ["enabled", "next_run_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_comp_price_watches_due", table_name="competitor_price_watches")
    op.drop_index("ix_comp_price_watches_business", table_name="competitor_price_watches")
    op.drop_table("competitor_price_watches")
