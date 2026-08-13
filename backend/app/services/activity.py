"""Turn normalized records into scored, dashboard-ready customers.

Pure (no I/O): groups visits/transactions onto deduped customers, runs the scoring
engine, and derives the presentation fields the UI needs (segment, days-since,
trend, churn pattern, confidence) plus portfolio aggregates. Powers the onboarding
"money screen" and the full dashboard straight from a CSV — no database required.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.integrations.csv_adapter import dedupe_customers
from app.schemas.normalized import NormalizedCustomer, SyncResult
from app.scoring import CustomerActivity, ScoreResult, SpendEvent, score_customer

# Five health segments shown in the dashboard donut + customer DB tabs.
SEGMENTS = ("needs_attention", "slipping_away", "keep_an_eye_on", "regulars", "new")
# Churn patterns shown in "Why They Leave".
PATTERNS = ("fading_away", "stopped_suddenly", "group_left", "not_enough_data")
# What we think the owner should actually *do*, in escalation order. Not every
# at-risk customer wants an email: the owner's time is the scarcest resource, so
# spend it on the ones where a phone call pays for itself and explicitly tell them
# who to leave alone.
ACTIONS = ("wait", "watch", "welcome", "email", "offer", "owner_call")


@dataclass
class ScoredCustomer:
    customer: NormalizedCustomer
    result: ScoreResult
    estimated_annual_value: float
    days_since_last_visit: int | None
    last_visit: str | None  # ISO date
    visit_count: int
    total_spend: float
    segment: str
    pattern: str | None
    confidence: str
    trend_pct: int  # negative = declining
    # Set in a second pass by build_scored_customers — "owner_call" is relative to
    # the rest of the portfolio, so it can't be decided one customer at a time.
    recommended_action: str = "email"
    action_reason: str = ""


@dataclass
class PortfolioSummary:
    total_customers: int
    high_risk: int
    med_risk: int
    low_risk: int
    revenue_at_risk: float
    avg_days_away: float
    revenue_series: list[dict] = field(default_factory=list)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


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


def _median_interval(visits: list[datetime]) -> float | None:
    if len(visits) < 2:
        return None
    ordered = sorted(visits)
    gaps = [
        (ordered[i] - ordered[i - 1]).total_seconds() / 86400.0 for i in range(1, len(ordered))
    ]
    gaps = [g for g in gaps if g > 0]
    return statistics.median(gaps) if gaps else None


def _estimate_annual_value(spend: list[SpendEvent], visits: list[datetime]) -> float:
    total = sum(e.amount for e in spend)
    if total <= 0:
        return 0.0
    dates = [e.at for e in spend] + list(visits)
    if len(dates) >= 2:
        span_days = (max(dates) - min(dates)).total_seconds() / 86400.0
        if span_days >= 30:
            return round(total * 365.0 / span_days, 2)
    return round(total, 2)


def _segment(score: int, is_new: bool) -> str:
    if is_new:
        return "new"
    if score >= 80:
        return "needs_attention"
    if score >= 60:
        return "slipping_away"
    if score >= 40:
        return "keep_an_eye_on"
    return "regulars"


def _trend_pct(visits: list[datetime], now: datetime, median: float | None) -> int:
    """Approximate visit-frequency change, recent month vs. prior trailing quarter."""
    recent = sum(1 for d in visits if (now - d).days <= 30)
    prior = sum(1 for d in visits if 30 < (now - d).days <= 120)
    if prior >= 3:
        ratio = recent / (prior / 3.0)
        return max(-95, min(50, round((ratio - 1) * 100)))
    # Fall back to recency: how far past their usual cadence are they?
    if median and visits:
        days_since = (now - max(visits)).days
        over = days_since / median
        return max(-95, -round(min(95, max(0, (over - 1) * 45))))
    return 0


def _pattern(
    segment: str, visits: list[datetime], now: datetime, median: float | None
) -> str | None:
    if segment == "regulars":
        return None
    if segment == "new":
        return "not_enough_data"
    recent = sum(1 for d in visits if (now - d).days <= 30)
    days_since = (now - max(visits)).days if visits else 999
    if recent == 0 and median and median < 10 and len(visits) >= 4:
        return "stopped_suddenly"
    if median and days_since > 2.5 * median:
        return "fading_away"
    return "group_left"


def _confidence(visit_count: int) -> str:
    if visit_count >= 6:
        return "high"
    if visit_count >= 2:
        return "medium"
    return "low"


def _high_value_threshold(values: list[float]) -> float:
    """75th percentile of annual value, used to decide who is worth the owner's
    own phone call. Relative to *this* portfolio on purpose — "high value" at a
    corner cafe and at a med spa are different numbers, and hardcoding one would
    be wrong for everybody."""
    positive = sorted(v for v in values if v > 0)
    if not positive:
        return 0.0
    return positive[int(0.75 * (len(positive) - 1))]


def recommend_action(scored: ScoredCustomer, high_value_threshold: float) -> tuple[str, str]:
    """Pick the single next action for one customer. Returns ``(action, reason)``.

    Pure and deterministic — no LLM. The reason is shown to the owner verbatim, so
    it must cite real numbers from this customer's record (same rule as the scoring
    engine's ``reasons``): never a generic platitude, never an invented fact.

    First match wins; ordering encodes the product opinion.
    """
    band = scored.result.band
    value = scored.estimated_annual_value
    days = scored.days_since_last_visit

    if band == "low":
        return "wait", "Visiting on their normal cadence — no outreach needed right now."

    if scored.segment == "new":
        return (
            "welcome",
            f"Joined recently with {scored.visit_count} "
            f"visit{'s' if scored.visit_count != 1 else ''} so far — a warm welcome "
            "beats a win-back offer.",
        )

    # Genuinely no evidence: a single visit row *and* no recorded spend. Note this
    # deliberately does NOT fire on thin visit history alone — an aggregate CSV
    # (the main onboarding path) synthesizes exactly one visit per customer from
    # their last_visit date, yet still carries tenure and lifetime spend. Gating on
    # visit_count alone marked every customer from an uploaded CSV "just watch",
    # which is the whole portfolio for most new accounts.
    if scored.visit_count < 2 and scored.total_spend <= 0:
        return (
            "watch",
            "One recorded visit and no spend on file, so the risk score is a guess — "
            "worth watching, not worth spending an offer on.",
        )

    if band == "high" and high_value_threshold > 0 and value >= high_value_threshold:
        away = f"{days} days" if days is not None else "a while"
        return (
            "owner_call",
            f"Worth about ${value:,.0f}/yr and away {away} — one of your most "
            "valuable at-risk customers. A call from you personally will land "
            "better than an email.",
        )

    monetary_risk = scored.result.signals.get("monetary", 0.0)
    if monetary_risk >= 0.5:
        return (
            "offer",
            f"Still coming in, but spending {int(round(monetary_risk * 100))}% less "
            "than they used to — a small incentive is the cheapest way to reset that.",
        )

    away = f"{days} days" if days is not None else "longer than usual"
    return (
        "email",
        f"Away {away} with no other complicating signal — a personal win-back "
        "email is the right first touch.",
    )


def build_scored_customers(
    sync: SyncResult, vertical: str | None = None, now: datetime | None = None
) -> list[ScoredCustomer]:
    now = _naive(now) if now else datetime.now(UTC).replace(tzinfo=None)
    customers = dedupe_customers(sync.customers)

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
            visits_by_idx.setdefault(idx, []).append(_naive(v.occurred_at))
    for t in sync.transactions:
        idx = resolve(t.customer_email, t.customer_phone, t.customer_external_id)
        if idx is not None:
            spend_by_idx.setdefault(idx, []).append(
                SpendEvent(at=_naive(t.occurred_at), amount=float(t.amount))
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

        is_new = any("New customer" in r for r in result.reasons)
        median = _median_interval(visits)
        days_since = (now - max(visits)).days if visits else None
        segment = _segment(result.score, is_new)
        scored.append(
            ScoredCustomer(
                customer=cust,
                result=result,
                estimated_annual_value=_estimate_annual_value(spend, visits),
                days_since_last_visit=days_since,
                last_visit=max(visits).date().isoformat() if visits else None,
                visit_count=len(visits),
                total_spend=round(sum(e.amount for e in spend), 2),
                segment=segment,
                pattern=_pattern(segment, visits, now, median),
                confidence=_confidence(len(visits)),
                trend_pct=_trend_pct(visits, now, median),
            )
        )

    # Second pass: "worth the owner's own call" is a portfolio-relative judgement.
    threshold = _high_value_threshold([s.estimated_annual_value for s in scored])
    for s in scored:
        s.recommended_action, s.action_reason = recommend_action(s, threshold)
    return scored


def monthly_revenue_series(
    sync: SyncResult, now: datetime | None = None, months: int = 12
) -> list[dict]:
    """Total spend per calendar month over the trailing window — Revenue Over Time."""
    now = _naive(now) if now else datetime.now(UTC).replace(tzinfo=None)
    buckets: dict[str, float] = {}
    order: list[str] = []
    for m in range(months - 1, -1, -1):
        year = now.year
        month = now.month - m
        while month <= 0:
            month += 12
            year -= 1
        label = datetime(year, month, 1).strftime("%b %y")
        buckets[label] = 0.0
        order.append(label)
    for t in sync.transactions:
        at = _naive(t.occurred_at)
        label = at.strftime("%b %y")
        if label in buckets:
            buckets[label] += float(t.amount)
    return [{"month": label, "amount": round(buckets[label], 2)} for label in order]


def summarize(
    scored: list[ScoredCustomer], revenue_series: list[dict] | None = None
) -> PortfolioSummary:
    high = [s for s in scored if s.result.band == "high"]
    med = [s for s in scored if s.result.band == "med"]
    low = [s for s in scored if s.result.band == "low"]
    at_risk = sum(s.estimated_annual_value for s in high)
    at_risk += 0.5 * sum(s.estimated_annual_value for s in med)
    days = [s.days_since_last_visit for s in scored if s.days_since_last_visit is not None]
    return PortfolioSummary(
        total_customers=len(scored),
        high_risk=len(high),
        med_risk=len(med),
        low_risk=len(low),
        revenue_at_risk=round(at_risk, 2),
        avg_days_away=round(statistics.mean(days), 1) if days else 0.0,
        revenue_series=revenue_series or [],
    )
