"""Persist deterministic pricing item-match explanations.

Revision ID: 20260804_0007
Revises: 20260804_0006
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260804_0007"
down_revision: str | None = "20260804_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competitor_price_observations",
        sa.Column("match_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "competitor_price_observations",
        sa.Column("match_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("competitor_price_observations", "match_reason")
    op.drop_column("competitor_price_observations", "match_score")
