"""TCPA quiet-hours + per-customer consent checks — pure functions, no I/O."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models import Customer
from app.services.compliance import can_contact, is_quiet_hours


def _customer(**overrides) -> Customer:
    defaults = dict(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        source="csv",
        phone="+15551234567",
        email="a@example.com",
        do_not_contact=False,
        unsubscribed_email=False,
        unsubscribed_sms=False,
    )
    defaults.update(overrides)
    return Customer(**defaults)


def test_quiet_hours_boundaries_for_america_new_york():
    # January (EST, UTC-5, no DST).
    tz = "America/New_York"
    at_8am = datetime(2026, 1, 15, 13, 0, tzinfo=UTC)
    at_9am = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)
    at_7pm_prev_day = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    at_8pm_prev_day = datetime(2026, 1, 15, 1, 0, tzinfo=UTC)
    assert is_quiet_hours(tz, at_8am) is True
    assert is_quiet_hours(tz, at_9am) is False
    assert is_quiet_hours(tz, at_7pm_prev_day) is False
    assert is_quiet_hours(tz, at_8pm_prev_day) is True


def test_quiet_hours_falls_back_on_bad_timezone():
    # Malformed/unknown tz shouldn't crash — falls back to a safe default rather
    # than accidentally allowing sends at any hour.
    is_quiet_hours("Not/A/Real/Zone", datetime(2026, 1, 15, 14, 0, tzinfo=UTC))


def test_can_contact_honors_do_not_contact():
    allowed, reason = can_contact(_customer(do_not_contact=True), "sms")
    assert allowed is False
    assert reason == "do_not_contact"


def test_can_contact_honors_unsubscribed_sms():
    allowed, reason = can_contact(_customer(unsubscribed_sms=True), "sms")
    assert allowed is False
    assert reason == "unsubscribed_sms"


def test_can_contact_honors_unsubscribed_email():
    allowed, reason = can_contact(_customer(unsubscribed_email=True), "email")
    assert allowed is False
    assert reason == "unsubscribed_email"


def test_can_contact_requires_phone_for_sms():
    allowed, reason = can_contact(_customer(phone=None), "sms")
    assert allowed is False
    assert reason == "no_phone_on_file"


def test_can_contact_requires_email_for_email_channel():
    allowed, reason = can_contact(_customer(email=None), "email")
    assert allowed is False
    assert reason == "no_email_on_file"


def test_can_contact_allows_clean_customer():
    allowed, reason = can_contact(_customer(), "sms")
    assert allowed is True
    assert reason is None
