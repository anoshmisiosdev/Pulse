"""Stripe data adapter — Phase 3/6.

Pulls Customers + Charges/Invoices to feed scoring (failed payments and
cancel-at-period-end are strong churn signals). Distinct from Pulse's own Stripe
*billing* in ``api/billing`` — this reads a connected merchant's account.
"""

from __future__ import annotations

from datetime import datetime

from app.integrations.base import DataSourceAdapter, IntegrationError
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
)


class StripeAdapter(DataSourceAdapter):
    source = "stripe"

    def __init__(self, account_token: str | None = None) -> None:
        self._account_token = account_token

    async def connect(self, auth_payload: dict) -> None:
        self._account_token = auth_payload.get("access_token", self._account_token)
        if not self._account_token:
            raise IntegrationError("Stripe connected-account token required")

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        raise NotImplementedError("Stripe customer sync — Phase 3")

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        raise NotImplementedError("Stripe charge/invoice sync — Phase 3")

    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        # Stripe is purchase-based; "visits" map to successful charges.
        raise NotImplementedError("Stripe visit derivation — Phase 3")
