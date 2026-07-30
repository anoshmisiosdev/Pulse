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

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.posthog_client import capture_event, request_distinct_id
from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistIn, WaitlistOut

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

logger = logging.getLogger("pulse.waitlist")


def _vertical_bucket(value: str | None) -> str:
    """Map free-form waitlist choices to a stable, non-PII analytics value."""
    if not value:
        return "not_provided"
    normalized = value.casefold()
    if "café" in normalized or "cafe" in normalized or "coffee" in normalized:
        return "cafe"
    if "salon" in normalized or "barber" in normalized:
        return "salon"
    if "gym" in normalized or "fitness" in normalized:
        return "fitness"
    if "med spa" in normalized:
        return "med_spa"
    if "yoga" in normalized or "pilates" in normalized:
        return "yoga_pilates"
    return "other"


@router.post("", response_model=WaitlistOut)
async def join_waitlist(
    payload: WaitlistIn, request: Request, db: AsyncSession = Depends(get_db)
) -> WaitlistOut:
    """Record a signup, or quietly refresh the one that already exists."""
    # Honeypot tripped: answer exactly as we would on success. A bot that can
    # tell it was rejected just tries again with the field left blank.
    if payload.website.strip():
        logger.info("waitlist honeypot tripped")
        return WaitlistOut(ok=True)

    distinct_id = request_distinct_id(request)
    acquisition_properties = {
        "surface": "landing",
        "metric_version": 1,
        "has_business_name": payload.business_name is not None,
        "vertical": _vertical_bucket(payload.vertical),
    }
    # The API has now accepted a valid, non-honeypot submission. Keeping this
    # adjacent to the conversion event preserves ordering in PostHog.
    capture_event(
        "landing_waitlist_submitted",
        distinct_id=distinct_id,
        properties=acquisition_properties,
    )

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
        already_joined = True
    else:
        db.add(
            WaitlistSignup(
                email=payload.email,
                name=payload.name,
                business_name=payload.business_name,
                vertical=payload.vertical,
                note=payload.note,
            )
        )
        already_joined = False

    # This is the acquisition conversion event, so emit it only after the
    # database has confirmed the write. The dependency's final commit is then
    # an idempotent no-op.
    await db.commit()
    capture_event(
        "landing_waitlist_joined",
        distinct_id=distinct_id,
        properties={
            **acquisition_properties,
            "already_joined": already_joined,
        },
    )
    logger.info("waitlist signup recorded (already_joined=%s)", already_joined)
    return WaitlistOut(ok=True, already_joined=already_joined)
