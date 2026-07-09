"""Stripe data adapter — pulls a merchant's customers + charges via a secret/restricted
API key and normalizes them. "Visits" are successful charges (Stripe is purchase-based).

Distinct from Pulse's own Stripe *billing*: this reads a connected merchant's account.
Pagination uses Stripe's cursor (`starting_after`); every call has a timeout and the
page count is capped so a huge account can't wedge a sync request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.integrations.base import DataSourceAdapter, IntegrationError
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
)

API = "https://api.stripe.com/v1"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_PAGE_SIZE = 100
_MAX_PAGES = 100  # 10k records per resource — plenty for v1 small businesses

# Zero-decimal currencies aren't divided by 100 (Stripe amounts are in minor units).
_ZERO_DECIMAL = {"jpy", "krw", "vnd", "clp", "pyg", "xaf", "xof", "bif", "djf",
                 "gnf", "kmf", "mga", "rwf", "ugx", "vuv", "xpf"}


def _ts(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=UTC) if epoch else None


def parse_stripe_customer(obj: dict[str, Any]) -> NormalizedCustomer:
    name = (obj.get("name") or "").strip()
    first, last = (name.split(" ", 1) + [None])[:2] if name else (None, None)
    return NormalizedCustomer(
        external_id=obj.get("id"),
        source="stripe",
        first_name=first or None,
        last_name=last or None,
        email=obj.get("email"),
        phone=obj.get("phone"),
        created_at=_ts(obj.get("created")),
    )


def parse_stripe_charge(obj: dict[str, Any]) -> NormalizedTransaction | None:
    """Successful, non-refunded charges only; amount converted from minor units."""
    if obj.get("status") != "succeeded" or obj.get("refunded"):
        return None
    customer = obj.get("customer")
    currency = (obj.get("currency") or "usd").lower()
    minor = Decimal(obj.get("amount", 0)) - Decimal(obj.get("amount_refunded", 0) or 0)
    amount = minor if currency in _ZERO_DECIMAL else minor / 100
    if amount <= 0:
        return None
    billing = obj.get("billing_details") or {}
    return NormalizedTransaction(
        external_id=obj.get("id"),
        source="stripe",
        customer_external_id=customer if isinstance(customer, str) else None,
        customer_email=billing.get("email"),
        customer_phone=billing.get("phone"),
        amount=amount,
        currency=currency.upper(),
        occurred_at=_ts(obj.get("created")) or datetime.now(UTC),
    )


class StripeAdapter(DataSourceAdapter):
    source = "stripe"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        # Charges power both transactions and visits — fetch once per sync.
        self._tx_cache: tuple[datetime | None, list[NormalizedTransaction]] | None = None

    async def _get(self, client: httpx.AsyncClient, path: str, **params) -> dict:
        resp = await client.get(
            f"{API}{path}", params=params, auth=(self._api_key or "", "")
        )
        if resp.status_code == 401:
            raise IntegrationError("Stripe rejected the API key (401)")
        if resp.status_code == 403:
            raise IntegrationError(
                "This Stripe key lacks permission — grant read access to Customers and Charges"
            )
        if resp.status_code >= 400:
            raise IntegrationError(f"Stripe error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _paginate(self, path: str, **params) -> list[dict]:
        """Walk Stripe's cursor pagination, newest-first, up to _MAX_PAGES."""
        out: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                cursor: str | None = None
                for _ in range(_MAX_PAGES):
                    page_params = {"limit": _PAGE_SIZE, **params}
                    if cursor:
                        page_params["starting_after"] = cursor
                    data = await self._get(client, path, **page_params)
                    items = data.get("data", [])
                    out.extend(items)
                    if not data.get("has_more") or not items:
                        break
                    cursor = items[-1]["id"]
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach Stripe: {exc}") from exc
        return out

    async def connect(self, auth_payload: dict) -> None:
        self._api_key = auth_payload.get("access_token") or self._api_key
        if not self._api_key:
            raise IntegrationError("Stripe API key required")
        # Validate the key with a cheap authenticated call.
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                await self._get(client, "/customers", limit=1)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach Stripe: {exc}") from exc

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        params: dict = {}
        if since:
            params["created[gte]"] = int(since.timestamp())
        return [parse_stripe_customer(o) for o in await self._paginate("/customers", **params)]

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        if self._tx_cache is not None and self._tx_cache[0] == since:
            return self._tx_cache[1]
        params: dict = {}
        if since:
            params["created[gte]"] = int(since.timestamp())
        charges = await self._paginate("/charges", **params)
        txs = [t for o in charges if (t := parse_stripe_charge(o)) is not None]
        self._tx_cache = (since, txs)
        return txs

    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        """Stripe has no first-class visits — each successful charge counts as one."""
        return [
            NormalizedVisit(
                external_id=f"visit-{t.external_id}",
                source="stripe",
                customer_external_id=t.customer_external_id,
                customer_email=t.customer_email,
                customer_phone=t.customer_phone,
                occurred_at=t.occurred_at,
            )
            for t in await self.sync_transactions(since)
        ]
