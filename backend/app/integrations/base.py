"""The adapter contract every data source implements.

Downstream code only ever sees the normalized types returned here. Adding a new
integration must require **zero changes outside this package**.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
)


class IntegrationError(Exception):
    """Raised when an adapter cannot connect or sync."""


class DataSourceAdapter(ABC):
    """Abstract base for Square, Stripe, CSV, Mindbody, ….

    Implementations are constructed with whatever auth/config they need, then
    ``connect`` is called once before any ``sync_*`` call.
    """

    source: str  # short slug, e.g. "csv", "square"

    @abstractmethod
    async def connect(self, auth_payload: dict) -> None:
        """Validate credentials / establish a session. Raise IntegrationError on failure."""

    @abstractmethod
    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        ...

    @abstractmethod
    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        ...

    @abstractmethod
    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        ...
