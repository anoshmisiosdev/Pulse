"""Social presence services: brand kit, company brain, inbox, review, publishing.

Runs against in-memory SQLite. The LLM is stubbed to fail throughout so the
deterministic template path is exercised — that path is the product's floor and
has to work on its own. One test covers the Claude path explicitly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.llm import LLMError
from app.models.social import SocialPost
from app.schemas.social import (
    BrandColors,
    BrandKitIn,
    BrandTypography,
    CampaignIn,
    CommentIn,
    CommentPatch,
    ContextItemIn,
)
from app.social import brain as brain_service
from app.social import brand as brand_service
from app.social import campaigns as campaign_service
from app.social import inbox as inbox_service
from app.social import publish as publish_service
from app.social import review as review_service

BUSINESS_ID = str(uuid.uuid4())
OTHER_BUSINESS_ID = str(uuid.uuid4())


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the template fallback. A developer's real .env must not make the
    suite fire live model calls."""
    async def _fail(*args, **kwargs):
        raise LLMError("no model in tests")

    monkeypatch.setattr(inbox_service, "complete_text", _fail)
    monkeypatch.setattr(campaign_service, "complete_text", _fail)


def _kit(**overrides) -> BrandKitIn:
    base = dict(
        name="Hayward Coffee Co.",
        tagline="Your morning, sorted.",
        audience="Regulars within a mile of the shop",
        tone="warm, plain-spoken",
        positioning="A neighbourhood coffee bar that remembers your order.",
        avoid=["world-class"],
        colors=BrandColors(
            primary="#b4532a", secondary="#a23b1e", accent="#efe3d3",
            background="#fbf6ee", text="#2a211c",
        ),
        typography=BrandTypography(heading_family="Spectral", body_family="Hanken Grotesk"),
        logo_url=None,
    )
    return BrandKitIn(**{**base, **overrides})


# ── Brand kit ────────────────────────────────────────────────────────────────


async def test_unsaved_brand_kit_is_version_zero(db):
    kit = await brand_service.load(db, business_id=BUSINESS_ID, business_name="Hayward")
    assert kit.version == 0
    assert kit.name == "Hayward"


async def test_every_save_appends_a_version(db):
    first = await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    second = await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    assert (first.version, second.version) == (1, 2)
    assert (await brand_service.load(db, business_id=BUSINESS_ID)).version == 2


async def test_hex_colors_are_normalised_to_uppercase(db):
    saved = await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    assert saved.colors.primary == "#B4532A"


