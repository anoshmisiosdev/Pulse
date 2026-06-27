"""Transparent churn-risk scoring engine.

**Pure functions only — no I/O, no DB, no clock except the injected ``now``.**
This is deliberately a weighted heuristic, not ML: owners must trust the number,
and the per-signal ``reasons`` are a first-class product feature. The public
surface (``score_customer``) is stable enough to swap in an ML model later.

Each signal returns a risk in ``[0, 1]`` (0 = healthy, 1 = maximally at risk) plus
an optional plain-English reason. Signals with no data are skipped and their weight
is redistributed, so a brand-new customer is never punished for missing history.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.scoring.config import VerticalConfig, get_vertical_config


@dataclass
class SpendEvent:
    at: datetime
    amount: float


@dataclass
class CustomerActivity:
    """Everything the engine needs about one customer. Built by the caller from
    normalized data — the engine itself never queries anything."""

    customer_id: str
    visit_dates: list[datetime] = field(default_factory=list)
    spend_events: list[SpendEvent] = field(default_factory=list)
    joined_at: datetime | None = None
    emails_sent_recent: int = 0
    emails_opened_recent: int = 0
    failed_payment: bool = False
    subscription_cancel_at: datetime | None = None


@dataclass
class ScoreResult:
    customer_id: str
    score: int  # 0–100
    band: str  # "low" | "med" | "high"
    reasons: list[str]
    signals: dict[str, float]  # raw per-signal risk, for transparency/debugging


# ── helpers ──────────────────────────────────────────────────────────────────


def _as_naive_utc(dt: datetime) -> datetime:
    """Coerce to naive UTC so mixed tz-aware/naive inputs subtract cleanly."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _median_interval_days(visits: list[datetime], cfg: VerticalConfig) -> float:
    """Median gap between consecutive visits, or the vertical default if we can't
    compute one (fewer than two visits)."""
    if len(visits) < 2:
        return cfg.expected_interval_days
    ordered = sorted(visits)
    gaps = [
        (ordered[i] - ordered[i - 1]).total_seconds() / 86400.0
        for i in range(1, len(ordered))
    ]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return cfg.expected_interval_days
    return max(0.5, statistics.median(gaps))


def _count_between(dates: list[datetime], now: datetime, start_days: float, end_days: float) -> int:
    """Count dates in the window [now - start_days, now - end_days)."""
    lo = now.timestamp() - start_days * 86400
    hi = now.timestamp() - end_days * 86400
    return sum(1 for d in dates if lo <= d.timestamp() < hi)


def _sum_between(
    events: list[SpendEvent], now: datetime, start_days: float, end_days: float
) -> float:
    lo = now.timestamp() - start_days * 86400
    hi = now.timestamp() - end_days * 86400
    return sum(e.amount for e in events if lo <= e.at.timestamp() < hi)


# ── individual signals ───────────────────────────────────────────────────────


def _recency_signal(
    visits: list[datetime], cfg: VerticalConfig, now: datetime
) -> tuple[float | None, str | None]:
    if not visits:
        return 1.0, "No recorded visits yet"

    last = max(visits)
    days_since = (now - last).total_seconds() / 86400.0
    median = _median_interval_days(visits, cfg)
    ratio = days_since / median if median else 0.0

    yellow, red = cfg.recency_yellow_ratio, cfg.recency_red_ratio
    if ratio <= yellow:
        risk = 0.5 * (ratio / yellow)
    elif ratio <= red:
        risk = 0.5 + 0.4 * (ratio - yellow) / (red - yellow)
    else:
        risk = _clamp(0.9 + 0.1 * (ratio - red) / red, 0.0, 1.0)

    reason = None
    if ratio > yellow:
        reason = (
            f"Last visit {int(round(days_since))} days ago — "
            f"{ratio:.1f}× their usual {int(round(median))}-day gap"
        )
    return _clamp(risk), reason


