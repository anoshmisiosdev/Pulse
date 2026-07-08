"""Auth endpoint. Login/signup happen on the frontend via Supabase Auth; the
backend only verifies the Supabase access token and returns the resolved tenant.
Multi-tenant: the token's claims carry business_id, which scopes all tenant data."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, CurrentUserDep
from app.schemas.api import AuthUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthUser)
async def me(user: CurrentUser = CurrentUserDep) -> AuthUser:
    return AuthUser(
        user_id=user.user_id,
        email=user.email,
        business_id=user.business_id,
        business_name=user.business_name,
        role=user.role,
    )
