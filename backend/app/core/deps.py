"""Shared FastAPI dependencies: auth + tenant resolution.

Auth is intentionally thin in this phase: a verified Supabase JWT resolves to a
``business_id`` we scope every query by. In development, if no Supabase secret is
configured, we fall back to a demo tenant so the dashboard is usable offline.
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


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """Resolve the caller from a Bearer token, or a demo user in dev."""
    if not authorization:
        if not settings.is_production and not settings.supabase_jwt_secret:
            return CurrentUser(
                user_id="demo-user", email="demo@pulse.app", business_id=DEMO_BUSINESS_ID
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

    business_id = (claims.get("app_metadata") or {}).get("business_id") or DEMO_BUSINESS_ID
    return CurrentUser(
        user_id=claims["sub"],
        email=claims.get("email"),
        business_id=business_id,
    )


CurrentUserDep = Depends(get_current_user)
