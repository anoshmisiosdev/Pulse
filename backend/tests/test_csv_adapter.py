"""CSV adapter — the reference integration. Must swallow messy real-world exports."""

from __future__ import annotations

import pytest

from app.integrations.base import IntegrationError
from app.integrations.csv_adapter import (
    CSVAdapter,
    dedupe_customers,
    parse_amount,
    parse_csv,
    parse_date,
    template_csv,
)


def test_parse_basic_template_shape():
    sync = parse_csv(template_csv())
    assert len(sync.customers) == 2
    assert sync.customers[0].email == "jordan@example.com"
    assert len(sync.visits) == 2  # last_visit column present on both rows
    assert len(sync.transactions) == 2  # total_spent present on both


def test_header_synonyms_and_full_name_split():
    csv_text = (
        "Full Name,Email Address,Mobile,Last Seen,LTV\n"
        'Casey Morgan,CASEY@Example.com , (555) 123-9000 ,2026-01-15,"$1,250.50"\n'
    )
    sync = parse_csv(csv_text)
    c = sync.customers[0]
    assert c.first_name == "Casey"
    assert c.last_name == "Morgan"
    assert c.email == "casey@example.com"  # normalized lower
    assert c.phone == "5551239000"  # digits only
    assert float(sync.transactions[0].amount) == pytest.approx(1250.50)


def test_dedupe_merges_by_email_filling_missing_fields():
    csv_text = (
        "first_name,last_name,email,phone\n"
        "Sam,,sam@example.com,\n"
        ",Rivera,sam@example.com,555-0101\n"
    )
    sync = parse_csv(csv_text)
    assert len(sync.customers) == 2  # parse keeps rows
    merged = dedupe_customers(sync.customers)
    assert len(merged) == 1
    assert merged[0].first_name == "Sam"
    assert merged[0].last_name == "Rivera"
    assert merged[0].phone == "5550101"


def test_name_only_rows_pass_through_dedupe():
    rows = parse_csv("name\nAnon Person\n").customers
    merged = dedupe_customers(rows)
    assert len(merged) == 1
    assert merged[0].full_name == "Anon Person"


def test_missing_identity_column_raises():
    with pytest.raises(IntegrationError):
        parse_csv("color,size\nred,large\n")


def test_no_header_returns_warning():
    sync = parse_csv("")
    assert sync.warnings


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,250.50", 1250.50),
        ("  42 ", 42.0),
        ("€99", 99.0),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_amount(raw, expected):
    if expected is None:
        assert parse_amount(raw) is None
    else:
        assert parse_amount(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    ["2026-01-15", "01/15/2026", "Jan 15, 2026", "2026-01-15T10:00:00"],
)
def test_parse_date_formats(raw):
    assert parse_date(raw) is not None


def test_parse_date_garbage_is_none():
    assert parse_date("not a date") is None
    assert parse_date("") is None


async def test_adapter_connect_and_sync_roundtrip():
    adapter = CSVAdapter()
    await adapter.connect({"content": template_csv()})
    customers = await adapter.sync_customers()
    visits = await adapter.sync_visits()
    transactions = await adapter.sync_transactions()
    assert len(customers) == 2
    assert len(visits) == 2
    assert len(transactions) == 2


async def test_adapter_requires_content():
    adapter = CSVAdapter()
    with pytest.raises(IntegrationError):
        await adapter.connect({})
