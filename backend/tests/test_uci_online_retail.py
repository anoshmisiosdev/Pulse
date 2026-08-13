"""Public UCI Online Retail sample normalization and scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.csv_adapter import parse_csv
from app.integrations.uci_online_retail import (
    OnlineRetailRow,
    build_online_retail_sync,
    rebase_sync,
)
from app.services.activity import build_scored_customers, portfolio_currency


def _row(invoice: str, customer: str, day: int, amount: str, item: str) -> OnlineRetailRow:
    return OnlineRetailRow(
        invoice_no=invoice,
        description=item,
        quantity=Decimal("1") if not invoice.startswith("C") else Decimal("-1"),
        invoice_at=datetime(2011, 1, day, tzinfo=UTC),
        unit_price=Decimal(amount),
        customer_id=customer,
    )


def test_online_retail_rows_become_invoice_payments_visits_and_refunds():
    rows = [
        _row("100", "A", 1, "10", "Mug"),
        _row("100", "A", 1, "5", "Tea"),
        _row("101", "A", 8, "12", "Mug"),
        _row("C102", "A", 9, "5", "Tea"),
        _row("200", "B", 2, "20", "Bag"),
        _row("201", "B", 12, "25", "Bag"),
    ]

    sync = build_online_retail_sync(
        rows, max_customers=None, max_transactions_per_customer=None
    )

    assert len(sync.customers) == 2
    assert len(sync.transactions) == 5
    assert len(sync.visits) == 4
    assert sum(t.amount for t in sync.transactions) == Decimal("72")
    refunded = next(t for t in sync.transactions if t.external_id.endswith("C102"))
    assert refunded.status == "refunded"
    assert refunded.amount == 0 and refunded.refunded_amount == Decimal("5")
    customer = next(c for c in sync.customers if c.external_id == "A")
    assert customer.favorite_item == "Mug"
    assert portfolio_currency(sync) == "GBP"


def test_rebase_preserves_interpurchase_intervals_and_scores():
    sync = build_online_retail_sync(
        [_row("100", "A", 1, "10", "Mug"), _row("101", "A", 8, "12", "Mug")],
        max_customers=None,
    )
    original_gap = sync.visits[1].occurred_at - sync.visits[0].occurred_at
    rebased = rebase_sync(sync, now=datetime(2026, 8, 12, tzinfo=UTC))

    assert rebased.visits[1].occurred_at - rebased.visits[0].occurred_at == original_gap
    assert rebased.visits[-1].occurred_at.date().isoformat() == "2026-08-11"
    scored = build_scored_customers(rebased, vertical="other", now=datetime(2026, 8, 12))
    assert len(scored) == 1 and scored[0].visit_count == 2


def test_csv_accepts_pseudonymous_customer_id_as_identity():
    sync = parse_csv(
        "customer_id,date,amount\n"
        "public-1,2026-08-01,12.50\n"
        "public-1,2026-08-08,8.25\n"
    )

    assert len(sync.customers) == 2
    assert len(sync.transactions) == 2
    assert sync.customers[0].dedupe_key == "csv:public-1"
