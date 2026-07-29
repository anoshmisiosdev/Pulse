"""waitlist signups (public landing-page form)

Revision ID: 20260728_0004
Revises: 20260712_0003
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0004"
# Chains onto the merge revision, not 20260712_0003 — branching off an older
# node would give `alembic upgrade head` two heads to choose between, which is
# the failure 20260715_0006 exists to have fixed.
down_revision: str | None = "20260715_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("business_name", sa.String(length=160), nullable=True),
        sa.Column("vertical", sa.String(length=60), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="landing"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique, not just indexed: the API upserts on email so a repeat submit is
    # idempotent, and that read-then-write needs the DB to be the final word.
    op.create_index(
        op.f("ix_waitlist_signups_email"), "waitlist_signups", ["email"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_waitlist_signups_email"), table_name="waitlist_signups")
    op.drop_table("waitlist_signups")
