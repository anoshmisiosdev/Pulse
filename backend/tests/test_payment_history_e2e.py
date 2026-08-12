"""End-to-end payment history -> identity -> retention risk verification."""

from __future__ import annotations

import uuid
from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.integrations.base import IntegrationError
from app.models import Customer, CustomerIdentity, ProviderWebhookEvent, Transaction, Visit
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)
from app.scripts.payment_history_demo import generate_provider_sync
from app.services import ingest
from app.services.activity import build_scored_customers, monthly_revenue_series
from app.services.payment_webhooks import apply_provider_event


@pytest.mark.parametrize("provider", ["stripe", "square"])
def test_provider_shaped_fixture_reaches_retention_scoring(provider, now):
    sync = generate_provider_sync(provider, n=24, now=now.replace(tzinfo=UTC))
    scored = build_scored_customers(sync, vertical="cafe", now=now)

    assert len(scored) == 24
    assert len(sync.transactions) > 24
    assert any(customer.result.band == "high" for customer in scored)
    assert any(customer.payment_issue for customer in scored)
    assert any(
        "Payment on file failed" in customer.result.reasons
        for customer in scored
        if customer.payment_issue
    )
    assert all(customer.return_likelihood == 100 - customer.result.score for customer in scored)
    assert sum(point["amount"] for point in monthly_revenue_series(sync, now=now)) > 0


async def test_cross_provider_identity_preserves_both_ids_and_payments(db, now):
    business_id = str(uuid.uuid4())
    anchored = now.replace(tzinfo=UTC)
    stripe = generate_provider_sync("stripe", n=8, now=anchored)
    square = generate_provider_sync("square", n=8, now=anchored)

    await ingest.ensure_business(db, business_id, "Dual Rail Cafe", "cafe")
    stripe_run = await ingest.persist_sync(db, business_id, "stripe", stripe)
    square_run = await ingest.persist_sync(db, business_id, "square", square)

    assert stripe_run.customers_synced == 8
    assert square_run.customers_synced == 0
    assert square_run.transactions_synced == len(square.transactions)
    assert (await db.scalar(select(func.count(Customer.id)))) == 8
    assert (await db.scalar(select(func.count(CustomerIdentity.id)))) == 16

    first = stripe.customers[0]
    canonical = (
        await db.execute(select(Customer).where(Customer.email == first.email))
    ).scalar_one()
    identities = (
        await db.execute(
            select(CustomerIdentity).where(CustomerIdentity.customer_id == canonical.id)
        )
    ).scalars().all()
    assert {identity.source for identity in identities} == {"stripe", "square"}


async def test_refund_reconciles_existing_revenue_and_visit(db, now):
    business_id = str(uuid.uuid4())
    occurred_at = now.replace(tzinfo=UTC) - timedelta(days=5)
    customer = NormalizedCustomer(
        source="stripe", external_id="cus_refund", email="refund@example.com"
    )
    completed = NormalizedTransaction(
        source="stripe",
        external_id="ch_refund",
        customer_external_id="cus_refund",
        customer_email=customer.email,
        amount=Decimal("20.00"),
        gross_amount=Decimal("20.00"),
        status="completed",
        occurred_at=occurred_at,
        updated_at=occurred_at,
    )
    visit = NormalizedVisit(
        source="stripe",
        external_id="visit-ch_refund",
        customer_external_id="cus_refund",
        customer_email=customer.email,
        occurred_at=occurred_at,
    )
    await ingest.ensure_business(db, business_id, "Refund Cafe", "cafe")
    await ingest.persist_sync(
        db,
        business_id,
        "stripe",
        SyncResult(customers=[customer], transactions=[completed], visits=[visit]),
    )

    refunded = completed.model_copy(
        update={
            "amount": Decimal("0"),
            "refunded_amount": Decimal("20.00"),
            "status": "refunded",
            "updated_at": occurred_at + timedelta(days=2),
        }
    )
    run = await ingest.persist_sync(
        db,
        business_id,
        "stripe",
        SyncResult(customers=[customer], transactions=[refunded]),
    )

    assert run.transactions_synced == 1
    assert run.visits_synced == 1
    transaction = (await db.execute(select(Transaction))).scalar_one()
    assert transaction.status == "refunded"
    assert transaction.amount == Decimal("0.00")
    assert (await db.scalar(select(func.count(Visit.id)))) == 0
    loaded = await ingest.load_sync(db, business_id)
    assert sum(point["amount"] for point in monthly_revenue_series(loaded, now=now)) == 0


