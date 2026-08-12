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

from app.core.http_retry import retry_transient
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
_CHARGE_EVENT_TYPES = (
    "charge.failed",
    "charge.refunded",
    "charge.succeeded",
    "charge.updated",
)

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
    """Normalize every meaningful charge state, including failures and refunds.

    Keeping a zero-net refunded row lets an update replace stale revenue that was
    imported while the charge was still successful.
    """
    if not obj.get("id"):
        return None
    customer = obj.get("customer")
    currency = (obj.get("currency") or "usd").lower()
    gross_minor = Decimal(obj.get("amount", 0) or 0)
    refunded_minor = Decimal(obj.get("amount_refunded", 0) or 0)
    net_minor = max(Decimal("0"), gross_minor - refunded_minor)
    divisor = Decimal("1") if currency in _ZERO_DECIMAL else Decimal("100")
    gross = gross_minor / divisor
    refunded = refunded_minor / divisor
    raw_status = (obj.get("status") or "pending").lower()
    if raw_status == "failed":
        status = "failed"
        amount = Decimal("0")
    elif raw_status != "succeeded":
        status = "pending"
        amount = Decimal("0")
    elif refunded_minor >= gross_minor and gross_minor > 0:
        status = "refunded"
        amount = Decimal("0")
    elif refunded_minor > 0:
        status = "partially_refunded"
        amount = net_minor / divisor
    else:
        status = "completed"
        amount = net_minor / divisor
    billing = obj.get("billing_details") or {}
    return NormalizedTransaction(
        external_id=obj.get("id"),
        source="stripe",
        customer_external_id=customer if isinstance(customer, str) else None,
        customer_email=billing.get("email") or obj.get("receipt_email"),
        customer_phone=billing.get("phone"),
        customer_name=billing.get("name"),
        amount=amount,
        gross_amount=gross,
        refunded_amount=refunded,
        currency=currency.upper(),
        status=status,
        occurred_at=_ts(obj.get("created")) or datetime.now(UTC),
        failure_code=obj.get("failure_code"),
    )


class StripeAdapter(DataSourceAdapter):
    source = "stripe"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._account_id: str | None = None
        # Charges power both transactions and visits — fetch once per sync.
        self._tx_cache: tuple[datetime | None, list[NormalizedTransaction]] | None = None

    @property
    def account_id(self) -> str | None:
        return self._account_id

    @property
    def environment(self) -> str:
        key = self._api_key or ""
        return "sandbox" if key.startswith(("sk_test_", "rk_test_")) else "production"

    @retry_transient
    async def _get(self, client: httpx.AsyncClient, path: str, **params) -> dict:
        resp = await client.get(
            f"{API}{path}", params=params, auth=(self._api_key or "", "")
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()  # transient — retried by the decorator
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
        # Validate the key and remember the account id used by Connect webhooks.
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                account = await self._get(client, "/account")
                self._account_id = account.get("id")
                await self._get(client, "/customers", limit=1)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach Stripe: {exc}") from exc

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        # Stripe can filter customer creation time, but not update time. A full
        # customer pass keeps changed emails/phones current; payments are the
        # larger collection and remain incremental.
        return [parse_stripe_customer(o) for o in await self._paginate("/customers")]

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        if self._tx_cache is not None and self._tx_cache[0] == since:
            return self._tx_cache[1]
        params: dict = {}
        if since:
            params["created[gte]"] = int(since.timestamp())
        charges = await self._paginate("/charges", **params)

        # Charges can be filtered only by creation time, so a refund or delayed
        # status transition on an older charge would otherwise be invisible to
        # an incremental pull. Stripe retains Events for 30 days; replay the
        # relevant snapshots as a repair rail for missed webhook deliveries.
        # Webhooks remain primary and the transaction upsert is idempotent.
        events: list[dict] = []
        if since:
            events = await self._paginate(
                "/events",
                **{
                    "created[gte]": int(since.timestamp()),
                    "types[]": list(_CHARGE_EVENT_TYPES),
                },
            )

        by_charge: dict[str, tuple[int, NormalizedTransaction]] = {}
        for obj in charges:
            transaction = parse_stripe_charge(obj)
            if transaction is not None and transaction.external_id:
                by_charge[transaction.external_id] = (-1, transaction)
        for event in events:
            if event.get("type") not in _CHARGE_EVENT_TYPES:
                continue
            obj = ((event.get("data") or {}).get("object") or {})
            transaction = parse_stripe_charge(obj)
            if transaction is None or not transaction.external_id:
                continue
            event_created = int(event.get("created") or 0)
            transaction.updated_at = _ts(event_created)
            current = by_charge.get(transaction.external_id)
            if current is None or event_created > current[0]:
                by_charge[transaction.external_id] = (event_created, transaction)

        txs = [entry[1] for entry in by_charge.values()]
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
            if t.is_revenue
        ]
