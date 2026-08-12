"""Integration connections (tokens encrypted at rest) and sync audit log."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class IntegrationConnection(UUIDMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "source", name="uq_integration_connections_business_source"
        ),
        UniqueConstraint(
            "source",
            "provider_account_id",
            name="uq_integration_connections_source_provider_account",
        ),
        Index("ix_integration_connections_provider_account", "source", "provider_account_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32))  # csv | square | stripe | ...
    status: Mapped[str] = mapped_column(String(16), default="active")
    # Fernet-encrypted OAuth token (see core.security). Never stored in plaintext.
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str] = mapped_column(String(16), default="production")
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncRun(UUIDMixin, Base):
    """One row per sync attempt — powers "Last synced 2h ago ✓" in the UI."""

    __tablename__ = "sync_runs"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|error
    customers_synced: Mapped[int] = mapped_column(Integer, default=0)
    transactions_synced: Mapped[int] = mapped_column(Integer, default=0)
    visits_synced: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProviderWebhookEvent(UUIDMixin, Base):
    """Small idempotency ledger for Stripe/Square webhook deliveries.

    We deliberately do not retain the raw payload: it contains customer PII and
    the normalized customer/payment rows are the durable source of truth.
    """

    __tablename__ = "provider_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "source", "provider_event_id", name="uq_provider_webhook_source_event"
        ),
        Index("ix_provider_webhook_business_created", "business_id", "created_at"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(255))
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="processed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
