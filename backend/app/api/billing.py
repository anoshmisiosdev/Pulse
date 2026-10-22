"""Subscription billing: plans, status, Checkout, the portal, and the webhook.

The webhook route is public and unauthenticated - Stripe calls it directly, so
the HMAC signature *is* the authentication. It verifies against the raw request
body before parsing anything, because any reserialization would invalidate the
signature.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service
from app.billing.store import ensure_subscription, entitlements, trial_days_left
from app.billing.tiers import TIERS, TRIAL_DAYS, Tier
from app.billing.webhooks import apply_subscription_event
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep, OwnerDep
from app.core.posthog_client import capture_event
from app.schemas.billing import (
    CheckoutIn,
    CheckoutOut,
    PlansOut,
    PortalOut,
    SubscriptionOut,
    TierOut,
    UsageMeterOut,
)
from app.services.webhooks import verify_stripe_signature

logger = logging.getLogger("pulse.api.billing")
router = APIRouter(prefix="/billing", tags=["billing"])

# Stripe events are small; anything this size is not a real Stripe delivery.
_MAX_WEBHOOK_BYTES = 1_048_576


def _tier_out(tier: Tier) -> TierOut:
    return TierOut(
        name=tier.name,
        label=tier.label,
        monthly_price_usd=tier.monthly_price_usd,
        annual_price_usd=tier.annual_price_usd,
        max_customers=tier.max_customers,
        max_integrations=tier.max_integrations,
        channels=sorted(tier.channels),
        automation=tier.automation,
        multi_location=tier.multi_location,
        blurb=tier.blurb,
        highlights=list(tier.highlights),
    )


@router.get("/plans", response_model=PlansOut)
async def plans(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> PlansOut:
    """The price list, plus which plan this tenant is on."""
    sub = await ensure_subscription(db, business_id=user.business_id)
    return PlansOut(
        tiers=[_tier_out(TIERS[name]) for name in ("starter", "growth", "pro")],
        trial_days=TRIAL_DAYS,
        current_tier=sub.tier,
        billing_configured=settings.billing_configured,
    )


@router.get("/subscription", response_model=SubscriptionOut)
async def subscription(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> SubscriptionOut:
    """This tenant's plan, entitlements, and usage meters.

    Read entirely from our own tables - never calls Stripe, so it still answers
    during a Stripe outage.
    """
    sub = await ensure_subscription(db, business_id=user.business_id)
    ent = await entitlements(db, business_id=user.business_id)
    return SubscriptionOut(
        tier=ent.tier.name,
        status=ent.status,
        active=ent.active,
        trial_days_left=trial_days_left(sub),
        current_period_end=(
            sub.current_period_end.isoformat() if sub.current_period_end else None
        ),
        channels=sorted(ent.channels),
        automation=ent.automation,
        multi_location=ent.multi_location,
        meters=[
            UsageMeterOut(
                key=m.key,
                label=m.label,
                used=m.used,
                limit=m.limit,
                severity=m.severity,
                message=m.message,
            )
            for m in ent.meters
        ],
        billing_configured=settings.billing_configured,
        has_payment_method=bool(sub.stripe_customer_id),
    )


@router.post("/checkout", response_model=CheckoutOut)
async def checkout(
    payload: CheckoutIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = OwnerDep,
) -> CheckoutOut:
    base = settings.billing_return_url
    try:
        session = await service.start_checkout(
            db,
            business_id=user.business_id,
            email=user.email,
            tier=payload.tier,
            annual=payload.annual,
            success_url=f"{base}/billing?checkout=success",
            cancel_url=f"{base}/billing?checkout=canceled",
        )
    except service.BillingError as exc:
        # 503, not 500: this is "billing isn't available", and the message is
        # already owner-safe by construction (see service.owner_safe_message).
        raise HTTPException(503, detail=str(exc)) from exc
    await db.commit()
    capture_event(
        "billing_checkout_started",
        distinct_id=user.user_id,
        properties={"tier": payload.tier, "annual": payload.annual},
    )
    return CheckoutOut(url=session.url, session_id=session.session_id)


@router.post("/portal", response_model=PortalOut)
async def portal(
    db: AsyncSession = Depends(get_db), user: CurrentUser = OwnerDep
) -> PortalOut:
    try:
        url = await service.portal_url(
            db,
            business_id=user.business_id,
            return_url=f"{settings.billing_return_url}/billing",
        )
    except service.BillingError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    return PortalOut(url=url)


@router.post("/webhook", status_code=202)
async def stripe_subscription_webhook(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Signed subscription-lifecycle events from *our* Stripe account.

    Distinct from ``/integrations/webhooks/stripe``, which handles a connected
    tenant's own account for retention data. Different trust domain, different
    signing secret - see app/billing/webhooks.py.
    """
    secret = settings.stripe_webhook_secret
    if not secret:
        raise HTTPException(503, detail="Stripe subscription webhooks are not configured")
    body = await request.body()
    if len(body) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail="Webhook payload is too large")
    if not verify_stripe_signature(body, request.headers.get("stripe-signature", ""), secret):
        raise HTTPException(401, detail="Invalid Stripe webhook signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, detail="Webhook body was not valid JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(422, detail="Webhook body must be a JSON object")
    return await apply_subscription_event(db, event)
