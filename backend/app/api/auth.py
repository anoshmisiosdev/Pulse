"""Auth endpoint. Login/signup happen on the frontend via Supabase Auth; the
backend only verifies the Supabase access token and returns the resolved tenant.
Multi-tenant: the token's claims carry business_id, which scopes all tenant data."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep, can_manage_visitors
from app.core.posthog_client import identify_user, request_distinct_id
from app.schemas.api import AuthUser
from app.visitor_intelligence.service import (
    link_authenticated_user,
    request_session_id,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("pulse.auth")


@router.get("/me", response_model=AuthUser)
async def me(
    request: Request,
    user: CurrentUser = CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> AuthUser:
    anonymous_id = request_distinct_id(request)
    # No consent header means no marketing-history link. Tracking failure is
    # non-critical and must never block a successful authentication response.
    if anonymous_id:
        identify_user(
            user.user_id,
            anonymous_id=anonymous_id,
            properties={
                "business_id": user.business_id,
                "business_name": user.business_name,
                "role": user.role,
            },
        )
        try:
            await link_authenticated_user(
                db,
                anonymous_id=anonymous_id,
                session_id=request_session_id(request),
                user_id=user.user_id,
                email=user.email,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Could not stitch authenticated visitor history")
    return AuthUser(
        user_id=user.user_id,
        email=user.email,
        business_id=user.business_id,
        business_name=user.business_name,
        role=user.role,
        can_manage_visitors=can_manage_visitors(user),
    )
