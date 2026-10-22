"""post-recovery review-request automation (n8n-backed)

Revision ID: 20260822_0009
Revises: 20260812_0008
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260822_0009"
down_revision: str | None = "20260812_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_COLUMNS = {"review_request_enabled", "review_link"}


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # Offline (--sql) mode has no connection to inspect; emit every ADD COLUMN.
    existing = set() if context.is_offline_mode() else _columns("businesses")
    if "review_request_enabled" not in existing:
        op.add_column(
            "businesses",
            sa.Column(
                "review_request_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "review_link" not in existing:
        op.add_column("businesses", sa.Column("review_link", sa.String(length=500), nullable=True))


def downgrade() -> None:
    existing = _NEW_COLUMNS if context.is_offline_mode() else _columns("businesses")
    if "review_link" in existing:
        op.drop_column("businesses", "review_link")
    if "review_request_enabled" in existing:
        op.drop_column("businesses", "review_request_enabled")
