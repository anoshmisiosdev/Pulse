"""Recovery attribution: did the outreach we sent actually bring anyone back?

This is the half of the product loop that was missing — ``RecoveryAttribution``
existed as a table that nothing ever wrote, so "3 customers recovered, ~$640
saved" was a number the frontend invented and forgot on refresh.

Two layers, same split as ``scoring/`` and ``services/activity.py``:

* :func:`match_recoveries` is **pure** — plain dataclasses in, matches out, no
  DB, no clock. All the judgement calls live here so they're unit-testable.
* :func:`detect_recoveries` does the I/O: load a tenant's sends and returns,
  run the matcher, write ``RecoveryAttribution`` rows.

The attribution rule is deliberately conservative and stated in one sentence,
because an owner will eventually ask us to defend it:

    **A customer counts as recovered if they visited or purchased after we
    contacted them, within their vertical's attribution window. Credit goes to
    the most recent message sent before that return (last touch), and the
    revenue recovered is what they actually spent inside that window — never an
    annualized projection.**

Consequences worth knowing:

* One recovery per customer. ``Customer.recovered`` is a boolean and a customer
  who lapses again later is a new story, not a second win on the same send.
* We under-claim rather than over-claim. A customer who was always going to come
  back gets credited to us (there is no control group yet — see the experiment
  engine discussion in the spec review), but we never credit revenue we didn't
  observe, and never credit a return that predates the send.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Business,
    CampaignSend,
    Customer,
    RecoveryAttribution,
    Transaction,
    Visit,
)
from app.scoring.config import get_vertical_config
from app.services.ingest import _uuid

logger = logging.getLogger("pulse.attribution")

# Only outreach that actually left the building can earn credit. "pending" is
# awaiting approval, "skipped"/"failed" never reached the customer.
CREDITABLE_SEND_STATUSES = ("sent", "delivered")


# ── pure core ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SendRecord:
    """One piece of outreach that reached a customer."""

    send_id: str
    customer_id: str
    sent_at: datetime


@dataclass(frozen=True)
class ReturnEvent:
    """A visit or purchase. ``amount`` is 0.0 for a visit with no recorded spend
    (some POS exports have door-scans but no ticket)."""

    customer_id: str
    occurred_at: datetime
    amount: float = 0.0


@dataclass(frozen=True)
class RecoveryMatch:
    send_id: str
    customer_id: str
    recovered_at: datetime
    revenue_recovered: float


@dataclass
class RecoverySummary:
    recoveries_found: int = 0
    revenue_recovered: float = 0.0
    sends_considered: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _naive(dt: datetime) -> datetime:
    """Coerce to naive UTC. Postgres hands back tz-aware datetimes and SQLite
    (tests) hands back naive ones; mixing them raises on subtraction."""
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _group(items, key):
    out: dict[str, list] = {}
    for item in items:
        out.setdefault(key(item), []).append(item)
    return out


def match_recoveries(
    sends: list[SendRecord],
    returns: list[ReturnEvent],
    window_days: int,
    already_recovered: frozenset[str] = frozenset(),
) -> list[RecoveryMatch]:
    """Match returns back to the outreach that plausibly caused them.

    ``already_recovered`` is the set of customer ids that have been credited
    before — passing it makes this idempotent, so re-running never double-counts.
    """
    window = timedelta(days=window_days)
    sends_by_customer = _group(sends, lambda s: s.customer_id)
    returns_by_customer = _group(returns, lambda r: r.customer_id)

    matches: list[RecoveryMatch] = []
    for customer_id, customer_sends in sends_by_customer.items():
        if customer_id in already_recovered:
            continue
        customer_returns = sorted(
            returns_by_customer.get(customer_id, []), key=lambda r: _naive(r.occurred_at)
        )
        if not customer_returns:
            continue
        ordered_sends = sorted(customer_sends, key=lambda s: _naive(s.sent_at))

        for event in customer_returns:
            at = _naive(event.occurred_at)
            # Last touch: the most recent send that this return could answer.
            credited = None
            for send in ordered_sends:
                sent_at = _naive(send.sent_at)
                if sent_at < at <= sent_at + window:
                    credited = send
            if credited is None:
                continue  # a return outside every window — coincidence, not recovery

            sent_at = _naive(credited.sent_at)
            revenue = sum(
                r.amount
                for r in customer_returns
                if sent_at < _naive(r.occurred_at) <= sent_at + window
            )
            matches.append(
                RecoveryMatch(
                    send_id=credited.send_id,
                    customer_id=customer_id,
                    recovered_at=at,
                    revenue_recovered=round(revenue, 2),
                )
            )
            break  # one recovery per customer

    return matches


# ── I/O wrapper ──────────────────────────────────────────────────────────────


async def detect_recoveries(
    db: AsyncSession, business_id: str, now: datetime | None = None
) -> RecoverySummary:
    """Find and persist new recoveries for one tenant.

    Safe to run as often as you like: existing attributions are loaded up front
    and their customers are excluded from matching. Caller commits (the Celery
    task and the manual endpoint both do), matching how
    ``services/automations.dispatch_automations`` behaves.
    """
    summary = RecoverySummary()
    bid = _uuid(business_id)
    now = _naive(now) if now else datetime.now(UTC).replace(tzinfo=None)

    biz = await db.get(Business, bid)
    if biz is None:
        return summary
    window_days = get_vertical_config(biz.vertical).attribution_window_days

    send_rows = (
        (
            await db.execute(
                select(CampaignSend).where(
                    CampaignSend.business_id == bid,
                    CampaignSend.status.in_(CREDITABLE_SEND_STATUSES),
                    CampaignSend.sent_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    summary.sends_considered = len(send_rows)
    if not send_rows:
        return summary

    sends = [
        SendRecord(
            send_id=str(row.id),
            customer_id=str(row.customer_id),
            sent_at=row.sent_at,  # not-null guaranteed by the query above
        )
        for row in send_rows
    ]
    contacted = {row.customer_id for row in send_rows}

    already_recovered = frozenset(
        str(cid)
        for cid in (
            await db.execute(
                select(RecoveryAttribution.customer_id).where(
                    RecoveryAttribution.business_id == bid
                )
            )
        )
        .scalars()
        .all()
    )

    # Only load activity for customers we actually contacted — a tenant can have
    # thousands of customers and a handful of sends, and nobody we didn't write to
    # can possibly be a recovery.
    visits = (
        await db.execute(
            select(Visit.customer_id, Visit.occurred_at).where(
                Visit.business_id == bid, Visit.customer_id.in_(contacted)
            )
        )
    ).all()
    transactions = (
        await db.execute(
            select(Transaction.customer_id, Transaction.occurred_at, Transaction.amount).where(
                Transaction.business_id == bid, Transaction.customer_id.in_(contacted)
            )
        )
    ).all()

    returns: list[ReturnEvent] = [
        ReturnEvent(customer_id=str(cid), occurred_at=at) for cid, at in visits
    ]
    returns += [
        ReturnEvent(customer_id=str(cid), occurred_at=at, amount=float(amount))
        for cid, at, amount in transactions
    ]

    matches = match_recoveries(sends, returns, window_days, already_recovered)

    for match in matches:
        if _naive(match.recovered_at) > now:
            summary.skip("future_dated")  # clock skew / bad import; don't credit it
            continue
        db.add(
            RecoveryAttribution(
                business_id=bid,
                customer_id=_uuid(match.customer_id),
                campaign_send_id=_uuid(match.send_id),
                estimated_value=round(match.revenue_recovered, 2),
                recovered_at=match.recovered_at,
            )
        )
        customer = await db.get(Customer, _uuid(match.customer_id))
        if customer is not None:
            customer.recovered = True
        summary.recoveries_found += 1
        summary.revenue_recovered += match.revenue_recovered

    summary.revenue_recovered = round(summary.revenue_recovered, 2)
    await db.flush()
    if summary.recoveries_found:
        logger.info(
            "attributed %d recoveries worth %.2f for business %s",
            summary.recoveries_found,
            summary.revenue_recovered,
            business_id,
        )
    return summary


@dataclass
class RecoveryTotals:
    """What the dashboard's "Revenue retained" tile reads."""

    recovered_count: int = 0
    revenue_recovered: float = 0.0


async def recovery_totals(db: AsyncSession, business_id: str) -> RecoveryTotals:
    """All-time recovered count + observed revenue for one tenant."""
    rows = (
        (
            await db.execute(
                select(RecoveryAttribution.estimated_value).where(
                    RecoveryAttribution.business_id == _uuid(business_id)
                )
            )
        )
        .scalars()
        .all()
    )
    return RecoveryTotals(
        recovered_count=len(rows),
        revenue_recovered=round(sum(float(v or 0) for v in rows), 2),
    )
