"""Outbound webhooks: an owner's URL that we POST signed events to.

Delivery uses an outbox. Emitting an event only inserts ``WebhookDelivery``
rows in the same transaction as the thing that happened, so a recovery is never
recorded without its webhook being queued, and a slow or dead receiver can
never stall attribution or a campaign approval. A Celery tick delivers pending
rows with backoff.

The signing secret is Fernet-encrypted at rest (CLAUDE.md: tokens are
encrypted at rest) because we need it back to sign each delivery; it is shown
to the owner exactly once, at creation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

WEBHOOK_EVENTS = (
    "customer.recovered",
    "campaign.sent",
    "webhook.test",
)


class WebhookEndpoint(UUIDMixin, Base):
    __tablename__ = "webhook_endpoints"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    url: Mapped[str] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_enc: Mapped[str] = mapped_column(Text)
    # Subscribed event types; empty means "all".
    events: Mapped[list] = mapped_column(_JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class WebhookDelivery(UUIDMixin, Base):
    __tablename__ = "webhook_deliveries"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    # Stable per event, shared by every endpoint's delivery of it. Receivers
    # dedupe on this, since a retried delivery is the same event, not a new one.
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(_JSON, default=dict)
    # pending | delivered | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
