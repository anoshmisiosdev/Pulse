"""Scoring engine — the trust-critical core. Deterministic via injected `now`."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.scoring import CustomerActivity, SpendEvent, score_customer
from app.scoring.config import get_vertical_config
from app.scoring.engine import _count_between


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


def test_activity_today_counts_toward_the_recent_window():
    """Regression: the recent window's upper bound is closed. A purchase timestamped
    exactly at ``now`` used to fall into no window at all, so a customer who bought
    something today scored as 100% spend decline against their prior quarter."""
    now = datetime(2026, 8, 13)
    activity = CustomerActivity(
        customer_id="today",
        visit_dates=[now - timedelta(days=d) for d in (0, 30, 60, 90, 120)],
        spend_events=[
            SpendEvent(at=now, amount=50.0),
            SpendEvent(at=now - timedelta(days=120), amount=50.0),
        ],
    )
    result = score_customer(activity, vertical="med_spa", now=now)
    # Equal spend in each window -> no monetary risk, and certainly not a claim of
    # total collapse.
    assert result.signals.get("monetary", 0.0) < 0.5
    assert not any("down 100%" in r for r in result.reasons)


def test_adjacent_windows_never_double_count_a_boundary_date():
    """The flip side: only the most-recent window is closed, so a visit sitting
    exactly on an interior boundary belongs to one window, not both."""
    now = datetime(2026, 8, 13)
    boundary = now - timedelta(days=30)
    assert _count_between([boundary], now, 30, 0) + _count_between([boundary], now, 120, 30) == 1


def test_same_day_payments_do_not_create_zero_day_cadence(now):
    visits = [
        now - timedelta(days=60, hours=8),
        now - timedelta(days=60, hours=1),
        now - timedelta(days=30, hours=8),
        now - timedelta(days=30, hours=1),
    ]

    result = score_customer(
        CustomerActivity(
            customer_id="split-checks",
            visit_dates=visits,
            joined_at=now - timedelta(days=300),
        ),
        vertical="cafe",
        now=now,
    )

    assert all("0-day gap" not in reason for reason in result.reasons)
    assert result.signals["recency"] < 0.9
