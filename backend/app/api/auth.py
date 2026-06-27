"""Auth endpoints. Backend-brokered: we verify credentials against Convex with the
server-only API key, then issue a Pulse session token. The browser never holds the
Convex key. Multi-tenant: the session carries business_id, and all tenant data is
scoped to it."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from app.core import convex
from app.core.config import settings
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.security import create_session_token
from app.schemas.api import AuthUser, LoginIn, LoginOut, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue(user: convex.ConvexUser) -> LoginOut:
    token = create_session_token(
        user_id=user.user_id,
        business_id=user.business_id,
        email=user.email,
        business_name=user.business_name,
        role=user.role,
    )
    return LoginOut(
        token=token,
        user=AuthUser(
            user_id=user.user_id,
            email=user.email,
            business_id=user.business_id,
            business_name=user.business_name,
            role=user.role,
        ),
    )


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn) -> LoginOut:
    try:
        user = await convex.verify_login(payload.email, payload.password)
    except convex.ConvexAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except convex.ConvexUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return _issue(user)


@router.post("/register", response_model=LoginOut)
async def register(
    payload: RegisterIn, x_admin_key: str | None = Header(default=None)
) -> LoginOut:
    """Operator-only tenant bootstrap. Guarded by the shared Convex API key so it
    isn't a public sign-up form."""
    if not settings.convex_api_key or x_admin_key != settings.convex_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin key required")
    try:
        user = await convex.register(payload.email, payload.password, payload.business_name)
    except convex.ConvexAuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except convex.ConvexUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return _issue(user)


@router.get("/me", response_model=AuthUser)
async def me(user: CurrentUser = CurrentUserDep) -> AuthUser:
    return AuthUser(
        user_id=user.user_id,
        email=user.email,
        business_id=user.business_id,
        business_name=user.business_name,
        role=user.role,
    )
