"""Public waitlist signup — the one write path that needs no authentication.

Everything here is shaped by that: bounded field lengths (enforced by
``WaitlistIn``), a honeypot, and an upsert instead of a uniqueness error so a
repeat submit is idempotent rather than a 409 the visitor has to interpret.

Rate limited per IP in ``app/main.py`` alongside the auth endpoints — an
unauthenticated write is worth a bucket even though the ceiling is one row per
email address. A human submits this once.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistIn, WaitlistOut

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

logger = logging.getLogger("pulse.waitlist")


@router.post("", response_model=WaitlistOut)
async def join_waitlist(
    payload: WaitlistIn, db: AsyncSession = Depends(get_db)
) -> WaitlistOut:
    """Record a signup, or quietly refresh the one that already exists."""
    # Honeypot tripped: answer exactly as we would on success. A bot that can
    # tell it was rejected just tries again with the field left blank.
    if payload.website.strip():
        logger.info("waitlist honeypot tripped")
        return WaitlistOut(ok=True)

    # WaitlistIn has already stripped and lowercased these.
    existing = (
        await db.execute(select(WaitlistSignup).where(WaitlistSignup.email == payload.email))
    ).scalar_one_or_none()

    if existing is not None:
        # Let a second submit correct a typo in the name or add a business,
        # but never blank out something we already have.
        existing.name = payload.name
        existing.business_name = payload.business_name or existing.business_name
        existing.vertical = payload.vertical or existing.vertical
        existing.note = payload.note or existing.note
        await db.flush()
        return WaitlistOut(ok=True, already_joined=True)

    db.add(
        WaitlistSignup(
            email=payload.email,
            name=payload.name,
            business_name=payload.business_name,
            vertical=payload.vertical,
            note=payload.note,
        )
    )
    await db.flush()
    logger.info("waitlist signup recorded")
    return WaitlistOut(ok=True)
