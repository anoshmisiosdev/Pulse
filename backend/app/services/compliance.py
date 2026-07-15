"""Outreach compliance: TCPA quiet hours (SMS) and per-customer contact consent.

Pure functions, no I/O — the automation dispatcher (app/services/automations.py)
checks these before ever calling a send client, and the manual "approve and send"
API path re-checks them too, since a customer can revoke consent (STOP reply)
between when a send was queued and when it's approved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.models import Customer

_FALLBACK_TZ = "America/New_York"


def is_quiet_hours(business_timezone: str, now: datetime | None = None) -> bool:
    """TCPA: SMS may not be sent before ``sms_quiet_hours_start`` or at/after
    ``sms_quiet_hours_end`` in the business's own local time (default 9am-8pm)."""
    now = now or datetime.now(UTC)
    try:
        local = now.astimezone(ZoneInfo(business_timezone))
    except (ZoneInfoNotFoundError, ValueError):
        local = now.astimezone(ZoneInfo(_FALLBACK_TZ))
    return not (settings.sms_quiet_hours_start <= local.hour < settings.sms_quiet_hours_end)


def can_contact(customer: Customer, channel: str) -> tuple[bool, str | None]:
    """Whether this customer may be contacted on this channel right now.

    Returns ``(allowed, reason)`` — ``reason`` is None when allowed, otherwise a
    short machine-readable skip reason (stored on skipped/failed sends).
    """
    if customer.do_not_contact:
        return False, "do_not_contact"
    if channel == "sms":
        if customer.unsubscribed_sms:
            return False, "unsubscribed_sms"
        if not customer.phone:
            return False, "no_phone_on_file"
    elif channel == "email":
        if customer.unsubscribed_email:
            return False, "unsubscribed_email"
        if not customer.email:
            return False, "no_email_on_file"
    return True, None
