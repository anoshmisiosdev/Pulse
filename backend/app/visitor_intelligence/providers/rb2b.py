"""RB2B fixed webhook payload adapter.

RB2B does not support custom headers or payload mapping. Keeping its unusual
title-cased field names in this adapter prevents the rest of Churnary from
depending on a single provider's contract.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.visitor_intelligence.providers.base import NormalizedVisitorSignal


def _clean(value: Any, maximum: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:maximum] if text else None


def _parse_seen_at(value: Any) -> datetime:
    text = _clean(value, 80)
    if not text:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _domain(website: str | None) -> str | None:
    if not website:
        return None
    try:
        return (urlparse(website).hostname or "").removeprefix("www.")[:253] or None
    except ValueError:
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


class Rb2bAdapter:
    name = "rb2b"

    def normalize(self, payload: dict[str, Any]) -> NormalizedVisitorSignal:
        linkedin = _clean(payload.get("LinkedIn URL"), 1000)
        email = _clean(payload.get("Business Email"), 320)
        if email:
            email = email.casefold()
        website = _clean(payload.get("Website"), 1000)
        company = _clean(payload.get("Company Name"), 255)
        captured_url = _clean(payload.get("Captured URL"), 1000) or "/"
        seen_at = _parse_seen_at(payload.get("Seen At"))
        if not any((linkedin, email, website, company)):
            raise ValueError("RB2B payload is missing person or company identity fields")

        # Person profiles are stable on LinkedIn. Company-only records fall
        # back to their domain; the fingerprint is only a provider key and is
        # never exposed to the browser.
        stable = linkedin or email or _domain(website) or company or captured_url
        provider_key = hashlib.sha256(stable.casefold().encode()).hexdigest()

        raw_tags = _clean(payload.get("Tags"), 500)
        tags = [tag.strip()[:80] for tag in (raw_tags or "").split(",") if tag.strip()][:20]

        return NormalizedVisitorSignal(
            provider=self.name,
            provider_key=provider_key,
            seen_at=seen_at,
            captured_url=captured_url,
            referrer=_clean(payload.get("Referrer"), 1000),
            first_name=_clean(payload.get("First Name"), 90),
            last_name=_clean(payload.get("Last Name"), 90),
            job_title=_clean(payload.get("Title"), 180),
            linkedin_url=linkedin,
            business_email=email,
            company_name=company,
            company_website=website,
            company_domain=_domain(website),
            industry=_clean(payload.get("Industry"), 180),
            employee_count=_clean(payload.get("Employee Count"), 40),
            estimated_revenue=_clean(payload.get("Estimate Revenue"), 80),
            city=_clean(payload.get("City"), 120),
            state=_clean(payload.get("State"), 120),
            zipcode=_clean(payload.get("Zipcode"), 24),
            tags=tags,
            repeat_visitor=_truthy(payload.get("is_repeat_visitor")),
        )
