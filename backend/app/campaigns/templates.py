"""Static fallback copy. Used when the LLM is unavailable or returns junk twice —
the send pipeline must never block on the model."""

from __future__ import annotations

UNSUBSCRIBE_LINE = "Reply STOP to opt out or unsubscribe: {unsubscribe_url}"


def fallback_email(
    *, business_name: str, customer_name: str, incentive: str | None, unsubscribe_url: str
) -> tuple[str, str]:
    """Return ``(subject, body)`` for a safe, claim-free win-back email."""
    first = customer_name.split()[0] if customer_name else "there"
    offer = f" Here's {incentive} to welcome you back." if incentive else ""
    subject = f"We miss you at {business_name}"
    body = (
        f"Hi {first},\n\n"
        f"We noticed it's been a while since your last visit to {business_name}, "
        f"and we'd love to see you again.{offer}\n\n"
        f"Hope to see you soon,\n"
        f"The {business_name} team\n\n"
        f"{UNSUBSCRIBE_LINE.format(unsubscribe_url=unsubscribe_url)}"
    )
    return subject, body


def fallback_sms(*, business_name: str, customer_name: str, incentive: str | None) -> str:
    first = customer_name.split()[0] if customer_name else "there"
    offer = f" {incentive} when you come back." if incentive else ""
    msg = f"Hi {first}, we miss you at {business_name}!{offer} Reply STOP to opt out."
    return msg[:320]
