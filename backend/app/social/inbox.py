"""Engagement inbox: triage inbound social comments and draft replies for approval.

Nothing here ever sends. A reply lives in Churnary until a human approves it and
copies it out — the product deliberately does not claim live LinkedIn or X
access, and the port must not quietly add it.

Drafting has two layers. ``app/social/inbox_rules`` always produces something;
Claude is asked for a better version only when it is safe to ask, and any
failure falls straight back to the template. Three invariants are enforced
*before* a prompt is built, not inside it:

1. a high-risk comment (fraud, legal, refund) never reaches the model — it gets
   the fixed escalation text so a human handles it;
2. spam produces no reply at all;
3. only ``public_safe`` company-brain records are supplied as context, and the
   evidence list names exactly what was supplied.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMError, active_model, complete_text, extract_json_object
from app.models.social import SocialComment
from app.schemas.social import BriefingOut, CommentIn, CommentOut, CommentPatch
from app.social import brain as brain_service
from app.social import brand as brand_service
from app.social.inbox_rules import (
    BriefingItem,
    Suggestion,
    build_suggestion,
    classify,
    rank_context,
    summarize,
)

logger = logging.getLogger("pulse.social.inbox")

MAX_REPLY_CHARS = 900

# Labelled demo fixtures so the inbox is never an empty box on first visit.
# Every row is stamped source="demo" and the UI says so — this is a worked
# example, not scraped data.
_DEMO_FIXTURES: tuple[dict, ...] = (
    {
        "platform": "linkedin",
        "author": "Maya Chen",
        "comment": "Does this integrate with Stripe, and how quickly could we get started?",
        "post_url": "https://www.linkedin.com/feed/",
        "original_post_excerpt": "Stop waiting until customers churn.",
        "minutes_ago": 8,
    },
    {
        "platform": "linkedin",
        "author": "Jordan Lee",
        "comment": "This looks useful. Can I get a demo for our customer success team?",
        "post_url": "https://www.linkedin.com/feed/",
        "original_post_excerpt": "Turn retention signals into timely action.",
        "minutes_ago": 18,
    },
    {
        "platform": "x",
        "author": "Avery Brooks",
        "comment": "We tried something similar and the alerts were too generic to be useful.",
        "post_url": "https://x.com/",
        "original_post_excerpt": "Explain churn risk in plain English.",
        "minutes_ago": 37,
    },
    {
        "platform": "linkedin",
        "author": "Nina Patel",
        "comment": "Congrats on the launch — the approval-first approach is exactly right.",
        "post_url": "https://www.linkedin.com/feed/",
        "original_post_excerpt": "Nothing publishes without your approval.",
        "minutes_ago": 52,
    },
    {
        "platform": "x",
        "author": "Growth King",
        "comment": "Guaranteed 10,000 followers. Follow me for crypto promotion!",
        "post_url": "https://x.com/",
        "original_post_excerpt": "A practical retention workflow.",
        "minutes_ago": 83,
    },
    {
        "platform": "linkedin",
        "author": "Sam Rivera",
        "comment": "I need a refund. This feels like a scam and I am considering legal action.",
        "post_url": "https://www.linkedin.com/feed/",
        "original_post_excerpt": "Customer retention without the guesswork.",
        "minutes_ago": 96,
    },
)


def to_out(row: SocialComment) -> CommentOut:
    return CommentOut(
        id=str(row.id),
        source=row.source,
        platform=row.platform,
        post_url=row.post_url,
        original_post_excerpt=row.original_post_excerpt,
        author=row.author,
        comment=row.comment,
        intent=row.intent,
        sentiment=row.sentiment,
        priority=row.priority,
        risk=row.risk,
        recommended_action=row.recommended_action,
        status=row.status,
        suggested_reply=row.suggested_reply or "",
        approved_reply=row.approved_reply,
        reply_variant=row.reply_variant,
        reply_version=row.reply_version,
        evidence=list(row.evidence or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _draft(
    db: AsyncSession,
    row: SocialComment,
    *,
    business_id: str,
    business_name: str,
    variant: str,
) -> Suggestion:
    """Template draft, upgraded by Claude when it is safe and available."""
    voice = await brand_service.voice(
        db, business_id=business_id, business_name=business_name
    )
    context = await brain_service.drafting_context(db, business_id=business_id)

    template = build_suggestion(
        author=row.author,
        comment=row.comment,
        intent=row.intent,
        risk=row.risk,
        brand=voice,
        context=context,
        variant=variant,
    )

    # Invariants 1 and 2: these two cases must never be model-generated.
    if row.risk == "high" or row.intent == "spam":
        return template

    from app.core.config import settings

    if not settings.llm_configured:
        return template

    supplied = rank_context(row.comment, context)[:2]
    facts = "\n".join(f"- {item.title}: {item.summary}" for item in supplied) or "- (none)"
    length = {
        "shorter": "Keep it to one short sentence.",
        "warmer": "Be a little warmer and more personal; two or three sentences.",
    }.get(variant, "Two or three sentences.")

    system = (
        f"You write public replies to social comments on behalf of {voice.name}. "
        f"Tone: {voice.tone}. {length} "
        "Use only the supplied facts. If they do not answer the question, say the "
        "team will follow up with an accurate answer rather than guessing. "
        "Never invent pricing, features, timelines, results, or customer names. "
        "No hashtags, no emoji, no links. "
        'Return strict JSON: {"reply": "<the reply text>"}'
    )
    user = (
        f"Comment from {row.author} on {row.platform}:\n{row.comment}\n\n"
        f"Approved facts you may use:\n{facts}\n\n"
        f"Brand positioning: {voice.positioning or '(none given)'}"
    )

    for attempt in (1, 2):
        try:
            raw = await complete_text(system, user, max_tokens=400)
            reply = (extract_json_object(raw).get("reply") or "").strip()
            if not reply:
                raise ValueError("model output missing 'reply'")
            logger.info(
                "inbox reply drafted by %s (comment=%s, variant=%s, attempt=%s)",
                active_model(),
                row.id,
                variant,
                attempt,
            )
            return Suggestion(reply[:MAX_REPLY_CHARS], template.evidence)
        except (LLMError, ValueError) as exc:
            logger.warning("inbox draft attempt %s failed (%s); %s", attempt, exc,
                           "retrying" if attempt == 1 else "using template")

    return template


async def _seed(db: AsyncSession, *, business_id: str, business_name: str) -> None:
    now = datetime.now(UTC)
    for fixture in _DEMO_FIXTURES:
        classification = classify(fixture["comment"])
        created = now - timedelta(minutes=fixture["minutes_ago"])
        row = SocialComment(
            business_id=uuid.UUID(business_id),
            source="demo",
            platform=fixture["platform"],
            post_url=fixture["post_url"],
            original_post_excerpt=fixture["original_post_excerpt"],
            author=fixture["author"],
            comment=fixture["comment"],
            intent=classification.intent,
            sentiment=classification.sentiment,
            priority=classification.priority,
            risk=classification.risk,
            recommended_action=classification.recommended_action,
            status="resolved" if classification.intent == "spam" else "drafted",
            created_at=created,
            updated_at=created,
        )
        db.add(row)
        await db.flush()
        # Seed drafts from templates only — seeding must not depend on the LLM
        # being reachable, or a first visit offline would produce a broken inbox.
        voice = await brand_service.voice(
            db, business_id=business_id, business_name=business_name
        )
        context = await brain_service.drafting_context(db, business_id=business_id)
        suggestion = build_suggestion(
            author=row.author, comment=row.comment, intent=row.intent, risk=row.risk,
            brand=voice, context=context, variant="standard",
        )
        row.suggested_reply = suggestion.reply
        row.evidence = suggestion.evidence
        row.reply_version = 1 if suggestion.reply else 0
    await db.flush()


async def list_comments(
    db: AsyncSession, *, business_id: str, business_name: str = "Your business"
) -> list[SocialComment]:
    """Newest first. Seeds the labelled demo fixtures on a business's first look."""
    stmt = (
        select(SocialComment)
        .where(SocialComment.business_id == uuid.UUID(business_id))
        .order_by(SocialComment.created_at.desc())
    )
    rows = list((await db.execute(stmt)).scalars())
    if rows:
        return rows
    await _seed(db, business_id=business_id, business_name=business_name)
    return list((await db.execute(stmt)).scalars())


