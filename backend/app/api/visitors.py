"""Platform-admin APIs and provider webhooks for visitor intelligence."""

from __future__ import annotations

import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, VisitorAdminDep
from app.core.posthog_client import capture_event
from app.discord_bot.service import (
    DiscordDeliveryError,
    DiscordNotConfiguredError,
    VisitorAlert,
    send_discord_test_alert,
    send_visitor_alert,
)
from app.models.visitor import VisitorEvent, VisitorIdentifier, VisitorProfile
from app.schemas.visitors import (
    DiscordTestOut,
    IdentityLevel,
    Rb2bWebhookOut,
    VisitorDetailOut,
    VisitorEventOut,
    VisitorIntegrationStatusOut,
    VisitorListItem,
    VisitorListOut,
    VisitorPilotMetricsOut,
    VisitorStatus,
    VisitorSummaryOut,
    VisitorUpdateIn,
)
from app.visitor_intelligence.providers.rb2b import Rb2bAdapter
from app.visitor_intelligence.service import ingest_provider_signal, suppress_profile

router = APIRouter(prefix="/visitors", tags=["visitor-intelligence"])
logger = logging.getLogger("pulse.visitors")


def _now() -> datetime:
    return datetime.now(UTC)


async def _count_profiles(db: AsyncSession, *criteria) -> int:
    statement = select(func.count(VisitorProfile.id)).where(
        VisitorProfile.suppressed.is_(False), *criteria
    )
    return int((await db.execute(statement)).scalar_one())


async def _summary(db: AsyncSession, days: int) -> VisitorSummaryOut:
    now = _now()
    cutoff = now - timedelta(days=days)
    unique = await _count_profiles(db, VisitorProfile.last_seen_at >= cutoff)
    identified = await _count_profiles(
        db,
        VisitorProfile.last_seen_at >= cutoff,
        VisitorProfile.identity_level != "anonymous",
    )
    return VisitorSummaryOut(
        active_24h=await _count_profiles(
            db, VisitorProfile.last_seen_at >= now - timedelta(hours=24)
        ),
        unique_visitors=unique,
        identified_visitors=identified,
        identification_rate=round((identified / unique * 100) if unique else 0.0, 1),
        high_intent=await _count_profiles(
            db,
            VisitorProfile.last_seen_at >= cutoff,
            VisitorProfile.intent_score >= 60,
        ),
        waitlist_conversions=await _count_profiles(
            db,
            VisitorProfile.last_seen_at >= cutoff,
            VisitorProfile.waitlist_signup_id.is_not(None),
        ),
        provider_matches=await _count_profiles(
            db,
            VisitorProfile.last_seen_at >= cutoff,
            VisitorProfile.source_provider != "first_party",
        ),
        window_days=days,
    )


