"""Recurring social campaigns: one brief becomes a run of scheduled drafts.

Generation never auto-approves and never publishes. It produces drafts that
already carry their slot time, so a campaign post sits in the review queue with
its future send time attached.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMError, active_model, complete_text, extract_json_object
from app.models.social import SocialCampaign, SocialPost
from app.schemas.social import CampaignIn, CampaignOut, SlotOut
from app.social import brain as brain_service
from app.social import brand as brand_service
from app.social.editorial import check_draft, repair_hashtags
from app.social.scheduling import as_utc, campaign_slots

logger = logging.getLogger("pulse.social.campaigns")


class SetupRequired(RuntimeError):
    """Generation can't start until the business has finished setting up."""


class CampaignStartElapsed(ValueError):
    """The campaign's start time is already in the past."""


def slots_for(row: SocialCampaign) -> list[SlotOut]:
    return [
        SlotOut(occurrence=s.occurrence, scheduled_for=s.scheduled_for, theme=s.theme)
        for s in campaign_slots(
            brief=row.brief,
            themes=list(row.themes or []),
            start_at=as_utc(row.start_at),
            timezone=row.timezone,
            interval_weeks=row.interval_weeks,
            occurrences=row.occurrences,
        )
    ]


async def to_out(db: AsyncSession, row: SocialCampaign) -> CampaignOut:
    count = (
        await db.scalar(
            select(func.count())
            .select_from(SocialPost)
            .where(SocialPost.campaign_id == row.id)
        )
    ) or 0
    return CampaignOut(
        id=str(row.id),
        name=row.name,
        brief=row.brief,
        themes=list(row.themes or []),
        platforms=list(row.platforms or []),
        start_at=row.start_at,
        timezone=row.timezone,
        interval_weeks=row.interval_weeks,
        occurrences=row.occurrences,
        status=row.status,
        last_error=row.last_error,
        slots=slots_for(row),
        post_count=count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_campaigns(db: AsyncSession, *, business_id: str) -> list[SocialCampaign]:
    result = await db.execute(
        select(SocialCampaign)
        .where(SocialCampaign.business_id == uuid.UUID(business_id))
        .order_by(SocialCampaign.created_at.desc())
    )
    return list(result.scalars())


async def get_campaign(
    db: AsyncSession, *, business_id: str, campaign_id: str
) -> SocialCampaign | None:
    try:
        parsed = uuid.UUID(campaign_id)
    except ValueError:
        return None
    result = await db.execute(
        select(SocialCampaign).where(
            SocialCampaign.id == parsed,
            SocialCampaign.business_id == uuid.UUID(business_id),
        )
    )
    return result.scalar_one_or_none()


async def create_campaign(
    db: AsyncSession, *, business_id: str, payload: CampaignIn
) -> SocialCampaign:
    row = SocialCampaign(
        business_id=uuid.UUID(business_id),
        name=payload.name,
        brief=payload.brief,
        themes=payload.themes,
        platforms=payload.platforms,
        start_at=payload.start_at.astimezone(UTC),
        timezone=payload.timezone,
        interval_weeks=payload.interval_weeks,
        occurrences=payload.occurrences,
        status="draft",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def set_status(
    db: AsyncSession, *, business_id: str, campaign_id: str, status: str
) -> SocialCampaign | None:
    row = await get_campaign(db, business_id=business_id, campaign_id=campaign_id)
    if row is None:
        return None
    row.status = status
    if status != "draft":
        row.last_error = None
    await db.flush()
    await db.refresh(row)  # updated_at is SQL-side onupdate; see brain.set_public_safe
    return row


async def assert_generation_ready(db: AsyncSession, *, business_id: str) -> None:
    """Both gates that must pass before Claude is allowed to write anything."""
    kit = await brand_service.current_row(db, business_id=business_id)
    if kit is None or kit.version < 1:
        raise SetupRequired("Save your brand kit before generating posts.")
    if await brain_service.public_count(db, business_id=business_id) == 0:
        raise SetupRequired(
            "Add at least one company-brain item approved for public content "
            "before generating posts."
        )


# ── Post drafting ────────────────────────────────────────────────────────────


def _fallback_text(*, theme: str, brief: str, fact: str, platform: str) -> str:
    """Static copy so a campaign still generates when the model is unreachable."""
    lead = fact or brief
    if platform == "x":
        return f"{theme}. {lead}"[:240]
    return (
        f"{theme}\n\n{lead}\n\n"
        "If that sounds like something you've run into, we'd love to hear how "
        "you're handling it."
    )


async def _draft_post(
    *, platform: str, theme: str, brief: str, kit, facts: list[tuple[str, str]]
) -> tuple[str, list[str], str]:
    """Return (text, hashtags, generated_by) for one slot on one platform."""
    fact_lines = "\n".join(f"- {title}: {summary}" for title, summary in facts)
    first_fact = facts[0][1] if facts else ""

    limits = (
        "Hard limit 240 characters. No more than one hashtag."
        if platform == "x"
        else "Between 500 and 1200 characters. Exactly 3 or 4 hashtags."
    )
    system = (
        f"You write {platform} posts for {kit.name}, a local business. "
        f"Audience: {kit.audience}. Tone: {kit.tone}. Positioning: {kit.positioning}. "
        f"Never say: {', '.join(kit.avoid) or '(nothing specified)'}. "
        f"{limits} "
        "Write only from the supplied facts — never invent offers, prices, "
        "results, or customer names. "
        'Return strict JSON: {"text": "<post>", "hashtags": ["Tag", "Tag"]}'
    )
    user = (
        f"Campaign brief: {brief}\nThis week's focus: {theme}\n\n"
        f"Approved facts you may use:\n{fact_lines or '- (none)'}"
    )

    from app.core.config import settings

    if settings.llm_configured:
        for attempt in (1, 2):
            try:
                raw = await complete_text(system, user, max_tokens=900)
                data = extract_json_object(raw)
                text = (data.get("text") or "").strip()
                if not text:
                    raise ValueError("model output missing 'text'")
                tags = [str(t).strip().lstrip("#") for t in (data.get("hashtags") or [])]
                return text, [t for t in tags if t], "claude"
            except (LLMError, ValueError) as exc:
                logger.warning(
                    "campaign draft attempt %s failed (%s); %s",
                    attempt, exc, "retrying" if attempt == 1 else "using template",
                )

    text = _fallback_text(theme=theme, brief=brief, fact=first_fact, platform=platform)
    return text, repair_hashtags(platform=platform, topic=theme, text=text), "fallback"


async def generate_posts(
    db: AsyncSession, *, business_id: str, campaign_id: str, business_name: str
) -> int:
    """Fill every future slot with a draft. Returns how many were created.

    Regeneration replaces this campaign's *drafts* only. Splay replaced every
    post; here anything already approved, scheduled, or published survives, so
    re-running generation can't destroy work an owner already signed off on.
    """
    campaign = await get_campaign(db, business_id=business_id, campaign_id=campaign_id)
    if campaign is None:
        return 0
    if as_utc(campaign.start_at) <= datetime.now(UTC):
        raise CampaignStartElapsed("Campaign start time must still be in the future.")

    await assert_generation_ready(db, business_id=business_id)

    campaign.status = "generating"
    campaign.last_error = None
    await db.flush()

    try:
        existing = await db.execute(
            select(SocialPost).where(
                SocialPost.campaign_id == campaign.id, SocialPost.status == "draft"
            )
        )
        for stale in existing.scalars():
            await db.delete(stale)
        await db.flush()

        kit = await brand_service.load(
            db, business_id=business_id, business_name=business_name
        )
        kit_row = await brand_service.current_row(db, business_id=business_id)
        public = await brain_service.list_public(db, business_id=business_id)

        created = 0
        for slot in slots_for(campaign):
            matched = brain_service.search(public, slot.theme)[:2]
            facts = [(r.title, r.summary) for r in matched]
            references = [r.source or f"brain/{r.id}" for r in matched]

            for platform in campaign.platforms:
                text, hashtags, generated_by = await _draft_post(
                    platform=platform, theme=slot.theme, brief=campaign.brief,
                    kit=kit, facts=facts,
                )
                gate = check_draft(
                    platform=platform, topic=slot.theme, text=text,
                    hashtags=hashtags, avoid=kit.avoid,
                )
                db.add(
                    SocialPost(
                        business_id=uuid.UUID(business_id),
                        campaign_id=campaign.id,
                        campaign_occurrence=slot.occurrence,
                        brand_kit_version_id=kit_row.id if kit_row else None,
                        platform=platform,
                        topic=slot.theme,
                        post_text=text,
                        hashtags=hashtags,
                        status="draft",
                        scheduled_for=slot.scheduled_for,
                        source_summary=facts[0][1] if facts else None,
                        source_references=references,
                        editorial=gate.as_dict(),
                        warnings=gate.warnings,
                        generated_by=generated_by,
                        generation_model=active_model() if generated_by == "claude" else None,
                    )
                )
                created += 1

        campaign.status = "active"
        await db.flush()
        logger.info("campaign %s generated %d posts", campaign.id, created)
        return created
    except Exception as exc:
        campaign.status = "draft"
        campaign.last_error = str(exc)[:500]
        await db.flush()
        raise
