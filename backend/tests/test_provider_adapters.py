"""Pure parsing tests for the Stripe/Square payload -> normalized mapping."""

from __future__ import annotations

from decimal import Decimal

from app.integrations.square_adapter import parse_square_customer, parse_square_payment
from app.integrations.stripe_adapter import parse_stripe_charge, parse_stripe_customer

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


def test_stripe_charge_skips_failed_refunded_and_zero():
    base = {"id": "ch", "amount": 500, "currency": "usd", "created": 1700000000}
    assert parse_stripe_charge({**base, "status": "failed"}) is None
    assert parse_stripe_charge({**base, "status": "succeeded", "refunded": True}) is None
    assert (
        parse_stripe_charge(
            {**base, "status": "succeeded", "amount": 500, "amount_refunded": 500}
        )
        is None
    )


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


def test_square_payment_skips_incomplete_and_refunded():
    assert parse_square_payment({"id": "p", "status": "FAILED"}) is None
    assert (
        parse_square_payment(
            {
                "id": "p2",
                "status": "COMPLETED",
                "amount_money": {"amount": 500, "currency": "USD"},
                "refunded_money": {"amount": 500},
                "created_at": "2024-06-01T12:00:00Z",
            }
        )
        is None
    )
