"""Turn normalized records into scored customers.

Pure (no I/O): groups visits/transactions onto deduped customers, runs the scoring
engine, and estimates revenue-at-risk. This is what powers the onboarding "money
screen" straight from an uploaded CSV — no database required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.integrations.csv_adapter import dedupe_customers
from app.schemas.normalized import (
    NormalizedCustomer,
    SyncResult,
)
from app.scoring import CustomerActivity, ScoreResult, SpendEvent, score_customer


@dataclass
class ScoredCustomer:
    customer: NormalizedCustomer
    result: ScoreResult
    estimated_annual_value: float


@dataclass
class PortfolioSummary:
    total_customers: int
    high_risk: int
    med_risk: int
    low_risk: int
    revenue_at_risk: float  # estimated annual $ tied to high/med-risk customers


def _identifiers(c: NormalizedCustomer) -> list[str]:
    ids = []
    if c.email:
        ids.append("email:" + c.email)
    if c.phone:
        ids.append("phone:" + c.phone)
    if c.external_id:
        ids.append("ext:" + c.external_id)
    return ids


def _event_keys(email: str | None, phone: str | None, external_id: str | None) -> list[str]:
    keys = []
    if email:
        keys.append("email:" + email.strip().lower())
    if phone:
        keys.append("phone:" + "".join(ch for ch in phone if ch.isdigit() or ch == "+"))
    if external_id:
        keys.append("ext:" + external_id)
    return keys


def _estimate_annual_value(spend: list[SpendEvent], visits: list[datetime]) -> float:
    """Transparent annualization of observed spend over the observed window."""
    total = sum(e.amount for e in spend)
    if total <= 0:
        return 0.0
    dates = [e.at for e in spend] + list(visits)
    if len(dates) >= 2:
        span_days = (max(dates) - min(dates)).total_seconds() / 86400.0
        if span_days >= 30:
            return round(total * 365.0 / span_days, 2)
    return round(total, 2)  # too little history to annualize; use observed total


def build_scored_customers(
    sync: SyncResult,
    vertical: str | None = None,
    now: datetime | None = None,
) -> list[ScoredCustomer]:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    customers = dedupe_customers(sync.customers)

    # Map every known identifier -> the index of its deduped customer.
    id_to_idx: dict[str, int] = {}
    for idx, cust in enumerate(customers):
        for ident in _identifiers(cust):
            id_to_idx.setdefault(ident, idx)

    visits_by_idx: dict[int, list[datetime]] = {}
    spend_by_idx: dict[int, list[SpendEvent]] = {}

    def resolve(email, phone, external_id) -> int | None:
        for key in _event_keys(email, phone, external_id):
            if key in id_to_idx:
                return id_to_idx[key]
        return None

    for v in sync.visits:
        idx = resolve(v.customer_email, v.customer_phone, v.customer_external_id)
        if idx is not None:
            visits_by_idx.setdefault(idx, []).append(v.occurred_at)

    for t in sync.transactions:
        idx = resolve(t.customer_email, t.customer_phone, t.customer_external_id)
        if idx is not None:
            spend_by_idx.setdefault(idx, []).append(
                SpendEvent(at=t.occurred_at, amount=float(t.amount))
            )

    scored: list[ScoredCustomer] = []
    for idx, cust in enumerate(customers):
        visits = visits_by_idx.get(idx, [])
        spend = spend_by_idx.get(idx, [])
        activity = CustomerActivity(
            customer_id=cust.dedupe_key or cust.external_id or f"row-{idx}",
            visit_dates=list(visits),
            spend_events=list(spend),
            joined_at=cust.created_at,
        )
        result = score_customer(activity, vertical=vertical, now=now)
        scored.append(
            ScoredCustomer(
                customer=cust,
                result=result,
                estimated_annual_value=_estimate_annual_value(spend, visits),
            )
        )
    return scored


def summarize(scored: list[ScoredCustomer]) -> PortfolioSummary:
    high = [s for s in scored if s.result.band == "high"]
    med = [s for s in scored if s.result.band == "med"]
    low = [s for s in scored if s.result.band == "low"]
    # High-risk counts fully; medium at half — these customers are recoverable but
    # not yet lost. Transparent and easy to explain to an owner.
    at_risk = sum(s.estimated_annual_value for s in high)
    at_risk += 0.5 * sum(s.estimated_annual_value for s in med)
    return PortfolioSummary(
        total_customers=len(scored),
        high_risk=len(high),
        med_risk=len(med),
        low_risk=len(low),
        revenue_at_risk=round(at_risk, 2),
    )
