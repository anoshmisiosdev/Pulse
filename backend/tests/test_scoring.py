"""Scoring engine — the trust-critical core. Deterministic via injected `now`."""

from __future__ import annotations

from datetime import timedelta

from app.scoring import CustomerActivity, SpendEvent, score_customer
from app.scoring.config import get_vertical_config


def _every_n_days(now, n, span_days, end_days_ago=0):
    """Visit timestamps every `n` days over `span_days`, ending `end_days_ago` ago."""
    out = []
    t = now - timedelta(days=end_days_ago)
    end = now - timedelta(days=end_days_ago + span_days)
    while t > end:
        out.append(t)
        t -= timedelta(days=n)
    return out


def test_healthy_customer_is_low_band(now):
    activity = CustomerActivity(
        customer_id="healthy",
        visit_dates=_every_n_days(now, 4, 180, end_days_ago=3),
        joined_at=now - timedelta(days=400),
    )
    result = score_customer(activity, vertical="fitness", now=now)
    assert result.band == "low"
    assert result.score < 40
    assert any("Healthy" in r for r in result.reasons)


def test_long_absence_is_high_band_with_reason(now):
    activity = CustomerActivity(
        customer_id="gone",
        visit_dates=_every_n_days(now, 4, 180, end_days_ago=60),
        joined_at=now - timedelta(days=400),
    )
    result = score_customer(activity, vertical="fitness", now=now)
    assert result.band == "high"
    assert result.score >= 70
    assert any("Last visit" in r for r in result.reasons)


def test_no_visits_is_maximal_recency_risk(now):
    activity = CustomerActivity(customer_id="ghost", visit_dates=[])
    result = score_customer(activity, vertical="fitness", now=now)
    assert result.signals["recency"] == 1.0
    assert any("No recorded visits" in r for r in result.reasons)


def test_new_customer_band_is_capped_without_hard_flags(now):
    # Thin history + long gap would score "high", but a new customer is capped to med.
    activity = CustomerActivity(
        customer_id="newbie",
        visit_dates=[now - timedelta(days=19)],
        joined_at=now - timedelta(days=20),
    )
    result = score_customer(activity, vertical="fitness", now=now)
    assert result.band == "med"
    assert any("New customer" in r for r in result.reasons)


def test_failed_payment_and_cancel_boost_score(now):
    base = CustomerActivity(
        customer_id="c",
        visit_dates=_every_n_days(now, 5, 120, end_days_ago=5),
        joined_at=now - timedelta(days=300),
    )
    flagged = CustomerActivity(
        customer_id="c",
        visit_dates=_every_n_days(now, 5, 120, end_days_ago=5),
        joined_at=now - timedelta(days=300),
        failed_payment=True,
        subscription_cancel_at=now + timedelta(days=10),
    )
    base_score = score_customer(base, vertical="fitness", now=now).score
    flagged_result = score_customer(flagged, vertical="fitness", now=now)
    assert flagged_result.score >= base_score + 40
    assert any("Payment" in r for r in flagged_result.reasons)
    assert any("cancel" in r for r in flagged_result.reasons)


def test_vertical_changes_outcome(now):
    # One visit 100 days ago: alarming for a gym, normal for a med spa.
    activity = CustomerActivity(
        customer_id="c",
        visit_dates=[now - timedelta(days=100)],
        joined_at=now - timedelta(days=500),
    )
    gym = score_customer(activity, vertical="fitness", now=now)
    spa = score_customer(activity, vertical="med_spa", now=now)
    assert gym.score > spa.score
    assert gym.band == "high"
    assert spa.band == "low"


def test_frequency_decline_surfaces_reason(now):
    # Used to come weekly, then went quiet in the last month.
    visits = _every_n_days(now, 5, 90, end_days_ago=35)
    activity = CustomerActivity(
        customer_id="slow", visit_dates=visits, joined_at=now - timedelta(days=300)
    )
    result = score_customer(activity, vertical="fitness", now=now)
    assert "frequency" in result.signals
    assert any("dropped" in r.lower() or "Last visit" in r for r in result.reasons)


def test_monetary_decline_signal(now):
    spend = [SpendEvent(at=now - timedelta(days=d), amount=10.0) for d in (100, 130, 160)]
    spend += [SpendEvent(at=now - timedelta(days=80), amount=2.0)]  # recent quarter down
    activity = CustomerActivity(
        customer_id="spender",
        visit_dates=_every_n_days(now, 7, 200, end_days_ago=5),
        spend_events=spend,
        joined_at=now - timedelta(days=400),
    )
    result = score_customer(activity, vertical="fitness", now=now)
    assert "monetary" in result.signals


def test_score_is_bounded_and_band_consistent(now):
    cfg = get_vertical_config("fitness")
    activity = CustomerActivity(
        customer_id="x",
        visit_dates=[now - timedelta(days=400)],
        failed_payment=True,
        subscription_cancel_at=now,
    )
    result = score_customer(activity, vertical=cfg, now=now)
    assert 0 <= result.score <= 100
    assert result.band in ("low", "med", "high")
