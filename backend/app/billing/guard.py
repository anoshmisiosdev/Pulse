"""Entitlement checks for the routes that need them.

CLAUDE.md says to enforce limits "in middleware". These are FastAPI
dependencies rather than ASGI middleware on purpose: an ASGI middleware runs
before routing, so it has no tenant, no database session, and no idea which
channel a request is about - it could only match on URL prefixes and would have
to open its own session to answer "is SMS included?". As dependencies they
compose per route, reuse the request's session, and can say exactly which
feature is missing and which plan includes it. The enforcement point is the
same; only the mechanism differs.

Volume limits are deliberately *not* enforced here. Those nag (see
``limits.py``) and surface through ``GET /billing/subscription``; they never
block. The only hard gates are feature entitlements - SMS and automation -
because sending on a channel a plan doesn't include means billing someone for
something they never agreed to.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.limits import Entitlements, automation_denial, channel_denial
from app.billing.store import entitlements
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep


async def get_entitlements(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> Entitlements:
    return await entitlements(db, business_id=user.business_id)


EntitlementsDep = Depends(get_entitlements)


def require_channel(ent: Entitlements, channel: str) -> None:
    """402 when this plan doesn't include the channel.

    402 Payment Required rather than 403: the caller is authenticated and
    authorized, the plan just doesn't cover this. The frontend keys its
    upgrade prompt off the 402 specifically, so a real permissions problem
    (403) stays distinguishable from a billing one.
    """
    denial = channel_denial(ent, channel)
    if denial:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, detail=denial)


def require_automation(ent: Entitlements) -> None:
    denial = automation_denial(ent)
    if denial:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, detail=denial)
