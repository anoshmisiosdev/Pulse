"""Tenant + user models. Multi-location is a column, never a rewrite."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Uuid
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


class User(UUIDMixin, Base):
    __tablename__ = "users"

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    # Maps to a Supabase Auth user id.
    supabase_user_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")
