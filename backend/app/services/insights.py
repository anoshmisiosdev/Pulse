"""Retention analytics: cohorts, score explainability, and segments.

The computational core is pure functions over plain inputs — same discipline as
``scoring/engine.py`` — so the cohort maths can be tested with literal dates
rather than a seeded database.

A note on what these numbers are and aren't. A fitness studio with 300 members
has enough history for a cohort curve to mean something; a med spa with 40
clients on a five-month visit cycle does not, and a retention chart drawn from
four people per cohort is a decorative lie. So cohorts carry their own size and
the API marks the thin ones, rather than letting a confident-looking line
imply precision the data can't support.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Visit
from app.scoring.config import get_vertical_config
from app.services.activity import ScoredCustomer

# A cohort smaller than this is reported but flagged: the percentages are real,
# they just aren't evidence of anything.
MIN_MEANINGFUL_COHORT = 10

# Months of cohort history. Two years is long enough to see a seasonal pattern
# and short enough that the grid stays readable on a laptop.
MAX_COHORT_MONTHS = 24


def _month_key(value: date | datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_index(key: str) -> int:
    """Months since year 0, so two keys can be subtracted."""
    year, month = key.split("-")
    return int(year) * 12 + int(month) - 1


@dataclass
class Cohort:
    """One acquisition month and how much of it was still visiting later."""

    cohort_month: str
    size: int
    # offset in months -> number of that cohort who visited in that month
    active_by_offset: dict[int, int] = field(default_factory=dict)

    @property
    def meaningful(self) -> bool:
        return self.size >= MIN_MEANINGFUL_COHORT

    def retention_at(self, offset: int) -> float:
        if not self.size:
            return 0.0
        return round(self.active_by_offset.get(offset, 0) / self.size, 4)


def build_cohorts(
    first_visit_by_customer: dict[str, date],
    visit_months_by_customer: dict[str, set[str]],
    *,
    max_months: int = MAX_COHORT_MONTHS,
) -> list[Cohort]:
    """Group customers by acquisition month and count later activity.

    Pure. ``first_visit_by_customer`` maps customer id to the date of their
    first visit; ``visit_months_by_customer`` maps customer id to every
    ``YYYY-MM`` they visited in.

    Offset 0 is the acquisition month itself, so it is always 100% by
    construction — included deliberately, because a chart that starts at
    month 1 reads as though the first month had unexplained churn.
    """
    by_cohort: dict[str, list[str]] = defaultdict(list)
    for customer_id, first in first_visit_by_customer.items():
        by_cohort[_month_key(first)].append(customer_id)

    cohorts: list[Cohort] = []
    for month in sorted(by_cohort, reverse=True)[:max_months]:
        members = by_cohort[month]
        cohort = Cohort(cohort_month=month, size=len(members))
        base = _month_index(month)
        for customer_id in members:
            for visited in visit_months_by_customer.get(customer_id, ()):  # noqa: B007
                offset = _month_index(visited) - base
                if offset < 0:
                    continue
                cohort.active_by_offset[offset] = cohort.active_by_offset.get(offset, 0) + 1
        cohorts.append(cohort)
    return sorted(cohorts, key=lambda c: c.cohort_month)


async def load_cohorts(
    db: AsyncSession, *, business_id: str, max_months: int = MAX_COHORT_MONTHS
) -> list[Cohort]:
    """Read visit history and build the cohort grid."""
    bid = uuid.UUID(business_id)
    rows = (
        await db.execute(
            select(Visit.customer_id, Visit.occurred_at)
            .join(Customer, Customer.id == Visit.customer_id)
            .where(Visit.business_id == bid, Visit.customer_id.is_not(None))
        )
    ).all()

    first_visit: dict[str, date] = {}
    months: dict[str, set[str]] = defaultdict(set)
    for customer_id, occurred_at in rows:
        if occurred_at is None:
            continue
        key = str(customer_id)
        occurred = occurred_at.date() if isinstance(occurred_at, datetime) else occurred_at
        if key not in first_visit or occurred < first_visit[key]:
            first_visit[key] = occurred
        months[key].add(_month_key(occurred))

    return build_cohorts(first_visit, months, max_months=max_months)


# -- Score explainability -----------------------------------------------------


@dataclass
class ScoreFactor:
    """One contributor to a risk score, with the points it added."""

    key: str
    label: str
    # Points on the 0-100 scale this factor contributed.
    points: float
    share: float  # 0..1 of the score this factor accounts for
    # The raw signal risk, 0 = healthy, 1 = maximally at risk. None for the
    # additive lifecycle flags, which aren't signals.
    risk: float | None
    detail: str


_SIGNAL_LABELS = {
    "recency": ("Time since last visit", "How long since they were last in"),
    "frequency": ("Visit frequency", "Whether they're visiting less than they used to"),
    "monetary": ("Spending", "Whether their spend is falling off"),
    "engagement": ("Email engagement", "Whether they're still opening what you send"),
}


def explain_score(scored: ScoredCustomer, vertical: str = "other") -> list[ScoreFactor]:
    """Break a score into the contributions that produced it.

    ``reasons`` is already the product's first-class explanation and is what
    owners read. This adds the *relative weight* behind those reasons, which is
    what a drill-down chart needs: "away 34 days" and "spend down 60%" can both
    appear as reasons, and an owner deciding where to spend an hour benefits
    from knowing which one actually moved the number.

    The arithmetic mirrors ``scoring/engine.score_customer`` exactly rather
    than approximating it: contributions come from ``ScoreResult.signals``
    (the raw per-signal risk the engine recorded) multiplied by that
    vertical's configured weight, renormalized over the signals that had data —
    which is precisely how the engine redistributes weight for a customer with
    thin history. The lifecycle boosts are added as their own factors because
    the engine adds them to the score after weighting, not as signals.

    Consequence worth knowing: these factors sum to the pre-clamp score. For a
    customer whose boosts pushed them past 100, the shares are computed against
    the clamped score the owner sees, so they can sum to slightly over 1.
    """
    cfg = get_vertical_config(vertical)
    signals = scored.result.signals or {}
    factors: list[ScoreFactor] = []

    present = {k: v for k, v in signals.items() if v is not None}
    weight_of = {
        "recency": cfg.weights.recency,
        "frequency": cfg.weights.frequency,
        "monetary": cfg.weights.monetary,
        "engagement": cfg.weights.engagement,
    }
    total_weight = sum(weight_of.get(k, 0.0) for k in present)

    score = max(1, scored.result.score)
    days = scored.days_since_last_visit

    for key, risk in present.items():
        weight = weight_of.get(key, 0.0)
        if not weight or not total_weight:
            continue
        # Same normalization the engine uses, scaled to 0-100.
        points = round(risk * weight / total_weight * 100.0, 1)
        label, generic = _SIGNAL_LABELS.get(key, (key.title(), key))
        if key == "recency" and days is not None:
            detail = f"{days} days since their last visit"
        elif key == "frequency" and scored.trend_pct < 0:
            detail = f"Visits are down {abs(scored.trend_pct)}% against their own pattern"
        elif key == "frequency":
            detail = "Visiting at or above their usual rate"
        else:
            detail = generic
        factors.append(
            ScoreFactor(
                key=key,
                label=label,
                points=points,
                share=round(points / score, 4),
                risk=round(risk, 3),
                detail=detail,
            )
        )

    # Additive lifecycle flags. The engine adds these after weighting, so they
    # are reported as flat point contributions, not signals.
    if scored.payment_issue:
        points = round(cfg.failed_payment_boost, 1)
        factors.append(
            ScoreFactor(
                key="payment_failure",
                label="Payment problem",
                points=points,
                share=round(points / score, 4),
                risk=None,
                detail="A payment on file failed, or the subscription is set to cancel",
            )
        )

    factors.sort(key=lambda f: f.points, reverse=True)
    return factors


# -- Segments -----------------------------------------------------------------


@dataclass(frozen=True)
class SegmentRule:
    """A named filter over scored customers. Pure predicate, no I/O."""

    key: str
    label: str
    description: str


SEGMENTS: tuple[SegmentRule, ...] = (
    SegmentRule("high_risk", "High risk", "Most likely to stop coming back."),
    SegmentRule(
        "high_value_at_risk",
        "High value at risk",
        "At risk and worth more than the typical customer — call these.",
    ),
    SegmentRule("lapsed_90", "Lapsed 90+ days", "No visit in three months or more."),
    SegmentRule("new_customers", "New customers", "Two or fewer visits so far."),
    SegmentRule("loyal", "Loyal regulars", "Frequent visitors at low risk."),
    SegmentRule("payment_issues", "Payment problems", "A payment failed recently."),
    SegmentRule(
        "contactable_high_risk",
        "High risk and reachable",
        "High risk, with a usable email or phone and no opt-out.",
    ),
)

SEGMENT_KEYS = tuple(s.key for s in SEGMENTS)


def _high_value_cutoff(scored: list[ScoredCustomer]) -> float:
    values = sorted((s.estimated_annual_value for s in scored), reverse=True)
    if not values:
        return 0.0
    # Top quartile, which is how `activity.recommend_action` already decides
    # "worth a phone call" — kept consistent so the segment and the
    # recommendation never disagree about who's valuable.
    index = max(0, len(values) // 4 - 1)
    return values[index]


def apply_segment(
    key: str, scored: list[ScoredCustomer], *, contactable: set[str] | None = None
) -> list[ScoredCustomer]:
    """Filter scored customers by segment. Unknown key returns everything.

    ``contactable`` is the set of customer row ids with a usable channel and no
    opt-out; passed in rather than looked up so this stays pure.
    """
    if key == "high_risk":
        return [s for s in scored if s.result.band == "high"]
    if key == "high_value_at_risk":
        cutoff = _high_value_cutoff(scored)
        return [
            s
            for s in scored
            if s.result.band in ("high", "med") and s.estimated_annual_value >= cutoff
        ]
    if key == "lapsed_90":
        return [
            s
            for s in scored
            if s.days_since_last_visit is not None and s.days_since_last_visit >= 90
        ]
    if key == "new_customers":
        return [s for s in scored if s.visit_count <= 2]
    if key == "loyal":
        return [s for s in scored if s.result.band == "low" and s.visit_count >= 5]
    if key == "payment_issues":
        return [s for s in scored if s.payment_issue]
    if key == "contactable_high_risk":
        allowed = contactable or set()
        return [
            s
            for s in scored
            if s.result.band == "high" and (s.customer.external_id or "") in allowed
        ]
    return list(scored)


async def contactable_ids(db: AsyncSession, *, business_id: str, channel: str) -> set[str]:
    """Row ids reachable on this channel right now, honouring every opt-out."""
    bid = uuid.UUID(business_id)
    rows = (
        (
            await db.execute(
                select(Customer).where(
                    Customer.business_id == bid, Customer.do_not_contact.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )
    out: set[str] = set()
    for row in rows:
        if channel == "sms" and row.phone and not row.unsubscribed_sms:
            out.add(str(row.id))
        elif channel == "email" and row.email and not row.unsubscribed_email:
            out.add(str(row.id))
    return out


# -- CSV export ---------------------------------------------------------------

CSV_COLUMNS = (
    "customer_id",
    "name",
    "email",
    "phone",
    "risk_score",
    "risk_band",
    "reasons",
    "days_since_last_visit",
    "visit_count",
    "total_spend",
    "estimated_annual_value",
    "recommended_action",
)


def to_csv_rows(scored: list[ScoredCustomer]) -> list[list[str]]:
    """Scored customers as CSV cells, header first.

    Reasons are joined with ``" | "`` rather than commas so the column survives
    a naive split in Excel, which is where these files actually get opened.
    """
    rows = [list(CSV_COLUMNS)]
    for s in scored:
        name = (
            f"{s.customer.first_name or ''} {s.customer.last_name or ''}".strip()
            or "Unnamed customer"
        )
        rows.append(
            [
                s.customer.external_id or "",
                name,
                s.customer.email or "",
                s.customer.phone or "",
                str(s.result.score),
                s.result.band,
                " | ".join(s.result.reasons),
                "" if s.days_since_last_visit is None else str(s.days_since_last_visit),
                str(s.visit_count),
                f"{s.total_spend:.2f}",
                f"{s.estimated_annual_value:.2f}",
                s.recommended_action,
            ]
        )
    return rows


def utc_today() -> str:
    return datetime.now(UTC).date().isoformat()
