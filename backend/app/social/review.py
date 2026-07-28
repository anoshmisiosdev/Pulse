"""Review queue: approve, revise, reject, and schedule generated posts.

Posted and queued items deliberately stay in the queue. It doubles as the audit
trail — an owner should be able to see what actually went out, with the decision
history that got it there, without going somewhere else. Only rejected and
failed posts drop out of the default view.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social import PostReviewEvent, SocialPost
from app.schemas.social import PostOut, ReviewEventOut
from app.social import brand as brand_service
from app.social.editorial import (
    check_draft,
    only_hashtag_errors,
    repair_hashtags,
)

# What the review queue shows by default: everything except rejected and failed.
QUEUE_STATUSES = ("draft", "approved", "staged", "posted")


class ApprovalBlocked(ValueError):
    """Approval refused by the editorial gates, with no override supplied."""


class ScheduleError(ValueError):
    """The requested schedule time can't be used."""


async def _history(db: AsyncSession, post_id: uuid.UUID) -> list[ReviewEventOut]:
    result = await db.execute(
        select(PostReviewEvent)
        .where(PostReviewEvent.post_id == post_id)
        .order_by(PostReviewEvent.decided_at)
    )
    return [
        ReviewEventOut(
            decision=e.decision, reason=e.reason, note=e.note, decided_at=e.decided_at
        )
        for e in result.scalars()
    ]


async def to_out(db: AsyncSession, row: SocialPost) -> PostOut:
    return PostOut(
        id=str(row.id),
        campaign_id=str(row.campaign_id) if row.campaign_id else None,
        campaign_occurrence=row.campaign_occurrence,
        platform=row.platform,
        topic=row.topic,
        post_text=row.post_text,
        hashtags=list(row.hashtags or []),
        status=row.status,
        scheduled_for=row.scheduled_for,
        posted_at=row.posted_at,
        image_url=row.image_url,
        alt_text=row.alt_text,
        source_summary=row.source_summary,
        source_references=list(row.source_references or []),
        editorial=dict(row.editorial or {}),
        warnings=list(row.warnings or []),
        generated_by=row.generated_by,
        published_url=row.published_url,
        failure_reason=row.failure_reason,
        review_history=await _history(db, row.id),
        created_at=row.created_at,
    )


async def list_posts(
    db: AsyncSession,
    *,
    business_id: str,
    status: str | None = None,
    platform: str | None = None,
    campaign_id: str | None = None,
) -> list[SocialPost]:
    stmt = select(SocialPost).where(SocialPost.business_id == uuid.UUID(business_id))
    if status:
        stmt = stmt.where(SocialPost.status == status)
    else:
        stmt = stmt.where(SocialPost.status.in_(QUEUE_STATUSES))
    if platform:
        stmt = stmt.where(SocialPost.platform == platform)
    if campaign_id:
        stmt = stmt.where(SocialPost.campaign_id == uuid.UUID(campaign_id))
    stmt = stmt.order_by(SocialPost.created_at.desc())
    return list((await db.execute(stmt)).scalars())


async def get_post(
    db: AsyncSession, *, business_id: str, post_id: str
) -> SocialPost | None:
    try:
        parsed = uuid.UUID(post_id)
    except ValueError:
        return None
    result = await db.execute(
        select(SocialPost).where(
            SocialPost.id == parsed,
            SocialPost.business_id == uuid.UUID(business_id),
        )
    )
    return result.scalar_one_or_none()


async def record_decision(
    db: AsyncSession,
    *,
    business_id: str,
    post_id: str,
    decision: str,
    reason: str,
    note: str | None = None,
    decided_by: str | None = None,
    business_name: str = "Your business",
) -> SocialPost | None:
    """Apply a review decision, re-running the gates on approval.

    Approving a post that fails a gate is allowed, but only with a written note
    — the override is recorded alongside the errors it overrode.
    """
    row = await get_post(db, business_id=business_id, post_id=post_id)
    if row is None:
        return None

    snapshot = row.post_text

    if decision == "approve":
        kit = await brand_service.load(
            db, business_id=business_id, business_name=business_name
        )
        gate = check_draft(
            platform=row.platform,
            topic=row.topic,
            text=row.post_text,
            hashtags=list(row.hashtags or []),
            avoid=kit.avoid,
        )
        if gate.errors:
            if only_hashtag_errors(gate.errors):
                # The copy is fine and only the tags are wrong, so fix the tags
                # rather than making a human retype them.
                row.hashtags = repair_hashtags(
                    platform=row.platform, topic=row.topic, text=row.post_text
                )
                row.warnings = [
                    *(row.warnings or []),
                    "Hashtags were repaired automatically during approval.",
                ]
                gate = check_draft(
                    platform=row.platform, topic=row.topic, text=row.post_text,
                    hashtags=row.hashtags, avoid=kit.avoid,
                )
            if gate.errors and not note:
                raise ApprovalBlocked(
                    "This post did not pass review: "
                    + " ".join(gate.errors)
                    + " Add a note explaining the override if you want to approve it anyway."
                )
        row.editorial = gate.as_dict()
        row.status = "approved"
    elif decision == "revise":
        row.status = "draft"
    elif decision == "reject":
        row.status = "rejected"
    else:  # pragma: no cover — schema restricts this
        raise ValueError(f"unknown decision: {decision}")

    db.add(
        PostReviewEvent(
            business_id=uuid.UUID(business_id),
            post_id=row.id,
            decision=decision,
            reason=reason,
            note=note,
            decided_by=decided_by,
            decided_at=datetime.now(UTC),
            text_snapshot=snapshot,
        )
    )
    await db.flush()
    return row


async def schedule_post(
    db: AsyncSession, *, business_id: str, post_id: str, scheduled_for: datetime | None
) -> SocialPost | None:
    """Set or clear a post's send time. Status is untouched either way."""
    row = await get_post(db, business_id=business_id, post_id=post_id)
    if row is None:
        return None
    if scheduled_for is not None:
        if scheduled_for <= datetime.now(UTC):
            raise ScheduleError("Schedule time must be in the future.")
        row.scheduled_for = scheduled_for.astimezone(UTC)
    else:
        row.scheduled_for = None
    await db.flush()
    return row
