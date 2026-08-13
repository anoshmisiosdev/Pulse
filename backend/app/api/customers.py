"""Per-customer detail: the chronological timeline behind a risk score.

Nothing new is stored to build this. Pulse already writes five timestamped
streams — visits, transactions, engagement events, risk-score changes and
outreach — and this merges them into one ordered narrative so "why is this
customer at risk" comes with receipts instead of just a number.

Every query filters on ``business_id`` from the authenticated session before the
customer id is trusted, so one tenant can't read another's customer by guessing
a UUID (spec §34, and the multi-tenant rule in CLAUDE.md).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.models import (
    CampaignSend,
    Customer,
    EngagementEvent,
    RecoveryAttribution,
    RiskScore,
    Transaction,
    Visit,
)
from app.schemas.api import CustomerTimelineOut, TimelineEntry
from app.services.ingest import _uuid

router = APIRouter(prefix="/customers", tags=["customers"])

# Engagement events read as plain English rather than event names — the timeline
# is shown to a salon owner, not to us.
_ENGAGEMENT_TITLE = {
    "email_sent": "Email sent",
    "email_open": "Opened the email",
    "email_click": "Clicked a link in the email",
    "email_delivered": "Email delivered",
    "email_bounced": "Email bounced",
    "email_complained": "Marked the email as spam",
    "sms_sent": "Text message sent",
    "reply": "Replied",
    "stop": "Replied STOP (opted out)",
}

_SEND_TITLE = {
    "pending": "Win-back message drafted, awaiting your approval",
    "approved": "Win-back message approved",
    "sent": "Win-back message sent",
    "delivered": "Win-back message delivered",
    "failed": "Win-back message failed to send",
    "skipped": "Win-back message skipped",
}


def _iso(dt: datetime | None) -> str:
    """ISO 8601 with an explicit UTC offset. SQLite hands back naive datetimes;
    the frontend needs to know what zone it's reading."""
    if dt is None:
        return ""
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


@router.get("/{customer_id}/timeline", response_model=CustomerTimelineOut)
async def customer_timeline(
    customer_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> CustomerTimelineOut:
    """Everything that happened to this customer, newest first."""
    try:
        cid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(404, "Not found") from None

    bid = _uuid(user.business_id)
    customer = await db.get(Customer, cid)
    # Same 404 for "no such customer" and "not yours" — a different status here
    # would leak which UUIDs exist in other tenants.
    if customer is None or customer.business_id != bid:
        raise HTTPException(404, "Not found")

    entries: list[TimelineEntry] = []

    visits = (
        await db.execute(
            select(Visit.occurred_at, Visit.source).where(
                Visit.business_id == bid, Visit.customer_id == cid
            )
        )
    ).all()
    entries += [
        TimelineEntry(at=_iso(at), kind="visit", title="Visited", detail=f"via {source}")
        for at, source in visits
    ]

    transactions = (
        await db.execute(
            select(Transaction.occurred_at, Transaction.amount, Transaction.currency).where(
                Transaction.business_id == bid, Transaction.customer_id == cid
            )
        )
    ).all()
    entries += [
        TimelineEntry(
            at=_iso(at),
            kind="purchase",
            title="Purchase",
            detail=currency,
            amount=float(amount),
        )
        for at, amount, currency in transactions
    ]

    engagement = (
        await db.execute(
            select(
                EngagementEvent.occurred_at, EngagementEvent.kind, EngagementEvent.detail
            ).where(EngagementEvent.business_id == bid, EngagementEvent.customer_id == cid)
        )
    ).all()
    entries += [
        TimelineEntry(
            at=_iso(at),
            kind="engagement",
            title=_ENGAGEMENT_TITLE.get(kind, kind.replace("_", " ").capitalize()),
            detail=detail,
        )
        for at, kind, detail in engagement
    ]

    # RiskScore is append-only and only written on a band change, so every row
    # here is a real inflection point worth showing.
    risk_changes = (
        await db.execute(
            select(RiskScore.created_at, RiskScore.score, RiskScore.band, RiskScore.reasons).where(
                RiskScore.business_id == bid, RiskScore.customer_id == cid
            )
        )
    ).all()
    entries += [
        TimelineEntry(
            at=_iso(created_at),
            kind="risk_change",
            title=f"Risk became {band} ({score}/100)",
            detail="; ".join(reasons or []) or None,
        )
        for created_at, score, band, reasons in risk_changes
    ]

    sends = (
        await db.execute(
            select(
                CampaignSend.created_at,
                CampaignSend.sent_at,
                CampaignSend.status,
                CampaignSend.channel,
                CampaignSend.subject,
                CampaignSend.failure_reason,
            ).where(CampaignSend.business_id == bid, CampaignSend.customer_id == cid)
        )
    ).all()
    for created_at, sent_at, status, channel, subject, failure_reason in sends:
        title = _SEND_TITLE.get(status, f"Win-back message {status}")
        entries.append(
            TimelineEntry(
                at=_iso(sent_at or created_at),
                kind="outreach",
                title=f"{title} ({channel})",
                detail=failure_reason or subject,
            )
        )

    recoveries = (
        await db.execute(
            select(RecoveryAttribution.recovered_at, RecoveryAttribution.estimated_value).where(
                RecoveryAttribution.business_id == bid, RecoveryAttribution.customer_id == cid
            )
        )
    ).all()
    entries += [
        TimelineEntry(
            at=_iso(at),
            kind="recovered",
            title="Came back after outreach",
            detail="Revenue observed since the message",
            amount=float(value or 0),
        )
        for at, value in recoveries
    ]

    entries.sort(key=lambda e: e.at, reverse=True)
    name = f"{customer.first_name or ''} {customer.last_name or ''}".strip() or (
        customer.email or customer.phone or "Customer"
    )
    return CustomerTimelineOut(
        customer_id=str(customer.id), name=name, entries=entries[:limit]
    )
