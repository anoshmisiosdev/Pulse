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
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.posthog_client import capture_event, identify_user, request_distinct_id
from app.discord_bot.service import WaitlistAlert, send_waitlist_alert
from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistIn, WaitlistOut
from app.services.waitlist_leads import (
    assign_founder,
    enqueue_email_sequence,
    signup_id_from_unsubscribe_token,
)
from app.visitor_intelligence.service import (
    link_waitlist_signup,
    request_session_id,
)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

logger = logging.getLogger("pulse.waitlist")


def _vertical_bucket(value: str | None, landing_variant: str | None = None) -> str:
    """Map enrichment or a vertical landing page to a stable analytics value."""
    normalized = (value or landing_variant or "").casefold()
    if not normalized:
        return "not_provided"
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


async def _find_signup(db: AsyncSession, email: str) -> WaitlistSignup | None:
    return (
        await db.execute(select(WaitlistSignup).where(WaitlistSignup.email == email))
    ).scalar_one_or_none()


def _enrich_existing_signup(
    signup: WaitlistSignup,
    payload: WaitlistIn,
    touch: dict[str, str],
) -> None:
    """Merge a repeat submit without erasing its first-touch relationship."""
    signup.name = payload.name or signup.name
    signup.business_name = payload.business_name or signup.business_name
    signup.vertical = payload.vertical or signup.vertical
    signup.note = payload.note or signup.note
    signup.assigned_founder = signup.assigned_founder or assign_founder(
        payload.email, payload.content
    )
    if touch:
        signup.last_touch = touch


@router.post("", response_model=WaitlistOut)
async def join_waitlist(
    payload: WaitlistIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> WaitlistOut:
    """Record a signup, or quietly refresh the one that already exists."""
    # Honeypot tripped: answer exactly as we would on success. A bot that can
    # tell it was rejected just tries again with the field left blank.
    if payload.website.strip():
        logger.info("waitlist honeypot tripped")
        return WaitlistOut(ok=True)

    distinct_id = request_distinct_id(request)
    touch = payload.acquisition_touch()
    acquisition_properties = {
        "surface": "landing",
        "metric_version": 1,
        "has_business_name": payload.business_name is not None,
        "vertical": _vertical_bucket(payload.vertical, payload.landing_variant),
    }
    acquisition_properties.update(
        {
            posthog_key: touch[key]
            for key, posthog_key in (
                ("source", "utm_source"),
                ("medium", "utm_medium"),
                ("campaign", "utm_campaign"),
                ("content", "utm_content"),
                ("landing_variant", "landing_variant"),
                ("referrer_host", "referrer_host"),
            )
            if key in touch
        }
    )
    # The API has now accepted a valid, non-honeypot submission. Keeping this
    # adjacent to the conversion event preserves ordering in PostHog.
    if distinct_id:
        capture_event(
            "landing_waitlist_submitted",
            distinct_id=distinct_id,
            properties=acquisition_properties,
        )

    # WaitlistIn has already stripped and lowercased these.
    existing = await _find_signup(db, payload.email)

    if existing is not None:
        # Let a second submit correct a typo in the name or add a business,
        # but never blank out something we already have.
        _enrich_existing_signup(existing, payload, touch)
        signup = existing
        already_joined = True
    else:
        candidate = WaitlistSignup(
            email=payload.email,
            name=payload.name,
            business_name=payload.business_name,
            vertical=payload.vertical,
            note=payload.note,
            first_touch=touch,
            last_touch=touch,
            assigned_founder=assign_founder(payload.email, payload.content),
        )
        try:
            # A savepoint keeps the request transaction usable if another
            # request commits this email between our SELECT and INSERT. Under
            # PostgreSQL the unique-index loser resumes after the winner
            # commits; SQLite raises the same IntegrityError for a stale read.
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
        except IntegrityError:
            existing = await _find_signup(db, payload.email)
            if existing is None:
                # The constraint failure was unrelated to the email race.
                raise
            _enrich_existing_signup(existing, payload, touch)
            signup = existing
            already_joined = True
            logger.info("concurrent waitlist signup merged")
        else:
            signup = candidate
            already_joined = False

    await db.flush()
    await link_waitlist_signup(
        db,
        signup=signup,
        anonymous_id=distinct_id,
        session_id=request_session_id(request),
        already_joined=already_joined,
    )
    # This is the acquisition conversion event, so emit it only after the
    # database has confirmed the write. The dependency's final commit is then
    # an idempotent no-op.
    await db.commit()
    if not already_joined:
        # Both operations are now failure-isolated post-commit work. Discord
        # gets a detached snapshot; Celery gets only the opaque record ID.
        background_tasks.add_task(
            send_waitlist_alert,
            WaitlistAlert.from_signup(signup),
        )
        background_tasks.add_task(enqueue_email_sequence, signup.id)
    # Alias the pseudonymous browser history to an opaque waitlist record ID.
    # Names and emails remain in Churnary's own database, never in PostHog.
    if distinct_id:
        identify_user(
            f"waitlist:{signup.id}",
            anonymous_id=distinct_id,
            properties={
                "lifecycle_stage": "waitlist",
                "source": "landing",
                "vertical": _vertical_bucket(payload.vertical, payload.landing_variant),
                "founder": signup.assigned_founder or "unassigned",
            },
        )
        capture_event(
            "landing_waitlist_joined",
            distinct_id=distinct_id,
            properties={
                **acquisition_properties,
                "already_joined": already_joined,
                "founder": signup.assigned_founder or "unassigned",
            },
        )
    logger.info("waitlist signup recorded (already_joined=%s)", already_joined)
    return WaitlistOut(ok=True, already_joined=already_joined)


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_waitlist_email(
    token: str = Query(min_length=20, max_length=1000),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Stop the two optional follow-ups (and any retry still in flight)."""
    try:
        signup_id = signup_id_from_unsubscribe_token(token)
    except ValueError:
        raise HTTPException(400, "Invalid or corrupted unsubscribe link") from None
    signup = await db.get(WaitlistSignup, signup_id)
    if signup is None:
        raise HTTPException(404, "Not found")
    if signup.email_opted_out_at is None:
        signup.email_opted_out_at = datetime.now(UTC)
        await db.commit()
    return (
        "<html><body><main><h1>You're unsubscribed.</h1>"
        "<p>Churnary won't send further early-access emails to this address.</p>"
        "</main></body></html>"
    )
