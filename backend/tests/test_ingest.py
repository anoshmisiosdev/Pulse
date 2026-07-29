"""Ingest round-trip: persist a normalized sync, load it back, score it.

Runs against in-memory SQLite so tests stay hermetic (no Supabase needed).
"""

from __future__ import annotations

import uuid

from app.models import Customer, SyncRun
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)
from app.services import ingest

BUSINESS_ID = str(uuid.uuid4())


def _sample_sync(now) -> SyncResult:
    from datetime import timedelta

    return SyncResult(
        customers=[
            NormalizedCustomer(
                external_id="cus_1", source="stripe", first_name="Amara",
                last_name="Nwosu", email="amara@example.com",
                created_at=now - timedelta(days=200),
            ),
            NormalizedCustomer(
                external_id="cus_2", source="stripe", first_name="Ravi",
                email="ravi@example.com", created_at=now - timedelta(days=100),
            ),
        ],
        transactions=[
            NormalizedTransaction(
                external_id=f"ch_{i}", source="stripe", customer_external_id="cus_1",
                customer_email="amara@example.com", amount=12,
                occurred_at=now - timedelta(days=7 * i),
            )
            for i in range(1, 8)
        ],
        visits=[
            NormalizedVisit(
                external_id=f"v_{i}", source="stripe", customer_external_id="cus_1",
                customer_email="amara@example.com",
                occurred_at=now - timedelta(days=7 * i),
            )
            for i in range(1, 8)
        ],
    )


async def test_persist_then_load_round_trips(db, now):
    await ingest.ensure_business(db, BUSINESS_ID, "Test Cafe", "cafe")
    run = await ingest.persist_sync(db, BUSINESS_ID, "stripe", _sample_sync(now))

    assert run.status == "success"
    assert run.customers_synced == 2
    assert run.transactions_synced == 7
    assert run.visits_synced == 7

    loaded = await ingest.load_sync(db, BUSINESS_ID)
    assert len(loaded.customers) == 2
    assert len(loaded.transactions) == 7
    emails = {c.email for c in loaded.customers}
    assert emails == {"amara@example.com", "ravi@example.com"}
    assert await ingest.has_data(db, BUSINESS_ID)


async def test_repersist_is_idempotent(db, now):
    await ingest.ensure_business(db, BUSINESS_ID, "Test Cafe", "cafe")
    await ingest.persist_sync(db, BUSINESS_ID, "stripe", _sample_sync(now))
    run2 = await ingest.persist_sync(db, BUSINESS_ID, "stripe", _sample_sync(now))

    # Second import of identical data creates nothing new.
    assert run2.customers_synced == 0
    assert run2.transactions_synced == 0
    assert run2.visits_synced == 0
    loaded = await ingest.load_sync(db, BUSINESS_ID)
    assert len(loaded.customers) == 2
    assert len(loaded.transactions) == 7


async def test_scores_are_written_after_persist(db, now):
    from sqlalchemy import select

    await ingest.ensure_business(db, BUSINESS_ID, "Test Cafe", "cafe")
    await ingest.persist_sync(db, BUSINESS_ID, "stripe", _sample_sync(now))

    rows = (await db.execute(select(Customer))).scalars().all()
    scored = [r for r in rows if r.current_score is not None]
    assert scored, "expected denormalized scores on customer rows"
    assert all(r.current_band in ("low", "med", "high") for r in scored)


async def test_wipe_business_data(db, now):
    await ingest.ensure_business(db, BUSINESS_ID, "Test Cafe", "cafe")
    await ingest.persist_sync(db, BUSINESS_ID, "stripe", _sample_sync(now))
    await ingest.wipe_business_data(db, BUSINESS_ID)

    assert not await ingest.has_data(db, BUSINESS_ID)
    from sqlalchemy import select

    assert (await db.execute(select(SyncRun))).scalars().first() is None


async def test_cross_source_merge_by_email(db, now):
    """A Square customer with the same email as an existing Stripe one merges."""
    await ingest.ensure_business(db, BUSINESS_ID, "Test Cafe", "cafe")
    await ingest.persist_sync(db, BUSINESS_ID, "stripe", _sample_sync(now))

    square = SyncResult(
        customers=[
            NormalizedCustomer(
                external_id="SQ1", source="square", first_name="Amara",
                email="amara@example.com", phone="555-000-1111",
            )
        ]
    )
    run = await ingest.persist_sync(db, BUSINESS_ID, "square", square)
    assert run.customers_synced == 0  # merged, not duplicated

    loaded = await ingest.load_sync(db, BUSINESS_ID)
    assert len(loaded.customers) == 2
    amara = next(c for c in loaded.customers if c.email == "amara@example.com")
    assert amara.phone == "5550001111"  # phone backfilled from the Square record
