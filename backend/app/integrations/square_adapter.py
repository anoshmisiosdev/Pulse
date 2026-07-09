"""Square data adapter — pulls a merchant's customers + payments via a personal
access token (from the Square Developer dashboard) and normalizes them. "Visits"
are completed payments.

Cursor pagination, timeouts on every call, and a page cap so a huge account can't
wedge a sync request. The environment (production/sandbox) is chosen per token.
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

_HOSTS = {
    "production": "https://connect.squareup.com",
    "sandbox": "https://connect.squareupsandbox.com",
}
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_PAGE_SIZE = 100
_MAX_PAGES = 100
_SQUARE_VERSION = "2024-01-18"

_ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "PYG", "XAF", "XOF", "BIF", "DJF",
                 "GNF", "KMF", "MGA", "RWF", "UGX", "VUV", "XPF"}


def parse_square_customer(obj: dict[str, Any]) -> NormalizedCustomer:
    created = obj.get("created_at")
    return NormalizedCustomer(
        external_id=obj.get("id"),
        source="square",
        first_name=obj.get("given_name") or None,
        last_name=obj.get("family_name") or None,
        email=obj.get("email_address"),
        phone=obj.get("phone_number"),
        created_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
    )


def parse_square_payment(obj: dict[str, Any]) -> NormalizedTransaction | None:
    """COMPLETED payments only; amount from minor units."""
    if obj.get("status") != "COMPLETED":
        return None
    money = obj.get("amount_money") or {}
    currency = (money.get("currency") or "USD").upper()
    minor = Decimal(money.get("amount", 0))
    refunded = Decimal((obj.get("refunded_money") or {}).get("amount", 0) or 0)
    net = minor - refunded
    amount = net if currency in _ZERO_DECIMAL else net / 100
    if amount <= 0:
        return None
    created = obj.get("created_at")
    return NormalizedTransaction(
        external_id=obj.get("id"),
        source="square",
        customer_external_id=obj.get("customer_id"),
        customer_email=obj.get("buyer_email_address"),
        amount=amount,
        currency=currency,
        occurred_at=(
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created
            else datetime.now(UTC)
        ),
    )


class SquareAdapter(DataSourceAdapter):
    source = "square"

    def __init__(self, access_token: str | None = None, environment: str = "production") -> None:
        self._access_token = access_token
        self._environment = environment if environment in _HOSTS else "production"
        self._tx_cache: tuple[datetime | None, list[NormalizedTransaction]] | None = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Square-Version": _SQUARE_VERSION,
            "Content-Type": "application/json",
        }

    async def _get(self, client: httpx.AsyncClient, path: str, **params) -> dict:
        base = _HOSTS[self._environment]
        resp = await client.get(f"{base}{path}", params=params, headers=self._headers())
        if resp.status_code == 401:
            raise IntegrationError("Square rejected the access token (401)")
        if resp.status_code == 429:
            raise IntegrationError("Square rate limit hit — try again in a minute")
        if resp.status_code >= 400:
            raise IntegrationError(f"Square error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _paginate(self, path: str, list_key: str, **params) -> list[dict]:
        out: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                cursor: str | None = None
                for _ in range(_MAX_PAGES):
                    page_params = {"limit": _PAGE_SIZE, **params}
                    if cursor:
                        page_params["cursor"] = cursor
                    data = await self._get(client, path, **page_params)
                    out.extend(data.get(list_key, []))
                    cursor = data.get("cursor")
                    if not cursor:
                        break
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach Square: {exc}") from exc
        return out

    async def connect(self, auth_payload: dict) -> None:
        self._access_token = auth_payload.get("access_token") or self._access_token
        self._environment = auth_payload.get("environment", self._environment)
        if self._environment not in _HOSTS:
            self._environment = "production"
        if not self._access_token:
            raise IntegrationError("Square access token required")
        # Validate with a cheap call; auto-fall back to sandbox for sandbox tokens.
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                try:
                    await self._get(client, "/v2/locations")
                except IntegrationError:
                    if self._environment == "production":
                        self._environment = "sandbox"
                        await self._get(client, "/v2/locations")
                    else:
                        raise
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach Square: {exc}") from exc

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        rows = await self._paginate("/v2/customers", "customers")
        return [parse_square_customer(o) for o in rows]

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        if self._tx_cache is not None and self._tx_cache[0] == since:
            return self._tx_cache[1]
        params: dict = {}
        if since:
            params["begin_time"] = since.astimezone(UTC).isoformat().replace("+00:00", "Z")
        rows = await self._paginate("/v2/payments", "payments", **params)
        txs = [t for o in rows if (t := parse_square_payment(o)) is not None]
        self._tx_cache = (since, txs)
        return txs

    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        """Each completed payment counts as a visit."""
        return [
            NormalizedVisit(
                external_id=f"visit-{t.external_id}",
                source="square",
                customer_external_id=t.customer_external_id,
                customer_email=t.customer_email,
                occurred_at=t.occurred_at,
            )
            for t in await self.sync_transactions(since)
        ]