async def test_stripe_webhook_is_idempotent_and_refund_aware(db, now):
    business_id = str(uuid.uuid4())
    await ingest.ensure_business(db, business_id, "Webhook Cafe", "cafe")
    await ingest.upsert_connection(
        db,
        business_id,
        "stripe",
        "encrypted-placeholder",
        provider_account_id="acct_demo",
        environment="sandbox",
    )
    created = int((now.replace(tzinfo=UTC) - timedelta(days=3)).timestamp())
    succeeded = {
        "id": "evt_success",
        "type": "charge.succeeded",
        "account": "acct_demo",
        "created": created,
        "data": {
            "object": {
                "id": "ch_webhook",
                "status": "succeeded",
                "amount": 1800,
                "amount_refunded": 0,
                "currency": "usd",
                "created": created,
                "billing_details": {
                    "name": "Ari Gomez",
                    "email": "ari@example.com",
                },
            }
        },
    }

    assert (await apply_provider_event(db, "stripe", succeeded))["status"] == "processed"
    assert (await apply_provider_event(db, "stripe", succeeded))["status"] == "duplicate"
    assert (await db.scalar(select(func.count(Customer.id)))) == 1
    assert (await db.scalar(select(func.count(Transaction.id)))) == 1
    assert (await db.scalar(select(func.count(Visit.id)))) == 1

    refunded = {
        **succeeded,
        "id": "evt_refund",
        "type": "charge.refunded",
        "created": created + 86400,
        "data": {
            "object": {
                **succeeded["data"]["object"],
                "refunded": True,
                "amount_refunded": 1800,
            }
        },
    }
    assert (await apply_provider_event(db, "stripe", refunded))["status"] == "processed"
    transaction = (await db.execute(select(Transaction))).scalar_one()
    assert transaction.status == "refunded" and transaction.amount == 0
    assert (await db.scalar(select(func.count(Visit.id)))) == 0
    assert (await db.scalar(select(func.count(ProviderWebhookEvent.id)))) == 2


async def test_square_webhook_accepts_event_id_and_merchant_id(db, now):
    business_id = str(uuid.uuid4())
    await ingest.ensure_business(db, business_id, "Square Webhook Cafe", "cafe")
    await ingest.upsert_connection(
        db,
        business_id,
        "square",
        "encrypted-placeholder",
        provider_account_id="merchant_demo",
        environment="sandbox",
    )
    timestamp = now.replace(tzinfo=UTC).isoformat()
    event = {
        "event_id": "square_event_1",
        "type": "payment.updated",
        "merchant_id": "merchant_demo",
        "data": {
            "object": {
                "payment": {
                    "id": "square_payment_1",
                    "status": "COMPLETED",
                    "amount_money": {"amount": 975, "currency": "USD"},
                    "buyer_email_address": "square-buyer@example.com",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            }
        },
    }

    result = await apply_provider_event(db, "square", event)
    assert result == {"status": "processed", "event_id": "square_event_1"}
    transaction = (await db.execute(select(Transaction))).scalar_one()
    assert transaction.source == "square" and transaction.amount == Decimal("9.75")
    assert (await db.scalar(select(func.count(Customer.id)))) == 1
    assert (await db.scalar(select(func.count(Visit.id)))) == 1


async def test_provider_account_cannot_route_into_two_businesses(db):
    first_business = str(uuid.uuid4())
    second_business = str(uuid.uuid4())
    await ingest.ensure_business(db, first_business, "First Cafe", "cafe")
    await ingest.ensure_business(db, second_business, "Second Cafe", "cafe")
    await ingest.upsert_connection(
        db,
        first_business,
        "stripe",
        "encrypted-placeholder",
        provider_account_id="acct_unique",
    )

    with pytest.raises(IntegrationError, match="already connected"):
        await ingest.upsert_connection(
            db,
            second_business,
            "stripe",
            "encrypted-placeholder",
            provider_account_id="acct_unique",
        )
