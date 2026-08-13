"""The generated test data must actually produce the actions it advertises.

app/scripts/make_test_data.py exists so a human can eyeball the dashboard against a
stated intent. That's worthless if the cohorts drift, so this pins each one — and it
doubles as end-to-end coverage of the action ladder over the real CSV adapter across
three verticals with different cadences.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.integrations.csv_adapter import parse_csv
from app.scripts.make_test_data import COHORTS, build_csv
from app.services.activity import build_scored_customers

# Fixed date so the assertions don't drift with the real clock; the generator emits
# every date relative to whatever "now" it's given.
NOW = datetime(2026, 8, 13)
VERTICALS = ("cafe", "salon", "med_spa")


def _by_cohort(vertical: str) -> dict[str, set[str]]:
    sync = parse_csv(build_csv(vertical, NOW, seed=11))
    scored = build_scored_customers(sync, vertical=vertical, now=NOW)
    out: dict[str, set[str]] = {}
    for s in scored:
        out.setdefault(s.customer.last_name or "?", set()).add(s.recommended_action)
    return out


@pytest.mark.parametrize("vertical", VERTICALS)
def test_every_cohort_produces_only_its_intended_action(vertical):
    actual = _by_cohort(vertical)
    for cohort in COHORTS:
        assert actual[cohort.label] == {cohort.expect}, (
            f"{vertical}/{cohort.label}: expected {cohort.expect}, got {actual[cohort.label]}"
        )


@pytest.mark.parametrize("vertical", VERTICALS)
def test_the_file_covers_every_action(vertical):
    """If an action stops being reachable, the fixtures stop testing it."""
    produced = {a for actions in _by_cohort(vertical).values() for a in actions}
    assert produced == {c.expect for c in COHORTS}
    assert len(produced) == 6


@pytest.mark.parametrize("vertical", VERTICALS)
def test_event_level_rows_accumulate_into_real_history(vertical):
    """The point of the event-level shape: multiple visits per customer, which is what
    switches the frequency and monetary signals on at all."""
    sync = parse_csv(build_csv(vertical, NOW, seed=11))
    scored = build_scored_customers(sync, vertical=vertical, now=NOW)

    assert len(scored) == sum(c.count for c in COHORTS)
    assert len(sync.visits) > len(scored) * 5  # genuinely event-level, not one-per-row
    assert max(s.visit_count for s in scored) >= 20
    assert any("monetary" in s.result.signals for s in scored)
    if vertical == "cafe":
        # The frequency signal needs 3+ visits in the trailing 90-day window, so the
        # engine deliberately switches it off for low-cadence verticals — a 30-day
        # read on a med spa is noise, not a trend. Only assert it where it applies.
        assert any("frequency" in s.result.signals for s in scored)


def test_generation_is_deterministic():
    assert build_csv("cafe", NOW, seed=11) == build_csv("cafe", NOW, seed=11)
    assert build_csv("cafe", NOW, seed=11) != build_csv("cafe", NOW, seed=12)


def test_emails_are_unique_so_dedupe_does_not_merge_distinct_customers():
    sync = parse_csv(build_csv("cafe", NOW, seed=11))
    scored = build_scored_customers(sync, vertical="cafe", now=NOW)
    emails = [s.customer.email for s in scored]
    assert len(emails) == len(set(emails))
