"""The action ladder: who gets a call, an offer, an email, or left alone.

These assertions are product decisions as much as code ones — if the ladder
changes, these tests should be the thing that argues about it.
"""

from __future__ import annotations

from datetime import datetime

from app.integrations.csv_adapter import parse_csv
from app.schemas.normalized import NormalizedCustomer
from app.scoring import ScoreResult
from app.scripts.demo_data import generate_sync, to_customer_csv
from app.services.activity import (
    ScoredCustomer,
    _high_value_threshold,
    build_scored_customers,
    recommend_action,
)

NOW = datetime(2026, 6, 26)


def _scored(
    *,
    band: str = "high",
    score: int = 80,
    segment: str = "needs_attention",
    value: float = 500.0,
    visits: int = 8,
    days_since: int | None = 40,
    signals: dict[str, float] | None = None,
    spend: float = 400.0,
) -> ScoredCustomer:
    return ScoredCustomer(
        customer=NormalizedCustomer(source="csv", first_name="Sam", email="sam@example.com"),
        result=ScoreResult(
            customer_id="sam@example.com",
            score=score,
            band=band,
            reasons=["Last visit 40 days ago"],
            signals=signals or {"recency": 0.8},
        ),
        estimated_annual_value=value,
        days_since_last_visit=days_since,
        last_visit="2026-05-17",
        visit_count=visits,
        total_spend=spend,
        segment=segment,
        pattern="fading_away",
        confidence="high",
        trend_pct=-40,
    )


def test_healthy_customers_are_left_alone():
    action, reason = recommend_action(_scored(band="low", segment="regulars"), 1000.0)
    assert action == "wait"
    assert "no outreach needed" in reason


def test_a_collapsing_ticket_beats_a_low_churn_score():
    """The customer who still turns up every week but whose spend halved. Churn risk
    is recency-weighted, so they score LOW — but "leave them alone" is the wrong call
    on someone quietly spending their money elsewhere. Low churn risk is not no
    revenue risk."""
    action, reason = recommend_action(
        _scored(band="low", segment="regulars", signals={"recency": 0.1, "monetary": 0.8}),
        high_value_threshold=1000.0,
    )
    assert action == "offer"
    assert "80% less" in reason


def test_new_customers_get_a_welcome_not_a_winback():
    action, reason = recommend_action(_scored(segment="new", visits=1), 100.0)
    assert action == "welcome"
    assert "welcome" in reason


def test_a_customer_with_no_evidence_at_all_is_only_watched():
    """One visit and no spend means the score is barely evidence."""
    action, reason = recommend_action(_scored(visits=1, spend=0.0), 100.0)
    assert action == "watch"
    assert "one recorded visit" in reason.lower()


def test_thin_visit_history_with_spend_still_gets_acted_on():
    """An aggregate CSV upload — the main onboarding path — synthesizes exactly one
    visit per customer from their last_visit date, but still carries lifetime
    spend. Those customers must not all collapse to "just watch"."""
    action, _ = recommend_action(_scored(visits=1, spend=275.0), 1000.0)
    assert action == "email"


def test_the_most_valuable_at_risk_customers_get_the_owners_call():
    action, reason = recommend_action(_scored(value=2000.0), high_value_threshold=1000.0)
    assert action == "owner_call"
    assert "$2,000/yr" in reason
    assert "40 days" in reason


def test_a_high_risk_but_ordinary_value_customer_gets_an_email():
    action, _ = recommend_action(_scored(value=200.0), high_value_threshold=1000.0)
    assert action == "email"


def test_declining_spend_gets_an_incentive_rather_than_a_plain_email():
    action, reason = recommend_action(
        _scored(value=200.0, signals={"recency": 0.4, "monetary": 0.7}),
        high_value_threshold=1000.0,
    )
    assert action == "offer"
    assert "70% less" in reason


def test_a_lapsed_customer_is_not_told_they_are_still_coming_in():
    """A customer who stopped visiting also has zero recent spend, so the monetary
    signal fires for them too — but "still coming in" would be a fabricated claim.
    High recency risk means gone, and gone means email, not offer."""
    action, reason = recommend_action(
        _scored(value=200.0, signals={"recency": 0.95, "monetary": 1.0}),
        high_value_threshold=1000.0,
    )
    assert action == "email"
    assert "still coming in" not in reason.lower()


def test_owner_call_outranks_offer_for_top_value_customers():
    action, _ = recommend_action(
        _scored(value=5000.0, signals={"monetary": 0.9}), high_value_threshold=1000.0
    )
    assert action == "owner_call"


def test_every_reason_is_non_empty_and_specific():
    """The reason is shown to the owner verbatim, so it can never be blank."""
    for kwargs in (
        {"band": "low"},
        {"segment": "new"},
        {"visits": 1, "spend": 0.0},
        {"value": 9999.0},
        {"signals": {"monetary": 0.8}},
        {},
    ):
        _, reason = recommend_action(_scored(**kwargs), 1000.0)
        assert len(reason) > 20
        assert reason[0].isupper()


def test_threshold_ignores_zero_value_customers():
    # Positives are [100, 200, 300, 400] -> 75th percentile is 300. Had the zeros
    # been counted the threshold would have dropped to 200, dragging low-value
    # customers into "worth a personal call".
    assert _high_value_threshold([0.0, 0.0, 100.0, 200.0, 300.0, 400.0]) == 300.0
    assert _high_value_threshold([]) == 0.0
    assert _high_value_threshold([0.0]) == 0.0


def test_no_owner_call_when_nobody_has_any_recorded_value():
    """A portfolio with no spend data at all shouldn't nominate anyone for a call."""
    action, _ = recommend_action(_scored(value=0.0), high_value_threshold=0.0)
    assert action != "owner_call"


def test_every_demo_customer_gets_an_action_and_a_reason():
    sync = generate_sync(n=120, seed=5, now=NOW)
    scored = build_scored_customers(sync, vertical="cafe", now=NOW)
    assert all(s.recommended_action for s in scored)
    assert all(s.action_reason for s in scored)
    # A realistic portfolio should not collapse onto a single action.
    assert len({s.recommended_action for s in scored}) >= 3


def test_an_uploaded_aggregate_csv_produces_actionable_recommendations():
    """Regression: the aggregate CSV shape (one row per customer, one synthesized
    visit each) must not collapse the whole portfolio to "just watch" — that's the
    default onboarding path, so it would make the feature useless on day one."""
    sync = generate_sync(n=60, seed=4, now=NOW)
    csv_text = to_customer_csv(sync)
    scored = build_scored_customers(parse_csv(csv_text), vertical="cafe", now=NOW)

    assert all(s.visit_count == 1 for s in scored)  # the shape this guards against
    watching = [s for s in scored if s.recommended_action == "watch"]
    assert len(watching) < len(scored) * 0.2
    assert any(s.recommended_action == "email" for s in scored)


def test_owner_call_stays_a_short_list():
    """If everyone is "call them personally", the ranking is useless — the owner
    has a finite number of phone calls in a day."""
    sync = generate_sync(n=200, seed=9, now=NOW)
    scored = build_scored_customers(sync, vertical="cafe", now=NOW)
    calls = [s for s in scored if s.recommended_action == "owner_call"]
    assert len(calls) < len(scored) * 0.3
