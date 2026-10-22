"""Team invites. Membership itself lives on the existing ``users`` table.

An invite is a bearer credential for joining a business, so only a hash of the
token is stored: a leaked database row can't be replayed into a membership. The
raw token exists once, in the link sent to the invitee.

Invites are bound to an email address. Accepting requires the authenticated
user's own (Supabase-verified) email to match, so a forwarded or leaked link
can't be used by whoever happens to have it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin

# The two roles. Kept deliberately small: "owner" can do everything; "staff"
# can do the day-to-day work (see who's at risk, build and approve campaigns,
# use the assistant) but cannot change billing, export or delete data, or
# manage the team. See app/core/deps.py::require_owner.
TEAM_ROLES = ("owner", "staff")


class TeamInvite(UUIDMixin, Base):
    __tablename__ = "team_invites"

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(16), default="staff")
    # sha256 hex of the raw token. Unique so a lookup is a single indexed read.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
