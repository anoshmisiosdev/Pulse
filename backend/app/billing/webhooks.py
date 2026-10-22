"""Applying Stripe subscription-lifecycle events to our ``subscriptions`` table.

Pure-ish by design: :func:`apply_subscription_event` takes a parsed event dict
and a session, and touches nothing else. No SDK import, no network. That makes
every branch testable with a literal payload, which matters because this is the
code that decides whether someone keeps access to the product.

Separate from ``app/services/payment_webhooks.py``, which handles the *tenant's*
Stripe account (their customers' charges, via Stripe Connect) for retention
data. This file handles *our* Stripe account - the money an owner pays Churnary.
Conflating them would mean one signing secret for two trust domains.

Idempotency: handlers write absolute state derived from the payload, so a
redelivered event is a no-op, and a subscription id that doesn't match the one
we have on file is ignored rather than clobbering current state with a stale
event from a subscription the owner already replaced.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.store import _uuid, get_subscription
from app.models import Subscription

logger = logging.getLogger("pulse.billing.webhooks")

# Everything else Stripe sends is acknowledged and ignored. Listing the ones we
# act on makes the blast radius of a new Stripe event type exactly zero.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.paid",
    }
)

# Stripe's subscription statuses mapped onto the four our product understands.
# ``incomplete``/``incomplete_expired`` mean checkout was abandoned before the
# first payment cleared, which is not a paying customer - treated as canceled.
_STATUS_MAP = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete": "canceled",
    "incomplete_expired": "canceled",
    "paused": "canceled",
}


def _ts(value) -> datetime | None:
    """A Stripe unix timestamp as an aware datetime, or None."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _business_id_from(obj: dict) -> str | None:
    """Find the tenant a Stripe object belongs to.

    Checked in order of reliability: the metadata we stamped on the
    subscription, then the checkout session's client_reference_id. Both are set
    by ``service.start_checkout``; having two means a Stripe object created by
    hand in the dashboard (support fixing something) can still be routed by
    adding one metadata field.
    """
    metadata = obj.get("metadata") or {}
    candidate = metadata.get("business_id") or obj.get("client_reference_id")
    if not candidate:
        return None
    try:
        _uuid(str(candidate))
    except (ValueError, AttributeError):
        logger.warning("Stripe object carried an unparseable business_id: %r", candidate)
        return None
    return str(candidate)


def _price_from_subscription(obj: dict) -> str | None:
    items = ((obj.get("items") or {}).get("data")) or []
    if not items:
        return None
    price = items[0].get("price") or {}
    return price.get("id")


async def _subscription_for(
    db: AsyncSession, *, business_id: str | None, stripe_customer_id: str | None
) -> Subscription | None:
    """Our row for this Stripe object, by tenant id or by Stripe customer id.

    The customer-id fallback carries the events that have no metadata of their
    own - ``invoice.payment_failed`` names a customer and a subscription but not
    a business.
    """
    if business_id:
        row = await get_subscription(db, business_id=business_id)
        if row is not None:
            return row
    if stripe_customer_id:
        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_customer_id == stripe_customer_id
            )
        )
        return result.scalar_one_or_none()
    return None


async def _handle_checkout_completed(db: AsyncSession, obj: dict) -> str:
    """Bind the Stripe customer/subscription ids to the tenant.

    Only the ids are written here. The plan and status come from the
    ``customer.subscription.*`` events, which carry the authoritative price and
    status - deriving them from the checkout session would mean two sources of
    truth for the same fields.
    """
    business_id = _business_id_from(obj)
    if not business_id:
        return "ignored_no_business_id"
    sub = await get_subscription(db, business_id=business_id)
    if sub is None:
        sub = Subscription(business_id=_uuid(business_id), tier="starter", status="trialing")
        db.add(sub)
    customer = obj.get("customer")
    subscription = obj.get("subscription")
    if isinstance(customer, str):
        sub.stripe_customer_id = customer
    if isinstance(subscription, str):
        sub.stripe_subscription_id = subscription
    await db.flush()
    return "linked"


