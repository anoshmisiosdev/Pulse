"""Recovery attribution: the matcher's judgement calls, then the DB round-trip.

The pure ``match_recoveries`` tests are the important ones — they pin down what we
are willing to claim credit for, which is the part an owner would argue with.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import Campaign, CampaignSend, Customer, RecoveryAttribution, Transaction, Visit
from app.services import ingest
from app.services.attribution import (
    ReturnEvent,
    SendRecord,
    detect_recoveries,
    match_recoveries,
    recovery_totals,
)

BUSINESS_ID = str(uuid.uuid4())
BASE = datetime(2026, 5, 1)
CUSTOMER = "c1"


def _send(days: int, send_id: str = "s1", customer: str = CUSTOMER) -> SendRecord:
    return SendRecord(send_id=send_id, customer_id=customer, sent_at=BASE + timedelta(days=days))


def _return(days: int, amount: float = 0.0, customer: str = CUSTOMER) -> ReturnEvent:
    return ReturnEvent(
        customer_id=customer, occurred_at=BASE + timedelta(days=days), amount=amount
    )


# ── the matcher ──────────────────────────────────────────────────────────────


def test_a_visit_inside_the_window_counts_as_recovered():
    matches = match_recoveries([_send(0)], [_return(5, amount=40.0)], window_days=30)
    assert len(matches) == 1
    assert matches[0].send_id == "s1"
    assert matches[0].revenue_recovered == 40.0
    assert matches[0].recovered_at == BASE + timedelta(days=5)


def test_a_return_before_the_send_is_not_a_recovery():
    """They came back on their own the day before we wrote to them. Not ours."""
    assert match_recoveries([_send(10)], [_return(9, amount=80.0)], window_days=30) == []


def test_a_return_after_the_window_is_not_a_recovery():
    assert match_recoveries([_send(0)], [_return(45, amount=80.0)], window_days=30) == []


def test_window_boundary_is_inclusive():
    assert len(match_recoveries([_send(0)], [_return(30, amount=10.0)], window_days=30)) == 1
    assert match_recoveries([_send(0)], [_return(31, amount=10.0)], window_days=30) == []


def test_credit_goes_to_the_most_recent_send_before_the_return():
    """Last-touch: two messages went out, the second one gets the credit."""
    matches = match_recoveries(
        [_send(0, "first"), _send(10, "second")],
        [_return(12, amount=25.0)],
        window_days=30,
    )
    assert [m.send_id for m in matches] == ["second"]


def test_one_recovery_per_customer_even_with_many_returns():
    """A customer who comes back three times is one recovery, not three."""
    matches = match_recoveries(
        [_send(0)],
        [_return(3, amount=10.0), _return(6, amount=20.0), _return(9, amount=30.0)],
        window_days=30,
    )
    assert len(matches) == 1
    # ...but all the spend inside the window counts toward what we recovered.
    assert matches[0].revenue_recovered == 60.0


def test_revenue_is_only_counted_inside_the_window():
    matches = match_recoveries(
        [_send(0)],
        [_return(5, amount=50.0), _return(40, amount=500.0)],
        window_days=30,
    )
    assert matches[0].revenue_recovered == 50.0


def test_a_visit_with_no_recorded_spend_still_counts_at_zero_revenue():
    """Door-scan POS exports have visits but no tickets. That's a real recovery
    worth reporting — we just can't claim revenue for it."""
    matches = match_recoveries([_send(0)], [_return(4)], window_days=30)
    assert len(matches) == 1
    assert matches[0].revenue_recovered == 0.0


def test_already_recovered_customers_are_skipped():
    """This is what makes re-running the job safe."""
    assert (
        match_recoveries(
            [_send(0)],
            [_return(5, amount=40.0)],
            window_days=30,
            already_recovered=frozenset({CUSTOMER}),
        )
        == []
    )


def test_customers_are_matched_independently():
    matches = match_recoveries(
        [_send(0, "s-a", "a"), _send(0, "s-b", "b")],
        [_return(5, 10.0, "a"), _return(90, 999.0, "b")],
        window_days=30,
    )
    assert [m.customer_id for m in matches] == ["a"]


def test_no_sends_means_no_recoveries():
    assert match_recoveries([], [_return(5, amount=100.0)], window_days=30) == []


# ── the DB path ──────────────────────────────────────────────────────────────


async def _seed_business(db) -> Customer:
    await ingest.ensure_business(db, BUSINESS_ID, "Hayward Coffee Co.", "cafe")
    customer = Customer(
        business_id=ingest._uuid(BUSINESS_ID),
        source="csv",
        first_name="Dana",
        last_name="Reyes",
        email="dana@example.com",
    )
    db.add(customer)
    await db.flush()
    return customer


