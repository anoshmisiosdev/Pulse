"""Campaign copy generation and the owner-driven campaign loop.

Approve-to-send is the default mode product-wide: creating a campaign generates
copy and queues every message as ``pending``. Nothing leaves the building until
an explicit approve call.

The single-shot ``/generate`` endpoint stays as it was - the dashboard uses it
to preview copy for one customer without persisting anything.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.guard import EntitlementsDep, require_channel
from app.billing.limits import Entitlements
from app.campaigns import manual
from app.campaigns.experiments import results_for
from app.campaigns.generator import CampaignContext, generate_campaign_traced
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.posthog_client import capture_event
from app.models import (
    Campaign,
    CampaignSend,
    Customer,
    EngagementEvent,
    RecoveryAttribution,
)
from app.schemas.api import GenerateCampaignIn, GeneratedCopyOut
from app.schemas.campaigns import (
    ApprovalSummaryOut,
    ArmResultOut,
    AuditLogOut,
    CampaignCreateIn,
    CampaignDetailOut,
    CampaignOut,
    CampaignSendSummary,
    CampaignStats,
    ExperimentOut,
    GenerationLogOut,
    SendEditIn,
)
from app.services.generation_log import (
    list_audit,
    list_generations,
    record_audit,
    record_generation,
)
from app.services.ingest import _uuid
from app.services.rag.knowledge_store import search_knowledge

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_ENGAGEMENT_KINDS = {"email_open": "opened", "email_click": "clicked"}


def _iso(value) -> str | None:
    return value.isoformat() if value else None


@router.post("/generate", response_model=GeneratedCopyOut)
async def generate(
    payload: GenerateCampaignIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> GeneratedCopyOut:
    if payload.channel not in ("email", "sms"):
        raise HTTPException(status_code=422, detail="channel must be 'email' or 'sms'")
    # Refuse before spending an LLM call on copy the plan can't send.
    require_channel(ent, payload.channel)

    retrieval_query = (
        f"win-back {payload.channel} for {payload.customer_name}. "
        f"Reasons: {'; '.join(payload.risk_reasons)}. Incentive: {payload.incentive or 'none'}."
    )
    knowledge = await search_knowledge(db, business_id=user.business_id, query=retrieval_query)

    ctx = CampaignContext(
        business_name=payload.business_name,
        business_type=payload.business_type,
        customer_name=payload.customer_name,
        channel=payload.channel,
        tone=payload.tone,
        incentive=payload.incentive,
        risk_reasons=payload.risk_reasons,
        history_summary=payload.history_summary,
        knowledge_snippets=[row.content for row in knowledge],
    )
    copy, trace = await generate_campaign_traced(ctx)
    # CLAUDE.md: log every generation (prompt + output + model version).
    await record_generation(
        db,
        business_id=user.business_id,
        purpose=f"campaign_{payload.channel}",
        system_prompt=trace.system_prompt,
        user_prompt=trace.user_prompt,
        raw_output=trace.raw_output,
        model=trace.model,
        generated_by=copy.generated_by,
        attempts=trace.attempts,
        latency_ms=trace.latency_ms,
        error=trace.error,
    )
    capture_event(
        "campaign_generated",
        distinct_id=user.user_id,
        properties={
            "channel": payload.channel,
            "tone": payload.tone,
            "has_incentive": bool(payload.incentive),
            "risk_reason_count": len(payload.risk_reasons),
            "knowledge_snippet_count": len(ctx.knowledge_snippets),
            "generated_by": copy.generated_by,
        },
    )
    return GeneratedCopyOut(
        channel=payload.channel,
        subject=copy.subject,
        body=copy.body,
        generated_by=copy.generated_by,
        model=copy.model,
    )


# -- Persisted campaigns ------------------------------------------------------


async def _stats_for(db: AsyncSession, campaign_ids: list[uuid.UUID]) -> dict:
    """Send/engagement/recovery counts for several campaigns in three queries.

    Aggregated in SQL rather than by loading sends: a campaign to 500 people
    shouldn't pull 500 rows into memory just to count statuses, and the list
    view asks for this on every page load.
    """
    if not campaign_ids:
        return {}

    out: dict[uuid.UUID, dict] = {
        cid: {
            "total": 0,
            "pending": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "opened": 0,
            "clicked": 0,
            "recovered": 0,
            "revenue_recovered": 0.0,
        }
        for cid in campaign_ids
    }

    status_rows = (
        await db.execute(
            select(CampaignSend.campaign_id, CampaignSend.status, func.count())
            .where(CampaignSend.campaign_id.in_(campaign_ids))
            .group_by(CampaignSend.campaign_id, CampaignSend.status)
        )
    ).all()
    for cid, status, count in status_rows:
        bucket = out.get(cid)
        if bucket is None:
            continue
        bucket["total"] += count
        if status == "pending":
            bucket["pending"] += count
        elif status in ("sent", "delivered"):
            bucket["sent"] += count
        elif status == "failed":
            bucket["failed"] += count
        elif status == "skipped":
            bucket["skipped"] += count

    engagement_rows = (
        await db.execute(
            select(CampaignSend.campaign_id, EngagementEvent.kind, func.count())
            .join(EngagementEvent, EngagementEvent.campaign_send_id == CampaignSend.id)
            .where(
                CampaignSend.campaign_id.in_(campaign_ids),
                EngagementEvent.kind.in_(tuple(_ENGAGEMENT_KINDS)),
            )
            .group_by(CampaignSend.campaign_id, EngagementEvent.kind)
        )
    ).all()
    for cid, kind, count in engagement_rows:
        bucket = out.get(cid)
        if bucket is not None:
            bucket[_ENGAGEMENT_KINDS[kind]] += count

    recovery_rows = (
        await db.execute(
            select(
                CampaignSend.campaign_id,
                func.count(RecoveryAttribution.id),
                func.coalesce(func.sum(RecoveryAttribution.estimated_value), 0),
            )
            .join(RecoveryAttribution, RecoveryAttribution.campaign_send_id == CampaignSend.id)
            .where(CampaignSend.campaign_id.in_(campaign_ids))
            .group_by(CampaignSend.campaign_id)
        )
    ).all()
    for cid, count, value in recovery_rows:
        bucket = out.get(cid)
        if bucket is not None:
            bucket["recovered"] = count
            bucket["revenue_recovered"] = round(float(value or 0), 2)

    return out


def _campaign_out(campaign: Campaign, stats: dict) -> CampaignOut:
    return CampaignOut(
        id=str(campaign.id),
        name=campaign.name,
        channel=campaign.channel,
        status=campaign.status,
        kind=campaign.kind or "winback",
        incentive=campaign.incentive,
        ab_test=campaign.ab_test,
        variant_b_incentive=campaign.variant_b_incentive,
        created_at=_iso(campaign.created_at) or "",
        stats=CampaignStats(**stats),
    )


async def _load_campaign(db: AsyncSession, user: CurrentUser, campaign_id: str) -> Campaign:
    try:
        parsed = _uuid(campaign_id)
    except (ValueError, AttributeError):
        raise HTTPException(404, "Not found") from None
    campaign = await db.get(Campaign, parsed)
    if campaign is None or campaign.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Not found")
    return campaign


async def _load_send(db: AsyncSession, user: CurrentUser, send_id: str) -> CampaignSend:
    try:
        parsed = _uuid(send_id)
    except (ValueError, AttributeError):
        raise HTTPException(404, "Not found") from None
    send = await db.get(CampaignSend, parsed)
    if send is None or send.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Not found")
    return send


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CampaignOut]:
    rows = (
        (
            await db.execute(
                select(Campaign)
                .where(Campaign.business_id == _uuid(user.business_id))
                .order_by(Campaign.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    stats = await _stats_for(db, [c.id for c in rows])
    return [_campaign_out(c, stats[c.id]) for c in rows]


@router.post("", response_model=CampaignDetailOut, status_code=201)
async def create_campaign(
    payload: CampaignCreateIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> CampaignDetailOut:
    """Generate copy for the selected customers and queue it for approval.

    Sends nothing. Every message lands as ``pending``.
    """
    require_channel(ent, payload.channel)
    try:
        result = await manual.build_campaign(
            db,
            user=user,
            name=payload.name,
            channel=payload.channel,
            customer_ids=payload.customer_ids,
            incentive=payload.incentive,
            tone=payload.tone,
            ab_test=payload.ab_test,
            variant_b_incentive=payload.variant_b_incentive,
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()

    capture_event(
        "campaign_created",
        distinct_id=user.user_id,
        properties={
            "channel": payload.channel,
            "recipients": len(result.sends),
            "skipped": len(result.skipped),
            "ab_test": payload.ab_test,
            "has_incentive": bool(payload.incentive),
        },
    )
    detail = await _detail(db, user, result.campaign)
    detail.skipped = result.skipped
    return detail


async def _detail(
    db: AsyncSession, user: CurrentUser, campaign: Campaign
) -> CampaignDetailOut:
    rows = (
        await db.execute(
            select(CampaignSend, Customer)
            .join(Customer, Customer.id == CampaignSend.customer_id)
            .where(CampaignSend.campaign_id == campaign.id)
            .order_by(CampaignSend.created_at)
        )
    ).all()

    engaged: dict[uuid.UUID, set[str]] = {}
    if rows:
        send_ids = [send.id for send, _ in rows]
        events = (
            await db.execute(
                select(EngagementEvent.campaign_send_id, EngagementEvent.kind).where(
                    EngagementEvent.campaign_send_id.in_(send_ids),
                    EngagementEvent.kind.in_(tuple(_ENGAGEMENT_KINDS)),
                )
            )
        ).all()
        for send_id, kind in events:
            engaged.setdefault(send_id, set()).add(_ENGAGEMENT_KINDS[kind])

    stats = await _stats_for(db, [campaign.id])
    base = _campaign_out(campaign, stats[campaign.id])
    return CampaignDetailOut(
        **base.model_dump(),
        sends=[
            CampaignSendSummary(
                id=str(send.id),
                customer_id=str(send.customer_id),
                customer_name=(
                    f"{customer.first_name or ''} {customer.last_name or ''}".strip()
                    or "Customer"
                ),
                channel=send.channel,
                subject=send.subject,
                body=send.body,
                status=send.status,
                generated_by=send.generated_by,
                variant=send.variant,
                sent_at=_iso(send.sent_at),
                failure_reason=send.failure_reason,
                opened="opened" in engaged.get(send.id, set()),
                clicked="clicked" in engaged.get(send.id, set()),
            )
            for send, customer in rows
        ],
    )


@router.get("/{campaign_id}", response_model=CampaignDetailOut)
async def get_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CampaignDetailOut:
    campaign = await _load_campaign(db, user, campaign_id)
    return await _detail(db, user, campaign)


@router.post("/{campaign_id}/approve", response_model=ApprovalSummaryOut)
async def approve_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> ApprovalSummaryOut:
    """Approve and send every pending message on this campaign."""
    campaign = await _load_campaign(db, user, campaign_id)
    require_channel(ent, campaign.channel)
    try:
        summary = await manual.approve_campaign(db, user=user, campaign=campaign)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    capture_event(
        "campaign_approved_bulk",
        distinct_id=user.user_id,
        properties={
            "channel": campaign.channel,
            "sent": summary.sent,
            "failed": summary.failed,
            "deferred": summary.deferred,
        },
    )
    return ApprovalSummaryOut(
        sent=summary.sent,
        failed=summary.failed,
        deferred=summary.deferred,
        skipped=summary.skipped,
    )


@router.patch("/sends/{send_id}", response_model=CampaignSendSummary)
async def edit_send(
    send_id: str,
    payload: SendEditIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CampaignSendSummary:
    """Rewrite a pending message before it goes out."""
    send = await _load_send(db, user, send_id)
    try:
        await manual.edit_send(
            db, user=user, send=send, subject=payload.subject, body=payload.body
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    customer = await db.get(Customer, send.customer_id)
    return _send_summary(send, customer)


@router.post("/sends/{send_id}/regenerate", response_model=CampaignSendSummary)
async def regenerate_send(
    send_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> CampaignSendSummary:
    """Ask for a different draft for one pending message."""
    send = await _load_send(db, user, send_id)
    require_channel(ent, send.channel)
    try:
        await manual.regenerate_send(db, user=user, send=send)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    customer = await db.get(Customer, send.customer_id)
    return _send_summary(send, customer)


@router.post("/sends/{send_id}/cancel", response_model=CampaignSendSummary)
async def cancel_send(
    send_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CampaignSendSummary:
    send = await _load_send(db, user, send_id)
    try:
        await manual.cancel_send(db, user=user, send=send)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    customer = await db.get(Customer, send.customer_id)
    return _send_summary(send, customer)


def _send_summary(send: CampaignSend, customer: Customer | None) -> CampaignSendSummary:
    name = "Customer"
    if customer is not None:
        name = (
            f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer"
        )
    return CampaignSendSummary(
        id=str(send.id),
        customer_id=str(send.customer_id),
        customer_name=name,
        channel=send.channel,
        subject=send.subject,
        body=send.body,
        status=send.status,
        generated_by=send.generated_by,
        variant=send.variant,
        sent_at=_iso(send.sent_at),
        failure_reason=send.failure_reason,
    )


@router.get("/{campaign_id}/experiment", response_model=ExperimentOut)
async def campaign_experiment(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> ExperimentOut:
    """A/B results, with an explicit "too early to tell" when underpowered."""
    campaign = await _load_campaign(db, user, campaign_id)
    if not campaign.ab_test:
        raise HTTPException(422, detail="This campaign isn't an A/B test.")
    result = await results_for(
        db, business_id=user.business_id, campaign_id=str(campaign.id)
    )

    def arm(a) -> ArmResultOut:
        return ArmResultOut(
            variant=a.variant,
            sent=a.sent,
            recovered=a.recovered,
            recovery_rate=round(a.recovery_rate, 4),
            revenue_recovered=a.revenue_recovered,
        )

    return ExperimentOut(
        a=arm(result.a),
        b=arm(result.b),
        lift_pp=result.lift_pp,
        confident=result.confident,
        verdict=result.verdict,
        winner=result.winner,
    )


# -- Transparency: generation + audit logs ------------------------------------


@router.get("/logs/generations", response_model=list[GenerationLogOut])
async def generation_logs(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    purpose: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[GenerationLogOut]:
    """Every LLM call made for this business: prompt, output, model version.

    Exists so "why did it write that?" has an answer, and so a copy-quality
    regression can be traced to a prompt change or a model change.
    """
    rows = await list_generations(
        db, business_id=user.business_id, purpose=purpose, limit=limit
    )
    return [
        GenerationLogOut(
            id=str(row.id),
            purpose=row.purpose,
            model=row.model,
            generated_by=row.generated_by,
            attempts=row.attempts,
            latency_ms=row.latency_ms,
            error=row.error,
            created_at=_iso(row.created_at) or "",
            system_prompt=row.system_prompt,
            user_prompt=row.user_prompt,
            raw_output=row.raw_output,
            campaign_send_id=str(row.campaign_send_id) if row.campaign_send_id else None,
        )
        for row in rows
    ]


@router.get("/logs/audit", response_model=list[AuditLogOut])
async def audit_logs(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogOut]:
    """Who approved, edited or cancelled what, and when."""
    rows = await list_audit(db, business_id=user.business_id, action=action, limit=limit)
    return [
        AuditLogOut(
            id=str(row.id),
            action=row.action,
            actor_email=row.actor_email,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            summary=row.summary,
            created_at=_iso(row.created_at) or "",
        )
        for row in rows
    ]


__all__ = ["router", "record_audit"]
