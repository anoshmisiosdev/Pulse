"""Social presence API: brand kit, company brain, campaigns, review queue,
publishing, and the engagement inbox.

Every route is scoped to the caller's ``business_id``. Nothing here reads a
tenant id from the request body.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.schemas.social import (
    BrainImportPayload,
    BrainImportResult,
    BrandKitIn,
    BrandKitOut,
    BriefingOut,
    CampaignIn,
    CampaignOut,
    CampaignStatusPatch,
    CommentIn,
    CommentListOut,
    CommentOut,
    CommentPatch,
    ContextItemIn,
    ContextItemOut,
    ContextListOut,
    DecisionIn,
    PostOut,
    PublishIn,
    PublishResultOut,
    ScheduleIn,
    SuggestIn,
)
from app.social import brain as brain_service
from app.social import brand as brand_service
from app.social import campaigns as campaign_service
from app.social import inbox as inbox_service
from app.social import publish as publish_service
from app.social import review as review_service

router = APIRouter(prefix="/social", tags=["social"])


def _context_out(row) -> ContextItemOut:
    return ContextItemOut(
        id=str(row.id),
        title=row.title,
        kind=row.kind,
        summary=row.summary,
        source=row.source,
        date=row.occurred_on,
        tags=list(row.tags or []),
        public_safe=row.public_safe,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── Brand kit ────────────────────────────────────────────────────────────────


@router.get("/brand-kit", response_model=BrandKitOut)
async def get_brand_kit(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> BrandKitOut:
    """Always returns a kit. Version 0 means "not set up yet"."""
    return await brand_service.load(
        db, business_id=user.business_id, business_name=user.business_name
    )


@router.put("/brand-kit", response_model=BrandKitOut)
async def put_brand_kit(
    payload: BrandKitIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> BrandKitOut:
    return await brand_service.save(db, business_id=user.business_id, payload=payload)


# ── Company brain ────────────────────────────────────────────────────────────


@router.get("/brain", response_model=ContextListOut)
async def list_context(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> ContextListOut:
    rows = await brain_service.list_all(db, business_id=user.business_id)
    return ContextListOut(
        data=[_context_out(r) for r in rows],
        total=len(rows),
        public_safe=sum(1 for r in rows if r.public_safe),
    )


@router.post("/brain", response_model=ContextItemOut, status_code=201)
async def add_context(
    payload: ContextItemIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> ContextItemOut:
    row = await brain_service.add(db, business_id=user.business_id, payload=payload)
    return _context_out(row)


@router.patch("/brain/{item_id}", response_model=ContextItemOut)
async def set_context_public_safe(
    item_id: str,
    public_safe: bool = Query(..., description="Release this record for public copy"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> ContextItemOut:
    row = await brain_service.set_public_safe(
        db, business_id=user.business_id, item_id=item_id, public_safe=public_safe
    )
    if row is None:
        raise HTTPException(404, "Not found")
    return _context_out(row)


@router.delete("/brain/{item_id}", status_code=204)
async def delete_context(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> None:
    if not await brain_service.delete(db, business_id=user.business_id, item_id=item_id):
        raise HTTPException(404, "Not found")


@router.post("/brain/import", response_model=BrainImportResult)
async def import_brain(
    payload: BrainImportPayload,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> BrainImportResult:
    """Commit a whole brand kit plus context set in one transaction.

    Splay replayed this over two endpoints from the browser, so a failure
    part-way left half the records in. Here it's all-or-nothing.
    """
    kit = await brand_service.save(
        db, business_id=user.business_id, payload=payload.brand_kit
    )
    imported = [
        _context_out(await brain_service.add(db, business_id=user.business_id, payload=item))
        for item in payload.context
    ]
    return BrainImportResult(brand_kit=kit, imported=imported)


# ── Campaigns ────────────────────────────────────────────────────────────────


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> list[CampaignOut]:
    rows = await campaign_service.list_campaigns(db, business_id=user.business_id)
    return [await campaign_service.to_out(db, r) for r in rows]


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    payload: CampaignIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CampaignOut:
    if payload.start_at <= datetime.now(UTC):
        raise HTTPException(422, "start_at must be in the future.")
    row = await campaign_service.create_campaign(
        db, business_id=user.business_id, payload=payload
    )
    return await campaign_service.to_out(db, row)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def patch_campaign(
    campaign_id: str,
    payload: CampaignStatusPatch,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CampaignOut:
    row = await campaign_service.set_status(
        db, business_id=user.business_id, campaign_id=campaign_id, status=payload.status
    )
    if row is None:
        raise HTTPException(404, "Campaign not found")
    return await campaign_service.to_out(db, row)


@router.post("/campaigns/{campaign_id}/generate", response_model=CampaignOut)
async def generate_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CampaignOut:
    row = await campaign_service.get_campaign(
        db, business_id=user.business_id, campaign_id=campaign_id
    )
    if row is None:
        raise HTTPException(404, "Campaign not found")
    try:
        await campaign_service.generate_posts(
            db,
            business_id=user.business_id,
            campaign_id=campaign_id,
            business_name=user.business_name,
        )
    except campaign_service.SetupRequired as exc:
        raise HTTPException(409, str(exc)) from exc
    except campaign_service.CampaignStartElapsed as exc:
        raise HTTPException(422, str(exc)) from exc
    return await campaign_service.to_out(db, row)


# ── Review queue ─────────────────────────────────────────────────────────────


@router.get("/posts", response_model=list[PostOut])
async def list_posts(
    status: str | None = None,
    platform: str | None = None,
    campaign_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> list[PostOut]:
    rows = await review_service.list_posts(
        db,
        business_id=user.business_id,
        status=status,
        platform=platform,
        campaign_id=campaign_id,
    )
    return [await review_service.to_out(db, r) for r in rows]


@router.post("/posts/{post_id}/decision", response_model=PostOut)
async def decide_post(
    post_id: str,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> PostOut:
    try:
        row = await review_service.record_decision(
            db,
            business_id=user.business_id,
            post_id=post_id,
            decision=payload.decision,
            reason=payload.reason,
            note=payload.note,
            decided_by=user.email,
            business_name=user.business_name,
        )
    except review_service.ApprovalBlocked as exc:
        raise HTTPException(422, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "Post not found")
    return await review_service.to_out(db, row)


@router.put("/posts/{post_id}/schedule", response_model=PostOut)
async def schedule_post(
    post_id: str,
    payload: ScheduleIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> PostOut:
    try:
        row = await review_service.schedule_post(
            db,
            business_id=user.business_id,
            post_id=post_id,
            scheduled_for=payload.scheduled_for,
        )
    except review_service.ScheduleError as exc:
        raise HTTPException(422, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "Post not found")
    return await review_service.to_out(db, row)


@router.post("/posts/publish", response_model=list[PublishResultOut])
async def publish_posts(
    payload: PublishIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> list[PublishResultOut]:
    """Publish approved posts. ``confirm`` must be true — there is no default."""
    try:
        outcomes = await publish_service.publish_approved(
            db, business_id=user.business_id, post_id=payload.post_id, mode=payload.mode
        )
    except publish_service.NothingToPublish as exc:
        raise HTTPException(409, str(exc)) from exc
    except publish_service.PublishNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    return [
        PublishResultOut(
            post_id=o.post_id,
            ok=o.ok,
            status=o.status,
            message=o.message,
            provider_post_ids=o.provider_post_ids,
            published_url=o.published_url,
        )
        for o in outcomes
    ]


# ── Engagement inbox ─────────────────────────────────────────────────────────


@router.get("/inbox", response_model=CommentListOut)
async def list_inbox(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> CommentListOut:
    rows = await inbox_service.list_comments(
        db, business_id=user.business_id, business_name=user.business_name
    )
    return CommentListOut(
        data=[inbox_service.to_out(r) for r in rows],
        total=len(rows),
        needs_reply=sum(1 for r in rows if r.status in ("needs_reply", "drafted")),
        high_priority=sum(
            1 for r in rows if r.priority == "high" and r.status != "resolved"
        ),
        # These are demo fixtures or comments the owner pasted in. Churnary does
        # not read from LinkedIn or X, and the UI says so.
        demo_mode=True,
    )


@router.get("/inbox/briefing", response_model=BriefingOut)
async def inbox_briefing(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> BriefingOut:
    return await inbox_service.briefing(
        db, business_id=user.business_id, business_name=user.business_name
    )


@router.post("/inbox", response_model=CommentOut, status_code=201)
async def capture_comment(
    payload: CommentIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CommentOut:
    row = await inbox_service.create_comment(
        db, business_id=user.business_id, payload=payload
    )
    return inbox_service.to_out(row)


@router.post("/inbox/{comment_id}/suggest", response_model=CommentOut)
async def suggest_reply(
    comment_id: str,
    payload: SuggestIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CommentOut:
    row = await inbox_service.suggest_reply(
        db,
        business_id=user.business_id,
        comment_id=comment_id,
        variant=payload.variant,
        business_name=user.business_name,
    )
    if row is None:
        raise HTTPException(404, "Comment not found")
    return inbox_service.to_out(row)


@router.patch("/inbox/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: str,
    payload: CommentPatch,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CommentOut:
    try:
        row = await inbox_service.update_comment(
            db, business_id=user.business_id, comment_id=comment_id, patch=payload
        )
    except inbox_service.ApprovalError as exc:
        raise HTTPException(422, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "Comment not found")
    return inbox_service.to_out(row)


# ── Setup status (drives the frontend's empty states) ────────────────────────


@router.get("/status")
async def social_status(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> dict:
    kit = await brand_service.current_row(db, business_id=user.business_id)
    return {
        "brand_kit_version": kit.version if kit else 0,
        "public_context_count": await brain_service.public_count(
            db, business_id=user.business_id
        ),
        "buffer_configured": settings.buffer_configured,
        "llm_configured": settings.llm_configured,
        "publish_mode": settings.buffer_publish_mode,
    }


@router.get("/buffer/connect")
async def buffer_connect(user: CurrentUser = CurrentUserDep) -> dict:
    """Where to send an owner to set Buffer up, plus whether they're connected.

    Scaffold only — there is deliberately no API key and no token exchange
    here. ``connected`` answers "has *this business* authorized Buffer?", which
    nothing can set to true yet: the shared ``BUFFER_API_KEY`` in the
    environment is one Buffer account for the whole deployment, so it is not an
    answer to that question and deliberately doesn't count.

    ``oauth_ready`` stays false until the real handshake exists
    (``auth.buffer.com``, Authorization Code + PKCE, one refresh-capable token
    encrypted per business). The frontend uses it to keep step 3 disabled.
    """
    return {
        "connected": False,
        "oauth_ready": False,
        "signup_url": settings.buffer_signup_url,
        "channels_url": settings.buffer_channels_url,
    }
