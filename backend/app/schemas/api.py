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
    days_since_last_visit: int | None = None
    last_visit: str | None = None
    visit_count: int = 0
    total_spend: float = 0.0
    segment: str = "regulars"
    pattern: str | None = None
    confidence: str = "medium"
    trend_pct: int = 0
    favorite_item: str | None = None


class PortfolioSummaryOut(BaseModel):
    total_customers: int
    high_risk: int
    med_risk: int
    low_risk: int
    revenue_at_risk: float
    avg_days_away: float = 0.0
    revenue_series: list[dict] = []


class CSVPreviewOut(BaseModel):
    business_name: str = "Your Business"
    vertical: str = "other"
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


# ── Automations (rule engine + SMS/email send history) ──
class AutomationRuleIn(BaseModel):
    name: str
    trigger_band: str = "high"  # low | med | high
    channel: str = "sms"  # sms | email
    incentive: str | None = None
    mode: str = "approve"  # suggest | approve | auto
    cooldown_days: int = 14
    enabled: bool = True


class AutomationRulePatch(BaseModel):
    name: str | None = None
    trigger_band: str | None = None
    channel: str | None = None
    incentive: str | None = None
    mode: str | None = None
    cooldown_days: int | None = None
    enabled: bool | None = None


class AutomationRuleOut(BaseModel):
    id: str
    name: str
    trigger_band: str
    channel: str
    incentive: str | None
    mode: str
    cooldown_days: int
    enabled: bool
    created_at: str


class CampaignSendOut(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    automation_rule_id: str | None
    channel: str
    subject: str | None
    body: str
    status: str
    sent_at: str | None
    failure_reason: str | None
    created_at: str
    opened: bool = False
    clicked: bool = False
    replied: bool = False


class DispatchSummaryOut(BaseModel):
    rules_evaluated: int
    sends_created: int
    skipped: dict[str, int]


# ── RAG knowledge base (grounds campaign generation in the business's own voice) ──
class KnowledgeIn(BaseModel):
    kind: str = "note"  # service | brand_voice | campaign_example | note
    content: str


class KnowledgeOut(BaseModel):
    id: str
    kind: str
    content: str
    created_at: str


# ── auth ── (Supabase issues the session; we only echo the resolved tenant)
class AuthUser(BaseModel):
    user_id: str
    email: str | None = None
    business_id: str
    business_name: str
    role: str = "owner"


# ── integrations / per-tenant portfolio ──
class ConnectIn(BaseModel):
    provider: str  # "stripe" | "square"
    credential: str  # Stripe secret key / Square access token
    environment: str = "production"  # square only: production | sandbox
    vertical: str = "other"
    business_name: str = ""


class ConnectionOut(BaseModel):
    source: str
    status: str
    last_synced_at: str | None = None


class SyncRunOut(BaseModel):
    source: str
    status: str
    customers_synced: int
    transactions_synced: int
    visits_synced: int
    error: str | None = None


class PortfolioOut(CSVPreviewOut):
    # "empty" -> no data yet: frontend routes the owner to /setup.
    status: str = "ready"
    connections: list[ConnectionOut] = []
