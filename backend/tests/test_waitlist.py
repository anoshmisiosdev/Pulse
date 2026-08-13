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
from app.services.waitlist_leads import unsubscribe_token

# /api/waitlist is rate limited per IP (5/60s) and the limiter's buckets live on
# the middleware instance for the life of the process — so a shared client IP
# would make later tests 429 depending on how many ran before them. Each test
# gets its own address out of TEST-NET-2, which the limiter reads from
# X-Forwarded-For.
_ips = itertools.count(1)


@pytest.fixture
async def client(monkeypatch):
    # Unit tests must never initialize real analytics, Discord, or Resend work.
    monkeypatch.setattr(settings, "posthog_disabled", True)
    monkeypatch.setattr(settings, "discord_webhook_url", "")
    monkeypatch.setattr(settings, "discord_bot_token", "")
    monkeypatch.setattr(settings, "discord_alert_channel_id", "")
    monkeypatch.setattr(settings, "resend_api_key", "")
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
    assert row.assigned_founder in settings.waitlist_founder_roster_list


async def test_email_only_signup_is_recorded_without_a_fake_name(client):
    c, SessionLocal = client

    response = c.post("/api/waitlist", json={"email": "dana@bluebird.com"})

    assert response.status_code == 200
    (row,) = await _rows(SessionLocal)
    assert row.name is None


async def test_vertical_landing_variant_supplies_audience_segment(client, monkeypatch):
    c, _ = client
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        waitlist_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = c.post(
        "/api/waitlist",
        headers={POSTHOG_DISTINCT_ID_HEADER: "landing-browser-coffee"},
        json={"email": "owner@bluebird.com", "landing_variant": "coffee_v1"},
    )

    assert response.status_code == 200
    assert [call[1]["properties"]["vertical"] for call in calls] == ["cafe", "cafe"]


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
    founder = waitlist_api.assign_founder("dana@bluebirdcoffee.com")
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
                    "founder": founder,
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

    headers = {POSTHOG_DISTINCT_ID_HEADER: "landing-browser-789"}
    c.post(
        "/api/waitlist",
        headers=headers,
        json={"name": "Dana", "email": "dana@bluebird.com"},
    )
    c.post(
        "/api/waitlist",
        headers=headers,
        json={"name": "Dana", "email": "dana@bluebird.com"},
    )

    assert calls[-1][0] == "landing_waitlist_joined"
    assert calls[-1][1]["properties"]["already_joined"] is True
    assert calls[-1][1]["properties"]["vertical"] == "not_provided"


async def test_signup_without_analytics_consent_does_not_send_posthog_events(
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
        json={"name": "Dana", "email": "dana@bluebird.com"},
    )

    assert response.status_code == 200
    assert calls == []


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


async def test_repeat_signup_assigns_migrated_unowned_lead(client):
    c, SessionLocal = client
    async with SessionLocal() as db:
        db.add(
            WaitlistSignup(
                email="legacy@bluebird.com",
                name=None,
                first_touch={},
                last_touch={},
                assigned_founder=None,
            )
        )
        await db.commit()

    response = c.post("/api/waitlist", json={"email": "legacy@bluebird.com"})

    assert response.status_code == 200
    assert response.json()["already_joined"] is True
    (row,) = await _rows(SessionLocal)
    assert row.assigned_founder in settings.waitlist_founder_roster_list


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


async def test_blank_name_is_treated_as_omitted(client):
    c, SessionLocal = client
    resp = c.post("/api/waitlist", json={"name": "", "email": "dana@bluebird.com"})
    assert resp.status_code == 200
    (row,) = await _rows(SessionLocal)
    assert row.name is None


async def test_overlong_fields_are_rejected(client):
    """Bounded input is the main defence on an unauthenticated write."""
    c, SessionLocal = client
    resp = c.post(
        "/api/waitlist",
        json={"name": "D" * 121, "email": "dana@bluebird.com"},
    )
    assert resp.status_code == 422
    assert await _count(SessionLocal) == 0


async def test_first_touch_is_preserved_and_last_touch_refreshes(client):
    c, SessionLocal = client
    first = {
        "source": "linkedin",
        "medium": "founder_dm",
        "campaign": "pilot_aug_2026",
        "content": "aditya_observation_a",
        "landing_variant": "coffee_shop",
        "referrer_host": "www.linkedin.com",
    }
    second = {
        "source": "x",
        "medium": "organic_social",
        "campaign": "pilot_aug_2026",
        "content": "soham_demo_b",
        "landing_variant": "calculator",
        "referrer_host": "t.co",
    }

    c.post("/api/waitlist", json={"email": "dana@bluebird.com", **first})
    c.post("/api/waitlist", json={"email": "dana@bluebird.com", **second})

    (row,) = await _rows(SessionLocal)
    assert row.first_touch == first
    assert row.last_touch == second
    # The tracked founder owns the lead; a later touch from another founder
    # updates attribution but never silently reassigns the relationship.
    assert row.assigned_founder == "Aditya Kolekar"