async def get_comment(
    db: AsyncSession, *, business_id: str, comment_id: str
) -> SocialComment | None:
    try:
        parsed = uuid.UUID(comment_id)
    except ValueError:
        return None
    result = await db.execute(
        select(SocialComment).where(
            SocialComment.id == parsed,
            SocialComment.business_id == uuid.UUID(business_id),
        )
    )
    return result.scalar_one_or_none()


async def create_comment(
    db: AsyncSession, *, business_id: str, payload: CommentIn
) -> SocialComment:
    """Capture a comment the owner pasted in. Classified, but not auto-drafted."""
    classification = classify(payload.comment)
    row = SocialComment(
        business_id=uuid.UUID(business_id),
        source="manual",
        platform=payload.platform,
        post_url=payload.post_url,
        original_post_excerpt=payload.original_post_excerpt,
        author=payload.author,
        comment=payload.comment,
        intent=classification.intent,
        sentiment=classification.sentiment,
        priority=classification.priority,
        risk=classification.risk,
        recommended_action=classification.recommended_action,
        status="needs_reply",
        suggested_reply="",
        reply_variant="standard",
        reply_version=0,
        evidence=[],
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def suggest_reply(
    db: AsyncSession,
    *,
    business_id: str,
    comment_id: str,
    variant: str = "standard",
    business_name: str = "Your business",
) -> SocialComment | None:
    row = await get_comment(db, business_id=business_id, comment_id=comment_id)
    if row is None:
        return None
    suggestion = await _draft(
        db, row, business_id=business_id, business_name=business_name, variant=variant
    )
    row.suggested_reply = suggestion.reply
    row.evidence = suggestion.evidence
    row.reply_variant = variant
    row.reply_version += 1
    # Drafting never reopens something the owner already closed out.
    if row.status != "resolved":
        row.status = "drafted"
    row.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(row)  # updated_at is SQL-side onupdate; see brain.set_public_safe
    return row


class ApprovalError(ValueError):
    """Raised when a comment can't move to approved yet."""


async def update_comment(
    db: AsyncSession, *, business_id: str, comment_id: str, patch: CommentPatch
) -> SocialComment | None:
    row = await get_comment(db, business_id=business_id, comment_id=comment_id)
    if row is None:
        return None

    reply = patch.suggested_reply.strip() if patch.suggested_reply is not None else None
    status = patch.status or row.status

    if status == "approved" and not (reply or row.suggested_reply or "").strip():
        raise ApprovalError("Generate or write a reply before approving it.")

    if reply is not None:
        row.suggested_reply = reply
        row.reply_version += 1
    row.status = status
    if status == "approved":
        # Snapshot exactly what was approved, so a later edit to the draft
        # can't change what the owner signed off on.
        row.approved_reply = reply or row.suggested_reply
    row.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(row)  # updated_at is SQL-side onupdate; see brain.set_public_safe
    return row


async def briefing(
    db: AsyncSession, *, business_id: str, business_name: str = "Your business"
) -> BriefingOut:
    rows = await list_comments(db, business_id=business_id, business_name=business_name)
    items = [
        BriefingItem(
            intent=r.intent,
            risk=r.risk,
            status=r.status,
            comment=r.comment,
            original_post_excerpt=r.original_post_excerpt,
            reply_version=r.reply_version,
            suggested_reply=r.suggested_reply or "",
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    now = datetime.now(UTC)
    result = summarize(items, today=now.date())
    return BriefingOut(**vars(result), generated_at=now)
