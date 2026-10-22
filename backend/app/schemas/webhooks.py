"""Outbound webhook shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EndpointIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    # Empty means every event.
    events: list[str] = Field(default_factory=list, max_length=10)
    description: str | None = Field(default=None, max_length=255)


class EndpointPatch(BaseModel):
    events: list[str] | None = Field(default=None, max_length=10)
    description: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None


class EndpointOut(BaseModel):
    id: str
    url: str
    description: str | None
    events: list[str]
    enabled: bool
    last_success_at: str | None
    last_failure_at: str | None
    consecutive_failures: int
    # True when we switched it off after repeated failures, as opposed to the
    # owner pausing it -- the UI explains which.
    auto_disabled: bool
    created_at: str


class EndpointCreatedOut(BaseModel):
    endpoint: EndpointOut
    # Shown once. Stored encrypted; never returned again.
    secret: str


class DeliveryOut(BaseModel):
    id: str
    event_type: str
    event_id: str
    status: str
    attempts: int
    response_status: int | None
    last_error: str | None
    created_at: str
    delivered_at: str | None
    next_attempt_at: str | None


class TestResultOut(BaseModel):
    delivered: bool
    response_status: int | None
    error: str | None
