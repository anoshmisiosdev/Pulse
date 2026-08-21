"""platform visitor intelligence and provider identity stitching

Revision ID: 20260730_0005
Revises: 20260728_0004
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260730_0005"
down_revision: str | None = "20260728_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = {"visitor_profiles", "visitor_identifiers", "visitor_events"}


def upgrade() -> None:
    # Adopt databases that already got these three tables via create_all()
    # (see 20260709_0001's comment for the same pattern).
    if not context.is_offline_mode():
        if _TABLES.issubset(set(sa.inspect(op.get_bind()).get_table_names())):
            return

    op.create_table(
        "visitor_profiles",
        sa.Column("primary_email", sa.String(length=320), nullable=True),
        sa.Column("full_name", sa.String(length=180), nullable=True),
        sa.Column("job_title", sa.String(length=180), nullable=True),
        sa.Column("linkedin_url", sa.String(length=1000), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("company_domain", sa.String(length=253), nullable=True),
        sa.Column("company_website", sa.String(length=1000), nullable=True),
        sa.Column("industry", sa.String(length=180), nullable=True),
        sa.Column("employee_count", sa.String(length=40), nullable=True),
        sa.Column("estimated_revenue", sa.String(length=80), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("zipcode", sa.String(length=24), nullable=True),
        sa.Column(
            "identity_level",
            sa.String(length=20),
            server_default="anonymous",
            nullable=False,
        ),
        sa.Column(
            "source_provider",
            sa.String(length=40),
            server_default="first_party",
            nullable=False,
        ),
        sa.Column("provider_profile_key", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="new", nullable=False),
        sa.Column("intent_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("visit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pageview_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_path", sa.String(length=500), nullable=True),
        sa.Column("referrer_host", sa.String(length=253), nullable=True),
        sa.Column("utm_source", sa.String(length=100), nullable=True),
        sa.Column("utm_medium", sa.String(length=100), nullable=True),
        sa.Column("utm_campaign", sa.String(length=100), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("waitlist_signup_id", sa.Uuid(), nullable=True),
        sa.Column("authenticated_user_id", sa.String(length=255), nullable=True),
        sa.Column("suppressed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["waitlist_signup_id"],
            ["waitlist_signups.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_provider",
            "provider_profile_key",
            name="uq_visitor_profile_provider_key",
        ),
    )
    for name, column in (
        ("ix_visitor_profiles_identity_level", "identity_level"),
        ("ix_visitor_profiles_source_provider", "source_provider"),
        ("ix_visitor_profiles_status", "status"),
        ("ix_visitor_profiles_first_seen_at", "first_seen_at"),
        ("ix_visitor_profiles_last_seen_at", "last_seen_at"),
        ("ix_visitor_profiles_waitlist_signup_id", "waitlist_signup_id"),
        ("ix_visitor_profiles_authenticated_user_id", "authenticated_user_id"),
        ("ix_visitor_profiles_suppressed", "suppressed"),
    ):
        op.create_index(name, "visitor_profiles", [column], unique=False)
    op.create_index(
        "ix_visitor_profiles_recent_intent",
        "visitor_profiles",
        ["last_seen_at", "intent_score"],
        unique=False,
    )

    op.create_table(
        "visitor_identifiers",
        sa.Column("visitor_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["visitor_id"], ["visitor_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "kind", "value_hash", name="uq_visitor_identifier_kind_hash"
        ),
    )
    op.create_index(
        "ix_visitor_identifiers_visitor_id",
        "visitor_identifiers",
        ["visitor_id"],
        unique=False,
    )

    op.create_table(
        "visitor_events",
        sa.Column("visitor_id", sa.Uuid(), nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=True),
        sa.Column("referrer", sa.String(length=1000), nullable=True),
        sa.Column("session_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "provider",
            sa.String(length=40),
            server_default="first_party",
            nullable=False,
        ),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["visitor_id"], ["visitor_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    for name, columns in (
        ("ix_visitor_events_visitor_id", ["visitor_id"]),
        ("ix_visitor_events_event_name", ["event_name"]),
        ("ix_visitor_events_occurred_at", ["occurred_at"]),
        (
            "ix_visitor_events_profile_occurred",
            ["visitor_id", "occurred_at"],
        ),
    ):
        op.create_index(name, "visitor_events", columns, unique=False)


def downgrade() -> None:
    op.drop_index("ix_visitor_events_profile_occurred", table_name="visitor_events")
    op.drop_index("ix_visitor_events_occurred_at", table_name="visitor_events")
    op.drop_index("ix_visitor_events_event_name", table_name="visitor_events")
    op.drop_index("ix_visitor_events_visitor_id", table_name="visitor_events")
    op.drop_table("visitor_events")
    op.drop_index(
        "ix_visitor_identifiers_visitor_id", table_name="visitor_identifiers"
    )
    op.drop_table("visitor_identifiers")
    op.drop_index(
        "ix_visitor_profiles_recent_intent", table_name="visitor_profiles"
    )
    for name in (
        "ix_visitor_profiles_suppressed",
        "ix_visitor_profiles_authenticated_user_id",
        "ix_visitor_profiles_waitlist_signup_id",
        "ix_visitor_profiles_last_seen_at",
        "ix_visitor_profiles_first_seen_at",
        "ix_visitor_profiles_status",
        "ix_visitor_profiles_source_provider",
        "ix_visitor_profiles_identity_level",
    ):
        op.drop_index(name, table_name="visitor_profiles")
    op.drop_table("visitor_profiles")
