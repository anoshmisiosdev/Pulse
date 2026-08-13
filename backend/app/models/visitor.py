"""First-party marketing visitor intelligence.

These records belong to Churnary itself, not to a customer tenant. Browser and
session identifiers are never stored in plaintext; ``VisitorIdentifier`` keeps
only deterministic hashes so anonymous activity can be stitched after an
explicit waitlist submission or sign-in without turning the table into a
fingerprint store.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class VisitorProfile(UUIDMixin, Base):
    __tablename__ = "visitor_profiles"

    primary_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    company_website: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(180), nullable=True)
    employee_count: Mapped[str | None] = mapped_column(String(40), nullable=True)
    estimated_revenue: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zipcode: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # anonymous | company | person | waitlist | account
    identity_level: Mapped[str] = mapped_column(
        String(20), default="anonymous", server_default="anonymous", index=True
    )
    # first_party | rb2b (future adapters can add their own stable name)
    source_provider: Mapped[str] = mapped_column(
        String(40), default="first_party", server_default="first_party", index=True
    )
    provider_profile_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # new | reviewing | qualified | contacted | dismissed
    status: Mapped[str] = mapped_column(
        String(20), default="new", server_default="new", index=True
    )
    intent_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    visit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pageview_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    referrer_host: Mapped[str | None] = mapped_column(String(253), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    waitlist_signup_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("waitlist_signups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    authenticated_user_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    suppressed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "source_provider",
            "provider_profile_key",
            name="uq_visitor_profile_provider_key",
        ),
        Index("ix_visitor_profiles_recent_intent", "last_seen_at", "intent_score"),
    )


class VisitorIdentifier(UUIDMixin, Base):
    __tablename__ = "visitor_identifiers"

    visitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("visitor_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # browser | email | user | linkedin | provider
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("kind", "value_hash", name="uq_visitor_identifier_kind_hash"),
    )


class VisitorEvent(UUIDMixin, Base):
    __tablename__ = "visitor_events"

    visitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("visitor_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(
        String(40), default="first_party", server_default="first_party"
    )
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    __table_args__ = (
        Index("ix_visitor_events_profile_occurred", "visitor_id", "occurred_at"),
    )
