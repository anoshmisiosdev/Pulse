"""Recurring-campaign slot math. Pure functions, no I/O.

Slots are *derived*, never stored: changing a campaign's start, timezone,
cadence, or length re-computes every slot on the next read. Storing them would
let the two drift apart.

The one subtlety is daylight saving. A campaign that posts at 9am local must
keep posting at 9am local after the clocks move, which means the UTC instant
has to shift by an hour. Adding ``timedelta(weeks=n)`` to an *aware* datetime
would hold the UTC offset fixed and drift the local time to 8am, so the
arithmetic is deliberately done on naive wall-clock fields and re-localised
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_INTERVAL_WEEKS, MAX_INTERVAL_WEEKS = 1, 4
MIN_OCCURRENCES, MAX_OCCURRENCES = 2, 52


@dataclass(frozen=True)
class CampaignSlot:
    occurrence: int  # 1-based
    scheduled_for: datetime  # UTC
    theme: str


def as_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC rather than local time.

    Postgres hands back aware datetimes, but the SQLite used in tests drops the
    tzinfo. Assuming local time there would silently shift every stored instant
    by the developer's offset.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def weekly_occurrence(start: datetime, tz_name: str, weeks: int) -> datetime:
    """The UTC instant ``weeks`` weeks after ``start`` at the same local time.

    Slot 0 returns ``start`` untouched so the first slot always equals the
    campaign's stored start instant exactly.
    """
    if weeks == 0:
        return start
    tz = ZoneInfo(tz_name)
    local_wall = start.astimezone(tz).replace(tzinfo=None) + timedelta(weeks=weeks)
    # Ambiguous wall times (the repeated hour when clocks go back) resolve to
    # the first pass, fold=0; nonexistent ones (the skipped hour going forward)
    # resolve using the pre-transition offset. Both are pinned by tests.
    return local_wall.replace(tzinfo=tz).astimezone(UTC)


def campaign_slots(
    *,
    brief: str,
    themes: list[str],
    start_at: datetime,
    timezone: str,
    interval_weeks: int,
    occurrences: int,
) -> list[CampaignSlot]:
    """Every future slot for a campaign, with its weekly theme.

    Themes recycle: with three themes over six weeks each is used twice. A
    campaign with no themes (or a blank one) falls back to the brief.
    """
    slots: list[CampaignSlot] = []
    for index in range(occurrences):
        theme = themes[index % len(themes)] if themes else ""
        slots.append(
            CampaignSlot(
                occurrence=index + 1,
                scheduled_for=weekly_occurrence(start_at, timezone, index * interval_weeks),
                theme=theme or brief,
            )
        )
    return slots
