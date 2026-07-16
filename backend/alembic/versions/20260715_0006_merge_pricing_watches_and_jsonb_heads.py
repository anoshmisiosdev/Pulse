"""Merge pricing-watches and jsonb migration heads.

The Churnary main merge brought in the pricing evidence/watches branch
(20260710_0003 -> 20260712_0004) alongside the existing chain ending at
20260714_0005. The branches touch disjoint columns, so no ordering is needed.

Revision ID: 20260715_0006
Revises: 20260712_0004, 20260714_0005
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "20260715_0006"
down_revision: str | Sequence[str] | None = ("20260712_0004", "20260714_0005")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
