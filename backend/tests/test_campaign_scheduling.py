"""Recurring-campaign slot math, with the DST cases pinned explicitly."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.social.scheduling import campaign_slots, valid_timezone, weekly_occurrence

LA = "America/Los_Angeles"


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def test_first_slot_is_the_start_instant_untouched():
    start = _utc("2026-08-03T16:30:00+00:00")
    assert weekly_occurrence(start, LA, 0) == start


def test_weekly_cadence_without_a_dst_boundary():
    start = _utc("2026-08-03T16:30:00+00:00")  # 09:30 PDT
    slots = campaign_slots(
        brief="b", themes=[], start_at=start, timezone=LA, interval_weeks=1, occurrences=4
    )
    assert slots[3].scheduled_for == _utc("2026-08-24T16:30:00+00:00")


def test_local_time_survives_the_fall_back_transition():
    # Oct 26 is PDT (UTC-7) → 09:00 local. Nov 2 is PST (UTC-8), so holding
    # 09:00 local means the UTC instant moves forward an hour.
    start = _utc("2026-10-26T16:00:00+00:00")
    slots = campaign_slots(
        brief="b", themes=[], start_at=start, timezone=LA, interval_weeks=1, occurrences=2
    )
    assert slots[0].scheduled_for == _utc("2026-10-26T16:00:00+00:00")
    assert slots[1].scheduled_for == _utc("2026-11-02T17:00:00+00:00")


def test_local_time_survives_the_spring_forward_transition():
    # Mar 1 2026 is PST; Mar 8 is PDT. 09:00 local both weeks.
    start = _utc("2026-03-01T17:00:00+00:00")
    slots = campaign_slots(
        brief="b", themes=[], start_at=start, timezone=LA, interval_weeks=1, occurrences=2
    )
    assert slots[1].scheduled_for == _utc("2026-03-08T16:00:00+00:00")


def test_ambiguous_wall_time_resolves_to_the_first_pass():
    # Clocks go back on 2026-11-01, so 01:30 local happens twice that morning.
    # Starting a week earlier at 01:30 PDT lands the next slot on the repeated
    # hour; we take the first pass (still PDT, UTC-7).
    start = _utc("2026-10-25T08:30:00+00:00")  # 01:30 PDT
    assert weekly_occurrence(start, LA, 1) == _utc("2026-11-01T08:30:00+00:00")


def test_nonexistent_wall_time_in_the_spring_forward_gap_still_resolves():
    # 02:30 local does not exist on 2026-03-08 — the clocks jump 02:00 → 03:00.
    # It must still produce a usable instant rather than raising.
    start = _utc("2026-03-01T10:30:00+00:00")  # 02:30 PST
    slot = weekly_occurrence(start, LA, 1)
    assert slot == _utc("2026-03-08T10:30:00+00:00")


def test_themes_recycle_and_fall_back_to_the_brief():
    start = _utc("2026-08-03T16:30:00+00:00")
    slots = campaign_slots(
        brief="Win back regulars",
        themes=["handoffs", "trackers"],
        start_at=start,
        timezone=LA,
        interval_weeks=1,
        occurrences=4,
    )
    assert [s.theme for s in slots] == ["handoffs", "trackers", "handoffs", "trackers"]

    no_themes = campaign_slots(
        brief="Win back regulars", themes=[], start_at=start, timezone=LA,
        interval_weeks=1, occurrences=2,
    )
    assert [s.theme for s in no_themes] == ["Win back regulars"] * 2


def test_blank_theme_falls_back_to_the_brief():
    start = _utc("2026-08-03T16:30:00+00:00")
    slots = campaign_slots(
        brief="Win back regulars", themes=["", "trackers"], start_at=start, timezone=LA,
        interval_weeks=1, occurrences=2,
    )
    assert [s.theme for s in slots] == ["Win back regulars", "trackers"]


def test_interval_weeks_spaces_the_slots_out():
    start = _utc("2026-08-03T16:30:00+00:00")
    slots = campaign_slots(
        brief="b", themes=[], start_at=start, timezone=LA, interval_weeks=2, occurrences=3
    )
    assert [s.occurrence for s in slots] == [1, 2, 3]
    assert slots[2].scheduled_for == _utc("2026-08-31T16:30:00+00:00")


@pytest.mark.parametrize("name,expected", [("America/New_York", True), ("Mars/Olympus", False)])
def test_timezone_validation(name, expected):
    assert valid_timezone(name) is expected
