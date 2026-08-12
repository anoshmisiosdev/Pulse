"""Pure parsing tests for the Stripe/Square payload -> normalized mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, call

from app.integrations.square_adapter import (
    SquareAdapter,
    parse_square_customer,
    parse_square_payment,
)
from app.integrations.stripe_adapter import (
    StripeAdapter,
    parse_stripe_charge,
    parse_stripe_customer,
)

# ── Stripe ──────────────────────────────────────────────────────────────────


def test_stripe_customer_maps_name_email_phone():
    c = parse_stripe_customer(
        {
            "id": "cus_123",
            "name": "Amara Nwosu",
            "email": "Amara@Example.com",
            "phone": "+1 (555) 010-2030",
            "created": 1700000000,
        }
    )
    assert c.external_id == "cus_123"
    assert c.first_name == "Amara" and c.last_name == "Nwosu"
    assert c.email == "amara@example.com"  # normalized
    assert c.phone == "+15550102030"
    assert c.created_at is not None
    assert c.source == "stripe"


def test_stripe_customer_handles_missing_fields():
    c = parse_stripe_customer({"id": "cus_x"})
    assert c.first_name is None and c.email is None


def test_stripe_charge_succeeded_maps_amount_from_cents():
    t = parse_stripe_charge(
        {
            "id": "ch_1",
            "status": "succeeded",
            "refunded": False,
            "amount": 1250,
            "amount_refunded": 0,
            "currency": "usd",
            "customer": "cus_123",
            "created": 1700000000,
            "billing_details": {"email": "a@b.com"},
        }
    )
    assert t is not None
    assert t.amount == Decimal("12.50")
    assert t.customer_external_id == "cus_123"
    assert t.customer_email == "a@b.com"


def test_stripe_charge_keeps_failed_and_refunded_lifecycle_states():
    base = {"id": "ch", "amount": 500, "currency": "usd", "created": 1700000000}
    failed = parse_stripe_charge({**base, "status": "failed", "failure_code": "card_declined"})
    assert failed is not None and failed.status == "failed" and failed.amount == 0
    assert failed.failure_code == "card_declined"

    refunded = parse_stripe_charge(
        {
            **base,
            "status": "succeeded",
            "refunded": True,
            "amount_refunded": 500,
        }
    )
    assert refunded is not None and refunded.status == "refunded"
    assert refunded.amount == 0 and refunded.refunded_amount == Decimal("5")

    partial = parse_stripe_charge(
        {**base, "status": "succeeded", "amount_refunded": 125}
    )
    assert partial is not None and partial.status == "partially_refunded"
    assert partial.amount == Decimal("3.75")


def test_stripe_charge_zero_decimal_currency():
    t = parse_stripe_charge(
        {"id": "ch_jpy", "status": "succeeded", "amount": 1200, "currency": "jpy",
         "created": 1700000000}
    )
    assert t is not None and t.amount == Decimal("1200")


# ── Square ──────────────────────────────────────────────────────────────────


def test_square_customer_maps_fields():
    c = parse_square_customer(
        {
            "id": "SQ_C1",
            "given_name": "Ravi",
            "family_name": "Patel",
            "email_address": "Ravi@Example.com",
            "phone_number": "555-010-9999",
            "created_at": "2024-03-01T10:00:00Z",
        }
    )
    assert c.external_id == "SQ_C1"
    assert c.first_name == "Ravi" and c.last_name == "Patel"
    assert c.email == "ravi@example.com"
    assert c.created_at is not None
    assert c.source == "square"


def test_square_payment_completed_maps_amount():
    t = parse_square_payment(
        {
            "id": "PAY1",
            "status": "COMPLETED",
            "amount_money": {"amount": 850, "currency": "USD"},
            "customer_id": "SQ_C1",
            "created_at": "2024-06-01T12:00:00Z",
        }
    )
    assert t is not None
    assert t.amount == Decimal("8.50")
    assert t.customer_external_id == "SQ_C1"


def test_square_payment_keeps_incomplete_and_refunded_lifecycle_states():
    failed = parse_square_payment({"id": "p", "status": "FAILED"})
    assert failed is not None and failed.status == "failed" and failed.amount == 0

    refunded = parse_square_payment(
        {
            "id": "p2",
            "status": "COMPLETED",
            "amount_money": {"amount": 500, "currency": "USD"},
            "refunded_money": {"amount": 500},
            "created_at": "2024-06-01T12:00:00Z",
        }
    )
    assert refunded is not None and refunded.status == "refunded"
    assert refunded.amount == 0 and refunded.refunded_amount == Decimal("5")


async def test_stripe_incremental_payments_use_created_cursor_but_customers_refresh_fully():
    adapter = StripeAdapter("sk_test_demo")
    adapter._paginate = AsyncMock(return_value=[])
    since = datetime(2026, 8, 1, tzinfo=UTC)

    await adapter.sync_customers(since)
    adapter._paginate.assert_awaited_with("/customers")
    await adapter.sync_transactions(since)
    adapter._paginate.assert_has_awaits(
        [
            call("/charges", **{"created[gte]": int(since.timestamp())}),
            call(
                "/events",
                **{
                    "created[gte]": int(since.timestamp()),
                    "types[]": [
                        "charge.failed",
                        "charge.refunded",
                        "charge.succeeded",
                        "charge.updated",
                    ],
                },
            ),
        ]
    )
    assert adapter.environment == "sandbox"


async def test_stripe_incremental_events_repair_an_older_refund():
    adapter = StripeAdapter("sk_test_demo")
    since = datetime(2026, 8, 1, tzinfo=UTC)
    created = int(datetime(2026, 7, 1, tzinfo=UTC).timestamp())
    updated = int(datetime(2026, 8, 2, tzinfo=UTC).timestamp())
    adapter._paginate = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "id": "evt_refund",
                    "type": "charge.refunded",
                    "created": updated,
                    "data": {
                        "object": {
                            "id": "ch_older",
                            "status": "succeeded",
                            "amount": 2500,
                            "amount_refunded": 2500,
                            "currency": "usd",
                            "created": created,
                        }
                    },
                }
            ],
        ]
    )

    transactions = await adapter.sync_transactions(since)

    assert len(transactions) == 1
    assert transactions[0].external_id == "ch_older"
    assert transactions[0].status == "refunded"
    assert transactions[0].updated_at == datetime(2026, 8, 2, tzinfo=UTC)


async def test_square_incremental_payments_cursor_on_updated_time():
    adapter = SquareAdapter("sandbox-token", environment="sandbox")
    adapter._paginate = AsyncMock(return_value=[])
    since = datetime(2026, 8, 1, tzinfo=UTC)

    await adapter.sync_transactions(since)
    adapter._paginate.assert_awaited_with(
        "/v2/payments",
        "payments",
        updated_at_begin_time="2026-08-01T00:00:00Z",
        sort_field="UPDATED_AT",
        sort_order="ASC",
    )


async def test_square_connected_account_pulls_every_active_location():
    adapter = SquareAdapter("sandbox-token", environment="sandbox")
    adapter._get = AsyncMock(
        side_effect=[
            {"merchant": {"id": "merchant-1"}},
            {
                "locations": [
                    {"id": "location-a", "status": "ACTIVE"},
                    {"id": "location-b", "status": "ACTIVE"},
                    {"id": "location-old", "status": "INACTIVE"},
                ]
            },
        ]
    )
    await adapter.connect({"access_token": "sandbox-token", "environment": "sandbox"})
    adapter._paginate = AsyncMock(side_effect=[[], []])

    await adapter.sync_transactions(datetime(2026, 8, 1, tzinfo=UTC))

    assert adapter.account_id == "merchant-1"
    adapter._paginate.assert_has_awaits(
        [
            call(
                "/v2/payments",
                "payments",
                updated_at_begin_time="2026-08-01T00:00:00Z",
                sort_field="UPDATED_AT",
                sort_order="ASC",
                location_id="location-a",
            ),
            call(
                "/v2/payments",
                "payments",
                updated_at_begin_time="2026-08-01T00:00:00Z",
                sort_field="UPDATED_AT",
                sort_order="ASC",
                location_id="location-b",
            ),
        ]
    )