def _frequency_signal(
    visits: list[datetime], now: datetime
) -> tuple[float | None, str | None]:
    """Visits in the last 30d vs the trailing 90d monthly average."""
    recent = _count_between(visits, now, 30, 0)
    prior = _count_between(visits, now, 120, 30)  # 90-day trailing window
    # Need enough visits to read a 30-day trend. This also disables the signal for
    # naturally low-cadence verticals (med spa), where a short window is noise.
    if prior < 3:
        return None, None
    prior_monthly = prior / 3.0
    if prior_monthly <= 0:
        return None, None
    trend = recent / prior_monthly
    risk = _clamp(1.0 - trend)
    reason = None
    if trend < 0.6:
        reason = (
            f"Visits dropped to {recent} in the last month vs "
            f"~{prior_monthly:.1f}/month before"
        )
    return risk, reason


def _monetary_signal(
    spend: list[SpendEvent], now: datetime
) -> tuple[float | None, str | None]:
    """Spend in the last 90d vs the prior 90d."""
    recent = _sum_between(spend, now, 90, 0)
    prior = _sum_between(spend, now, 180, 90)
    if prior <= 0:
        return None, None
    trend = recent / prior
    risk = _clamp(1.0 - trend)
    reason = None
    if trend < 0.7:
        drop = int(round((1.0 - trend) * 100))
        reason = f"Spend down {drop}% vs the prior quarter"
    return risk, reason


def _engagement_signal(
    sent: int, opened: int
) -> tuple[float | None, str | None]:
    if sent < 3:
        return None, None  # too little signal to read
    open_rate = opened / sent
    risk = _clamp(1.0 - open_rate)
    reason = None
    if open_rate <= 0.2:
        reason = f"Email engagement fading — opened {opened} of last {sent}"
    return risk, reason


# ── public entry point ───────────────────────────────────────────────────────


def score_customer(
    activity: CustomerActivity,
    vertical: str | VerticalConfig | None = None,
    now: datetime | None = None,
) -> ScoreResult:
    """Score one customer. ``vertical`` may be a name or a ``VerticalConfig``."""
    cfg = vertical if isinstance(vertical, VerticalConfig) else get_vertical_config(vertical)
    now = _as_naive_utc(now) if now else datetime.now(UTC).replace(tzinfo=None)

    visits = [_as_naive_utc(v) for v in activity.visit_dates]
    spend = [SpendEvent(_as_naive_utc(e.at), e.amount) for e in activity.spend_events]

    weighted: list[tuple[float, float]] = []  # (risk, weight)
    reasons: list[str] = []
    signals: dict[str, float] = {}

    for key, weight, (risk, reason) in (
        ("recency", cfg.weights.recency, _recency_signal(visits, cfg, now)),
        ("frequency", cfg.weights.frequency, _frequency_signal(visits, now)),
        ("monetary", cfg.weights.monetary, _monetary_signal(spend, now)),
        (
            "engagement",
            cfg.weights.engagement,
            _engagement_signal(activity.emails_sent_recent, activity.emails_opened_recent),
        ),
    ):
        if risk is None:
            continue
        signals[key] = round(risk, 3)
        weighted.append((risk, weight))
        if reason:
            reasons.append(reason)

    total_weight = sum(w for _, w in weighted)
    base = (sum(r * w for r, w in weighted) / total_weight) if total_weight else 0.0
    score = base * 100.0

    # ── situational lifecycle adjustments ───────────────────────────────────
    is_new = False
    if activity.joined_at is not None:
        tenure_days = (now - _as_naive_utc(activity.joined_at)).total_seconds() / 86400.0
        is_new = tenure_days < cfg.new_customer_days
        if is_new:
            reasons.append(f"New customer — joined {int(round(tenure_days))} days ago")

    if activity.failed_payment:
        score += cfg.failed_payment_boost
        reasons.append("Payment on file failed")
    if activity.subscription_cancel_at is not None:
        score += cfg.cancel_pending_boost
        reasons.append("Subscription is set to cancel")

    score = _clamp(score, 0.0, 100.0)
    score_int = int(round(score))

    if score >= cfg.band_high:
        band = "high"
    elif score >= cfg.band_med:
        band = "med"
    else:
        band = "low"

    # A new customer with thin history shouldn't be screamed about on recency
    # alone — cap the band unless a hard lifecycle flag justifies it.
    if is_new and band == "high" and not (
        activity.failed_payment or activity.subscription_cancel_at
    ):
        band = "med"

    if not reasons:
        reasons.append("Healthy — visiting on their normal cadence")

    return ScoreResult(
        customer_id=activity.customer_id,
        score=score_int,
        band=band,
        reasons=reasons,
        signals=signals,
    )
