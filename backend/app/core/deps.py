"""Shared FastAPI dependencies: auth + tenant resolution.

A verified Supabase access token resolves to a tenant we scope every query by.
Resolution order, most authoritative first:

1. ``app_metadata.business_id`` in the JWT. Only Supabase's service role can
   write app_metadata, so it's trusted, and it wins.
2. A membership row in our ``users`` table, keyed by the Supabase ``sub``.
   This is how team invites work: accepting an invite writes the row, and the
   invitee's requests resolve to the inviter's business from then on.
3. The ``sub`` itself — every user owns a business of their own by default.

Membership lives in our database rather than in the JWT on purpose. A JWT claim
persists until the token expires, so removing a teammate via app_metadata
would leave them access for up to an hour. A row we read per request revokes
on the very next request.

In dev, if Supabase isn't configured, we fall back to a demo tenant so the
dashboard is usable without logging in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_supabase_jwt

DEMO_BUSINESS_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None
    business_id: str
    business_name: str = "Demo Business"
    role: str = "owner"


# Roles that belong to Churnary's own staff (see can_manage_visitors). These come
# only from app_metadata, and a tenant membership row must never overwrite them.
PLATFORM_ROLES = frozenset({"admin", "platform_admin"})


def _tenant_from_claims(claims: dict) -> CurrentUser:
    app_meta = claims.get("app_metadata") or {}
    user_meta = claims.get("user_metadata") or {}
    sub = claims["sub"]
    email = claims.get("email")
    return CurrentUser(
        user_id=sub,
        email=email,
        business_id=str(app_meta.get("business_id") or sub),
        business_name=user_meta.get("business_name") or email or "My Business",
        role=app_meta.get("role", "owner"),
    )


def demo_tenant_allowed() -> bool:
    """Whether an unauthenticated request may fall back to the demo tenant.

    Two ways in, both dev-only: Supabase simply isn't configured, or it is but
    ``AUTH_DISABLED=true`` asks us to ignore it for a local run. Production is
    excluded twice — here, and by the settings validator that refuses to boot
    with ``AUTH_DISABLED`` set.
    """
    if settings.is_production:
        return False
    return settings.auth_disabled or not settings.auth_configured


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Resolve the caller from a Supabase Bearer token, or a demo user in dev."""
    if not authorization:
        if demo_tenant_allowed():
            return CurrentUser(
                user_id="demo-user",
                email="demo@pulse.app",
                business_id=DEMO_BUSINESS_ID,
                business_name="Hayward Coffee Co.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = verify_supabase_jwt(token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return await resolve_membership(db, claims)


async def resolve_membership(db: AsyncSession, claims: dict) -> CurrentUser:
    """Apply the resolution order in the module docstring to verified claims."""
    from app.models import Business, User

    user = _tenant_from_claims(claims)
    app_meta = claims.get("app_metadata") or {}
    if app_meta.get("business_id"):
        return user  # (1) service-role assigned; authoritative

    try:
        row = (
            await db.execute(
                select(User)
                .where(User.supabase_user_id == user.user_id)
                .order_by(User.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    except (SQLAlchemyError, OSError):
        # Degrading to (3) is safe: it resolves to the caller's *own* business,
        # never to anyone else's, so a DB hiccup can't widen access. OSError is
        # here because an unreachable database can surface as a raw socket
        # error rather than a wrapped SQLAlchemy one.
        return user

    if row is not None:  # (2) a team membership
        business = await db.get(Business, row.business_id)
        return CurrentUser(
            user_id=user.user_id,
            email=user.email,
            business_id=str(row.business_id),
            business_name=business.name if business else user.business_name,
            role=user.role if user.role in PLATFORM_ROLES else row.role,
        )

    # (3) The user's own business. Record them as its owner the first time we
    # see them with a business that exists -- until now nothing ever wrote a
    # `users` row, so anything addressed to "the owner" (the weekly digest)
    # had nobody to send to. Skipped until the business exists, because the
    # row's foreign key needs it.
    await _record_owner(db, user)
    return user


async def _record_owner(db: AsyncSession, user: CurrentUser) -> None:
    from app.models import Business, User

    try:
        business_id = uuid.UUID(user.business_id)
    except ValueError:
        return
    if not user.email:
        return
    try:
        if await db.get(Business, business_id) is None:
            return
        db.add(
            User(
                business_id=business_id,
                supabase_user_id=user.user_id,
                email=user.email,
                role="owner",
            )
        )
        await db.commit()
    except (SQLAlchemyError, OSError):
        await db.rollback()


CurrentUserDep = Depends(get_current_user)


def can_manage_visitors(user: CurrentUser) -> bool:
    """Platform authorization for Churnary's own marketing visitor data."""
    if not settings.is_production and not settings.auth_configured:
        return True
    if user.role in {"admin", "platform_admin"}:
        return True
    return bool(user.email and user.email.casefold() in settings.visitor_admin_email_set)


async def get_visitor_admin(user: CurrentUser = CurrentUserDep) -> CurrentUser:
    if not can_manage_visitors(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access required",
        )
    return user


VisitorAdminDep = Depends(get_visitor_admin)


async def get_owner(user: CurrentUser = CurrentUserDep) -> CurrentUser:
    """The caller, if they're the account owner; otherwise 403.

    Staff can do the day-to-day work. These are the things they can't, because
    each one either spends money, moves customer data out of the product, or
    changes who has access:

    - billing (checkout, the Stripe portal),
    - data export and deletion,
    - team management,
    - turning on outbound messaging that runs unattended (review requests,
      webhooks to third-party URLs).
    """
    if user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the account owner can do that. Ask them to make the change.",
        )
    return user


OwnerDep = Depends(get_owner)
