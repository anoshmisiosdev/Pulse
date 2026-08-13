"""Normalized provider payload shared by visitor identity adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class NormalizedVisitorSignal:
    provider: str
    provider_key: str
    seen_at: datetime
    captured_url: str
    referrer: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None
    business_email: str | None = None
    company_name: str | None = None
    company_website: str | None = None
    company_domain: str | None = None
    industry: str | None = None
    employee_count: str | None = None
    estimated_revenue: str | None = None
    city: str | None = None
    state: str | None = None
    zipcode: str | None = None
    tags: list[str] = field(default_factory=list)
    repeat_visitor: bool = False


class VisitorProviderAdapter(Protocol):
    name: str

    def normalize(self, payload: dict[str, Any]) -> NormalizedVisitorSignal: ...
