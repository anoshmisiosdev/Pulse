"""Review-request settings, and a manual "draft them now".

Changing the settings is owner-only: enabling this sets up drafting that runs
unattended and puts the owner's review link in front of customers. Drafting on
demand is open to any member, since it only queues pending requests that
still need approval.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.guard import EntitlementsDep, require_channel
from app.billing.limits import Entitlements
from app.campaigns import reviews
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep, OwnerDep
from app.models import Business
from app.services.generation_log import record_audit
from app.services.ingest import _uuid

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewSettingsOut(BaseModel):
    enabled: bool
    review_url: str | None
    channel: str
    delay_days: int
    lookback_days: int = reviews.LOOKBACK_DAYS
    cooldown_days: int = reviews.REVIEW_COOLDOWN_DAYS


class ReviewSettingsIn(BaseModel):
    enabled: bool
    review_url: str | None = Field(default=None, max_length=500)
    channel: Literal["email", "sms"] = "email"
    delay_days: int = Field(default=2, ge=0, le=30)


class QueueOut(BaseModel):
    queued: int
    skipped: dict[str, int]


def _out(business: Business) -> ReviewSettingsOut:
    return ReviewSettingsOut(
        enabled=business.review_request_enabled,
        review_url=business.review_link,
        channel=business.review_request_channel or "email",
        delay_days=business.review_request_delay_days or 0,
    )


async def _business(db: AsyncSession, user: CurrentUser) -> Business:
    business = await db.get(Business, _uuid(user.business_id))
    if business is None:
        raise HTTPException(
            404, "Connect a data source first — review requests follow recovered customers."
        )
    return business


@router.get("/settings", response_model=ReviewSettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> ReviewSettingsOut:
    return _out(await _business(db, user))


@router.put("/settings", response_model=ReviewSettingsOut)
async def put_settings(
    payload: ReviewSettingsIn,
    db: AsyncSession = Depends(get_db),
    owner: CurrentUser = OwnerDep,
    ent: Entitlements = EntitlementsDep,
) -> ReviewSettingsOut:
    business = await _business(db, owner)
    try:
        url = reviews.validate_review_url(payload.review_url)
    except reviews.ReviewSettingsError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if payload.enabled:
        if not url:
            raise HTTPException(422, detail="Add your review link before turning this on.")
        require_channel(ent, payload.channel)
        if payload.channel == "sms":
            _subject, body = reviews.review_copy(
                business_name=business.name, first_name=None, review_url=url, channel="sms"
            )
            if len(body) > reviews.SMS_MAX_CHARS:
                raise HTTPException(
                    422,
                    detail="That link is too long to fit in a text message. Use email, "
                    "or a shorter link.",
                )

    business.review_request_enabled = payload.enabled
    business.review_link = url
    business.review_request_channel = payload.channel
    business.review_request_delay_days = payload.delay_days
    await record_audit(
        db,
        business_id=business.id,
        action="review_settings_changed",
        actor=owner,
        subject_type="business",
        subject_id=str(business.id),
        summary=(
            f"Review requests {'on' if payload.enabled else 'off'} "
            f"({payload.channel}, {payload.delay_days}-day delay)"
        ),
    )
    await db.commit()
    return _out(business)


@router.post("/queue", response_model=QueueOut)
async def queue_now(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> QueueOut:
    """Draft review requests now instead of waiting for the hourly run."""
    summary = await reviews.queue_review_requests(db, business_id=user.business_id)
    await db.commit()
    return QueueOut(queued=summary.queued, skipped=summary.skipped)
