"""Shared FastAPI dependencies: auth + tenant resolution.

A verified Pulse session token (issued after Convex auth) resolves to a tenant we
scope every query by. In development, if auth isn't configured, we fall back to a
demo tenant so the dashboard is usable offline without logging in.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.security import decode_session_token

DEMO_BUSINESS_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None
    business_id: str
    business_name: str = "Demo Business"
    role: str = "owner"


def _auth_enabled() -> bool:
    return bool(settings.convex_url and settings.convex_api_key)


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """Resolve the caller from a Bearer session token, or a demo user in dev."""
    if not authorization:
        if not settings.is_production and not _auth_enabled():
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
        claims = decode_session_token(token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return CurrentUser(
        user_id=claims["sub"],
        email=claims.get("email"),
        business_id=claims.get("business_id") or DEMO_BUSINESS_ID,
        business_name=claims.get("business_name", "My Business"),
        role=claims.get("role", "owner"),
    )


CurrentUserDep = Depends(get_current_user)
