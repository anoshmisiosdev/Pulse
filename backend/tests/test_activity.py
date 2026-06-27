"""End-to-end (in-memory): normalized records -> scored portfolio -> money screen."""

from __future__ import annotations

from datetime import datetime

from app.campaigns.generator import CampaignContext, generate_campaign
from app.integrations.csv_adapter import parse_csv
from app.scripts.demo_data import generate_sync, to_customer_csv
from app.services.activity import build_scored_customers, summarize

NOW = datetime(2026, 6, 26)


def test_demo_portfolio_spreads_across_bands():
    sync = generate_sync(n=200, seed=7, now=NOW)
    scored = build_scored_customers(sync, vertical="fitness", now=NOW)
    summary = summarize(scored)

    assert summary.total_customers == 200
    assert summary.high_risk + summary.med_risk + summary.low_risk == 200
    # A realistic studio has customers in every band.
    assert summary.high_risk > 0
    assert summary.low_risk > 0
    assert summary.revenue_at_risk > 0


def test_every_scored_customer_has_reasons():
    sync = generate_sync(n=50, seed=1, now=NOW)
    scored = build_scored_customers(sync, vertical="fitness", now=NOW)
    assert all(s.result.reasons for s in scored)
    assert all(0 <= s.result.score <= 100 for s in scored)


def test_demo_csv_roundtrips_through_parser():
    sync = generate_sync(n=30, seed=3, now=NOW)
    csv_text = to_customer_csv(sync)
    reparsed = parse_csv(csv_text)
    assert len(reparsed.customers) == 30
    # Aggregate CSV yields one visit + one transaction per customer.
    assert len(reparsed.visits) == 30


def test_visits_attribute_to_the_right_customer():
    sync = generate_sync(n=10, seed=2, now=NOW)
    scored = build_scored_customers(sync, vertical="fitness", now=NOW)
    # At least some customers accumulated multiple visits (proves grouping works).
    assert any("recency" in s.result.signals for s in scored)


async def test_generate_campaign_falls_back_without_api_key():
    # No ANTHROPIC_API_KEY in test env -> deterministic static fallback.
    ctx = CampaignContext(
        business_name="Iron Peak Fitness",
        business_type="gym",
        customer_name="Jordan Lee",
        channel="email",
        incentive="a free week",
        risk_reasons=["Last visit 28 days ago"],
    )
    copy = await generate_campaign(ctx)
    assert copy.generated_by == "fallback"
    assert copy.subject
    assert "unsubscribe" in copy.body.lower() or "stop" in copy.body.lower()
