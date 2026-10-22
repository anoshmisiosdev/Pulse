"""Reading and writing the one ``Subscription`` row per business.

Kept apart from ``service.py`` so the parts that touch the database don't also
need Stripe importable: the dashboard asks "what plan am I on?" on every page
load, and that question must be answerable with Stripe entirely offline.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.limits import Entitlements, evaluate
from app.billing.tiers import TRIAL_DAYS
from app.models import Customer, IntegrationConnection, Subscription

logger = logging.getLogger("pulse.billing.store")


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


async def get_subscription(db: AsyncSession, *, business_id: str) -> Subscription | None:
    result = await db.execute(
        select(Subscription).where(Subscription.business_id == _uuid(business_id))
    )
    return result.scalar_one_or_none()


async def ensure_subscription(db: AsyncSession, *, business_id: str) -> Subscription:
    """The business's subscription row, creating a trialing one if absent.

    Every business gets a trial row on first read rather than at signup, so a
    tenant created before billing existed (or by a seed script, or by the demo
    fallback in ``core/deps.py``) still resolves to a plan instead of a 404.

    ``business_id`` is unique on this table, so two concurrent first-page-loads
    race here. The loser catches the IntegrityError and re-reads rather than
    surfacing a 500 on what is, from the owner's side, just opening the app.
    """
    existing = await get_subscription(db, business_id=business_id)
    if existing is not None:
        return existing

    row = Subscription(
        business_id=_uuid(business_id),
        tier="starter",
        status="trialing",
        trial_ends_at=datetime.now(UTC) + timedelta(days=TRIAL_DAYS),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        concurrent = await get_subscription(db, business_id=business_id)
        if concurrent is None:  # pragma: no cover — only if the unique index changed
            raise
        return concurrent
    return row


async def usage_counts(db: AsyncSession, *, business_id: str) -> tuple[int, int]:
    """(customer_count, connected_integration_count) for the limit meters.

    Counts in SQL rather than loading rows: this runs on every dashboard load
    and a Pro tenant can have far more customers than we want in memory just to
    call ``len()`` on them.
    """
    bid = _uuid(business_id)
    customers = (
        await db.scalar(
            select(func.count()).select_from(Customer).where(Customer.business_id == bid)
        )
    ) or 0
    integrations = (
        await db.scalar(
            select(func.count())
            .select_from(IntegrationConnection)
            .where(
                IntegrationConnection.business_id == bid,
                IntegrationConnection.status == "connected",
            )
        )
    ) or 0
    return customers, integrations


async def entitlements(db: AsyncSession, *, business_id: str) -> Entitlements:
    """The single question the rest of the app asks billing."""
    sub = await ensure_subscription(db, business_id=business_id)
    customers, integrations = await usage_counts(db, business_id=business_id)
    return evaluate(
        tier_name=sub.tier,
        status=_effective_status(sub),
        customer_count=customers,
        integration_count=integrations,
    )


def _effective_status(sub: Subscription) -> str:
    """``status`` with an expired trial resolved.

    Stripe sends ``customer.subscription.updated`` when a trial converts, but we
    can't depend on having received it — a missed webhook would leave a tenant
    reading "trialing" forever. Deriving the expiry locally means the worst a
    lost webhook costs us is a stale tier name, not an unbounded free trial.
    """
    if sub.status != "trialing":
        return sub.status
    if sub.trial_ends_at and sub.trial_ends_at <= datetime.now(UTC):
        return "trial_expired"
    return "trialing"


def trial_days_left(sub: Subscription, *, now: datetime | None = None) -> int | None:
    """Whole days until the trial ends, or None when not trialing.

    Rounded up, so the banner reads "1 day left" through the final day rather
    than flipping to "0 days left" with hours still on the clock.
    """
    if sub.status != "trialing" or sub.trial_ends_at is None:
        return None
    remaining = sub.trial_ends_at - (now or datetime.now(UTC))
    if remaining.total_seconds() <= 0:
        return 0
    return math.ceil(remaining.total_seconds() / 86_400)
