"""Square adapter — Phase 3.

OAuth + customer/order sync. The shape is wired so Phase 3 fills in HTTP calls
(respecting 429 + Retry-After) without touching anything outside this package.
"""

from __future__ import annotations

from datetime import datetime

from app.integrations.base import DataSourceAdapter, IntegrationError
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
)


class SquareAdapter(DataSourceAdapter):
    source = "square"

    def __init__(self, access_token: str | None = None, environment: str = "sandbox") -> None:
        self._access_token = access_token
        self._environment = environment

    async def connect(self, auth_payload: dict) -> None:
        self._access_token = auth_payload.get("access_token", self._access_token)
        if not self._access_token:
            raise IntegrationError("Square access token required")

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        raise NotImplementedError("Square customer sync — Phase 3")

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        raise NotImplementedError("Square order sync — Phase 3")

    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        # Square has no first-class "visit"; Phase 3 derives them from orders.
        raise NotImplementedError("Square visit derivation — Phase 3")
