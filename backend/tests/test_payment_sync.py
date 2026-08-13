"""Scheduled/manual incremental payment sync orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import encrypt_token
from app.models import Transaction
from app.schemas.normalized import NormalizedCustomer, NormalizedTransaction, NormalizedVisit
from app.services import ingest
from app.services.payment_sync import sync_connection


async def test_sync_connection_uses_overlap_and_updates_account_metadata(db, now, monkeypatch):
    business_id = str(uuid.uuid4())
    anchor = now.replace(tzinfo=UTC)
    await ingest.ensure_business(db, business_id, "Scheduled Cafe", "cafe")
    connection = await ingest.upsert_connection(
        db,
        business_id,
        "stripe",
        encrypt_token("sk_test_fixture"),
        provider_account_id="acct_old",
        environment="production",
        synced_at=anchor,
    )
    observed_since = []

    class FakeStripeAdapter:
        account_id = "acct_current"
        environment = "production"

        async def connect(self, auth_payload):
            assert auth_payload["access_token"] == "sk_test_fixture"

        async def sync_customers(self, since=None):
            observed_since.append(since)
            return [
                NormalizedCustomer(
                    source="stripe", external_id="cus_sync", email="sync@example.com"
                )
            ]

        async def sync_transactions(self, since=None):
            observed_since.append(since)
            return [
                NormalizedTransaction(
                    source="stripe",
                    external_id="ch_sync",
                    customer_external_id="cus_sync",
                    customer_email="sync@example.com",
                    amount=Decimal("11.25"),
                    status="completed",
                    occurred_at=anchor - timedelta(days=1),
                )
            ]

        async def sync_visits(self, since=None):
            observed_since.append(since)
            return [
                NormalizedVisit(
                    source="stripe",
                    external_id="visit-ch_sync",
                    customer_external_id="cus_sync",
                    customer_email="sync@example.com",
                    occurred_at=anchor - timedelta(days=1),
                )
            ]

    monkeypatch.setattr(
        "app.services.payment_sync.get_adapter_class", lambda source: FakeStripeAdapter
    )
    run = await sync_connection(db, connection)

    expected_since = anchor - timedelta(minutes=settings.payment_sync_overlap_minutes)
    assert observed_since == [expected_since, expected_since, expected_since]
    assert run.transactions_synced == 1
    assert connection.provider_account_id == "acct_current"
    assert connection.status == "active" and connection.last_error is None
    assert (await db.scalar(select(func.count(Transaction.id)))) == 1
