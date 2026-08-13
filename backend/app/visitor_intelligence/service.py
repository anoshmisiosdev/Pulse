"""Identity stitching and minimized event persistence for marketing visitors."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visitor import VisitorEvent, VisitorIdentifier, VisitorProfile
from app.models.waitlist import WaitlistSignup
from app.visitor_intelligence.providers.base import NormalizedVisitorSignal

VISITOR_SESSION_ID_HEADER = "X-Visitor-Session-Id"
_MAX_CLIENT_ID_LENGTH = 200

_SCORE_WEIGHTS = {
    "landing_viewed": 5,
    "landing_section_viewed": 8,
    "landing_cta_clicked": 14,
    "landing_demo_interacted": 8,
    "landing_waitlist_started": 20,
    "landing_waitlist_validation_failed": 0,
    "landing_waitlist_submit_failed": 0,
    "waitlist_joined": 45,
    "account_identified": 30,
    "provider_identified": 25,
}
_IDENTITY_PRIORITY = {
    "anonymous": 0,
    "company": 1,
    "person": 2,
    "waitlist": 3,
    "account": 4,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def identity_hash(value: str) -> str:
    """Return a deterministic, one-way lookup key for an identifier."""
    return hashlib.sha256(value.strip().casefold().encode()).hexdigest()


def _bounded_client_id(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value or len(value) > _MAX_CLIENT_ID_LENGTH:
        return None
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        return None
    return value


def request_session_id(request: Request) -> str | None:
    return _bounded_client_id(request.headers.get(VISITOR_SESSION_ID_HEADER))


def _path_from_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
        path = parsed.path or "/"
        return path[:500]
    except ValueError:
        return value[:500]


def _host_from_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return (urlparse(value).hostname or "")[:253] or None
    except ValueError:
        return None


async def _find_profiles(
    db: AsyncSession,
    identifiers: list[tuple[str, str]],
    *,
    provider: str | None = None,
    provider_key: str | None = None,
) -> list[VisitorProfile]:
    profile_ids: set = set()
    clauses = [
        (VisitorIdentifier.kind == kind)
        & (VisitorIdentifier.value_hash == identity_hash(value))
        for kind, value in identifiers
        if value
    ]
    if clauses:
        rows = (await db.execute(select(VisitorIdentifier).where(or_(*clauses)))).scalars()
        profile_ids.update(row.visitor_id for row in rows)

    if provider and provider_key:
        provider_profile = (
            await db.execute(
                select(VisitorProfile).where(
                    VisitorProfile.source_provider == provider,
                    VisitorProfile.provider_profile_key == provider_key,
                )
            )
        ).scalar_one_or_none()
        if provider_profile is not None:
            profile_ids.add(provider_profile.id)

    profiles: list[VisitorProfile] = []
    for profile_id in profile_ids:
        profile = await db.get(VisitorProfile, profile_id)
        if profile is not None:
            profiles.append(profile)
    return profiles


def _copy_missing(target: VisitorProfile, source: VisitorProfile) -> None:
    for field in (
        "primary_email",
        "full_name",
        "job_title",
        "linkedin_url",
        "company_name",
        "company_domain",
        "company_website",
        "industry",
        "employee_count",
        "estimated_revenue",
        "city",
        "state",
        "zipcode",
        "last_path",
        "referrer_host",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "waitlist_signup_id",
        "authenticated_user_id",
    ):
        if getattr(target, field) is None and getattr(source, field) is not None:
            setattr(target, field, getattr(source, field))
    target.tags = sorted(set(target.tags or []) | set(source.tags or []))
    if _IDENTITY_PRIORITY[source.identity_level] > _IDENTITY_PRIORITY[target.identity_level]:
        target.identity_level = source.identity_level
    if source.source_provider != "first_party":
        target.source_provider = source.source_provider
        target.provider_profile_key = target.provider_profile_key or source.provider_profile_key
    target.first_seen_at = min(target.first_seen_at, source.first_seen_at)
    target.last_seen_at = max(target.last_seen_at, source.last_seen_at)
    target.visit_count += source.visit_count
    target.pageview_count += source.pageview_count
    target.intent_score = min(100, target.intent_score + source.intent_score)
    target.suppressed = target.suppressed or source.suppressed


async def _merge_profiles(
    db: AsyncSession, profiles: list[VisitorProfile]
) -> VisitorProfile:
    target = max(
        profiles,
        key=lambda profile: (
            _IDENTITY_PRIORITY.get(profile.identity_level, 0),
            int(profile.source_provider != "first_party"),
            -profile.first_seen_at.timestamp(),
        ),
    )
    for source in profiles:
        if source.id == target.id:
            continue
        _copy_missing(target, source)
        # Prevent a transient provider-key unique conflict while the losing row
        # still exists in the current transaction.
        source.provider_profile_key = None
        await db.flush()
        await db.execute(
            update(VisitorIdentifier)
            .where(VisitorIdentifier.visitor_id == source.id)
            .values(visitor_id=target.id)
        )
        await db.execute(
            update(VisitorEvent)
            .where(VisitorEvent.visitor_id == source.id)
            .values(visitor_id=target.id)
        )
        await db.delete(source)
    await db.flush()
    return target


async def _ensure_identifier(
    db: AsyncSession,
    profile: VisitorProfile,
    kind: str,
    value: str | None,
    provider: str | None = None,
) -> None:
    if not value:
        return
    hashed = identity_hash(value)
    exists = (
        await db.execute(
            select(VisitorIdentifier.id).where(
                VisitorIdentifier.kind == kind,
                VisitorIdentifier.value_hash == hashed,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(
            VisitorIdentifier(
                visitor_id=profile.id,
                kind=kind,
                value_hash=hashed,
                provider=provider,
            )
        )


async def _resolve_profile(
    db: AsyncSession,
    identifiers: list[tuple[str, str]],
    *,
    provider: str | None = None,
    provider_key: str | None = None,
    seen_at: datetime | None = None,
) -> VisitorProfile:
    profiles = await _find_profiles(
        db,
        identifiers,
        provider=provider,
        provider_key=provider_key,
    )
    when = seen_at or utcnow()
    if profiles:
        profile = profiles[0] if len(profiles) == 1 else await _merge_profiles(db, profiles)
    else:
        profile = VisitorProfile(
            first_seen_at=when,
            last_seen_at=when,
            source_provider=provider or "first_party",
            provider_profile_key=provider_key,
        )
        db.add(profile)
        await db.flush()

    for kind, value in identifiers:
        await _ensure_identifier(db, profile, kind, value, provider)
    await db.flush()
    return profile


async def _event_exists(db: AsyncSession, dedupe_key: str) -> bool:
    found = (
        await db.execute(
            select(VisitorEvent.id).where(VisitorEvent.dedupe_key == dedupe_key)
        )
    ).scalar_one_or_none()
    return found is not None


async def _add_event(
    db: AsyncSession,
    profile: VisitorProfile,
    event_name: str,
    *,
    occurred_at: datetime,
    path: str | None = None,
    referrer: str | None = None,
    session_id: str | None = None,
    provider: str = "first_party",
    properties: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    db.add(
        VisitorEvent(
            visitor_id=profile.id,
            event_name=event_name,
            occurred_at=occurred_at,
            path=path,
            referrer=referrer,
            session_hash=identity_hash(session_id) if session_id else None,
            provider=provider,
            properties=properties or {},
            dedupe_key=dedupe_key,
        )
    )


async def record_browser_event(
    db: AsyncSession,
    *,
    anonymous_id: str | None,
    session_id: str | None,
    event_name: str,
    properties: dict[str, Any],
) -> VisitorProfile | None:
    """Persist an allow-listed browser event only when consent supplied an ID."""
    anonymous_id = _bounded_client_id(anonymous_id)
    if not anonymous_id:
        return None

    now = utcnow()
    profile = await _resolve_profile(db, [("browser", anonymous_id)], seen_at=now)
    if profile.suppressed:
        return profile

    path = str(properties.get("path") or profile.last_path or "/")[:500]
    profile.last_seen_at = now
    profile.last_path = path
    profile.intent_score = min(100, profile.intent_score + _SCORE_WEIGHTS.get(event_name, 0))
    if event_name == "landing_viewed":
        profile.visit_count += 1
        profile.pageview_count += 1
        profile.referrer_host = properties.get("referrer_host") or profile.referrer_host
        profile.utm_source = properties.get("utm_source") or profile.utm_source
        profile.utm_medium = properties.get("utm_medium") or profile.utm_medium
        profile.utm_campaign = properties.get("utm_campaign") or profile.utm_campaign

    await _add_event(
        db,
        profile,
        event_name,
        occurred_at=now,
        path=path,
        session_id=_bounded_client_id(session_id),
        properties=properties,
    )
    return profile


async def link_waitlist_signup(
    db: AsyncSession,
    *,
    signup: WaitlistSignup,
    anonymous_id: str | None,
    session_id: str | None,
    already_joined: bool,
) -> VisitorProfile:
    identifiers = [("email", signup.email)]
    anonymous_id = _bounded_client_id(anonymous_id)
    if anonymous_id:
        identifiers.append(("browser", anonymous_id))
    profile = await _resolve_profile(db, identifiers)
    if profile.suppressed:
        return profile

    now = utcnow()
    profile.primary_email = signup.email
    profile.full_name = signup.name
    profile.company_name = signup.business_name or profile.company_name
    profile.waitlist_signup_id = signup.id
    profile.identity_level = "waitlist"
    profile.status = "qualified"
    profile.last_seen_at = now
    profile.intent_score = max(80, profile.intent_score)
    if signup.vertical:
        profile.tags = sorted(set(profile.tags or []) | {signup.vertical[:80]})

    dedupe = identity_hash(f"waitlist:{signup.id}:joined")
    if not await _event_exists(db, dedupe):
        await _add_event(
            db,
            profile,
            "waitlist_joined",
            occurred_at=now,
            path=profile.last_path,
            session_id=_bounded_client_id(session_id),
            properties={"already_joined": already_joined},
            dedupe_key=dedupe,
        )
    return profile


async def link_authenticated_user(
    db: AsyncSession,
    *,
    anonymous_id: str,
    session_id: str | None,
    user_id: str,
    email: str | None,
) -> VisitorProfile:
    identifiers = [("browser", anonymous_id), ("user", user_id)]
    if email:
        identifiers.append(("email", email.casefold()))
    profile = await _resolve_profile(db, identifiers)
    if profile.suppressed:
        return profile

    now = utcnow()
    profile.primary_email = email.casefold() if email else profile.primary_email
    profile.authenticated_user_id = user_id
    profile.identity_level = "account"
    profile.status = "qualified"
    profile.last_seen_at = now
    profile.intent_score = max(90, profile.intent_score)
    dedupe = identity_hash(f"account:{user_id}")
    if not await _event_exists(db, dedupe):
        await _add_event(
            db,
            profile,
            "account_identified",
            occurred_at=now,
            path=profile.last_path,
            session_id=_bounded_client_id(session_id),
            dedupe_key=dedupe,
        )
    return profile


async def ingest_provider_signal(
    db: AsyncSession, signal: NormalizedVisitorSignal
) -> tuple[VisitorProfile, bool]:
    identifiers = [("provider", signal.provider_key)]
    if signal.business_email:
        identifiers.append(("email", signal.business_email))
    if signal.linkedin_url:
        identifiers.append(("linkedin", signal.linkedin_url))

    profile = await _resolve_profile(
        db,
        identifiers,
        provider=signal.provider,
        provider_key=signal.provider_key,
        seen_at=signal.seen_at,
    )
    dedupe = identity_hash(
        f"{signal.provider}:{signal.provider_key}:{signal.seen_at.isoformat()}:{signal.captured_url}"
    )
    if await _event_exists(db, dedupe):
        return profile, True
    if profile.suppressed:
        return profile, False

    full_name = " ".join(
        part for part in (signal.first_name, signal.last_name) if part
    ).strip() or None
    profile.primary_email = signal.business_email or profile.primary_email
    profile.full_name = full_name or profile.full_name
    profile.job_title = signal.job_title or profile.job_title
    profile.linkedin_url = signal.linkedin_url or profile.linkedin_url
    profile.company_name = signal.company_name or profile.company_name
    profile.company_website = signal.company_website or profile.company_website
    profile.company_domain = signal.company_domain or profile.company_domain
    profile.industry = signal.industry or profile.industry
    profile.employee_count = signal.employee_count or profile.employee_count
    profile.estimated_revenue = signal.estimated_revenue or profile.estimated_revenue
    profile.city = signal.city or profile.city
    profile.state = signal.state or profile.state
    profile.zipcode = signal.zipcode or profile.zipcode
    if _IDENTITY_PRIORITY[profile.identity_level] < _IDENTITY_PRIORITY["waitlist"]:
        profile.identity_level = (
            "person"
            if signal.linkedin_url or signal.business_email or full_name
            else "company"
        )
    profile.source_provider = signal.provider
    profile.provider_profile_key = signal.provider_key
    profile.first_seen_at = min(profile.first_seen_at, signal.seen_at)
    profile.last_seen_at = max(profile.last_seen_at, signal.seen_at)
    profile.visit_count += 1
    profile.pageview_count += 1
    profile.last_path = _path_from_url(signal.captured_url)
    profile.referrer_host = _host_from_url(signal.referrer) or profile.referrer_host
    profile.tags = sorted(set(profile.tags or []) | set(signal.tags))
    profile.intent_score = min(
        100,
        profile.intent_score
        + _SCORE_WEIGHTS["provider_identified"]
        + (10 if signal.repeat_visitor else 0),
    )

    await _add_event(
        db,
        profile,
        "provider_identified",
        occurred_at=signal.seen_at,
        path=_path_from_url(signal.captured_url),
        # Provider URLs may contain search terms or other query-string data.
        # Retain only the referring hostname, matching first-party collection.
        referrer=_host_from_url(signal.referrer),
        provider=signal.provider,
        properties={
            "repeat_visitor": signal.repeat_visitor,
            "tags": signal.tags,
            "identity_level": profile.identity_level,
        },
        dedupe_key=dedupe,
    )
    return profile, False


async def suppress_profile(db: AsyncSession, profile: VisitorProfile) -> None:
    """Erase raw identity/history while retaining hashes as a do-not-recreate tombstone."""
    profile.primary_email = None
    profile.full_name = None
    profile.job_title = None
    profile.linkedin_url = None
    profile.company_name = None
    profile.company_domain = None
    profile.company_website = None
    profile.industry = None
    profile.employee_count = None
    profile.estimated_revenue = None
    profile.city = None
    profile.state = None
    profile.zipcode = None
    profile.tags = []
    profile.last_path = None
    profile.referrer_host = None
    profile.utm_source = None
    profile.utm_medium = None
    profile.utm_campaign = None
    profile.waitlist_signup_id = None
    profile.authenticated_user_id = None
    profile.identity_level = "anonymous"
    profile.status = "dismissed"
    profile.intent_score = 0
    profile.suppressed = True
    await db.execute(delete(VisitorEvent).where(VisitorEvent.visitor_id == profile.id))
