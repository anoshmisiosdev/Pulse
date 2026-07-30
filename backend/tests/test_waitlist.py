"""Public waitlist endpoint.

The one route an unauthenticated caller can write with, so the tests lean on
the things that keep that safe: bounded input, an idempotent upsert, and a
honeypot that fails closed without saying so.
"""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.api import waitlist as waitlist_api
from app.core import database as database_module
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.posthog_client import POSTHOG_DISTINCT_ID_HEADER
from app.main import app, fastapi_app
from app.models.waitlist import WaitlistSignup

# /api/waitlist is rate limited per IP (5/60s) and the limiter's buckets live on
# the middleware instance for the life of the process — so a shared client IP
# would make later tests 429 depending on how many ran before them. Each test
# gets its own address out of TEST-NET-2, which the limiter reads from
# X-Forwarded-For.
_ips = itertools.count(1)


@pytest.fixture
async def client(monkeypatch):
    # Unit tests must never initialize a real PostHog worker or send test data.
    monkeypatch.setattr(settings, "posthog_disabled", True)
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    # The app's lifespan re-imports the module-level engine and runs create_all
    # against it; without this it would reach for the real (private) RDS host.
    monkeypatch.setattr(database_module, "engine", engine)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    headers = {"x-forwarded-for": f"198.51.100.{next(_ips) % 250 + 1}"}
    with TestClient(app, headers=headers) as c:
        yield c, SessionLocal
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


async def _rows(SessionLocal) -> list[WaitlistSignup]:
    async with SessionLocal() as db:
        return list((await db.execute(select(WaitlistSignup))).scalars())


async def _count(SessionLocal) -> int:
    async with SessionLocal() as db:
        return (await db.execute(select(func.count(WaitlistSignup.id)))).scalar_one()


async def test_signup_is_recorded(client):
    c, SessionLocal = client
    resp = c.post(
        "/api/waitlist",
        json={
            "name": "Dana Okafor",
            "email": "dana@bluebirdcoffee.com",
            "business_name": "Bluebird Coffee",
            "vertical": "cafe",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "already_joined": False}

    (row,) = await _rows(SessionLocal)
    assert row.name == "Dana Okafor"
    assert row.email == "dana@bluebirdcoffee.com"
    assert row.business_name == "Bluebird Coffee"
    assert row.vertical == "cafe"
    assert row.source == "landing"


async def test_signup_captures_database_confirmed_conversion_without_pii(
    client, monkeypatch
):
    c, _ = client
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        waitlist_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = c.post(
        "/api/waitlist",
        headers={POSTHOG_DISTINCT_ID_HEADER: "landing-browser-456"},
        json={
            "name": "Dana Okafor",
            "email": "dana@bluebirdcoffee.com",
            "business_name": "Bluebird Coffee",
            "vertical": "Café / coffee shop",
        },
    )

    assert response.status_code == 200
    assert calls == [
        (
            "landing_waitlist_submitted",
            {
                "distinct_id": "landing-browser-456",
                "properties": {
                    "surface": "landing",
                    "metric_version": 1,
                    "has_business_name": True,
                    "vertical": "cafe",
                },
            },
        ),
        (
            "landing_waitlist_joined",
            {
                "distinct_id": "landing-browser-456",
                "properties": {
                    "surface": "landing",
                    "metric_version": 1,
                    "already_joined": False,
                    "has_business_name": True,
                    "vertical": "cafe",
                },
            },
        )
    ]
    for _, call in calls:
        assert "email" not in call["properties"]
        assert "name" not in call["properties"]


async def test_repeat_signup_marks_conversion_as_already_joined(client, monkeypatch):
    c, _ = client
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        waitlist_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    c.post("/api/waitlist", json={"name": "Dana", "email": "dana@bluebird.com"})
    c.post("/api/waitlist", json={"name": "Dana", "email": "dana@bluebird.com"})

    assert calls[-1][0] == "landing_waitlist_joined"
    assert calls[-1][1]["properties"]["already_joined"] is True
    assert calls[-1][1]["properties"]["vertical"] == "not_provided"


async def test_email_is_normalized(client):
    """Mixed case and stray whitespace must not create a second person."""
    c, SessionLocal = client
    c.post("/api/waitlist", json={"name": "Dana", "email": "  Dana@Bluebird.com "})
    (row,) = await _rows(SessionLocal)
    assert row.email == "dana@bluebird.com"


async def test_repeat_signup_upserts_rather_than_duplicating(client):
    c, SessionLocal = client
    c.post("/api/waitlist", json={"name": "D", "email": "dana@bluebird.com"})
    resp = c.post(
        "/api/waitlist",
        json={
            "name": "Dana Okafor",
            "email": "dana@bluebird.com",
            "business_name": "Bluebird Coffee",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "already_joined": True}

    (row,) = await _rows(SessionLocal)
    assert row.name == "Dana Okafor"  # corrected
    assert row.business_name == "Bluebird Coffee"  # added


async def test_repeat_signup_never_blanks_existing_fields(client):
    c, SessionLocal = client
    c.post(
        "/api/waitlist",
        json={"name": "Dana", "email": "dana@bluebird.com", "business_name": "Bluebird"},
    )
    c.post("/api/waitlist", json={"name": "Dana", "email": "dana@bluebird.com"})

    (row,) = await _rows(SessionLocal)
    assert row.business_name == "Bluebird"


async def test_honeypot_is_dropped_without_telling_the_bot(client, monkeypatch):
    c, SessionLocal = client
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        waitlist_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )
    resp = c.post(
        "/api/waitlist",
        json={"name": "Bot", "email": "bot@spam.example", "website": "http://spam.example"},
    )
    # Indistinguishable from success on the wire...
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # ...but nothing was stored.
    assert await _count(SessionLocal) == 0
    # Nor does bot activity inflate the acquisition funnel.
    assert calls == []


async def test_invalid_email_is_rejected(client):
    c, SessionLocal = client
    resp = c.post("/api/waitlist", json={"name": "Dana", "email": "not-an-email"})
    assert resp.status_code == 422
    assert await _count(SessionLocal) == 0


async def test_blank_name_is_rejected(client):
    c, SessionLocal = client
    resp = c.post("/api/waitlist", json={"name": "", "email": "dana@bluebird.com"})
    assert resp.status_code == 422
    assert await _count(SessionLocal) == 0


async def test_overlong_fields_are_rejected(client):
    """Bounded input is the main defence on an unauthenticated write."""
    c, SessionLocal = client
    resp = c.post(
        "/api/waitlist",
        json={"name": "D" * 121, "email": "dana@bluebird.com"},
    )
    assert resp.status_code == 422
    assert await _count(SessionLocal) == 0


async def test_needs_no_authentication(client):
    """No Authorization header anywhere in these tests — that's the point."""
    c, _ = client
    resp = c.post("/api/waitlist", json={"name": "Dana", "email": "dana@bluebird.com"})
    assert resp.status_code == 200


async def test_is_rate_limited_per_ip(client):
    """An unauthenticated write needs a ceiling, or the table is a free-for-all."""
    c, SessionLocal = client
    codes = [
        c.post("/api/waitlist", json={"name": "Dana", "email": f"d{i}@bluebird.com"}).status_code
        for i in range(7)
    ]
    assert codes[:5] == [200] * 5
    assert codes[5:] == [429, 429]
    # The 429s never reached the handler, so only the allowed ones were stored.
    assert await _count(SessionLocal) == 5
