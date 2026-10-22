"""Owner-driven campaigns: pick customers, generate copy, review, send.

This is the loop in the Definition of Done - "approve an AI-written win-back
email -> see it send" - for a campaign the owner starts themselves, as opposed
to one an automation rule queues. It deliberately reuses the automation
machinery rather than paralleling it:

* copy comes from ``generate_campaigns_batch``, so one campaign to 40 customers
  is a handful of LLM calls, not 40;
* sends are ordinary ``CampaignSend`` rows, so the existing approve endpoint,
  Twilio/Resend status webhooks, engagement tracking and recovery attribution
  all work on them with no special-casing;
* ``attempt_send`` from ``services/automations.py`` is the only thing that
  touches a sender, so TCPA quiet hours and consent are enforced on exactly one
  path.

Creating a campaign never sends anything. Sends are queued as ``pending`` and
wait for an explicit approval, because approve-to-send is the product default.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.generator import CampaignContext, GeneratedCopy, generate_campaigns_batch
from app.core.deps import CurrentUser
from app.models import Business, Campaign, CampaignSend, Customer
from app.services.activity import ScoredCustomer, build_scored_customers
from app.services.automations import attempt_send, unsubscribe_url
from app.services.compliance import can_contact
from app.services.generation_log import record_audit, record_generation
from app.services.ingest import _uuid, load_sync
from app.services.outbound_webhooks import emit as emit_webhook
from app.services.rag.knowledge_store import search_knowledge

logger = logging.getLogger("pulse.campaigns.manual")

# One owner-launched campaign can't exceed this many recipients. Not a billing
# limit - a guard against a mis-click selecting the whole book and firing off
# thousands of generations in one request.
MAX_RECIPIENTS = 500


@dataclass
class BuildResult:
    campaign: Campaign
    sends: list[CampaignSend] = field(default_factory=list)
    # customer_id -> why they were left out, surfaced in the UI so an owner can
    # see "3 of your 20 picks can't be emailed" rather than silently getting 17.
    skipped: dict[str, str] = field(default_factory=dict)


def _history_summary(scored: ScoredCustomer | None) -> str:
    if scored is None:
        return ""
    days = scored.days_since_last_visit
    return (
        f"{scored.visit_count} visits, last one "
        f"{days if days is not None else 'unknown'} days ago"
    )


def _display_name(scored: ScoredCustomer) -> str:
    first = scored.customer.first_name or ""
    last = scored.customer.last_name or ""
    return f"{first} {last}".strip() or "there"


def _assign_variant(index: int, ab_test: bool) -> str | None:
    """Alternate A/B/A/B down the recipient list.

    Deterministic alternation rather than a random coin flip: with the small
    lists a local business actually has (often under 50), random assignment
    regularly produces a 60/40 split that makes a result unreadable. Assigning
    by position guarantees the halves differ by at most one.
    """
    if not ab_test:
        return None
    return "A" if index % 2 == 0 else "B"


async def build_campaign(
    db: AsyncSession,
    *,
    user: CurrentUser,
    name: str,
    channel: str,
    customer_ids: list[str],
    incentive: str | None = None,
    tone: str | None = None,
    ab_test: bool = False,
    variant_b_incentive: str | None = None,
) -> BuildResult:
    """Create a draft campaign with one pending send per eligible customer.

    Nothing is sent. Consent and channel-reachability are checked here so an
    owner sees who was excluded at review time rather than discovering it in a
    failure count afterwards; they're checked *again* at send time, since
    consent can change in between.
    """
    if channel not in ("email", "sms"):
        raise ValueError("channel must be 'email' or 'sms'")
    if not customer_ids:
        raise ValueError("Pick at least one customer to send to.")
    if len(customer_ids) > MAX_RECIPIENTS:
        raise ValueError(
            f"That's {len(customer_ids)} people in one campaign. "
            f"The limit is {MAX_RECIPIENTS} - try narrowing the list."
        )

    bid = _uuid(user.business_id)
    biz = await db.get(Business, bid)
    if biz is None:
        raise ValueError("Business not found")

    # Deduplicate while preserving the owner's ordering, so A/B assignment is
    # stable and a double-selected customer can't be messaged twice.
    wanted: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in customer_ids:
        try:
            parsed = _uuid(raw)
        except (ValueError, AttributeError):
            continue
        if parsed not in seen:
            seen.add(parsed)
            wanted.append(parsed)

    customers = {
        c.id: c
        for c in (
            await db.execute(
                select(Customer).where(Customer.business_id == bid, Customer.id.in_(wanted))
            )
        )
        .scalars()
        .all()
    }

    # Scores give the generator its "why they're at risk" reasons, which is what
    # makes the copy specific rather than a form letter.
    sync = await load_sync(db, user.business_id)
    scored_by_id = {
        s.customer.external_id: s
        for s in build_scored_customers(sync, vertical=biz.vertical)
        if s.customer.external_id
    }

    campaign = Campaign(
        business_id=bid,
        name=name.strip() or "Win-back campaign",
        channel=channel,
        status="draft",
        incentive=incentive,
        ab_test=ab_test,
        variant_b_incentive=variant_b_incentive if ab_test else None,
    )
    db.add(campaign)
    await db.flush()

    result = BuildResult(campaign=campaign)
    recipients: list[tuple[Customer, CampaignContext, str | None]] = []

    for customer_id in wanted:
        customer = customers.get(customer_id)
        if customer is None:
            result.skipped[str(customer_id)] = "not_found"
            continue
        allowed, reason = can_contact(customer, channel)
        if not allowed:
            result.skipped[str(customer_id)] = reason or "not_allowed"
            continue

        variant = _assign_variant(len(recipients), ab_test)
        offer = variant_b_incentive if (variant == "B" and variant_b_incentive) else incentive
        scored = scored_by_id.get(str(customer_id))

        if scored is not None:
            reasons = scored.result.reasons
            history = _history_summary(scored)
            display = _display_name(scored)
        else:
            # A customer with no visit history yet still gets a message; the
            # copy just has less to work with.
            reasons = []
            history = ""
            display = (
                f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "there"
            )

        knowledge = await search_knowledge(
            db,
            business_id=user.business_id,
            query=(
                f"win-back {channel} for {display}. Reasons: {'; '.join(reasons)}. "
                f"Incentive: {offer or 'none'}."
            ),
        )
        ctx = CampaignContext(
            business_name=biz.name,
            business_type=biz.vertical,
            customer_name=display,
            channel=channel,
            incentive=offer,
            risk_reasons=list(reasons),
            history_summary=history,
            knowledge_snippets=[row.content for row in knowledge],
            unsubscribe_url=unsubscribe_url(user.business_id, str(customer.id)),
            **({"tone": tone} if tone else {}),
        )
        recipients.append((customer, ctx, variant))

    if not recipients:
        campaign.status = "failed"
        await db.flush()
        return result

    copies = await generate_campaigns_batch([ctx for _, ctx, _ in recipients])

    for (customer, ctx, variant), copy in zip(recipients, copies, strict=True):
        send = CampaignSend(
            business_id=bid,
            campaign_id=campaign.id,
            customer_id=customer.id,
            channel=channel,
            subject=copy.subject,
            body=copy.body,
            status="pending",
            generation_model=copy.model,
            generated_by=copy.generated_by,
            variant=variant,
        )
        db.add(send)
        await db.flush()
        result.sends.append(send)
        # Batch generation shares one prompt across recipients, so the trace
        # recorded per send is the per-recipient context that went into it.
        await record_generation(
            db,
            business_id=bid,
            purpose=f"campaign_{channel}",
            system_prompt=f"[batch] {ctx.business_name} / {ctx.business_type}",
            user_prompt=(
                f"Customer: {ctx.customer_name}\n"
                f"Reasons: {'; '.join(ctx.risk_reasons)}\n"
                f"History: {ctx.history_summary}\n"
                f"Incentive: {ctx.incentive or 'none'}"
            ),
            raw_output=(f"subject={copy.subject!r}\n{copy.body}"),
            model=copy.model,
            generated_by=copy.generated_by,
            campaign_send_id=send.id,
            customer_id=customer.id,
        )

    campaign.status = "pending_approval"
    await db.flush()
    await record_audit(
        db,
        business_id=bid,
        action="campaign_created",
        actor=user,
        subject_type="campaign",
        subject_id=str(campaign.id),
        summary=(
            f"Created {channel} campaign '{campaign.name}' for "
            f"{len(result.sends)} customer(s)"
            + (" as an A/B test" if ab_test else "")
        ),
    )
    return result


@dataclass
class ApprovalSummary:
    sent: int = 0
    failed: int = 0
    deferred: int = 0  # held back by TCPA quiet hours; retry later
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


async def approve_campaign(
    db: AsyncSession, *, user: CurrentUser, campaign: Campaign
) -> ApprovalSummary:
    """Approve and send every pending send on a campaign.

    Consent is re-checked per send: this is the owner saying "send all of it",
    which can be minutes or days after the copy was generated, and a customer
    who replied STOP in between must not be messaged.
    """
    summary = ApprovalSummary()
    biz = await db.get(Business, campaign.business_id)
    if biz is None:
        raise ValueError("Business not found")

    pending = (
        (
            await db.execute(
                select(CampaignSend).where(
                    CampaignSend.campaign_id == campaign.id,
                    CampaignSend.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    if not pending:
        return summary

    campaign.status = "sending"
    await db.flush()

    for send in pending:
        customer = await db.get(Customer, send.customer_id)
        if customer is None:
            send.status = "skipped"
            send.failure_reason = "customer_removed"
            summary.skip("customer_removed")
            continue
        allowed, reason = can_contact(customer, send.channel)
        if not allowed:
            send.status = "skipped"
            send.failure_reason = reason
            summary.skip(reason or "not_allowed")
            continue
        if not send.body.strip():
            # A send with no copy (generation produced nothing usable and the
            # owner never wrote one) is held rather than sent blank.
            summary.skip("no_copy")
            continue

        await attempt_send(db, send, customer, biz)
        if send.status == "sent":
            summary.sent += 1
        elif send.status == "pending":
            summary.deferred += 1
        else:
            summary.failed += 1

    await db.flush()
    # "sent" once nothing is waiting on us. Quiet-hours deferrals keep the
    # campaign in "sending" so the next dispatch tick picks them up.
    campaign.status = "sending" if summary.deferred else "sent"
    if not summary.sent and not summary.deferred and summary.failed:
        campaign.status = "failed"
    await db.flush()

    if summary.sent:
        await emit_webhook(
            db,
            business_id=campaign.business_id,
            event_type="campaign.sent",
            data={
                "campaign": {
                    "id": str(campaign.id),
                    "name": campaign.name,
                    "channel": campaign.channel,
                    "kind": campaign.kind,
                },
                "sent": summary.sent,
                "failed": summary.failed,
                "deferred": summary.deferred,
            },
        )
    await record_audit(
        db,
        business_id=campaign.business_id,
        action="campaign_launched",
        actor=user,
        subject_type="campaign",
        subject_id=str(campaign.id),
        summary=(
            f"Approved campaign '{campaign.name}': {summary.sent} sent, "
            f"{summary.failed} failed, {summary.deferred} waiting for sending hours"
        ),
    )
    return summary


async def edit_send(
    db: AsyncSession,
    *,
    user: CurrentUser,
    send: CampaignSend,
    subject: str | None,
    body: str | None,
) -> CampaignSend:
    """Rewrite a pending send's copy before it goes out.

    Only pending sends are editable - once something is sent, the record of
    what was sent has to stay accurate.
    """
    if send.status != "pending":
        raise ValueError(f"This message is already '{send.status}' and can't be edited.")
    changed = []
    if body is not None and body.strip():
        send.body = body.strip()
        changed.append("body")
    if subject is not None and send.channel == "email":
        send.subject = subject.strip()
        changed.append("subject")
    if changed:
        # An owner-edited message is no longer the model's output, and the
        # dashboard shouldn't keep crediting Claude for copy a human rewrote.
        send.generated_by = "owner_edited"
        await db.flush()
        await record_audit(
            db,
            business_id=send.business_id,
            action="send_edited",
            actor=user,
            subject_type="campaign_send",
            subject_id=str(send.id),
            summary=f"Edited {', '.join(changed)} before sending",
        )
    return send


async def cancel_send(
    db: AsyncSession, *, user: CurrentUser, send: CampaignSend
) -> CampaignSend:
    """Drop a pending send without sending it."""
    if send.status != "pending":
        raise ValueError(f"This message is already '{send.status}' and can't be cancelled.")
    send.status = "skipped"
    send.failure_reason = "cancelled_by_owner"
    await db.flush()
    await record_audit(
        db,
        business_id=send.business_id,
        action="send_cancelled",
        actor=user,
        subject_type="campaign_send",
        subject_id=str(send.id),
        summary="Cancelled before sending",
    )
    return send


async def regenerate_send(
    db: AsyncSession, *, user: CurrentUser, send: CampaignSend
) -> CampaignSend:
    """Ask for different copy for one pending send."""
    from app.campaigns.generator import generate_campaign_traced

    if send.status != "pending":
        raise ValueError(f"This message is already '{send.status}' and can't be regenerated.")
    biz = await db.get(Business, send.business_id)
    customer = await db.get(Customer, send.customer_id)
    if biz is None or customer is None:
        raise ValueError("Customer or business not found")
    campaign = await db.get(Campaign, send.campaign_id)

    sync = await load_sync(db, str(send.business_id))
    scored = next(
        (
            s
            for s in build_scored_customers(sync, vertical=biz.vertical)
            if s.customer.external_id == str(send.customer_id)
        ),
        None,
    )
    display = (
        _display_name(scored)
        if scored
        else (f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "there")
    )
    offer = (
        campaign.variant_b_incentive
        if (campaign and send.variant == "B" and campaign.variant_b_incentive)
        else (campaign.incentive if campaign else None)
    )
    knowledge = await search_knowledge(
        db,
        business_id=str(send.business_id),
        query=f"win-back {send.channel} for {display}. Incentive: {offer or 'none'}.",
    )
    ctx = CampaignContext(
        business_name=biz.name,
        business_type=biz.vertical,
        customer_name=display,
        channel=send.channel,
        incentive=offer,
        risk_reasons=list(scored.result.reasons) if scored else [],
        history_summary=_history_summary(scored),
        knowledge_snippets=[row.content for row in knowledge],
        unsubscribe_url=unsubscribe_url(str(send.business_id), str(customer.id)),
    )

    copy, trace = await generate_campaign_traced(ctx)
    send.subject = copy.subject
    send.body = copy.body
    send.generation_model = copy.model
    send.generated_by = copy.generated_by
    await db.flush()
    await record_generation(
        db,
        business_id=send.business_id,
        purpose=f"campaign_{send.channel}",
        system_prompt=trace.system_prompt,
        user_prompt=trace.user_prompt,
        raw_output=trace.raw_output,
        model=trace.model,
        generated_by=copy.generated_by,
        attempts=trace.attempts,
        latency_ms=trace.latency_ms,
        error=trace.error,
        campaign_send_id=send.id,
        customer_id=customer.id,
    )
    return send


def fallback_copy_for(
    *, business_name: str, customer_name: str, channel: str, incentive: str | None
) -> GeneratedCopy:
    """Static copy, for callers that need something without an LLM round trip."""
    from app.campaigns.templates import fallback_email, fallback_sms

    if channel == "sms":
        return GeneratedCopy(
            body=fallback_sms(
                business_name=business_name,
                customer_name=customer_name,
                incentive=incentive,
            ),
            generated_by="fallback",
        )
    subject, body = fallback_email(
        business_name=business_name,
        customer_name=customer_name,
        incentive=incentive,
        unsubscribe_url="",
    )
    return GeneratedCopy(body=body, subject=subject, generated_by="fallback")