async def test_repeat_enrichment_without_attribution_does_not_erase_last_touch(client):
    c, SessionLocal = client
    touch = {
        "source": "community",
        "medium": "community",
        "landing_variant": "salon",
    }
    c.post("/api/waitlist", json={"email": "dana@bluebird.com", **touch})
    c.post(
        "/api/waitlist",
        json={
            "email": "dana@bluebird.com",
            "name": "Dana",
            "business_name": "Bluebird",
        },
    )

    (row,) = await _rows(SessionLocal)
    assert row.first_touch == touch
    assert row.last_touch == touch
    assert row.name == "Dana"


async def test_stale_same_email_insert_conflict_merges_without_duplicate_work(
    client, monkeypatch
):
    """Model the unique-index loser after two requests read before either insert."""
    c, SessionLocal = client
    first_touch = {
        "source": "linkedin",
        "medium": "founder_dm",
        "content": "aditya_observation_a",
    }
    async with SessionLocal() as db:
        db.add(
            WaitlistSignup(
                email="race@bluebird.com",
                name="D",
                first_touch=first_touch,
                last_touch=first_touch,
                assigned_founder="Aditya Kolekar",
            )
        )
        await db.commit()

    real_find = waitlist_api._find_signup
    finds = 0

    async def stale_once(db, email):
        nonlocal finds
        finds += 1
        if finds == 1:
            return None
        return await real_find(db, email)

    alerts = []
    scheduled = []
    monkeypatch.setattr(waitlist_api, "_find_signup", stale_once)
    monkeypatch.setattr(
        waitlist_api,
        "send_waitlist_alert",
        lambda alert: alerts.append(alert),
    )
    monkeypatch.setattr(
        waitlist_api,
        "enqueue_email_sequence",
        lambda signup_id: scheduled.append(signup_id),
    )

    response = c.post(
        "/api/waitlist",
        json={
            "email": "race@bluebird.com",
            "name": "Dana",
            "business_name": "Bluebird Coffee",
            "source": "x",
            "medium": "organic_social",
            "content": "soham_demo_b",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "already_joined": True}
    assert await _count(SessionLocal) == 1
    (row,) = await _rows(SessionLocal)
    assert row.name == "Dana"
    assert row.business_name == "Bluebird Coffee"
    assert row.first_touch == first_touch
    assert row.last_touch == {
        "source": "x",
        "medium": "organic_social",
        "content": "soham_demo_b",
    }
    assert row.assigned_founder == "Aditya Kolekar"
    assert alerts == []
    assert scheduled == []


async def test_acquisition_fields_are_bounded_and_referrer_is_host_only(client):
    c, SessionLocal = client
    too_long = c.post(
        "/api/waitlist",
        json={"email": "dana@bluebird.com", "content": "x" * 101},
    )
    full_url = c.post(
        "/api/waitlist",
        json={
            "email": "dana@bluebird.com",
            "referrer_host": "https://example.com/private/path?person=dana",
        },
    )

    assert too_long.status_code == 422
    assert full_url.status_code == 422
    assert await _count(SessionLocal) == 0


async def test_new_signup_schedules_post_commit_work_once(client, monkeypatch):
    c, SessionLocal = client
    alerts = []
    scheduled = []

    async def capture_alert(alert):
        # A fresh session can see the row, proving the handler committed before
        # FastAPI began the background notification.
        async with SessionLocal() as db:
            assert await db.get(WaitlistSignup, alert.signup_id) is not None
        alerts.append(alert)
        return True

    def capture_schedule(signup_id):
        scheduled.append(signup_id)
        return {}

    monkeypatch.setattr(waitlist_api, "send_waitlist_alert", capture_alert)
    monkeypatch.setattr(waitlist_api, "enqueue_email_sequence", capture_schedule)

    c.post("/api/waitlist", json={"email": "dana@bluebird.com"})
    c.post("/api/waitlist", json={"email": "dana@bluebird.com"})

    assert len(alerts) == 1
    assert alerts[0].assigned_founder in settings.waitlist_founder_roster_list
    assert scheduled == [alerts[0].signup_id]


async def test_waitlist_unsubscribe_is_idempotent(client):
    c, SessionLocal = client
    c.post("/api/waitlist", json={"email": "dana@bluebird.com"})
    (row,) = await _rows(SessionLocal)

    first = c.get("/api/waitlist/unsubscribe", params={"token": unsubscribe_token(row)})
    second = c.get("/api/waitlist/unsubscribe", params={"token": unsubscribe_token(row)})

    assert first.status_code == 200
    assert second.status_code == 200
    (updated,) = await _rows(SessionLocal)
    assert updated.email_opted_out_at is not None


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
