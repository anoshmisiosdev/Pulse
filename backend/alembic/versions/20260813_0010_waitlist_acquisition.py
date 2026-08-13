"""waitlist attribution, assignment, and bounded nurture state

Revision ID: 20260813_0010
Revises: 20260812_0008
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0010"
# This PR is stacked on the committed payment-retention migration. The separate
# retention-intelligence work in the local checkout is intentionally not part
# of this acquisition PR.
down_revision: str | None = "20260812_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "waitlist_signups",
        "name",
        existing_type=sa.String(length=120),
        nullable=True,
    )
    op.add_column(
        "waitlist_signups",
        sa.Column(
            "first_touch",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column(
            "last_touch",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column("assigned_founder", sa.String(length=80), nullable=True),
    )
    for column_name in (
        "email_opted_out_at",
        "confirmation_sent_at",
        "useful_followup_sent_at",
        "pilot_invitation_sent_at",
    ):
        op.add_column(
            "waitlist_signups",
            sa.Column(column_name, sa.DateTime(timezone=True), nullable=True),
        )
    for column_name in (
        "confirmation_provider_message_id",
        "useful_followup_provider_message_id",
        "pilot_invitation_provider_message_id",
    ):
        op.add_column(
            "waitlist_signups",
            sa.Column(column_name, sa.String(length=255), nullable=True),
        )
        op.create_index(
            op.f(f"ix_waitlist_signups_{column_name}"),
            "waitlist_signups",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    for column_name in (
        "pilot_invitation_provider_message_id",
        "useful_followup_provider_message_id",
        "confirmation_provider_message_id",
    ):
        op.drop_index(
            op.f(f"ix_waitlist_signups_{column_name}"),
            table_name="waitlist_signups",
        )
        op.drop_column("waitlist_signups", column_name)
    for column_name in (
        "pilot_invitation_sent_at",
        "useful_followup_sent_at",
        "confirmation_sent_at",
        "email_opted_out_at",
    ):
        op.drop_column("waitlist_signups", column_name)
    op.drop_column("waitlist_signups", "assigned_founder")
    op.drop_column("waitlist_signups", "last_touch")
    op.drop_column("waitlist_signups", "first_touch")
    # Keep the harmless nullable relaxation on downgrade. Re-introducing the
    # old NOT NULL constraint would require deleting email-only leads or storing
    # invented names; preserving real data is the safer compatibility choice.
