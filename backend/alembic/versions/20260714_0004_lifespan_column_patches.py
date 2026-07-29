"""Columns/indexes previously hand-patched in app lifespan.

Moves the idempotent ALTER TABLE block out of `app/main.py` startup into a real
migration. Uses IF NOT EXISTS throughout because production databases already
received these via the old startup patches.

Revision ID: 20260714_0004
Revises: 20260712_0003
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0004"
down_revision: str | None = "20260712_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS favorite_item VARCHAR(255)",
    "ALTER TABLE campaign_sends ADD COLUMN IF NOT EXISTS automation_rule_id UUID",
    "ALTER TABLE campaign_sends ADD COLUMN IF NOT EXISTS provider_message_id VARCHAR(255)",
    "ALTER TABLE campaign_sends ADD COLUMN IF NOT EXISTS failure_reason TEXT",
    "CREATE INDEX IF NOT EXISTS ix_campaign_sends_provider_message_id "
    "ON campaign_sends (provider_message_id)",
    "ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS cooldown_days INTEGER "
    "DEFAULT 14 NOT NULL",
    "ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS campaign_id UUID",
    "ALTER TABLE engagement_events ADD COLUMN IF NOT EXISTS campaign_send_id UUID",
    "ALTER TABLE engagement_events ADD COLUMN IF NOT EXISTS detail TEXT",
    "CREATE INDEX IF NOT EXISTS ix_engagement_events_campaign_send_id "
    "ON engagement_events (campaign_send_id)",
]


def upgrade() -> None:
    for ddl in STATEMENTS:
        op.execute(ddl)


def downgrade() -> None:
    # Columns predate this migration on live databases; dropping them would
    # destroy data, so downgrade is a no-op.
    pass
