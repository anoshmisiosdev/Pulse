"""Shared FastAPI dependencies: auth + tenant resolution.

A verified Supabase access token resolves to a tenant we scope every query by.
One owner = one tenant for now: ``business_id`` defaults to the Supabase user id
(``sub``), overridable via ``app_metadata.business_id`` once teams exist. In dev,
if Supabase isn't configured, we fall back to a demo tenant so the dashboard is
usable without logging in.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.security import verify_supabase_jwt

DEMO_BUSINESS_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None
    business_id: str
    business_name: str = "Demo Business"
    role: str = "owner"


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


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """Resolve the caller from a Supabase Bearer token, or a demo user in dev."""
    if not authorization:
        if not settings.is_production and not settings.auth_configured:
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

    return _tenant_from_claims(claims)


CurrentUserDep = Depends(get_current_user)
