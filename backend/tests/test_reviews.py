"""Review requests after a recovery: the copy, the queueing rules, and the
guarantee that a review request is never credited as a win-back."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.campaigns import reviews
from app.models import (
    Business,
    Campaign,
    CampaignSend,
    Customer,
    RecoveryAttribution,
    Subscription,
    Transaction,
)
from app.services import ingest
from app.services.attribution import detect_recoveries

BUSINESS_ID = str(uuid.uuid4())
REVIEW_URL = "https://g.page/r/hayward-coffee/review"


# -- URL validation + copy (pure) ---------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(document.cookie)",
        "data:text/html,<script>alert(1)</script>",
        "/relative/path",
        "g.page/r/no-scheme",
        "ftp://example.com/review",
    ],
)
def test_review_links_must_be_plain_web_links(bad):
    """The link goes in front of customers, so no script or data schemes."""
    with pytest.raises(reviews.ReviewSettingsError):
        reviews.validate_review_url(bad)


def test_a_real_review_link_is_accepted():
    assert reviews.validate_review_url(f"  {REVIEW_URL}  ") == REVIEW_URL
    assert reviews.validate_review_url("") is None


def test_the_email_asks_carries_the_link_and_an_unsubscribe_line():
    subject, body = reviews.review_copy(
        business_name="Hayward Coffee Co.",
        first_name="Dana",
        review_url=REVIEW_URL,
        channel="email",
        unsubscribe="https://api.test/unsub?token=x",
    )
    assert subject == "Thanks for coming back to Hayward Coffee Co"
    assert REVIEW_URL in body
    assert "Unsubscribe: https://api.test/unsub?token=x" in body  # CAN-SPAM
    assert "Co.." not in body
    assert body.startswith("Hi Dana,")


def test_the_text_fits_in_one_message_and_offers_stop():
    _subject, body = reviews.review_copy(
        business_name="Hayward Coffee Co.", first_name="Dana", review_url=REVIEW_URL, channel="sms"
    )
    assert len(body) <= reviews.SMS_MAX_CHARS
    assert "Reply STOP" in body  # TCPA


def test_a_long_link_shortens_the_text_but_never_cuts_the_link():
    long_url = "https://example.com/" + "r" * 200
    _subject, body = reviews.review_copy(
        business_name="A Business With A Very Long Name Indeed",
        first_name="Bartholomew",
        review_url=long_url,
        channel="sms",
    )
    assert long_url in body


# -- Queueing -----------------------------------------------------------------


async def _seed(db, *, enabled=True, channel="email", delay=2, tier="growth"):
    biz = await ingest.ensure_business(db, BUSINESS_ID, "Hayward Coffee Co.", "cafe")
    biz.review_request_enabled = enabled
    biz.review_link = REVIEW_URL
    biz.review_request_channel = channel
    biz.review_request_delay_days = delay
    db.add(Subscription(business_id=biz.id, tier=tier, status="active"))
    await db.flush()
    return biz


async def _recovered(db, *, days_ago: float, **customer_fields) -> Customer:
    bid = uuid.UUID(BUSINESS_ID)
    customer = Customer(
        business_id=bid, source="csv", first_name="Dana",
        email=f"{uuid.uuid4().hex[:8]}@example.com", phone="+15550001111",
        **customer_fields,
    )
    db.add(customer)
    await db.flush()
    db.add(
        RecoveryAttribution(
            business_id=bid, customer_id=customer.id, estimated_value=120,
            recovered_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )
    await db.flush()
    return customer


async def _review_sends(db) -> list[CampaignSend]:
    return list(
        (
            await db.execute(
                select(CampaignSend)
                .join(Campaign, Campaign.id == CampaignSend.campaign_id)
                .where(Campaign.kind == reviews.REVIEW_KIND)
            )
        ).scalars()
    )


async def test_a_recent_recovery_gets_a_pending_review_request(db):
    await _seed(db)
    await _recovered(db, days_ago=3)
    summary = await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    assert summary.queued == 1
    sends = await _review_sends(db)
    assert len(sends) == 1
    # Approve-to-send: drafted, never sent.
    assert sends[0].status == "pending"
    assert sends[0].sent_at is None
    assert REVIEW_URL in sends[0].body


async def test_nothing_is_queued_when_the_feature_is_off(db):
    await _seed(db, enabled=False)
    await _recovered(db, days_ago=3)
    assert (await reviews.queue_review_requests(db, business_id=BUSINESS_ID)).queued == 0


async def test_the_delay_is_respected(db):
    """Asking at the till feels transactional; a couple of days later doesn't."""
    await _seed(db, delay=2)
    await _recovered(db, days_ago=1)
    assert (await reviews.queue_review_requests(db, business_id=BUSINESS_ID)).queued == 0


