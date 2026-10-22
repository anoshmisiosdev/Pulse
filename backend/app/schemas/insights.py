"""Analytics, segment, and digest shapes."""

from __future__ import annotations

from pydantic import BaseModel


class CohortOut(BaseModel):
    cohort_month: str  # YYYY-MM
    size: int
    # False when the cohort is too small for its percentages to mean anything.
    # The UI greys these rows rather than hiding them, so a thin month reads as
    # "not enough data" instead of vanishing.
    meaningful: bool
    # Index is months since acquisition; index 0 is the acquisition month and
    # is always 1.0 by construction.
    retention: list[float]
    active: list[int]


class CohortsOut(BaseModel):
    cohorts: list[CohortOut]
    max_offset: int
    min_meaningful_size: int


class ScoreFactorOut(BaseModel):
    key: str
    label: str
    points: float
    share: float
    risk: float | None
    detail: str


class ScoreExplanationOut(BaseModel):
    customer_id: str
    name: str
    score: int
    band: str
    reasons: list[str]
    recommended_action: str
    action_reason: str
    confidence: str
    factors: list[ScoreFactorOut]


class SegmentDefinitionOut(BaseModel):
    key: str
    label: str
    description: str
    size: int


class SegmentsOut(BaseModel):
    segments: list[SegmentDefinitionOut]


class SegmentPreviewOut(BaseModel):
    key: str
    total: int
    customer_ids: list[str]
    reachable_on_channel: int
    channel: str


class DigestPreviewOut(BaseModel):
    subject: str
    body: str
    generated_by: str
    model: str | None
    window_days: int
    # False when there's nothing worth reporting, in which case the scheduled
    # job sends nothing.
    would_send: bool
    recipients: list[str]
    recovered_count: int
    revenue_recovered: float
    messages_sent: int
    awaiting_approval: int
    high_risk_count: int
    revenue_at_risk: float


class DigestSendOut(BaseModel):
    outcome: str
    message: str
    sent: bool


class LocationSummaryOut(BaseModel):
    location: str
    customers: int
    high_risk: int
    med_risk: int
    low_risk: int
    high_risk_share: float
    revenue_at_risk: float
    annual_value: float


class LocationsOut(BaseModel):
    locations: list[LocationSummaryOut]
    # False when no visit carries a location yet -- the UI says how to get
    # them (connect Square, or add a "location" column to the CSV) instead of
    # showing a single "Unassigned" row that looks like a bug.
    has_location_data: bool