async def _seed_send(
    db, customer: Customer, *, days_ago: int, status: str = "sent"
) -> CampaignSend:
    bid = ingest._uuid(BUSINESS_ID)
    campaign = Campaign(business_id=bid, name="Win back", channel="email", status="sending")
    db.add(campaign)
    await db.flush()
    send = CampaignSend(
        business_id=bid,
        campaign_id=campaign.id,
        customer_id=customer.id,
        channel="email",
        subject="We miss you",
        body="Come back",
        status=status,
        sent_at=datetime.now() - timedelta(days=days_ago),
    )
    db.add(send)
    await db.flush()
    return send


async def test_detect_recoveries_writes_an_attribution_and_flags_the_customer(db):
    customer = await _seed_business(db)
    send = await _seed_send(db, customer, days_ago=10)
    db.add(
        Transaction(
            business_id=ingest._uuid(BUSINESS_ID),
            customer_id=customer.id,
            source="csv",
            amount=64,
            occurred_at=datetime.now() - timedelta(days=3),
        )
    )
    await db.flush()

    summary = await detect_recoveries(db, BUSINESS_ID)
    assert summary.recoveries_found == 1
    assert summary.revenue_recovered == 64.0
    assert summary.sends_considered == 1

    rows = (await db.execute(select(RecoveryAttribution))).scalars().all()
    assert len(rows) == 1
    assert rows[0].campaign_send_id == send.id
    assert float(rows[0].estimated_value) == 64.0
    assert (await db.get(Customer, customer.id)).recovered is True


async def test_detect_recoveries_is_idempotent(db):
    customer = await _seed_business(db)
    await _seed_send(db, customer, days_ago=10)
    db.add(
        Visit(
            business_id=ingest._uuid(BUSINESS_ID),
            customer_id=customer.id,
            source="csv",
            occurred_at=datetime.now() - timedelta(days=2),
        )
    )
    await db.flush()

    first = await detect_recoveries(db, BUSINESS_ID)
    second = await detect_recoveries(db, BUSINESS_ID)
    assert first.recoveries_found == 1
    assert second.recoveries_found == 0

    rows = (await db.execute(select(RecoveryAttribution))).scalars().all()
    assert len(rows) == 1


async def test_pending_sends_earn_no_credit(db):
    """An unapproved draft never reached the customer, so their return isn't ours."""
    customer = await _seed_business(db)
    await _seed_send(db, customer, days_ago=10, status="pending")
    db.add(
        Visit(
            business_id=ingest._uuid(BUSINESS_ID),
            customer_id=customer.id,
            source="csv",
            occurred_at=datetime.now() - timedelta(days=2),
        )
    )
    await db.flush()

    summary = await detect_recoveries(db, BUSINESS_ID)
    assert summary.recoveries_found == 0
    assert summary.sends_considered == 0


async def test_recovery_is_scoped_to_the_tenant(db):
    """Another business's identical activity must not show up in our totals."""
    customer = await _seed_business(db)
    await _seed_send(db, customer, days_ago=10)
    db.add(
        Transaction(
            business_id=ingest._uuid(BUSINESS_ID),
            customer_id=customer.id,
            source="csv",
            amount=30,
            occurred_at=datetime.now() - timedelta(days=1),
        )
    )
    await db.flush()
    await detect_recoveries(db, BUSINESS_ID)

    other = str(uuid.uuid4())
    await ingest.ensure_business(db, other, "Someone Else", "cafe")
    await db.flush()

    assert (await recovery_totals(db, BUSINESS_ID)).recovered_count == 1
    assert (await recovery_totals(db, other)).recovered_count == 0
    assert (await recovery_totals(db, other)).revenue_recovered == 0.0


async def test_recovery_totals_sum_observed_revenue(db):
    customer = await _seed_business(db)
    await _seed_send(db, customer, days_ago=10)
    for days, amount in ((4, 20), (2, 15)):
        db.add(
            Transaction(
                business_id=ingest._uuid(BUSINESS_ID),
                customer_id=customer.id,
                source="csv",
                amount=amount,
                occurred_at=datetime.now() - timedelta(days=days),
            )
        )
    await db.flush()
    await detect_recoveries(db, BUSINESS_ID)

    totals = await recovery_totals(db, BUSINESS_ID)
    assert totals.recovered_count == 1
    assert totals.revenue_recovered == 35.0