async def test_brand_kits_are_isolated_per_business(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    other = await brand_service.load(db, business_id=OTHER_BUSINESS_ID)
    assert other.version == 0


# ── Company brain ────────────────────────────────────────────────────────────


async def _add_context(db, business_id=BUSINESS_ID, **overrides):
    base = dict(
        title="Supported data sources",
        kind="product",
        summary="Churnary connects to Square and Stripe.",
        tags=["integrations"],
        public_safe=True,
    )
    return await brain_service.add(
        db, business_id=business_id, payload=ContextItemIn(**{**base, **overrides})
    )


async def test_context_defaults_to_private(db):
    row = await brain_service.add(
        db,
        business_id=BUSINESS_ID,
        payload=ContextItemIn(title="Margin notes", summary="Internal only."),
    )
    assert row.public_safe is False


async def test_private_context_never_reaches_the_drafter(db):
    await _add_context(db, title="Public fact", public_safe=True)
    await _add_context(db, title="Secret fact", summary="Do not share.", public_safe=False)

    titles = [c.title for c in await brain_service.drafting_context(db, business_id=BUSINESS_ID)]
    assert titles == ["Public fact"]
    assert len(await brain_service.list_all(db, business_id=BUSINESS_ID)) == 2


async def test_public_safe_can_be_withdrawn(db):
    row = await _add_context(db, public_safe=True)
    await brain_service.set_public_safe(
        db, business_id=BUSINESS_ID, item_id=str(row.id), public_safe=False
    )
    assert await brain_service.public_count(db, business_id=BUSINESS_ID) == 0


async def test_context_is_isolated_per_business(db):
    await _add_context(db, business_id=BUSINESS_ID)
    assert await brain_service.public_count(db, business_id=OTHER_BUSINESS_ID) == 0


# ── Engagement inbox ─────────────────────────────────────────────────────────


async def test_first_visit_seeds_labelled_demo_fixtures(db):
    rows = await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    assert len(rows) == 6
    assert {r.source for r in rows} == {"demo"}
    spam = next(r for r in rows if r.intent == "spam")
    assert (spam.status, spam.suggested_reply, spam.reply_version) == ("resolved", "", 0)
    complaint = next(r for r in rows if r.intent == "complaint")
    assert complaint.risk == "high"


async def test_seeding_happens_once(db):
    await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    again = await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    assert len(again) == 6


async def test_captured_comment_is_classified_but_not_drafted(db):
    await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    row = await inbox_service.create_comment(
        db,
        business_id=BUSINESS_ID,
        payload=CommentIn(author="Alex Morgan", comment="Can I book a demo this week?"),
    )
    assert (row.source, row.intent, row.status) == ("manual", "sales_lead", "needs_reply")
    assert row.suggested_reply == "" and row.reply_version == 0


async def test_suggest_drafts_a_reply_from_public_context(db):
    await _add_context(db)
    await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    row = await inbox_service.create_comment(
        db,
        business_id=BUSINESS_ID,
        payload=CommentIn(author="Alex Morgan", comment="Which data sources are supported?"),
    )
    updated = await inbox_service.suggest_reply(
        db, business_id=BUSINESS_ID, comment_id=str(row.id), variant="shorter"
    )
    assert updated.status == "drafted"
    assert updated.reply_variant == "shorter" and updated.reply_version == 1
    assert "Supported data sources" in updated.evidence


async def test_high_risk_comment_gets_the_escalation_text(db):
    rows = await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    complaint = next(r for r in rows if r.risk == "high")
    updated = await inbox_service.suggest_reply(
        db, business_id=BUSINESS_ID, comment_id=str(complaint.id), variant="warmer"
    )
    assert "appropriate support channel" in updated.suggested_reply


async def test_approving_snapshots_the_edited_reply(db):
    await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    row = await inbox_service.create_comment(
        db, business_id=BUSINESS_ID,
        payload=CommentIn(author="Alex", comment="Nice work on the launch"),
    )
    approved = await inbox_service.update_comment(
        db, business_id=BUSINESS_ID, comment_id=str(row.id),
        patch=CommentPatch(status="approved", suggested_reply="Thanks Alex — much appreciated."),
    )
    assert approved.approved_reply == "Thanks Alex — much appreciated."
    assert approved.status == "approved"


async def test_cannot_approve_an_empty_reply(db):
    await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    row = await inbox_service.create_comment(
        db, business_id=BUSINESS_ID, payload=CommentIn(author="Alex", comment="Hello there")
    )
    with pytest.raises(inbox_service.ApprovalError):
        await inbox_service.update_comment(
            db, business_id=BUSINESS_ID, comment_id=str(row.id),
            patch=CommentPatch(status="approved"),
        )


async def test_briefing_summarises_the_seeded_inbox(db):
    briefing = await inbox_service.briefing(db, business_id=BUSINESS_ID)
    assert briefing.leads == 1
    assert briefing.high_risk == 1
    assert briefing.awaiting_reply == 5
    assert briefing.approved_today == 0
    assert briefing.estimated_minutes_saved > 0
    assert "high-risk conversation" in briefing.recommended_action


async def test_claude_reply_is_used_when_the_model_answers(db, monkeypatch):
    await _add_context(db)
    await inbox_service.list_comments(db, business_id=BUSINESS_ID)
    row = await inbox_service.create_comment(
        db, business_id=BUSINESS_ID,
        payload=CommentIn(author="Alex", comment="Which data sources are supported?"),
    )

    async def _reply(system, user, max_tokens=400):
        assert "Secret" not in user  # only public-safe facts may be in the prompt
        return '```json\n{"reply": "We connect to Square and Stripe today."}\n```'

    from app.core.config import settings

    monkeypatch.setattr(inbox_service, "complete_text", _reply)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    updated = await inbox_service.suggest_reply(
        db, business_id=BUSINESS_ID, comment_id=str(row.id)
    )
    assert updated.suggested_reply == "We connect to Square and Stripe today."


# ── Campaigns and the review queue ───────────────────────────────────────────


def _campaign(**overrides) -> CampaignIn:
    base = dict(
        name="Autumn regulars",
        brief="Bring back customers who have not visited in a month",
        themes=["Loyalty perks", "New seasonal menu"],
        platforms=["linkedin"],
        start_at=datetime.now(UTC) + timedelta(days=7),
        timezone="America/Los_Angeles",
        interval_weeks=1,
        occurrences=2,
    )
    return CampaignIn(**{**base, **overrides})


async def test_generation_requires_a_saved_brand_kit(db):
    with pytest.raises(campaign_service.SetupRequired, match="brand kit"):
        await campaign_service.assert_generation_ready(db, business_id=BUSINESS_ID)


async def test_generation_requires_public_safe_context(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    with pytest.raises(campaign_service.SetupRequired, match="public content"):
        await campaign_service.assert_generation_ready(db, business_id=BUSINESS_ID)


async def test_generate_fills_every_slot_with_a_draft(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    await _add_context(db)
    campaign = await campaign_service.create_campaign(
        db, business_id=BUSINESS_ID, payload=_campaign()
    )
    created = await campaign_service.generate_posts(
        db, business_id=BUSINESS_ID, campaign_id=str(campaign.id),
        business_name="Hayward Coffee Co.",
    )
    assert created == 2  # 2 occurrences x 1 platform
    posts = await review_service.list_posts(db, business_id=BUSINESS_ID)
    assert {p.status for p in posts} == {"draft"}
    assert all(p.scheduled_for is not None for p in posts)
    assert {p.campaign_occurrence for p in posts} == {1, 2}
    assert campaign.status == "active"


async def test_regeneration_keeps_approved_work(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    await _add_context(db)
    campaign = await campaign_service.create_campaign(
        db, business_id=BUSINESS_ID, payload=_campaign()
    )
    await campaign_service.generate_posts(
        db, business_id=BUSINESS_ID, campaign_id=str(campaign.id), business_name="Hayward"
    )
    posts = await review_service.list_posts(db, business_id=BUSINESS_ID)
    keeper = posts[0]
    keeper.status = "approved"
    await db.flush()

    await campaign_service.generate_posts(
        db, business_id=BUSINESS_ID, campaign_id=str(campaign.id), business_name="Hayward"
    )
    after = await review_service.list_posts(db, business_id=BUSINESS_ID)
    assert str(keeper.id) in {str(p.id) for p in after}


async def _make_post(db, **overrides) -> SocialPost:
    base = dict(
        business_id=uuid.UUID(BUSINESS_ID),
        platform="linkedin",
        topic="Loyalty perks",
        post_text="A" * 600,
        hashtags=["Loyalty", "Coffee", "Local"],
        status="draft",
    )
    row = SocialPost(**{**base, **overrides})
    db.add(row)
    await db.flush()
    return row


async def test_approve_records_a_review_event(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    post = await _make_post(db)
    updated = await review_service.record_decision(
        db, business_id=BUSINESS_ID, post_id=str(post.id),
        decision="approve", reason="strong_insight",
    )
    assert updated.status == "approved"
    out = await review_service.to_out(db, updated)
    assert [e.decision for e in out.review_history] == ["approve"]


async def test_approval_is_blocked_by_an_avoid_phrase(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    post = await _make_post(db, post_text="Our world-class beans " + "A" * 600)
    with pytest.raises(review_service.ApprovalBlocked, match="world-class"):
        await review_service.record_decision(
            db, business_id=BUSINESS_ID, post_id=str(post.id),
            decision="approve", reason="strong_insight",
        )


async def test_a_note_overrides_a_blocked_approval(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    post = await _make_post(db, post_text="Our world-class beans " + "A" * 600)
    updated = await review_service.record_decision(
        db, business_id=BUSINESS_ID, post_id=str(post.id), decision="approve",
        reason="strong_insight", note="Quoting a customer review verbatim.",
    )
    assert updated.status == "approved"
    out = await review_service.to_out(db, updated)
    assert out.review_history[0].note == "Quoting a customer review verbatim."


async def test_hashtag_only_failure_is_repaired_not_blocked(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    post = await _make_post(
        db, topic="Loyalty perks for regulars",
        post_text="Regulars keep the lights on around here. " + "A" * 600,
        hashtags=["OnlyOne"],
    )
    updated = await review_service.record_decision(
        db, business_id=BUSINESS_ID, post_id=str(post.id),
        decision="approve", reason="strong_insight",
    )
    assert updated.status == "approved"
    assert 3 <= len(updated.hashtags) <= 4
    assert any("repaired automatically" in w for w in updated.warnings)


async def test_revise_returns_a_post_to_draft(db):
    post = await _make_post(db, status="approved")
    updated = await review_service.record_decision(
        db, business_id=BUSINESS_ID, post_id=str(post.id),
        decision="revise", reason="too_generic",
    )
    assert updated.status == "draft"


async def test_posted_items_stay_in_the_review_queue(db):
    await _make_post(db, status="posted")
    await _make_post(db, status="rejected")
    queued = await review_service.list_posts(db, business_id=BUSINESS_ID)
    assert [p.status for p in queued] == ["posted"]


async def test_schedule_rejects_a_past_time(db):
    post = await _make_post(db)
    with pytest.raises(review_service.ScheduleError):
        await review_service.schedule_post(
            db, business_id=BUSINESS_ID, post_id=str(post.id),
            scheduled_for=datetime.now(UTC) - timedelta(hours=1),
        )


# ── Publishing ───────────────────────────────────────────────────────────────


async def test_only_approved_posts_are_eligible(db):
    await _make_post(db, status="draft")
    approved = await _make_post(db, status="approved")
    eligible = await publish_service.eligible_posts(db, business_id=BUSINESS_ID)
    assert [str(p.id) for p in eligible] == [str(approved.id)]


async def test_pausing_a_campaign_makes_its_posts_ineligible(db):
    await brand_service.save(db, business_id=BUSINESS_ID, payload=_kit())
    campaign = await campaign_service.create_campaign(
        db, business_id=BUSINESS_ID, payload=_campaign()
    )
    campaign.status = "active"
    await _make_post(db, status="approved", campaign_id=campaign.id)
    assert len(await publish_service.eligible_posts(db, business_id=BUSINESS_ID)) == 1

    await campaign_service.set_status(
        db, business_id=BUSINESS_ID, campaign_id=str(campaign.id), status="paused"
    )
    assert await publish_service.eligible_posts(db, business_id=BUSINESS_ID) == []


async def test_posts_without_a_campaign_are_always_eligible(db):
    await _make_post(db, status="approved", campaign_id=None)
    assert len(await publish_service.eligible_posts(db, business_id=BUSINESS_ID)) == 1


async def test_publish_refuses_when_nothing_is_eligible(db):
    with pytest.raises(publish_service.NothingToPublish):
        await publish_service.publish_approved(db, business_id=BUSINESS_ID)


async def test_publish_refuses_when_buffer_is_not_configured(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "buffer_api_key", "")
    await _make_post(db, status="approved")
    with pytest.raises(publish_service.PublishNotConfigured):
        await publish_service.publish_approved(db, business_id=BUSINESS_ID)
