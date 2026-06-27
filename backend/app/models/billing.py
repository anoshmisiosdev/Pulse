"""Pulse's own subscription billing (Stripe Checkout + Customer Portal)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class Subscription(UUIDMixin, Base):
    __tablename__ = "subscriptions"

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True, unique=True
    )
    tier: Mapped[str] = mapped_column(String(16), default="starter")  # starter|growth|pro
    # trialing | active | past_due | canceled
    status: Mapped[str] = mapped_column(String(16), default="trialing")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
