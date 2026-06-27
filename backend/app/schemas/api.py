"""Request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel


class CustomerRisk(BaseModel):
    customer_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    score: int
    band: str
    reasons: list[str]
    estimated_annual_value: float


class PortfolioSummaryOut(BaseModel):
    total_customers: int
    high_risk: int
    med_risk: int
    low_risk: int
    revenue_at_risk: float


class CSVPreviewOut(BaseModel):
    summary: PortfolioSummaryOut
    customers: list[CustomerRisk]
    warnings: list[str] = []


class GenerateCampaignIn(BaseModel):
    business_name: str
    business_type: str = "local business"
    customer_name: str
    channel: str = "email"  # email | sms
    incentive: str | None = None
    risk_reasons: list[str] = []
    history_summary: str = ""
    tone: str = "warm, concise, local small-business"


class GeneratedCopyOut(BaseModel):
    channel: str
    subject: str | None = None
    body: str
    generated_by: str
    model: str | None = None
