"""Campaigns, sends, automation rules, and recovery attribution."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class Campaign(UUIDMixin, Base):
    __tablename__ = "campaigns"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(8))  # email | sms
    # draft | pending_approval | approved | sending | sent | failed
    status: Mapped[str] = mapped_column(String(24), default="draft")
    incentive: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CampaignSend(UUIDMixin, Base):
    __tablename__ = "campaign_sends"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(8))
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    # pending | approved | sent | delivered | failed | skipped
    status: Mapped[str] = mapped_column(String(16), default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Provenance for the generation that produced this copy.
    generation_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_by: Mapped[str] = mapped_column(String(16), default="claude")  # claude | fallback
    # The rule that queued this send, if any (manual sends leave this null).
    automation_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True
    )
    # Twilio MessageSid / Resend email id — lets delivery-status webhooks find this row.
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AutomationRule(UUIDMixin, Base):
    __tablename__ = "automation_rules"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # Trigger: minimum band to act on.
    trigger_band: Mapped[str] = mapped_column(String(8), default="high")
    channel: Mapped[str] = mapped_column(String(8), default="email")
    incentive: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # suggest | approve | auto
    mode: Mapped[str] = mapped_column(String(16), default="approve")
    enabled: Mapped[bool] = mapped_column(default=True)
    # Don't re-contact the same customer via this rule more than once per window.
    cooldown_days: Mapped[int] = mapped_column(Integer, default=14)
    # Lazily created on first dispatch — the Campaign every send from this rule attaches to.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )


class RecoveryAttribution(UUIDMixin, Base):
    """Links a recovered customer back to the outreach that won them back."""

    __tablename__ = "recovery_attributions"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    campaign_send_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("campaign_sends.id", ondelete="SET NULL"), nullable=True
    )
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    recovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
