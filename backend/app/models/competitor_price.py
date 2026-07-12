"""Competitor price research persistence.

Google Maps grounded content can carry display/storage obligations. We store the
small, user-facing report plus source URLs/evidence for auditability, and keep
raw Maps output out of separate long-lived columns until legal review.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class CompetitorPriceResearchRun(UUIDMixin, Base):
    __tablename__ = "competitor_price_research_runs"
    __table_args__ = (
        Index("ix_comp_price_runs_business_cache", "business_id", "cache_key"),
        Index("ix_comp_price_runs_business_created", "business_id", "created_at"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cache_key: Mapped[str] = mapped_column(String(512), index=True)
    business_category: Mapped[str] = mapped_column(String(255))
    target_offer: Mapped[str] = mapped_column(String(255))
    location_json: Mapped[str] = mapped_column(Text, default="{}")
    radius_miles: Mapped[float] = mapped_column(Float, default=5.0)
    models_used_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CompetitorPriceCompetitor(UUIDMixin, Base):
    __tablename__ = "competitor_price_competitors"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("competitor_price_research_runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    website: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discovery_provider: Mapped[str] = mapped_column(String(32), default="perplexity")


class CompetitorPriceSource(UUIDMixin, Base):
    __tablename__ = "competitor_price_sources"
    __table_args__ = (Index("ix_comp_price_sources_competitor_url", "competitor_id", "url"),)

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("competitor_price_competitors.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="unknown")
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_status: Mapped[str] = mapped_column(String(32), default="discovered")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_updated_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieval_method: Mapped[str] = mapped_column(String(32), default="search_snippet")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CompetitorPriceObservation(UUIDMixin, Base):
    __tablename__ = "competitor_price_observations"

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("competitor_price_sources.id", ondelete="CASCADE"), index=True
    )
    offer_name: Mapped[str] = mapped_column(String(255))
    normalized_offer_name: Mapped[str] = mapped_column(String(255))
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    price_type: Mapped[str] = mapped_column(String(32), default="unknown")
    evidence_text: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    price_channel: Mapped[str] = mapped_column(String(32), default="unknown")
    match_quality: Mapped[str] = mapped_column(String(16), default="weak")
    corroborated: Mapped[bool] = mapped_column(default=False)
    included_in_summary: Mapped[bool] = mapped_column(default=False)
    source_published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_updated_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retrieval_method: Mapped[str] = mapped_column(String(32), default="search_snippet")
    extraction_method: Mapped[str] = mapped_column(String(32), default="search_snippet")
    freshness_status: Mapped[str] = mapped_column(String(16), default="unknown")
    needs_review: Mapped[bool] = mapped_column(default=False)