@router.get("", response_model=VisitorListOut)
async def list_visitors(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=120),
    visitor_status: VisitorStatus | None = Query(default=None, alias="status"),
    identity: IdentityLevel | None = None,
    source: str | None = Query(default=None, max_length=40),
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = VisitorAdminDep,
) -> VisitorListOut:
    cutoff = _now() - timedelta(days=days)
    criteria = [
        VisitorProfile.suppressed.is_(False),
        VisitorProfile.last_seen_at >= cutoff,
    ]
    if visitor_status:
        criteria.append(VisitorProfile.status == visitor_status)
    if identity:
        criteria.append(VisitorProfile.identity_level == identity)
    if source:
        criteria.append(VisitorProfile.source_provider == source)
    if q:
        needle = f"%{q.strip()}%"
        criteria.append(
            or_(
                VisitorProfile.full_name.ilike(needle),
                VisitorProfile.primary_email.ilike(needle),
                VisitorProfile.company_name.ilike(needle),
                VisitorProfile.company_domain.ilike(needle),
                VisitorProfile.job_title.ilike(needle),
            )
        )

    total = int(
        (
            await db.execute(
                select(func.count(VisitorProfile.id)).where(*criteria)
            )
        ).scalar_one()
    )
    profiles = list(
        (
            await db.execute(
                select(VisitorProfile)
                .where(*criteria)
                .order_by(
                    VisitorProfile.intent_score.desc(),
                    VisitorProfile.last_seen_at.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return VisitorListOut(
        items=[VisitorListItem.model_validate(profile) for profile in profiles],
        total=total,
        limit=limit,
        offset=offset,
        summary=await _summary(db, days),
    )


@router.get("/summary", response_model=VisitorSummaryOut)
async def visitor_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = VisitorAdminDep,
) -> VisitorSummaryOut:
    return await _summary(db, days)


@router.get("/pilot", response_model=VisitorPilotMetricsOut)
async def visitor_pilot(
    days: int = Query(default=30, ge=1, le=365),
    provider: str = Query(default="rb2b", max_length=40),
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = VisitorAdminDep,
) -> VisitorPilotMetricsOut:
    cutoff = _now() - timedelta(days=days)
    events = list(
        (
            await db.execute(
                select(VisitorEvent).where(
                    VisitorEvent.provider == provider,
                    VisitorEvent.event_name == "provider_identified",
                    VisitorEvent.occurred_at >= cutoff,
                )
            )
        ).scalars()
    )
    profile_ids = {event.visitor_id for event in events}
    profiles = (
        list(
            (
                await db.execute(
                    select(VisitorProfile).where(VisitorProfile.id.in_(profile_ids))
                )
            ).scalars()
        )
        if profile_ids
        else []
    )
    people = sum(
        profile.identity_level in {"person", "waitlist", "account"}
        for profile in profiles
    )
    companies = sum(profile.identity_level == "company" for profile in profiles)
    conversions = sum(profile.waitlist_signup_id is not None for profile in profiles)
    high_intent = sum(profile.intent_score >= 60 for profile in profiles)
    repeats = sum(bool(event.properties.get("repeat_visitor")) for event in events)
    cost = settings.rb2b_monthly_cost_usd or None
    cost_per_match = round(cost / len(profiles), 2) if cost and profiles else None
    conversion_rate = round((conversions / len(profiles) * 100) if profiles else 0.0, 1)
    if len(profiles) < 25:
        recommendation = "Keep the pilot running until at least 25 unique matches are observed."
    elif conversions or high_intent >= 5:
        recommendation = (
            "Promising signal: review lead quality and outreach outcomes before scaling."
        )
    else:
        recommendation = "Identification is working, but intent or conversion signal is still weak."
    return VisitorPilotMetricsOut(
        provider=provider,
        window_days=days,
        deliveries=len(events),
        unique_profiles=len(profiles),
        person_matches=people,
        company_matches=companies,
        repeat_visitors=repeats,
        high_intent_matches=high_intent,
        waitlist_conversions=conversions,
        conversion_rate=conversion_rate,
        monthly_cost_usd=cost,
        cost_per_match_usd=cost_per_match,
        recommendation=recommendation,
    )


@router.post("/webhooks/rb2b", response_model=Rb2bWebhookOut)
async def rb2b_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    key: str = Query(default="", max_length=256),
    db: AsyncSession = Depends(get_db),
) -> Rb2bWebhookOut:
    """Receive RB2B's fixed payload through its headerless generic webhook."""
    if not settings.rb2b_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RB2B webhook is not configured")
    if not hmac.compare_digest(key, settings.rb2b_webhook_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook key")
    try:
        content_length = int(request.headers.get("content-length", "0") or "0")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Content-Length") from exc
    if content_length > 64_000:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Payload too large")
    raw_payload = await request.body()
    if len(raw_payload) > 64_000:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Payload too large")
    try:
        payload = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "JSON object required")

    try:
        signal = Rb2bAdapter().normalize(payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    profile, duplicate = await ingest_provider_signal(db, signal)
    await db.commit()
    if not profile.suppressed and not duplicate:
        capture_event(
            "visitor_identity_resolved",
            distinct_id=f"visitor:{profile.id}",
            properties={
                "provider": signal.provider,
                "identity_level": profile.identity_level,
                "repeat_visitor": signal.repeat_visitor,
                "captured_path": profile.last_path,
                "intent_score": profile.intent_score,
            },
        )
        background_tasks.add_task(
            send_visitor_alert,
            VisitorAlert.from_profile(profile),
            signal.repeat_visitor,
        )
    logger.info(
        "visitor provider payload processed (provider=%s duplicate=%s suppressed=%s)",
        signal.provider,
        duplicate,
        profile.suppressed,
    )
    return Rb2bWebhookOut(
        duplicate=duplicate,
        visitor_id=None if profile.suppressed else profile.id,
    )


@router.get("/integrations/status", response_model=VisitorIntegrationStatusOut)
async def visitor_integration_status(
    _admin: CurrentUser = VisitorAdminDep,
) -> VisitorIntegrationStatusOut:
    api_base = settings.api_base_url.rstrip("/")
    return VisitorIntegrationStatusOut(
        rb2b_webhook_configured=bool(settings.rb2b_webhook_secret),
        rb2b_webhook_endpoint=(
            f"{api_base}/api/visitors/webhooks/rb2b?key=<RB2B_WEBHOOK_SECRET>"
        ),
        discord_alerts_configured=settings.discord_alerts_configured,
        discord_commands_configured=settings.discord_commands_configured,
        discord_interactions_endpoint=f"{api_base}/api/discord/interactions",
        discord_guild_configured=bool(settings.discord_guild_id),
        discord_alert_min_intent_score=min(
            100, max(0, settings.discord_alert_min_intent_score)
        ),
        discord_includes_email=settings.discord_include_email,
    )


@router.post("/integrations/discord/test", response_model=DiscordTestOut)
async def test_discord_integration(
    _admin: CurrentUser = VisitorAdminDep,
) -> DiscordTestOut:
    try:
        transport = await send_discord_test_alert()
    except DiscordNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DiscordDeliveryError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return DiscordTestOut(delivered=True, transport=transport)


@router.get("/{visitor_id}", response_model=VisitorDetailOut)
async def visitor_detail(
    visitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = VisitorAdminDep,
) -> VisitorDetailOut:
    profile = await db.get(VisitorProfile, visitor_id)
    if profile is None or profile.suppressed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visitor not found")
    events = list(
        (
            await db.execute(
                select(VisitorEvent)
                .where(VisitorEvent.visitor_id == visitor_id)
                .order_by(VisitorEvent.occurred_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    return VisitorDetailOut(
        **VisitorListItem.model_validate(profile).model_dump(),
        events=[VisitorEventOut.model_validate(event) for event in events],
    )


@router.patch("/{visitor_id}", response_model=VisitorListItem)
async def update_visitor(
    visitor_id: uuid.UUID,
    payload: VisitorUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = VisitorAdminDep,
) -> VisitorListItem:
    profile = await db.get(VisitorProfile, visitor_id)
    if profile is None or profile.suppressed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visitor not found")
    profile.status = payload.status
    await db.commit()
    capture_event(
        "visitor_status_changed",
        distinct_id=admin.user_id,
        properties={"status": payload.status, "visitor_identity_level": profile.identity_level},
    )
    return VisitorListItem.model_validate(profile)


@router.post("/{visitor_id}/suppress", status_code=status.HTTP_204_NO_CONTENT)
async def suppress_visitor(
    visitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = VisitorAdminDep,
) -> Response:
    profile = await db.get(VisitorProfile, visitor_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visitor not found")
    await suppress_profile(db, profile)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{visitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visitor(
    visitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = VisitorAdminDep,
) -> Response:
    profile = await db.get(VisitorProfile, visitor_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visitor not found")
    # Explicit child deletes also work in SQLite test databases where foreign
    # key cascades may be disabled.
    await db.execute(delete(VisitorEvent).where(VisitorEvent.visitor_id == visitor_id))
    await db.execute(delete(VisitorIdentifier).where(VisitorIdentifier.visitor_id == visitor_id))
    await db.delete(profile)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
