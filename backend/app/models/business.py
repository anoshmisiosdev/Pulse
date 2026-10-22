"""Tenant + user models. Multi-location is a column, never a rewrite."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class Business(UUIDMixin, Base):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255))
    # Drives scoring config: fitness | salon | med_spa | other
    vertical: Mapped[str] = mapped_column(String(32), default="other")
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    # Multi-location readiness without a multi-location product yet.
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Review requests: after a customer is recovered, ask them for a review.
    # Off by default -- it messages real people, so it's an explicit opt-in.
    review_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_requests_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    review_request_channel: Mapped[str] = mapped_column(String(8), default="email")
    # Days after the recovering visit before asking. Asking at the till feels
    # transactional; a couple of days later reads as genuine.
    review_request_delay_days: Mapped[int] = mapped_column(Integer, default=2)


class User(UUIDMixin, Base):
    __tablename__ = "users"

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    # Maps to a Supabase Auth user id.
    supabase_user_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")
