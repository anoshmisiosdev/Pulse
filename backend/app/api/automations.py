"""Automation rules (rule engine + SMS/email dispatch), send history, and the
Twilio/unsubscribe webhooks that keep consent state honest.

Default mode is approve-to-send product-wide (see CLAUDE.md) — "auto" is an
explicit opt-in per rule, not the default.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.security import decrypt_token
from app.models import AutomationRule, Business, CampaignSend, Customer, EngagementEvent
from app.schemas.api import (
    AutomationRuleIn,
    AutomationRuleOut,
    AutomationRulePatch,
    CampaignSendOut,
    DispatchSummaryOut,
)
from app.services.automations import attempt_send, dispatch_automations
from app.services.ingest import _uuid
from app.services.webhooks import verify_svix_signature

logger = logging.getLogger("pulse.api.automations")

router = APIRouter(prefix="/automations", tags=["automations"])


def _rule_out(rule: AutomationRule) -> AutomationRuleOut:
    return AutomationRuleOut(
        id=str(rule.id),
        name=rule.name,
        trigger_band=rule.trigger_band,
        channel=rule.channel,
        incentive=rule.incentive,
        mode=rule.mode,
        cooldown_days=rule.cooldown_days,
        enabled=rule.enabled,
        created_at=rule.created_at.isoformat(),
    )


_ENGAGEMENT_KINDS = {"email_open": "opened", "email_click": "clicked", "reply": "replied"}


def _send_out(
    send: CampaignSend, customer: Customer, engagement: set[str] | None = None
) -> CampaignSendOut:
    name = f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer"
    engagement = engagement or set()
    return CampaignSendOut(
        id=str(send.id),
        customer_id=str(customer.id),
        customer_name=name,
        automation_rule_id=str(send.automation_rule_id) if send.automation_rule_id else None,
        channel=send.channel,
        subject=send.subject,
        body=send.body,
        status=send.status,
        sent_at=send.sent_at.isoformat() if send.sent_at else None,
        failure_reason=send.failure_reason,
        created_at=send.created_at.isoformat(),
        opened="opened" in engagement,
        clicked="clicked" in engagement,
        replied="replied" in engagement,
    )


@router.get("/rules", response_model=list[AutomationRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> list[AutomationRuleOut]:
    rows = (
        (
            await db.execute(
                select(AutomationRule)
                .where(AutomationRule.business_id == _uuid(user.business_id))
                .order_by(AutomationRule.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_rule_out(r) for r in rows]


@router.post("/rules", response_model=AutomationRuleOut, status_code=201)
async def create_rule(
    payload: AutomationRuleIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> AutomationRuleOut:
    if payload.channel not in ("sms", "email"):
        raise HTTPException(422, "channel must be 'sms' or 'email'")
    if payload.trigger_band not in ("low", "med", "high"):
        raise HTTPException(422, "trigger_band must be 'low', 'med', or 'high'")
    if payload.mode not in ("suggest", "approve", "auto"):
        raise HTTPException(422, "mode must be 'suggest', 'approve', or 'auto'")
    rule = AutomationRule(business_id=_uuid(user.business_id), **payload.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_out(rule)


@router.patch("/rules/{rule_id}", response_model=AutomationRuleOut)
async def update_rule(
    rule_id: str,
    payload: AutomationRulePatch,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> AutomationRuleOut:
    rule = await db.get(AutomationRule, _uuid(rule_id))
    if rule is None or rule.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    await db.commit()
    await db.refresh(rule)
    return _rule_out(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str, db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> None:
    rule = await db.get(AutomationRule, _uuid(rule_id))
    if rule is None or rule.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Not found")
    await db.delete(rule)
    await db.commit()


@router.get("/sends", response_model=list[CampaignSendOut])
async def list_sends(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> list[CampaignSendOut]:
    rows = (
        await db.execute(
            select(CampaignSend, Customer)
            .join(Customer, Customer.id == CampaignSend.customer_id)
            .where(CampaignSend.business_id == _uuid(user.business_id))
            .order_by(CampaignSend.created_at.desc())
            .limit(min(limit, 200))
        )
    ).all()

    send_ids = [send.id for send, _ in rows]
    engagement_by_send: dict = {}
    if send_ids:
        events = (
            await db.execute(
                select(EngagementEvent.campaign_send_id, EngagementEvent.kind).where(
                    EngagementEvent.campaign_send_id.in_(send_ids),
                    EngagementEvent.kind.in_(_ENGAGEMENT_KINDS),
                )
            )
        ).all()
        for send_id, kind in events:
            engagement_by_send.setdefault(send_id, set()).add(_ENGAGEMENT_KINDS[kind])

    return [_send_out(send, customer, engagement_by_send.get(send.id)) for send, customer in rows]


@router.post("/sends/{send_id}/approve", response_model=CampaignSendOut)
async def approve_send(
    send_id: str, db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> CampaignSendOut:
    send = await db.get(CampaignSend, _uuid(send_id))
    if send is None or send.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Not found")
    if send.status != "pending":
        raise HTTPException(422, f"Send is '{send.status}', not pending")

    customer = await db.get(Customer, send.customer_id)
    biz = await db.get(Business, send.business_id)
    if customer is None or biz is None:
        raise HTTPException(404, "Customer or business not found")

    await attempt_send(db, send, customer, biz)
    await db.commit()
    await db.refresh(send)

    if send.status == "pending":
        raise HTTPException(
            409,
            "Still outside allowed SMS hours (9am-8pm local) — "
            "TCPA requires waiting; try again later.",
        )
    return _send_out(send, customer)


@router.post("/dispatch", response_model=DispatchSummaryOut)
async def trigger_dispatch(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> DispatchSummaryOut:
    """Manually run the rule engine now, instead of waiting for the next beat tick."""
    summary = await dispatch_automations(db, user.business_id)
    await db.commit()
    return DispatchSummaryOut(
        rules_evaluated=summary.rules_evaluated,
        sends_created=summary.sends_created,
        skipped=summary.skipped,
    )


# ── Public webhooks (no auth — Twilio and email links call these directly) ──


def _verify_twilio_signature(request: Request, form: dict) -> bool:
    if not settings.twilio_configured:
        return False
    from twilio.request_validator import RequestValidator

    signature = request.headers.get("X-Twilio-Signature", "")
    url = f"{settings.api_base_url}{request.url.path}"
    return RequestValidator(settings.twilio_auth_token).validate(url, form, signature)


@router.post("/twilio/inbound")
async def twilio_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    """Twilio POSTs here on every inbound SMS reply. Twilio's own Advanced
    Opt-Out already blocks future sends to STOP-family numbers at the carrier
    level; we still track it ourselves so the dashboard/dispatcher agree."""
    form = dict(await request.form())
    if not _verify_twilio_signature(request, form):
        raise HTTPException(403, "Invalid Twilio signature")

    raw_body = str(form.get("Body", "")).strip()
    from_number = str(form.get("From", ""))
    customers = (
        await db.execute(select(Customer).where(Customer.phone == from_number))
    ).scalars().all()

    if raw_body.upper() in ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
        for customer in customers:
            customer.unsubscribed_sms = True
        logger.info("SMS opt-out recorded for %s (%d customer rows)", from_number, len(customers))
    else:
        now = datetime.now(UTC)
        for customer in customers:
            last_send = (
                await db.execute(
                    select(CampaignSend.id)
                    .where(CampaignSend.customer_id == customer.id, CampaignSend.channel == "sms")
                    .order_by(CampaignSend.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            db.add(
                EngagementEvent(
                    business_id=customer.business_id,
                    customer_id=customer.id,
                    kind="reply",
                    occurred_at=now,
                    campaign_send_id=last_send,
                    detail=raw_body[:1000],
                )
            )
    await db.commit()

    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml"
    )


@router.post("/twilio/status")
async def twilio_status(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Twilio's delivery-status callback: updates a CampaignSend's status by
    the MessageSid we stored as provider_message_id when it was sent."""
    form = dict(await request.form())
    if not _verify_twilio_signature(request, form):
        raise HTTPException(403, "Invalid Twilio signature")

    sid = form.get("MessageSid")
    status = str(form.get("MessageStatus", ""))
    if sid and status in ("delivered", "undelivered", "failed"):
        send = (
            await db.execute(select(CampaignSend).where(CampaignSend.provider_message_id == sid))
        ).scalar_one_or_none()
        if send is not None:
            send.status = "delivered" if status == "delivered" else "failed"
            if status != "delivered":
                send.failure_reason = f"twilio_status:{status}"
            await db.commit()
    return {"ok": True}


