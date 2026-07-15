"""Customer + activity models. Customers are deduped by email/phone on ingest."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin

# JSONB on Postgres (indexable, queryable); plain JSON elsewhere (SQLite tests).
JsonCol = JSON().with_variant(JSONB(), "postgresql")


class Customer(UUIDMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_business_email", "business_id", "email"),
        Index("ix_customers_business_phone", "business_id", "phone"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="csv")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional POS metadata surfaced in outreach ("they love X").
    favorite_item: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Compliance flags honored everywhere outreach happens.
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribed_email: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribed_sms: Mapped[bool] = mapped_column(Boolean, default=False)

    # Denormalized latest score for fast dashboard reads (source of truth is RiskScore).
    current_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)


class Transaction(UUIDMixin, Base):
    __tablename__ = "transactions"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Visit(UUIDMixin, Base):
    __tablename__ = "visits"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EngagementEvent(UUIDMixin, Base):
    __tablename__ = "engagement_events"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    # "email_sent" | "email_open" | "email_click" | "email_bounced" | "email_complained"
    # | "sms_sent" | "reply" | "stop"
    kind: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # The send this event is about, when known (opens/clicks/replies all trace
    # back to one). Null for events with no obvious originating send.
    campaign_send_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("campaign_sends.id", ondelete="SET NULL"), nullable=True
    )
    # Free text: the clicked URL, the SMS reply body, etc.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class RiskScore(UUIDMixin, Base):
    """Append-only log of every score we computed (never updated in place)."""

    __tablename__ = "risk_scores"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    band: Mapped[str] = mapped_column(String(8))
    reasons: Mapped[list] = mapped_column(JsonCol, default=list)  # list[str]
    signals: Mapped[dict] = mapped_column(JsonCol, default=dict)
