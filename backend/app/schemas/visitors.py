"""Public contracts for the platform-admin visitor intelligence surface."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

VisitorStatus = Literal["new", "reviewing", "qualified", "contacted", "dismissed"]
IdentityLevel = Literal["anonymous", "company", "person", "waitlist", "account"]


class VisitorSummaryOut(BaseModel):
    active_24h: int
    unique_visitors: int
    identified_visitors: int
    identification_rate: float
    high_intent: int
    waitlist_conversions: int
    provider_matches: int
    window_days: int


class VisitorListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    primary_email: str | None
    full_name: str | None
    job_title: str | None
    linkedin_url: str | None
    company_name: str | None
    company_domain: str | None
    company_website: str | None
    industry: str | None
    employee_count: str | None
    estimated_revenue: str | None
    city: str | None
    state: str | None
    zipcode: str | None
    identity_level: IdentityLevel
    source_provider: str
    status: VisitorStatus
    intent_score: int
    first_seen_at: datetime
    last_seen_at: datetime
    visit_count: int
    pageview_count: int
    last_path: str | None
    referrer_host: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    tags: list[str]
    waitlist_signup_id: uuid.UUID | None
    authenticated_user_id: str | None
    suppressed: bool


class VisitorEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_name: str
    occurred_at: datetime
    path: str | None
    referrer: str | None
    provider: str
    properties: dict


class VisitorDetailOut(VisitorListItem):
    events: list[VisitorEventOut]


class VisitorListOut(BaseModel):
    items: list[VisitorListItem]
    total: int
    limit: int
    offset: int
    summary: VisitorSummaryOut


class VisitorUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VisitorStatus


class VisitorPilotMetricsOut(BaseModel):
    provider: str
    window_days: int
    deliveries: int
    unique_profiles: int
    person_matches: int
    company_matches: int
    repeat_visitors: int
    high_intent_matches: int
    waitlist_conversions: int
    conversion_rate: float
    monthly_cost_usd: float | None
    cost_per_match_usd: float | None
    recommendation: str


class Rb2bWebhookOut(BaseModel):
    ok: bool = True
    duplicate: bool = False
    visitor_id: uuid.UUID | None = None
