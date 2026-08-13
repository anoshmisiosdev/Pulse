"""Normalize and apply signed Stripe/Square payment webhook events."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError
from app.integrations.square_adapter import parse_square_customer, parse_square_payment
from app.integrations.stripe_adapter import parse_stripe_charge, parse_stripe_customer
from app.models import ProviderWebhookEvent
from app.schemas.normalized import NormalizedVisit, SyncResult
from app.services import ingest

_STRIPE_CHARGE_EVENTS = {
    "charge.failed",
    "charge.refunded",
    "charge.succeeded",
    "charge.updated",
}
_STRIPE_CUSTOMER_EVENTS = {"customer.created", "customer.updated"}
_SQUARE_PAYMENT_EVENTS = {"payment.created", "payment.updated"}
_SQUARE_CUSTOMER_EVENTS = {"customer.created", "customer.updated"}


def _event_time(value: object) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC)


def _payment_visit(transaction) -> NormalizedVisit:
    return NormalizedVisit(
        external_id=f"visit-{transaction.external_id}",
        source=transaction.source,
        customer_external_id=transaction.customer_external_id,
        customer_email=transaction.customer_email,
        customer_phone=transaction.customer_phone,
        occurred_at=transaction.occurred_at,
    )


def normalize_provider_event(source: str, event: dict) -> SyncResult:
    """Convert a provider event payload into the same contract as a pull sync."""
    event_type = str(event.get("type") or "")
    data_object = ((event.get("data") or {}).get("object") or {})
    sync = SyncResult()

    if source == "stripe":
        if event_type in _STRIPE_CUSTOMER_EVENTS:
            sync.customers.append(parse_stripe_customer(data_object))
        elif event_type in _STRIPE_CHARGE_EVENTS:
            transaction = parse_stripe_charge(data_object)
            if transaction is not None:
                # Event creation time gives lifecycle updates a monotonic ordering.
                transaction.updated_at = _event_time(event.get("created"))
                sync.transactions.append(transaction)
                if transaction.is_revenue:
                    sync.visits.append(_payment_visit(transaction))
        return sync

    if source == "square":
        if event_type in _SQUARE_CUSTOMER_EVENTS:
            customer = data_object.get("customer") or data_object
            sync.customers.append(parse_square_customer(customer))
        elif event_type in _SQUARE_PAYMENT_EVENTS:
            payment = data_object.get("payment") or data_object
            transaction = parse_square_payment(payment)
            if transaction is not None:
                sync.transactions.append(transaction)
                if transaction.is_revenue:
                    sync.visits.append(_payment_visit(transaction))
        return sync

    raise IntegrationError(f"Unsupported webhook provider {source!r}")


async def apply_provider_event(
    db: AsyncSession,
    source: str,
    event: dict,
) -> dict[str, str]:
    event_id = str(event.get("id") or event.get("event_id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    account_id = str(event.get("account") or event.get("merchant_id") or "").strip()
    if not event_id or not event_type:
        raise IntegrationError("Provider webhook is missing an event id or type")
    if not account_id:
        raise IntegrationError("Provider webhook is missing its account/merchant id")

    duplicate = (
        await db.execute(
            select(ProviderWebhookEvent.id).where(
                ProviderWebhookEvent.source == source,
                ProviderWebhookEvent.provider_event_id == event_id,
            )
        )
    ).first()
    if duplicate:
        return {"status": "duplicate", "event_id": event_id}

    connection = await ingest.find_connection_by_provider_account(db, source, account_id)
    if connection is None:
        return {"status": "unmatched", "event_id": event_id}

    sync = normalize_provider_event(source, event)
    if sync.customers or sync.transactions or sync.visits:
        await ingest.persist_sync(db, str(connection.business_id), source, sync)

    now = datetime.now(UTC)
    db.add(
        ProviderWebhookEvent(
            business_id=connection.business_id,
            source=source,
            provider_event_id=event_id,
            provider_account_id=account_id,
            event_type=event_type,
            status="processed",
            processed_at=now,
        )
    )
    await db.flush()
    return {"status": "processed", "event_id": event_id}
