"""team invites, multi-location activity, outbound webhooks, review requests

Revision ID: 20261022_0010
Revises: 20261021_0009
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20261022_0010"
down_revision: str | None = "20261021_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def _offline() -> bool:
    return context.is_offline_mode()


def _has_table(name: str) -> bool:
    """Offline (--sql) answers False so the generated script is complete; see
    20261021_0009 for the full reasoning."""
    if _offline():
        return False
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table: str, column: str) -> bool:
    if _offline():
        return False
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_table("team_invites"):
        op.create_table(
            "team_invites",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="staff"),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("invited_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        )
        op.create_index(op.f("ix_team_invites_business_id"), "team_invites", ["business_id"])
        op.create_index(op.f("ix_team_invites_email"), "team_invites", ["email"])
        op.create_index(
            op.f("ix_team_invites_token_hash"), "team_invites", ["token_hash"], unique=True
        )

    if not _has_table("webhook_endpoints"):
        op.create_table(
            "webhook_endpoints",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("url", sa.String(length=2048), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("secret_enc", sa.Text(), nullable=False),
            sa.Column("events", _JSON, nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_webhook_endpoints_business_id"), "webhook_endpoints", ["business_id"]
        )

    if not _has_table("webhook_deliveries"):
        op.create_table(
            "webhook_deliveries",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("endpoint_id", sa.Uuid(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("event_id", sa.String(length=64), nullable=False),
            sa.Column("payload", _JSON, nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["endpoint_id"], ["webhook_endpoints.id"], ondelete="CASCADE"
            ),
        )
        op.create_index(
            op.f("ix_webhook_deliveries_business_id"), "webhook_deliveries", ["business_id"]
        )
        op.create_index(
            op.f("ix_webhook_deliveries_endpoint_id"), "webhook_deliveries", ["endpoint_id"]
        )
        op.create_index(
            op.f("ix_webhook_deliveries_event_id"), "webhook_deliveries", ["event_id"]
        )
        op.create_index(op.f("ix_webhook_deliveries_status"), "webhook_deliveries", ["status"])
        op.create_index(
            op.f("ix_webhook_deliveries_next_attempt_at"),
            "webhook_deliveries",
            ["next_attempt_at"],
        )

    # Nullable adds: no table rewrite on Postgres, safe on large visit/tx tables.
    for table in ("visits", "transactions"):
        if not _has_column(table, "location"):
            op.add_column(table, sa.Column("location", sa.String(length=120), nullable=True))

    if not _has_column("campaigns", "kind"):
        op.add_column(
            "campaigns",
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="winback"),
        )

    business_columns = (
        sa.Column("review_url", sa.String(length=500), nullable=True),
        sa.Column(
            "review_requests_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "review_request_channel", sa.String(length=8), nullable=False, server_default="email"
        ),
        sa.Column(
            "review_request_delay_days", sa.Integer(), nullable=False, server_default="2"
        ),
    )
    for column in business_columns:
        if not _has_column("businesses", column.name):
            op.add_column("businesses", column)


def downgrade() -> None:
    for name in (
        "review_request_delay_days",
        "review_request_channel",
        "review_requests_enabled",
        "review_url",
    ):
        if _offline() or _has_column("businesses", name):
            op.drop_column("businesses", name)
    if _offline() or _has_column("campaigns", "kind"):
        op.drop_column("campaigns", "kind")
    for table in ("transactions", "visits"):
        if _offline() or _has_column(table, "location"):
            op.drop_column(table, "location")
    # Child before parent: deliveries reference endpoints.
    for table in ("webhook_deliveries", "webhook_endpoints", "team_invites"):
        if _offline() or _has_table(table):
            op.drop_table(table)
