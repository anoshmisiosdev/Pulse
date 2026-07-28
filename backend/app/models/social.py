"""Social presence: brand kit, company brain, campaigns, posts, and the
engagement inbox.

Ported from Splay, where all of this lived in per-tenant JSON files on disk
(``output/tenants/<team>/brand-kit.json`` and friends). Promoting them to tables
means tenancy is a ``business_id`` column rather than a directory, which is the
single most important change: an unscoped query here would leak one business's
private context into another's generated copy.

Two deliberate departures from the original, both fixing latent bugs:

* the brand kit is **append-only** rather than overwritten in place, so a post's
  ``brand_kit_version`` can actually be resolved back to the kit that produced it;
* review events are their own append-only table instead of a JSON blob nested in
  the post, so the audit trail is queryable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin

# ── Vocabularies ─────────────────────────────────────────────────────────────

TYPE_SCALES = ("compact", "balanced", "editorial")
CONTEXT_KINDS = ("company", "product", "customer", "founder", "market", "proof", "other")

SOCIAL_PLATFORMS = ("linkedin", "x")
POST_STATUSES = ("draft", "approved", "rejected", "staged", "posted", "failed")
CAMPAIGN_STATUSES = ("draft", "generating", "active", "paused", "completed")

REVIEW_DECISIONS = ("approve", "revise", "reject")
REVIEW_REASONS = (
    # positive
    "strong_insight",
    "strong_proof",
    "good_voice",
    "approved_without_note",
    # revise
    "too_generic",
    "unsupported",
    "different_angle",
    "visual_not_useful",
    # reject
    "too_promotional",
    "wrong_audience",
    "repetitive",
)

COMMENT_PLATFORMS = ("linkedin", "x", "other")
COMMENT_SOURCES = ("demo", "manual")
COMMENT_INTENTS = ("product_question", "sales_lead", "complaint", "praise", "feedback", "spam")
COMMENT_SENTIMENTS = ("positive", "neutral", "negative")
COMMENT_LEVELS = ("high", "medium", "low")
COMMENT_STATUSES = ("needs_reply", "drafted", "approved", "resolved")
REPLY_VARIANTS = ("standard", "shorter", "warmer")


# ── Brand kit ────────────────────────────────────────────────────────────────


class BrandKitVersion(UUIDMixin, Base):
    """One saved brand kit. Append-only: every save writes a new row.

    ``version`` starts at 1. Version 0 is never stored — it's the synthetic
    "never configured" default the service layer returns, and the sentinel that
    blocks campaign generation until the owner has actually filled this in.
    """

    __tablename__ = "brand_kit_versions"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version: Mapped[int] = mapped_column(Integer)

    name: Mapped[str] = mapped_column(String(80))
    tagline: Mapped[str] = mapped_column(String(160))
    audience: Mapped[str] = mapped_column(String(500))
    tone: Mapped[str] = mapped_column(String(500))
    positioning: Mapped[str] = mapped_column(String(500))
    avoid: Mapped[list[str]] = mapped_column(JSON, default=list)

    color_primary: Mapped[str] = mapped_column(String(7))
    color_secondary: Mapped[str] = mapped_column(String(7))
    color_accent: Mapped[str] = mapped_column(String(7))
    color_background: Mapped[str] = mapped_column(String(7))
    color_text: Mapped[str] = mapped_column(String(7))

    heading_family: Mapped[str] = mapped_column(String(80))
    body_family: Mapped[str] = mapped_column(String(80))
    heading_weight: Mapped[int] = mapped_column(Integer, default=400)
    body_weight: Mapped[int] = mapped_column(Integer, default=400)
    scale: Mapped[str] = mapped_column(String(16), default="balanced")

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("business_id", "version", name="uq_brand_kit_business_version"),
        CheckConstraint("heading_weight BETWEEN 100 AND 900", name="ck_brand_kit_heading_weight"),
        CheckConstraint("body_weight BETWEEN 100 AND 900", name="ck_brand_kit_body_weight"),
    )


# ── Company brain ────────────────────────────────────────────────────────────


class CompanyContextItem(UUIDMixin, Base):
    """A fact about the business that AI copy is allowed to draw on.

    ``public_safe`` defaults to False and is the content-safety gate for the
    whole product: only rows with it set may be read by anything that builds a
    prompt. The management UI reads the table unfiltered; generation must go
    through the filtered accessor in ``app/social/brain.py``.
    """

    __tablename__ = "company_context_items"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(80), default="other")
    summary: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    public_safe: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_company_context_business_public", "business_id", "public_safe"),
    )


# ── Campaigns and posts ──────────────────────────────────────────────────────


class SocialCampaign(UUIDMixin, Base):
    """A recurring brief that fans out into weekly draft slots.

    The slots themselves are never stored — they're recomputed from
    ``start_at``/``timezone``/``interval_weeks``/``occurrences`` on every read
    (see ``app/social/scheduling.py``), so editing the cadence can't leave
    stale rows behind.
    """

    __tablename__ = "social_campaigns"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(100))
    brief: Mapped[str] = mapped_column(String(500))
    themes: Mapped[list[str]] = mapped_column(JSON, default=list)
    platforms: Mapped[list[str]] = mapped_column(JSON, default=list)

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    interval_weeks: Mapped[int] = mapped_column(Integer, default=1)
    occurrences: Mapped[int] = mapped_column(Integer, default=6)

    status: Mapped[str] = mapped_column(String(16), default="draft")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("interval_weeks BETWEEN 1 AND 4", name="ck_campaign_interval_weeks"),
        CheckConstraint("occurrences BETWEEN 2 AND 52", name="ck_campaign_occurrences"),
    )


class SocialPost(UUIDMixin, Base):
    """One generated post awaiting review, scheduled, or already out the door.

    ``scheduled_for`` is orthogonal to ``status``: a campaign post is created as
    a draft that already carries its future slot time, so it is simultaneously
    "in review" and "pre-scheduled".
    """

    __tablename__ = "social_posts"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("social_campaigns.id", ondelete="CASCADE"), nullable=True, index=True
    )
    campaign_occurrence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brand_kit_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("brand_kit_versions.id", ondelete="SET NULL"), nullable=True
    )

    platform: Mapped[str] = mapped_column(String(16))
    topic: Mapped[str] = mapped_column(String(500))
    post_text: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Why this post exists: the public-safe context that grounded it, so a
    # reviewer can check the claim without leaving the review queue.
    source_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_references: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Gate output: {"passed": bool, "errors": [...], "warnings": [...],
    #               "verdict": "publish"|"revise"|"reject"}
    editorial: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    generated_by: Mapped[str] = mapped_column(String(16), default="claude")
    generation_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Provider ids from the publish leg, for status reconciliation.
    provider_post_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PostReviewEvent(UUIDMixin, Base):
    """Append-only record of every approve/revise/reject decision.

    ``text_snapshot`` holds the copy as it read *before* the decision, so the
    trail still makes sense after the post is regenerated.
    """

    __tablename__ = "post_review_events"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("social_posts.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text_snapshot: Mapped[str] = mapped_column(Text)


# ── Engagement inbox ─────────────────────────────────────────────────────────


class SocialComment(UUIDMixin, Base):
    """An inbound comment on a social post, triaged and awaiting a reply.

    Distinct from ``EngagementEvent`` in ``models/customer.py``, which tracks
    email opens and SMS replies for a known customer. This is a stranger on
    LinkedIn or X, and nothing here is ever sent automatically — a human
    approves the text and copies it out.
    """

    __tablename__ = "social_comments"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    source: Mapped[str] = mapped_column(String(8), default="manual")
    platform: Mapped[str] = mapped_column(String(16), default="linkedin")
    post_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    original_post_excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str] = mapped_column(String(120))
    comment: Mapped[str] = mapped_column(String(4000))

    intent: Mapped[str] = mapped_column(String(24))
    sentiment: Mapped[str] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(8))
    risk: Mapped[str] = mapped_column(String(8))
    recommended_action: Mapped[str] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(16), default="needs_reply")
    suggested_reply: Mapped[str] = mapped_column(Text, default="")
    approved_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_variant: Mapped[str] = mapped_column(String(16), default="standard")
    reply_version: Mapped[int] = mapped_column(Integer, default=0)
    # Ordered: ranked context titles first, then "Brand positioning".
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)

    __table_args__ = (
        Index("ix_social_comments_business_created", "business_id", "created_at"),
    )
