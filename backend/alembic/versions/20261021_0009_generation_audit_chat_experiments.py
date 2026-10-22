"""generation + audit logs, assistant conversations, campaign A/B columns

Revision ID: 20261021_0009
Revises: 20260812_0008
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20261021_0009"
down_revision: str | None = "20260812_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres; the models declare the same variant so a create_all()
# database and a migrated one end up with the same column type.
_JSON = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

_TIMESTAMPS = (
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
    """Whether the table is already there.

    Offline (``--sql``) mode can't inspect anything, so it emits the full
    migration: a generated script has to contain every statement, and a
    database that already has the table would be adopted by the online path
    instead. The same reasoning applies to :func:`_has_column` below —
    answering "already present?" with False offline is what makes the generated
    SQL complete rather than silently missing the ALTERs.
    """
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
    # Databases that already picked these up via create_all() on startup are
    # adopted rather than re-created — same pattern as 20260709_0001.
    if not _has_table("generation_logs"):
        op.create_table(
            "generation_logs",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("system_prompt", sa.Text(), nullable=False),
            sa.Column("user_prompt", sa.Text(), nullable=False),
            sa.Column("raw_output", sa.Text(), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column(
                "generated_by", sa.String(length=16), nullable=False, server_default="claude"
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("campaign_send_id", sa.Uuid(), nullable=True),
            sa.Column("customer_id", sa.Uuid(), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_TIMESTAMPS,
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_generation_logs_business_id"), "generation_logs", ["business_id"]
        )
        op.create_index(op.f("ix_generation_logs_purpose"), "generation_logs", ["purpose"])
        op.create_index(
            op.f("ix_generation_logs_campaign_send_id"),
            "generation_logs",
            ["campaign_send_id"],
        )

    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("actor_user_id", sa.String(length=255), nullable=True),
            sa.Column("actor_email", sa.String(length=320), nullable=True),
            sa.Column("subject_type", sa.String(length=32), nullable=True),
            sa.Column("subject_id", sa.String(length=64), nullable=True),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_TIMESTAMPS,
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_audit_logs_business_id"), "audit_logs", ["business_id"])
        op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
        op.create_index(op.f("ix_audit_logs_subject_id"), "audit_logs", ["subject_id"])

    if not _has_table("chat_conversations"):
        op.create_table(
            "chat_conversations",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column(
                "title",
                sa.String(length=255),
                nullable=False,
                server_default="New conversation",
            ),
            sa.Column("created_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_TIMESTAMPS,
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_chat_conversations_business_id"), "chat_conversations", ["business_id"]
        )

    if not _has_table("chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tool_calls", _JSON, nullable=True),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column(
                "generated_by", sa.String(length=16), nullable=False, server_default="claude"
            ),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_TIMESTAMPS,
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
            ),
        )
        op.create_index(
            op.f("ix_chat_messages_business_id"), "chat_messages", ["business_id"]
        )
        op.create_index(
            op.f("ix_chat_messages_conversation_id"), "chat_messages", ["conversation_id"]
        )

    # ``campaigns``/``campaign_sends`` predate this revision, so these are
    # ALTERs rather than table creates.
    if not _has_column("campaigns", "ab_test"):
        op.add_column(
            "campaigns",
            sa.Column("ab_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_column("campaigns", "variant_b_incentive"):
        op.add_column(
            "campaigns", sa.Column("variant_b_incentive", sa.String(length=255), nullable=True)
        )
    if not _has_column("campaign_sends", "variant"):
        op.add_column(
            "campaign_sends", sa.Column("variant", sa.String(length=1), nullable=True)
        )


def downgrade() -> None:
    for table, column in (
        ("campaign_sends", "variant"),
        ("campaigns", "variant_b_incentive"),
        ("campaigns", "ab_test"),
    ):
        if _offline() or _has_column(table, column):
            op.drop_column(table, column)

    # Child before parent: chat_messages has an FK onto chat_conversations.
    for table in ("chat_messages", "chat_conversations", "audit_logs", "generation_logs"):
        if _offline() or _has_table(table):
            op.drop_table(table)
