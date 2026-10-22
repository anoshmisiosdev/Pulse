"""Outbound webhook endpoints: register, list, toggle, test, delete.

Owner-only throughout: an endpoint ships customer names and contact details to
a third-party URL, which is exactly the kind of change staff can't make (see
core/deps.py::get_owner). Creating one also needs the automation entitlement,
the same gate as unattended sending.

The signing secret is returned once, at creation. Listing never includes it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.guard import EntitlementsDep, require_automation
from app.billing.limits import Entitlements
from app.core.database import get_db
from app.core.deps import CurrentUser, OwnerDep
from app.core.posthog_client import capture_event
from app.models import WebhookDelivery, WebhookEndpoint
from app.models.webhooks import WEBHOOK_EVENTS
from app.schemas.webhooks import (
    DeliveryOut,
    EndpointCreatedOut,
    EndpointIn,
    EndpointOut,
    EndpointPatch,
    TestResultOut,
)
from app.services import outbound_webhooks as hooks
from app.services.generation_log import record_audit

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _endpoint_out(row: WebhookEndpoint) -> EndpointOut:
    return EndpointOut(
        id=str(row.id),
        url=row.url,
        description=row.description,
        events=list(row.events or []),
        enabled=row.enabled,
        last_success_at=_iso(row.last_success_at),
        last_failure_at=_iso(row.last_failure_at),
        consecutive_failures=row.consecutive_failures or 0,
        auto_disabled=(
            not row.enabled
            and (row.consecutive_failures or 0) >= hooks.DISABLE_AFTER_CONSECUTIVE_FAILURES
        ),
        created_at=_iso(row.created_at) or "",
    )


async def _load(db: AsyncSession, owner: CurrentUser, endpoint_id: str) -> WebhookEndpoint:
    try:
        parsed = uuid.UUID(endpoint_id)
    except ValueError:
        raise HTTPException(404, "Not found") from None
    row = await db.get(WebhookEndpoint, parsed)
    if row is None or row.business_id != uuid.UUID(owner.business_id):
        raise HTTPException(404, "Not found")
    return row


@router.get("/events", response_model=list[str])
async def events(_owner: CurrentUser = OwnerDep) -> list[str]:
    return [e for e in WEBHOOK_EVENTS if e != "webhook.test"]


@router.get("", response_model=list[EndpointOut])
async def list_endpoints(
    db: AsyncSession = Depends(get_db), owner: CurrentUser = OwnerDep
) -> list[EndpointOut]:
    rows = (
        (
            await db.execute(
                select(WebhookEndpoint)
                .where(WebhookEndpoint.business_id == uuid.UUID(owner.business_id))
                .order_by(WebhookEndpoint.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_endpoint_out(r) for r in rows]


@router.post("", response_model=EndpointCreatedOut, status_code=201)
async def create(
    payload: EndpointIn,
    db: AsyncSession = Depends(get_db),
    owner: CurrentUser = OwnerDep,
    ent: Entitlements = EntitlementsDep,
) -> EndpointCreatedOut:
    require_automation(ent)
    try:
        created = await hooks.create_endpoint(
            db,
            business_id=owner.business_id,
            url=payload.url,
            events=payload.events,
            description=payload.description,
        )
    except hooks.WebhookURLError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await record_audit(
        db,
        business_id=owner.business_id,
        action="webhook_created",
        actor=owner,
        subject_type="webhook_endpoint",
        subject_id=str(created.endpoint.id),
        summary=f"Added webhook endpoint {created.endpoint.url}",
    )
    await db.commit()
    capture_event("webhook_endpoint_created", distinct_id=owner.user_id)
    return EndpointCreatedOut(endpoint=_endpoint_out(created.endpoint), secret=created.secret)


@router.patch("/{endpoint_id}", response_model=EndpointOut)
async def update(
    endpoint_id: str,
    payload: EndpointPatch,
    db: AsyncSession = Depends(get_db),
    owner: CurrentUser = OwnerDep,
) -> EndpointOut:
    row = await _load(db, owner, endpoint_id)
    if payload.events is not None:
        unknown = [e for e in payload.events if e not in WEBHOOK_EVENTS]
        if unknown:
            raise HTTPException(422, detail=f"Unknown event(s): {', '.join(unknown)}.")
        row.events = hooks._clean_events(payload.events)
    if payload.description is not None:
        row.description = payload.description.strip()[:255] or None
    if payload.enabled is not None:
        if payload.enabled and not row.enabled:
            # Re-validate on re-enable: the host may have moved since.
            try:
                hooks.validate_url(row.url)
            except hooks.WebhookURLError as exc:
                raise HTTPException(422, detail=str(exc)) from exc
            row.consecutive_failures = 0
        row.enabled = payload.enabled
    await db.commit()
    return _endpoint_out(row)


@router.delete("/{endpoint_id}", status_code=204)
async def delete(
    endpoint_id: str, db: AsyncSession = Depends(get_db), owner: CurrentUser = OwnerDep
) -> None:
    row = await _load(db, owner, endpoint_id)
    url = row.url
    # Deliveries first: explicit rather than trusting ON DELETE CASCADE, which
    # SQLite doesn't enforce (same reason as the chat and privacy deletes).
    from sqlalchemy import delete as sql_delete

    await db.execute(sql_delete(WebhookDelivery).where(WebhookDelivery.endpoint_id == row.id))
    await db.delete(row)
    await record_audit(
        db,
        business_id=owner.business_id,
        action="webhook_deleted",
        actor=owner,
        subject_type="webhook_endpoint",
        subject_id=endpoint_id,
        summary=f"Removed webhook endpoint {url}",
    )
    await db.commit()


@router.post("/{endpoint_id}/test", response_model=TestResultOut)
async def send_test(
    endpoint_id: str, db: AsyncSession = Depends(get_db), owner: CurrentUser = OwnerDep
) -> TestResultOut:
    """Send a `webhook.test` event right now and report what happened."""
    row = await _load(db, owner, endpoint_id)
    if not row.enabled:
        raise HTTPException(422, detail="Enable this endpoint before testing it.")
    queued = await hooks.emit(
        db,
        business_id=owner.business_id,
        event_type="webhook.test",
        data={"message": "Test event from Churnary. If you can read this, it works."},
        only_endpoint_id=row.id,
    )
    if not queued:
        raise HTTPException(422, detail="Couldn't queue a test event for this endpoint.")
    await hooks.deliver_pending(db, business_id=uuid.UUID(owner.business_id), limit=5)
    latest = (
        await db.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.endpoint_id == row.id,
                WebhookDelivery.event_type == "webhook.test",
            )
            .order_by(WebhookDelivery.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    await db.commit()
    return TestResultOut(
        delivered=latest.status == "delivered",
        response_status=latest.response_status,
        error=latest.last_error,
    )


@router.get("/{endpoint_id}/deliveries", response_model=list[DeliveryOut])
async def deliveries(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    owner: CurrentUser = OwnerDep,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[DeliveryOut]:
    """Recent deliveries: status and timing only. Payloads hold customer data
    and aren't echoed back here."""
    row = await _load(db, owner, endpoint_id)
    rows = (
        (
            await db.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.endpoint_id == row.id)
                .order_by(WebhookDelivery.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        DeliveryOut(
            id=str(d.id),
            event_type=d.event_type,
            event_id=d.event_id,
            status=d.status,
            attempts=d.attempts,
            response_status=d.response_status,
            last_error=d.last_error,
            created_at=_iso(d.created_at) or "",
            delivered_at=_iso(d.delivered_at),
            next_attempt_at=_iso(d.next_attempt_at),
        )
        for d in rows
    ]
