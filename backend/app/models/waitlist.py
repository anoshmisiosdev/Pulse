"""Landing-page waitlist signups.

Deliberately **not** tenant-scoped: a signup arrives from the public marketing
page before any ``Business`` exists, so there is no ``business_id`` to hang it
on. That also means this is the one table an unauthenticated request can write
to, which is why the endpoint keeps the row small and the columns bounded.

Only what we need to email someone back. No tracking, no IP, no fingerprint —
the CLAUDE.md rule about collecting the minimum applies to prospects too.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class WaitlistSignup(UUIDMixin, Base):
    __tablename__ = "waitlist_signups"

    # Unique so a double-submit (or an eager refresh) updates rather than
    # duplicates — the API upserts on this column instead of erroring, because
    # "you already signed up" is not a failure the visitor should have to read.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    business_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Free text, not an enum: the picker offers the verticals we know about, and
    # anything else an owner types is exactly the signal we want to keep.
    vertical: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="landing")
