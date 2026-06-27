"""Mindbody adapter — interface stub only (explicitly out of scope for v1).

Present so the adapter registry and tests prove a new vertical drops in with zero
changes outside this package. Every method raises ``NotImplementedError``.
"""

from __future__ import annotations

from datetime import datetime

from app.integrations.base import DataSourceAdapter
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
)


class MindbodyAdapter(DataSourceAdapter):
    source = "mindbody"

    async def connect(self, auth_payload: dict) -> None:
        raise NotImplementedError("Mindbody integration is not part of v1")

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        raise NotImplementedError("Mindbody integration is not part of v1")

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        raise NotImplementedError("Mindbody integration is not part of v1")

    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        raise NotImplementedError("Mindbody integration is not part of v1")