_RESEND_EVENT_KIND = {
    "email.opened": "email_open",
    "email.clicked": "email_click",
    "email.bounced": "email_bounced",
    "email.complained": "email_complained",
    "email.delivered": "email_delivered",
}


@router.post("/resend/webhook")
async def resend_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Resend's delivery-event webhook (opens/clicks/bounces/complaints).
    Bounces and spam complaints unsubscribe the customer immediately —
    continuing to send to either damages sender reputation for everyone."""
    raw = await request.body()
    ok = verify_svix_signature(
        settings.resend_webhook_secret,
        raw,
        svix_id=request.headers.get("svix-id", ""),
        svix_timestamp=request.headers.get("svix-timestamp", ""),
        svix_signature=request.headers.get("svix-signature", ""),
    )
    if not ok:
        raise HTTPException(403, "Invalid webhook signature")

    payload = json.loads(raw)
    event_type = payload.get("type", "")
    kind = _RESEND_EVENT_KIND.get(event_type)
    if kind is None:
        return {"ok": True}  # event we don't track (e.g. email.sent, email.delivery_delayed)

    data = payload.get("data") or {}
    email_id = data.get("email_id")
    if not email_id:
        return {"ok": True}

    send = (
        await db.execute(select(CampaignSend).where(CampaignSend.provider_message_id == email_id))
    ).scalar_one_or_none()
    if send is None:
        return {"ok": True}

    detail = None
    if event_type == "email.clicked":
        detail = (data.get("click") or {}).get("link")

    db.add(
        EngagementEvent(
            business_id=send.business_id,
            customer_id=send.customer_id,
            kind=kind,
            occurred_at=datetime.now(UTC),
            campaign_send_id=send.id,
            detail=detail,
        )
    )

    if event_type == "email.delivered":
        send.status = "delivered"
    elif event_type in ("email.bounced", "email.complained"):
        send.status = "failed"
        send.failure_reason = event_type.removeprefix("email.")
        customer = await db.get(Customer, send.customer_id)
        if customer is not None:
            customer.unsubscribed_email = True

    await db.commit()
    return {"ok": True}


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str, db: AsyncSession = Depends(get_db)) -> str:
    """CAN-SPAM unsubscribe link target — every generated email includes this
    URL (see app.services.automations.unsubscribe_url)."""
    try:
        business_id, customer_id = decrypt_token(token).split(":", 1)
    except ValueError:
        raise HTTPException(400, "Invalid or corrupted unsubscribe link") from None

    customer = await db.get(Customer, _uuid(customer_id))
    if customer is None or customer.business_id != _uuid(business_id):
        raise HTTPException(404, "Not found")

    customer.unsubscribed_email = True
    await db.commit()
    return (
        "<html><body><p>You've been unsubscribed and won't receive "
        "further emails.</p></body></html>"
    )
