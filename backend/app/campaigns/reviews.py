"""Review requests: after a customer comes back, ask them for a review.

The timing is the point. A customer who was drifting away and then returned
has just had a good enough experience to come back -- the best moment a small
business will get to ask for a public review.

Review requests ride the ordinary campaign machinery, so everything that keeps
outreach honest applies unchanged: consent and opt-outs (``can_contact``), TCPA
quiet hours and the single send path (``attempt_send``), unsubscribe links,
and approve-to-send. Nothing here sends anything. Requests are queued as
``pending`` in a "Review requests" campaign that the owner approves like any
other.

Rules that keep it from becoming spam:

* **Recent recoveries only** (``LOOKBACK_DAYS``). Switching the feature on
  must not suddenly ask everyone who came back last year.
* **One ask per customer per ``REVIEW_COOLDOWN_DAYS``**, counting *every*
  earlier request whatever happened to it. A request the owner dropped stays
  dropped; it must not reappear on the next hourly run.
* **Never credited as a win-back.** These go to people who already came
  back, so ``services/attribution.py`` ignores ``kind="review_request"``
  campaigns -- otherwise a returning customer would be "recovered" by the
  thank-you note.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.limits import channel_denial
from app.billing.store import entitlements
from app.models import Business, Campaign, CampaignSend, Customer, RecoveryAttribution
from app.services.automations import unsubscribe_url
from app.services.compliance import can_contact

logger = logging.getLogger("pulse.campaigns.reviews")

REVIEW_KIND = "review_request"
LOOKBACK_DAYS = 30
REVIEW_COOLDOWN_DAYS = 180
SMS_MAX_CHARS = 320


class ReviewSettingsError(ValueError):
    """Owner-facing validation error."""


def validate_review_url(url: str | None) -> str | None:
    """A review link is put in front of customers, so it must be a plain web
    link: no ``javascript:``/``data:`` schemes, no relative paths.

    Not an SSRF concern -- we never fetch it -- which is why this doesn't do
    the DNS checks the webhook URLs do.
    """
    url = (url or "").strip()
    if not url:
        return None
    if len(url) > 500:
        raise ReviewSettingsError("That link is too long.")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ReviewSettingsError(
            "Use the full review link, starting with https:// (for example your "
            "Google Business review link)."
        )
    return url


def _sentence_end(name: str) -> str:
    """'Hayward Coffee Co.' + '.' should not read 'Co..'."""
    return name[:-1] if name.endswith(".") else name


def review_copy(
    *,
    business_name: str,
    first_name: str | None,
    review_url: str,
    channel: str,
    unsubscribe: str = "",
) -> tuple[str | None, str]:
    """``(subject, body)`` for a review request. Pure.

    Static rather than AI-written on purpose: it's a short, specific ask where
    a template is already right, and it means the request works the same with
    no LLM configured. The owner can still edit any of them before approving.
    """
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    if channel == "sms":
        full = (
            f"{greeting} thanks for coming back to {business_name}! A quick review "
            f"would mean a lot: {review_url} Reply STOP to opt out."
        )
        if len(full) <= SMS_MAX_CHARS:
            return None, full
        # Never cut the link: a truncated URL is worse than no message. If even
        # the short form won't fit, the caller skips the customer.
        short = (
            "Thanks for coming back! Mind leaving us a review? "
            f"{review_url} Reply STOP to opt out."
        )
        return None, short

    subject = f"Thanks for coming back to {_sentence_end(business_name)}"
    body = (
        f"{greeting}\n\n"
        f"It was great to see you back at {_sentence_end(business_name)}. If you "
        "have a minute, a quick review would mean a lot to us -- it's how other "
        "people in the neighbourhood find us.\n\n"
        f"{review_url}\n\n"
        "Thank you!\n"
        f"The {_sentence_end(business_name)} team"
    )
    if unsubscribe:
        body += f"\n\nUnsubscribe: {unsubscribe}"
    return subject, body


@dataclass
class ReviewSummary:
    queued: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str, n: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + n


async def _review_campaign(db: AsyncSession, business: Business, channel: str) -> Campaign:
    """The standing "Review requests" campaign for this channel, created once."""
    existing = (
        await db.execute(
            select(Campaign)
            .where(
                Campaign.business_id == business.id,
                Campaign.kind == REVIEW_KIND,
                Campaign.channel == channel,
            )
            .order_by(Campaign.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    campaign = Campaign(
        business_id=business.id,
        name="Review requests" + (" (text)" if channel == "sms" else ""),
        channel=channel,
        status="pending_approval",
        kind=REVIEW_KIND,
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def queue_review_requests(
    db: AsyncSession, *, business_id: str, now: datetime | None = None
) -> ReviewSummary:
    """Queue a pending review request for each eligible recent recovery.

    Idempotent: safe to run hourly. Does not commit.
    """
    summary = ReviewSummary()
    now = now or datetime.now(UTC)
    bid = uuid.UUID(business_id)
    business = await db.get(Business, bid)
    if business is None or not business.review_requests_enabled or not business.review_url:
        return summary

    channel = business.review_request_channel or "email"
    denial = channel_denial(await entitlements(db, business_id=business_id), channel)
    if denial:
        summary.skip("not_in_plan")
        return summary

    newest_allowed = now - timedelta(days=max(0, business.review_request_delay_days or 0))
    oldest_allowed = now - timedelta(days=LOOKBACK_DAYS)
    recoveries = (
        await db.execute(
            select(RecoveryAttribution.customer_id).where(
                RecoveryAttribution.business_id == bid,
                RecoveryAttribution.recovered_at <= newest_allowed,
                RecoveryAttribution.recovered_at >= oldest_allowed,
            )
        )
    ).scalars().all()
    candidates = list(dict.fromkeys(recoveries))  # dedupe, keep order
    if not candidates:
        return summary

    # Everyone asked recently, whatever became of the ask -- including ones the
    # owner dropped, so a dropped request doesn't come back next hour.
    already_asked = set(
        (
            await db.execute(
                select(CampaignSend.customer_id)
                .join(Campaign, Campaign.id == CampaignSend.campaign_id)
                .where(
                    CampaignSend.business_id == bid,
                    Campaign.kind == REVIEW_KIND,
                    CampaignSend.created_at >= now - timedelta(days=REVIEW_COOLDOWN_DAYS),
                )
            )
        ).scalars().all()
    )

    campaign: Campaign | None = None
    for customer_id in candidates:
        if customer_id in already_asked:
            summary.skip("asked_recently")
            continue
        customer = await db.get(Customer, customer_id)
        if customer is None or customer.business_id != bid:
            continue
        allowed, reason = can_contact(customer, channel)
        if not allowed:
            summary.skip(reason or "not_allowed")
            continue

        subject, body = review_copy(
            business_name=business.name,
            first_name=customer.first_name,
            review_url=business.review_url,
            channel=channel,
            unsubscribe=(
                unsubscribe_url(business_id, str(customer.id)) if channel == "email" else ""
            ),
        )
        if channel == "sms" and len(body) > SMS_MAX_CHARS:
            summary.skip("link_too_long_for_text")
            continue
        campaign = campaign or await _review_campaign(db, business, channel)
        db.add(
            CampaignSend(
                business_id=bid,
                campaign_id=campaign.id,
                customer_id=customer.id,
                channel=channel,
                subject=subject,
                body=body,
                status="pending",
                generated_by="template",
            )
        )
        already_asked.add(customer_id)
        summary.queued += 1

    if campaign is not None and summary.queued:
        campaign.status = "pending_approval"
    await db.flush()
    return summary
