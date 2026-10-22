"""Owner-driven campaign shapes: build, review, approve, measure.

Separate from ``schemas/api.py``, which carries the single-shot
``/campaigns/generate`` contract the dashboard already uses. These are the
persisted-campaign payloads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    channel: Literal["email", "sms"] = "email"
    # Row ids from the dashboard's customer list (CustomerRisk.db_customer_id).
    customer_ids: list[str] = Field(min_length=1, max_length=500)
    incentive: str | None = Field(default=None, max_length=255)
    tone: str | None = Field(default=None, max_length=255)
    ab_test: bool = False
    # Only meaningful with ab_test; varies the offer rather than just the copy.
    variant_b_incentive: str | None = Field(default=None, max_length=255)


class CampaignSendSummary(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    channel: str
    subject: str | None
    body: str
    status: str
    generated_by: str
    variant: str | None
    sent_at: str | None
    failure_reason: str | None
    opened: bool = False
    clicked: bool = False


class CampaignStats(BaseModel):
    total: int
    pending: int
    sent: int
    failed: int
    skipped: int
    opened: int
    clicked: int
    recovered: int
    revenue_recovered: float


class CampaignOut(BaseModel):
    id: str
    name: str
    channel: str
    status: str
    incentive: str | None
    ab_test: bool
    variant_b_incentive: str | None
    created_at: str
    stats: CampaignStats


class CampaignDetailOut(CampaignOut):
    sends: list[CampaignSendSummary]
    # Customers that were left out at build time, keyed by id, with a reason.
    skipped: dict[str, str] = {}


class SendEditIn(BaseModel):
    subject: str | None = Field(default=None, max_length=512)
    body: str | None = None


class ApprovalSummaryOut(BaseModel):
    sent: int
    failed: int
    deferred: int
    skipped: dict[str, int]


class ArmResultOut(BaseModel):
    variant: str
    sent: int
    recovered: int
    recovery_rate: float
    revenue_recovered: float


class ExperimentOut(BaseModel):
    a: ArmResultOut
    b: ArmResultOut
    lift_pp: float
    confident: bool
    verdict: str
    winner: str | None


class GenerationLogOut(BaseModel):
    id: str
    purpose: str
    model: str | None
    generated_by: str
    attempts: int
    latency_ms: int | None
    error: str | None
    created_at: str
    system_prompt: str
    user_prompt: str
    raw_output: str | None
    campaign_send_id: str | None


class AuditLogOut(BaseModel):
    id: str
    action: str
    actor_email: str | None
    subject_type: str | None
    subject_id: str | None
    summary: str
    created_at: str
