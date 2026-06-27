"""Integration connections (tokens encrypted at rest) and sync audit log."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin


class IntegrationConnection(UUIDMixin, Base):
    __tablename__ = "integration_connections"

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32))  # csv | square | stripe | ...
    status: Mapped[str] = mapped_column(String(16), default="active")
    # Fernet-encrypted OAuth token (see core.security). Never stored in plaintext.
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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
