"""Automation rule engine: evaluates each business's enabled AutomationRules
against currently-scored customers and queues or sends outreach.

Runs on a schedule (Celery beat, see app/workers/celery_app.py) and can also be
triggered manually via POST /api/automations/dispatch. Every actual send goes
through app/services/compliance.py first — this is the one place TCPA/opt-out
rules are enforced, so there's exactly one path that can go wrong, not N.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.generator import CampaignContext, generate_campaign
from app.core.config import settings
from app.core.security import encrypt_token
from app.models import AutomationRule, Business, Campaign, CampaignSend, Customer, EngagementEvent
from app.services import ingest
from app.services.activity import build_scored_customers
from app.services.compliance import can_contact, is_quiet_hours
from app.services.ingest import _uuid
from app.services.rag.knowledge_store import search_knowledge
from app.services.senders.resend_client import send_email
from app.services.senders.twilio_client import send_sms

logger = logging.getLogger("pulse.automations")


def unsubscribe_url(business_id: str, customer_id: str) -> str:
    token = encrypt_token(f"{business_id}:{customer_id}")
    return f"{settings.api_base_url}/api/automations/unsubscribe?token={token}"


@dataclass
class DispatchSummary:
    rules_evaluated: int = 0
    sends_created: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


async def _get_or_create_campaign(db: AsyncSession, rule: AutomationRule) -> Campaign:
    if rule.campaign_id is not None:
        campaign = await db.get(Campaign, rule.campaign_id)
        if campaign is not None:
            return campaign
    campaign = Campaign(
        business_id=rule.business_id,
        name=rule.name,
        channel=rule.channel,
        status="sending",
        incentive=rule.incentive,
    )
    db.add(campaign)
    await db.flush()
    rule.campaign_id = campaign.id
    return campaign


async def attempt_send(
    db: AsyncSession, send: CampaignSend, customer: Customer, biz: Business
) -> None:
    """Actually dispatch a pending send. Shared by auto-mode dispatch and the
    manual approve endpoint (app/api/automations.py) — the one place that
    calls a real sender, so re-checking quiet hours here (not just at queue
    time) matters: an owner can hit "approve" well after a send was queued."""
    if send.channel == "sms" and is_quiet_hours(biz.timezone):
        return  # stays "pending"; try again later (approve endpoint surfaces this)

    if send.channel == "sms":
        result = await send_sms(customer.phone, send.body)
    else:
        result = await send_email(customer.email, send.subject or "", send.body)

    if result.ok:
        send.status = "sent"
        send.sent_at = datetime.now(UTC)
        send.provider_message_id = result.provider_message_id
        db.add(
            EngagementEvent(
                business_id=send.business_id,
                customer_id=customer.id,
                kind="sms_sent" if send.channel == "sms" else "email_sent",
                occurred_at=send.sent_at,
            )
        )
    else:
        send.status = "failed"
        send.failure_reason = result.error


async def dispatch_automations(
    db: AsyncSession, business_id: str, now: datetime | None = None
) -> DispatchSummary:
    """Evaluate every enabled rule for one business and queue/send outreach.

    ``now`` defaults to the real current time; tests pass a fixed value so
    scoring (which is recency-based) lines up with synthetic fixture data —
    same reason app/services/activity.py's build_scored_customers takes it.
    """
    summary = DispatchSummary()
    bid = _uuid(business_id)
    now = now or datetime.now(UTC)

    biz = await db.get(Business, bid)
    if biz is None:
        return summary

    rules = (
        (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.business_id == bid, AutomationRule.enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not rules:
        return summary

    sync = await ingest.load_sync(db, business_id)
    if not sync.customers:
        return summary
    # load_sync sets NormalizedCustomer.external_id = str(row.id) (see its
    # docstring) specifically so scored results join back to DB rows by PK —
    # same join key app.services.ingest.refresh_scores uses.
    scored = build_scored_customers(sync, vertical=biz.vertical, now=now)
    scored_by_row_id = {s.customer.external_id: s for s in scored if s.customer.external_id}

    db_customers = (
        (await db.execute(select(Customer).where(Customer.business_id == bid))).scalars().all()
    )
    customers_by_row_id = {str(c.id): c for c in db_customers}

    for rule in rules:
        summary.rules_evaluated += 1
        quiet = rule.channel == "sms" and is_quiet_hours(biz.timezone, now)

        for row_id, s in scored_by_row_id.items():
            if s.result.band != rule.trigger_band:
                continue
            customer = customers_by_row_id.get(row_id)
            if customer is None:
                continue

            allowed, reason = can_contact(customer, rule.channel)
            if not allowed:
                summary.skip(reason or "not_allowed")
                continue

            recent = await db.execute(
                select(CampaignSend.id)
                .where(
                    CampaignSend.automation_rule_id == rule.id,
                    CampaignSend.customer_id == customer.id,
                    CampaignSend.created_at >= now - timedelta(days=rule.cooldown_days),
                )
                .limit(1)
            )
            if recent.first() is not None:
                summary.skip("cooldown")
                continue

            if quiet:
                # Don't create a row at all — the next tick (once inside allowed
                # hours) re-evaluates this customer fresh, no cooldown consumed.
                summary.skip("quiet_hours")
                continue

            name = f"{s.customer.first_name or ''} {s.customer.last_name or ''}".strip() or "there"
            knowledge = await search_knowledge(
                db,
                business_id=business_id,
                query=(
                    f"win-back {rule.channel} for a {s.result.band}-risk customer. "
                    f"Reasons: {'; '.join(s.result.reasons)}. "
                    f"Incentive: {rule.incentive or 'none'}."
                ),
            )
            days_ago = s.days_since_last_visit if s.days_since_last_visit is not None else "unknown"
            ctx = CampaignContext(
                business_name=biz.name,
                business_type=biz.vertical,
                customer_name=name,
                channel=rule.channel,
                incentive=rule.incentive,
                risk_reasons=s.result.reasons,
                history_summary=f"{s.visit_count} visits, last one {days_ago} days ago",
                knowledge_snippets=[row.content for row in knowledge],
                unsubscribe_url=unsubscribe_url(business_id, str(customer.id)),
            )
            copy = await generate_campaign(ctx)

            campaign = await _get_or_create_campaign(db, rule)
            send = CampaignSend(
                business_id=bid,
                campaign_id=campaign.id,
                customer_id=customer.id,
                automation_rule_id=rule.id,
                channel=rule.channel,
                subject=copy.subject,
                body=copy.body,
                status="pending",
                generation_model=copy.model,
                generated_by=copy.generated_by,
            )
            db.add(send)
            summary.sends_created += 1

            if rule.mode == "auto":
                await attempt_send(db, send, customer, biz)

            await db.flush()

    return summary
