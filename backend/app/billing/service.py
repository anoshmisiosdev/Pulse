"""Stripe Checkout, the Customer Portal, and subscription webhooks.

The only module in the codebase that imports the Stripe SDK. Two rules shape it:

* **Stripe is never on the read path.** Plan state lives in our ``subscriptions``
  table and is updated by webhooks. Rendering the dashboard never calls Stripe,
  so a Stripe outage degrades to "can't start a new checkout" rather than
  "nobody can open the app".
* **Webhooks are idempotent and order-independent.** Stripe redelivers, and
  events can arrive out of order. Every handler writes absolute state derived
  from the event payload rather than incrementing anything.

The SDK is imported lazily inside functions, the same way ``senders/`` does it,
so the package stays optional for local runs and tests that never touch billing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.store import ensure_subscription, get_subscription
from app.billing.tiers import TIERS, TRIAL_DAYS, TierName
from app.core.config import settings

logger = logging.getLogger("pulse.billing.service")


class BillingError(Exception):
    """Billing couldn't be completed. Carries owner-safe text, not SDK internals."""


@dataclass(frozen=True)
class CheckoutSession:
    url: str
    session_id: str


def stripe_configured() -> bool:
    return bool(settings.stripe_secret_key)


def price_id_for(tier: TierName, *, annual: bool = False) -> str:
    """The configured Stripe price for a tier.

    Annual uses a separate price in Stripe. We only treat a tier as
    annual-capable when that price is actually configured, so a missing annual
    price degrades to monthly instead of failing checkout outright.
    """
    monthly = {
        "starter": settings.stripe_price_starter,
        "growth": settings.stripe_price_growth,
        "pro": settings.stripe_price_pro,
    }
    annual_prices = {
        "starter": settings.stripe_price_starter_annual,
        "growth": settings.stripe_price_growth_annual,
        "pro": settings.stripe_price_pro_annual,
    }
    if annual and annual_prices.get(tier):
        return annual_prices[tier]
    price = monthly.get(tier, "")
    if not price:
        raise BillingError(f"No Stripe price is configured for the {tier} plan.")
    return price


def tier_for_price(price_id: str | None) -> TierName | None:
    """Reverse the price map, so a webhook tells us which plan was bought."""
    if not price_id:
        return None
    mapping: dict[str, TierName] = {}
    for tier in ("starter", "growth", "pro"):
        for key in (f"stripe_price_{tier}", f"stripe_price_{tier}_annual"):
            configured = getattr(settings, key, "")
            if configured:
                mapping[configured] = tier  # type: ignore[assignment]
    return mapping.get(price_id)


def _stripe():
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise BillingError("Billing is unavailable: the Stripe SDK isn't installed.") from exc
    if not settings.stripe_secret_key:
        raise BillingError("Billing isn't configured yet.")
    stripe.api_key = settings.stripe_secret_key
    return stripe


# -- Checkout -----------------------------------------------------------------


def _create_checkout_sync(
    *,
    price: str,
    business_id: str,
    email: str | None,
    stripe_customer_id: str | None,
    success_url: str,
    cancel_url: str,
    trial_days: int | None,
) -> CheckoutSession:
    stripe = _stripe()
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        # Card required for the trial - the trial is a trial, not a free tier.
        "payment_method_collection": "always",
        # Stamped on the subscription too, so a webhook that arrives without a
        # client_reference_id can still be routed to the right tenant.
        "subscription_data": {"metadata": {"business_id": business_id}},
        "client_reference_id": business_id,
        # Stripe's own promotion-code box on the hosted page. This is the only
        # discount path: a promotion code is the customer-facing token and
        # carries max_redemptions / expires_at / first_time_transaction, which
        # a bare coupon id does not. Never replace this with a client-supplied
        # `discounts` value -- that hands every tenant every coupon in the
        # account.
        "allow_promotion_codes": True,
    }
    if trial_days:
        params["subscription_data"]["trial_period_days"] = trial_days
    if stripe_customer_id:
        params["customer"] = stripe_customer_id
    elif email:
        params["customer_email"] = email
    try:
        session = stripe.checkout.Session.create(**params)
    except Exception as exc:
        raise BillingError(owner_safe_message(exc)) from exc
    url = session.get("url") if hasattr(session, "get") else getattr(session, "url", None)
    if not url:
        raise BillingError("Stripe didn't return a checkout URL.")
    session_id = (
        session.get("id") if hasattr(session, "get") else getattr(session, "id", "")
    )
    return CheckoutSession(url=url, session_id=session_id or "")


async def start_checkout(
    db: AsyncSession,
    *,
    business_id: str,
    email: str | None,
    tier: TierName,
    annual: bool = False,
    success_url: str,
    cancel_url: str,
) -> CheckoutSession:
    """Create a Checkout Session for a plan and hand back its hosted URL."""
    if tier not in TIERS:
        raise BillingError(f"'{tier}' isn't a plan we offer.")
    sub = await ensure_subscription(db, business_id=business_id)
    price = price_id_for(tier, annual=annual)
    # Only offer trial days to someone who has never subscribed - otherwise
    # cancelling and re-subscribing is an endless free trial.
    trial_days = TRIAL_DAYS if sub.stripe_subscription_id is None else None
    return await asyncio.to_thread(
        _create_checkout_sync,
        price=price,
        business_id=business_id,
        email=email,
        stripe_customer_id=sub.stripe_customer_id,
        success_url=success_url,
        cancel_url=cancel_url,
        trial_days=trial_days,
    )


# -- Customer Portal ----------------------------------------------------------


def _create_portal_sync(*, customer_id: str, return_url: str) -> str:
    stripe = _stripe()
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id, return_url=return_url
        )
    except Exception as exc:
        raise BillingError(owner_safe_message(exc)) from exc
    url = session.get("url") if hasattr(session, "get") else getattr(session, "url", None)
    if not url:
        raise BillingError("Stripe didn't return a billing portal URL.")
    return url


async def portal_url(db: AsyncSession, *, business_id: str, return_url: str) -> str:
    """A Stripe-hosted page where the owner updates their card or cancels.

    Deliberately not reimplemented in-product: card capture, dunning, proration
    and cancellation flows are Stripe's job, and routing them through our own UI
    would put card data in our request path for no benefit.
    """
    sub = await get_subscription(db, business_id=business_id)
    if sub is None or not sub.stripe_customer_id:
        raise BillingError("You don't have a billing account yet - pick a plan first.")
    return await asyncio.to_thread(
        _create_portal_sync, customer_id=sub.stripe_customer_id, return_url=return_url
    )


def owner_safe_message(exc: Exception) -> str:
    """Stripe's own message when it's meant for a human, a generic line otherwise.

    Stripe marks errors it considers user-facing (card declines, invalid
    requests) with a ``user_message``. Anything else - auth failures, API
    version mismatches - is our misconfiguration and must not be echoed to an
    owner, so it goes to the log and they get a neutral retry prompt.
    """
    user_message = getattr(exc, "user_message", None)
    if user_message:
        return str(user_message)
    err = getattr(exc, "error", None)
    err_type = getattr(err, "type", None) or type(exc).__name__
    if "card" in str(err_type).lower():
        return str(getattr(exc, "message", None) or "Your card was declined.")
    logger.warning("Stripe error (%s): %s", err_type, exc)
    return "Stripe couldn't complete that right now. Please try again."