async def _handle_subscription_changed(db: AsyncSession, obj: dict) -> str:
    """Write plan, status, trial end and period end from a subscription object."""
    from app.billing.service import tier_for_price

    business_id = _business_id_from(obj)
    customer = obj.get("customer") if isinstance(obj.get("customer"), str) else None
    sub = await _subscription_for(db, business_id=business_id, stripe_customer_id=customer)
    if sub is None:
        logger.warning("Stripe subscription event for an unknown tenant: %s", obj.get("id"))
        return "ignored_unknown_tenant"

    stripe_sub_id = obj.get("id")
    # A stale event for a subscription we've already replaced must not overwrite
    # the current one. A *new* id is accepted: that's an upgrade creating a
    # fresh subscription, and it becomes the one on file.
    if (
        sub.stripe_subscription_id
        and stripe_sub_id
        and sub.stripe_subscription_id != stripe_sub_id
        and obj.get("status") in {"canceled", "incomplete_expired"}
    ):
        return "ignored_stale_subscription"

    if isinstance(stripe_sub_id, str):
        sub.stripe_subscription_id = stripe_sub_id
    if customer:
        sub.stripe_customer_id = customer

    tier = tier_for_price(_price_from_subscription(obj))
    if tier:
        sub.tier = tier
    else:
        logger.warning(
            "Stripe subscription %s has a price we don't recognize - keeping tier %r",
            stripe_sub_id,
            sub.tier,
        )

    sub.status = _STATUS_MAP.get(str(obj.get("status")), "canceled")
    sub.trial_ends_at = _ts(obj.get("trial_end")) or sub.trial_ends_at
    sub.current_period_end = _ts(obj.get("current_period_end")) or sub.current_period_end
    await db.flush()
    return f"status={sub.status},tier={sub.tier}"


async def _handle_subscription_deleted(db: AsyncSession, obj: dict) -> str:
    business_id = _business_id_from(obj)
    customer = obj.get("customer") if isinstance(obj.get("customer"), str) else None
    sub = await _subscription_for(db, business_id=business_id, stripe_customer_id=customer)
    if sub is None:
        return "ignored_unknown_tenant"
    if (
        sub.stripe_subscription_id
        and obj.get("id")
        and sub.stripe_subscription_id != obj.get("id")
    ):
        return "ignored_stale_subscription"
    sub.status = "canceled"
    sub.current_period_end = _ts(obj.get("ended_at")) or sub.current_period_end
    await db.flush()
    return "canceled"


async def _handle_invoice(db: AsyncSession, obj: dict, *, paid: bool) -> str:
    """Reflect payment success/failure without waiting for the subscription event.

    Stripe does follow an ``invoice.payment_failed`` with a subscription update,
    but not always promptly. Setting ``past_due`` here means the in-app "update
    your card" nag shows up on the owner's next page load instead of whenever
    the second event lands.
    """
    customer = obj.get("customer") if isinstance(obj.get("customer"), str) else None
    sub = await _subscription_for(db, business_id=None, stripe_customer_id=customer)
    if sub is None:
        return "ignored_unknown_tenant"
    if paid:
        # Only clear past_due. An invoice paid against a canceled subscription
        # (a final proration) must not silently reactivate the account.
        if sub.status == "past_due":
            sub.status = "active"
        period_end = _ts((obj.get("lines") or {}).get("period_end")) or _ts(
            obj.get("period_end")
        )
        sub.current_period_end = period_end or sub.current_period_end
    elif sub.status in {"active", "trialing"}:
        sub.status = "past_due"
    await db.flush()
    return f"status={sub.status}"


async def apply_subscription_event(db: AsyncSession, event: dict) -> dict[str, str]:
    """Apply one verified Stripe event. Never raises on an unknown shape.

    Returns a small dict for the webhook response and the logs. Unknown event
    types are acknowledged (``200``) rather than rejected: Stripe retries 4xx
    responses, and retrying something we will never handle is noise.
    """
    event_type = str(event.get("type") or "")
    obj = ((event.get("data") or {}).get("object")) or {}
    if not isinstance(obj, dict):
        return {"status": "ignored", "reason": "unexpected_payload"}
    if event_type not in HANDLED_EVENTS:
        return {"status": "ignored", "type": event_type}

    if event_type == "checkout.session.completed":
        outcome = await _handle_checkout_completed(db, obj)
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        outcome = await _handle_subscription_changed(db, obj)
    elif event_type == "customer.subscription.deleted":
        outcome = await _handle_subscription_deleted(db, obj)
    elif event_type == "invoice.paid":
        outcome = await _handle_invoice(db, obj, paid=True)
    else:  # invoice.payment_failed
        outcome = await _handle_invoice(db, obj, paid=False)

    logger.info("Stripe %s -> %s", event_type, outcome)
    return {"status": "applied", "type": event_type, "outcome": outcome}
