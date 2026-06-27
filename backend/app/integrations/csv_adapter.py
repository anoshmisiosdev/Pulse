"""CSV adapter — the reference integration and the first thing demos depend on.

Built to swallow whatever a salon owner exports: lenient header matching, dollar
signs and commas in amounts, and a handful of common date formats. Handles both
*customer-level* CSVs (one row per customer, with an aggregate last-visit/spend)
and *event-level* CSVs (repeated emails across rows) — duplicates merge and their
visits/transactions accumulate via :func:`dedupe_customers`.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from app.integrations.base import DataSourceAdapter, IntegrationError
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)

SOURCE = "csv"

# canonical field -> accepted header synonyms (post-normalization)
_HEADER_SYNONYMS: dict[str, set[str]] = {
    "external_id": {"id", "customer_id", "external_id", "member_id"},
    "first_name": {"first_name", "firstname", "first", "given_name"},
    "last_name": {"last_name", "lastname", "last", "surname", "family_name"},
    "name": {"name", "full_name", "customer", "customer_name", "client", "member"},
    "email": {"email", "e_mail", "email_address", "mail"},
    "phone": {"phone", "phone_number", "mobile", "cell", "telephone", "tel"},
    "joined_at": {
        "join_date", "joined", "created_at", "member_since", "signup_date",
        "start_date", "first_visit", "since",
    },
    "last_visit": {
        "last_visit", "last_visit_date", "last_seen", "last_order_date",
        "last_appointment", "date", "occurred_at", "visit_date",
    },
    "amount": {
        "amount", "total_spent", "total_spend", "lifetime_spend", "ltv",
        "revenue", "spend", "price",
    },
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_")


def _build_field_map(headers: list[str]) -> dict[str, str]:
    """Map normalized CSV headers -> canonical field names."""
    field_map: dict[str, str] = {}
    for raw in headers:
        norm = _normalize_header(raw)
        for canonical, synonyms in _HEADER_SYNONYMS.items():
            if norm in synonyms:
                field_map[raw] = canonical
                break
    return field_map


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:  # last resort: dateutil if it happens to be installed
        from dateutil import parser as _du  # type: ignore

        return _du.parse(text)
    except Exception:
        return None


def parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.strip().replace("$", "").replace(",", "").replace("£", "").replace("€", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_csv(content: str) -> SyncResult:
    """Pure parse: CSV text -> normalized records (no dedupe yet)."""
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        return SyncResult(warnings=["CSV had no header row"])

    field_map = _build_field_map(reader.fieldnames)
    if not any(c in field_map.values() for c in ("email", "phone", "name", "first_name")):
        raise IntegrationError(
            "CSV must contain at least one identity column (email, phone, or name)."
        )

    result = SyncResult()
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        fields = {field_map[k]: (v or "").strip() for k, v in row.items() if k in field_map}

        first = fields.get("first_name")
        last = fields.get("last_name")
        if not first and not last and fields.get("name"):
            parts = fields["name"].split()
            first = parts[0]
            last = " ".join(parts[1:]) or None

        email = fields.get("email") or None
        phone = fields.get("phone") or None
        external_id = fields.get("external_id") or None

        if not (email or phone or first):
            result.warnings.append(f"Row {i}: no identity, skipped")
            continue

        customer = NormalizedCustomer(
            external_id=external_id,
            source=SOURCE,
            first_name=first or None,
            last_name=last or None,
            email=email,
            phone=phone,
            created_at=parse_date(fields.get("joined_at")),
        )
        result.customers.append(customer)

        visit_at = parse_date(fields.get("last_visit"))
        if visit_at is not None:
            result.visits.append(
                NormalizedVisit(
                    source=SOURCE,
                    customer_external_id=external_id,
                    customer_email=email,
                    customer_phone=phone,
                    occurred_at=visit_at,
                )
            )

        amount = parse_amount(fields.get("amount"))
        if amount is not None and amount > 0:
            result.transactions.append(
                NormalizedTransaction(
                    source=SOURCE,
                    customer_external_id=external_id,
                    customer_email=email,
                    customer_phone=phone,
                    amount=amount,  # Decimal coercion handled by pydantic
                    occurred_at=visit_at or customer.created_at or datetime.utcnow(),
                )
            )

    return result


def dedupe_customers(customers: list[NormalizedCustomer]) -> list[NormalizedCustomer]:
    """Merge duplicates by email (then phone), filling missing fields from dupes.

    Rows with no dedupe key (name-only) are passed through untouched.
    """
    merged: dict[str, NormalizedCustomer] = {}
    passthrough: list[NormalizedCustomer] = []

    for cust in customers:
        key = cust.dedupe_key
        if key is None:
            passthrough.append(cust)
            continue
        if key not in merged:
            merged[key] = cust.model_copy(deep=True)
            continue
        existing = merged[key]
        for fld in ("first_name", "last_name", "email", "phone", "external_id", "created_at"):
            if getattr(existing, fld) is None and getattr(cust, fld) is not None:
                setattr(existing, fld, getattr(cust, fld))

    return list(merged.values()) + passthrough


def template_csv() -> str:
    """The downloadable template we hand owners during onboarding."""
    return (
        "first_name,last_name,email,phone,join_date,last_visit,total_spent\n"
        "Jordan,Lee,jordan@example.com,555-0100,2024-03-01,2025-12-20,840.00\n"
        "Sam,Rivera,sam@example.com,555-0101,2023-08-15,2026-06-01,1290.50\n"
    )


class CSVAdapter(DataSourceAdapter):
    """Adapter wrapping an uploaded CSV blob."""

    source = SOURCE

    def __init__(self, content: str | None = None) -> None:
        self._content = content
        self._parsed: SyncResult | None = None

    async def connect(self, auth_payload: dict) -> None:
        content = auth_payload.get("content")
        if content is None:
            content = self._content
        if not content:
            raise IntegrationError("No CSV content provided")
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig")
        self._content = content
        self._parsed = parse_csv(content)

    def _ensure_parsed(self) -> SyncResult:
        if self._parsed is None:
            if not self._content:
                raise IntegrationError("connect() must be called before sync")
            self._parsed = parse_csv(self._content)
        return self._parsed

    async def sync_customers(self, since: datetime | None = None) -> list[NormalizedCustomer]:
        return dedupe_customers(self._ensure_parsed().customers)

    async def sync_transactions(
        self, since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        return self._ensure_parsed().transactions

    async def sync_visits(self, since: datetime | None = None) -> list[NormalizedVisit]:
        return self._ensure_parsed().visits
