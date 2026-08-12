"""Normalized types every integration adapter emits.

Downstream code (scoring, campaigns, dashboard) only ever touches these — never a
provider-specific shape. Adding an integration must require zero changes here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_phone(value: str | None) -> str | None:
    """Reduce a phone to digits (keep leading +) for dedupe; cosmetic only."""
    if not value:
        return None
    cleaned = value.strip()
    plus = cleaned.startswith("+")
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return None
    return ("+" + digits) if plus else digits


def _normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


class NormalizedCustomer(BaseModel):
    """A customer as seen by any source, before persistence/dedupe."""

    model_config = ConfigDict(str_strip_whitespace=True)

    external_id: str | None = None
    source: str  # "csv", "square", "stripe", ...
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    created_at: datetime | None = None
    # Optional metadata many POS exports carry — surfaced in outreach ("they love X").
    favorite_item: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _normalize_email(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)

    @property
    def dedupe_key(self) -> str | None:
        """Identity used to merge duplicates, including pseudonymous public data."""
        if self.email or self.phone:
            return self.email or self.phone
        if self.external_id:
            return f"{self.source}:{self.external_id}"
        return None

    @property
    def full_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else (self.email or self.phone or "Unknown")


class NormalizedTransaction(BaseModel):
    external_id: str | None = None
    source: str
    customer_external_id: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    # Net amount recognized as revenue. Failed/fully-refunded payments use 0.
    amount: Decimal
    gross_amount: Decimal | None = None
    refunded_amount: Decimal = Decimal("0")
    currency: str = "USD"
    # completed | partially_refunded | refunded | failed | pending | canceled
    status: str = "completed"
    occurred_at: datetime
    updated_at: datetime | None = None
    failure_code: str | None = None

    @field_validator("customer_email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _normalize_email(v)

    @field_validator("customer_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)

    @property
    def is_revenue(self) -> bool:
        return self.status in {"completed", "partially_refunded"} and self.amount > 0


class NormalizedVisit(BaseModel):
    external_id: str | None = None
    source: str
    customer_external_id: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    occurred_at: datetime

    @field_validator("customer_email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _normalize_email(v)

    @field_validator("customer_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)


class SyncResult(BaseModel):
    """Counts returned by an adapter sync, mirrored into a SyncRun row."""

    customers: list[NormalizedCustomer] = Field(default_factory=list)
    transactions: list[NormalizedTransaction] = Field(default_factory=list)
    visits: list[NormalizedVisit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