async def test_turning_it_on_does_not_ask_everyone_from_last_year(db):
    await _seed(db)
    await _recovered(db, days_ago=reviews.LOOKBACK_DAYS + 5)
    assert (await reviews.queue_review_requests(db, business_id=BUSINESS_ID)).queued == 0


async def test_running_it_twice_asks_once(db):
    await _seed(db)
    await _recovered(db, days_ago=3)
    await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    second = await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    assert second.queued == 0
    assert second.skipped == {"asked_recently": 1}


async def test_a_dropped_request_stays_dropped(db):
    """If the owner drops one, the hourly run must not bring it back."""
    await _seed(db)
    await _recovered(db, days_ago=3)
    await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    send = (await _review_sends(db))[0]
    send.status = "skipped"
    send.failure_reason = "cancelled_by_owner"
    await db.flush()

    again = await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    assert again.queued == 0
    assert len(await _review_sends(db)) == 1


async def test_opt_outs_are_respected(db):
    await _seed(db)
    await _recovered(db, days_ago=3, unsubscribed_email=True)
    await _recovered(db, days_ago=3, do_not_contact=True)
    summary = await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    assert summary.queued == 0
    assert summary.skipped == {"unsubscribed_email": 1, "do_not_contact": 1}


async def test_text_review_requests_need_a_plan_with_sms(db):
    await _seed(db, channel="sms", tier="starter")
    await _recovered(db, days_ago=3)
    summary = await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    assert summary.queued == 0
    assert summary.skipped == {"not_in_plan": 1}


async def test_all_requests_share_one_standing_campaign(db):
    await _seed(db)
    await _recovered(db, days_ago=3)
    await _recovered(db, days_ago=4)
    await reviews.queue_review_requests(db, business_id=BUSINESS_ID)
    campaigns = (
        await db.execute(select(Campaign).where(Campaign.kind == reviews.REVIEW_KIND))
    ).scalars().all()
    assert len(campaigns) == 1
    assert campaigns[0].status == "pending_approval"


# -- Attribution must not credit review requests ------------------------------


async def test_a_review_request_is_never_credited_as_a_recovery(db):
    """A customer who returns after the thank-you note was already recovered;
    crediting the note would count the same win twice under a false cause."""
    biz = await _seed(db)
    customer = Customer(business_id=biz.id, source="csv", first_name="Dana", email="d@x.com")
    db.add(customer)
    await db.flush()
    review_campaign = Campaign(
        business_id=biz.id, name="Review requests", channel="email",
        status="sent", kind=reviews.REVIEW_KIND,
    )
    db.add(review_campaign)
    await db.flush()
    db.add(
        CampaignSend(
            business_id=biz.id, campaign_id=review_campaign.id, customer_id=customer.id,
            channel="email", body="Leave us a review?", status="sent",
            sent_at=datetime.now() - timedelta(days=10),
        )
    )
    db.add(
        Transaction(
            business_id=biz.id, customer_id=customer.id, source="csv", amount=40,
            occurred_at=datetime.now() - timedelta(days=3),
        )
    )
    await db.flush()

    summary = await detect_recoveries(db, BUSINESS_ID)
    assert summary.recoveries_found == 0
    assert summary.sends_considered == 0


async def test_a_winback_send_is_still_credited(db):
    """The exclusion is narrow: ordinary win-backs still count."""
    biz = await _seed(db)
    customer = Customer(business_id=biz.id, source="csv", first_name="Dana", email="d@x.com")
    db.add(customer)
    await db.flush()
    campaign = Campaign(business_id=biz.id, name="Win back", channel="email", status="sent")
    db.add(campaign)
    await db.flush()
    db.add(
        CampaignSend(
            business_id=biz.id, campaign_id=campaign.id, customer_id=customer.id,
            channel="email", body="We miss you", status="sent",
            sent_at=datetime.now() - timedelta(days=10),
        )
    )
    db.add(
        Transaction(
            business_id=biz.id, customer_id=customer.id, source="csv", amount=40,
            occurred_at=datetime.now() - timedelta(days=3),
        )
    )
    await db.flush()
    assert (await detect_recoveries(db, BUSINESS_ID)).recoveries_found == 1


async def test_a_business_row_must_exist(db):
    assert (await reviews.queue_review_requests(db, business_id=str(uuid.uuid4()))).queued == 0


def test_business_model_defaults_keep_the_feature_off():
    """It messages real people, so it has to be an explicit opt-in."""
    column = Business.__table__.c.review_request_enabled
    assert column.default.arg is False
