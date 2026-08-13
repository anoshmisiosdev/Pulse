"""Landing-page waitlist signups.

Deliberately **not** tenant-scoped: a signup arrives from the public marketing
page before any ``Business`` exists, so there is no ``business_id`` to hang it
on. That also means this is the one table an unauthenticated request can write
to, which is why the endpoint keeps the row small and the columns bounded.

Only what we need to email someone back. Acquisition data is deliberately a
small, allow-listed first/last-touch object; no IP address, full referrer URL,
or browser fingerprint is stored.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class WaitlistSignup(UUIDMixin, Base):
    __tablename__ = "waitlist_signups"

    # Unique so a double-submit (or an eager refresh) updates rather than
    # duplicates — the API upserts on this column instead of erroring, because
    # "you already signed up" is not a failure the visitor should have to read.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Email is sufficient for the first conversion. Name/business/vertical can
    # be added by the optional enrichment step without blocking the signup.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Free text, not an enum: the picker offers the verticals we know about, and
    # anything else an owner types is exactly the signal we want to keep.
    vertical: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ``source`` predates acquisition attribution and describes the product
    # surface. Keep it stable for compatibility; UTM source lives in the
    # bounded first_touch/last_touch dictionaries below.
    source: Mapped[str] = mapped_column(String(40), default="landing")
    first_touch: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    last_touch: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    assigned_founder: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # A three-message maximum: confirmation, one useful note, one pilot invite.
    # Timestamps are both the audit trail and the task-level idempotency guard.
    email_opted_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmation_provider_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    useful_followup_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    useful_followup_provider_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    pilot_invitation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pilot_invitation_provider_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
