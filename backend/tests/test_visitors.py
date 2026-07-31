"""Consent-based first-party stitching and provider-neutral visitor reporting."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.core import database as database_module
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.posthog_client import POSTHOG_DISTINCT_ID_HEADER
from app.main import app, fastapi_app
from app.models.visitor import VisitorEvent, VisitorIdentifier, VisitorProfile
from app.visitor_intelligence.providers.rb2b import Rb2bAdapter
from app.visitor_intelligence.service import VISITOR_SESSION_ID_HEADER

_ips = itertools.count(20)


@pytest.fixture
async def visitor_client(monkeypatch):
    monkeypatch.setattr(settings, "posthog_disabled", True)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "rb2b_webhook_secret", "test-rb2b-secret")
    monkeypatch.setattr(settings, "discord_webhook_url", "")
    monkeypatch.setattr(settings, "discord_bot_token", "")
    monkeypatch.setattr(settings, "discord_alert_channel_id", "")

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "engine", engine)

    async def override_get_db():
        async with session_local() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    headers = {"x-forwarded-for": f"198.51.100.{next(_ips)}"}
    with TestClient(app, headers=headers) as client:
        yield client, session_local
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


async def test_waitlist_stitches_consented_history_without_plain_browser_id(
    visitor_client,
):
    client, session_local = visitor_client
    headers = {
        POSTHOG_DISTINCT_ID_HEADER: "browser-consented-123",
        VISITOR_SESSION_ID_HEADER: "session-consented-123",
    }
    viewed = client.post(
        "/api/analytics/landing",
        headers=headers,
        json={
            "event": "landing_viewed",
            "path": "/",
            "utm_source": "founder-post",
        },
    )
    joined = client.post(
        "/api/waitlist",
        headers=headers,
        json={
            "name": "Dana Okafor",
            "email": "dana@example.com",
            "business_name": "Bluebird Coffee",
        },
    )
    assert viewed.status_code == 204
    assert joined.status_code == 200

    async with session_local() as db:
        profiles = list((await db.execute(select(VisitorProfile))).scalars())
        identifiers = list((await db.execute(select(VisitorIdentifier))).scalars())
        events = list(
            (
                await db.execute(
                    select(VisitorEvent).order_by(VisitorEvent.occurred_at)
                )
            ).scalars()
        )

    assert len(profiles) == 1
    assert profiles[0].identity_level == "waitlist"
    assert profiles[0].primary_email == "dana@example.com"
    assert profiles[0].utm_source == "founder-post"
    assert profiles[0].intent_score >= 80
    assert {identifier.kind for identifier in identifiers} == {"browser", "email"}
    assert all(
        "browser-consented-123" not in identifier.value_hash
        for identifier in identifiers
    )
    assert [event.event_name for event in events] == [
        "landing_viewed",
        "waitlist_joined",
    ]
    assert events[0].session_hash != "session-consented-123"


async def test_rb2b_webhook_is_authenticated_idempotent_and_reported(
    visitor_client, monkeypatch
):
    client, _ = visitor_client
    alert = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.visitors.send_visitor_alert", alert)
    payload = {
        "LinkedIn URL": "https://www.linkedin.com/in/dana-okafor/",
        "First Name": "Dana",
        "Last Name": "Okafor",
        "Title": "Owner",
        "Company Name": "Bluebird Coffee",
        "Business Email": "dana@bluebird.example",
        "Website": "https://bluebird.example",
        "Industry": "Hospitality",
        "Employee Count": "11-50",
        "Estimate Revenue": "$2M",
        "City": "Fremont",
        "State": "California",
        "Zipcode": "94538",
        "Seen At": "2026-07-30T12:34:56+00:00",
        "Referrer": "https://www.google.com/search?q=retention",
        "Captured URL": "https://churnary.com/pricing",
        "Tags": "Pricing, ICP",
        "is_repeat_visitor": True,
    }

    rejected = client.post("/api/visitors/webhooks/rb2b?key=wrong", json=payload)
    accepted = client.post(
        "/api/visitors/webhooks/rb2b?key=test-rb2b-secret", json=payload
    )
    duplicate = client.post(
        "/api/visitors/webhooks/rb2b?key=test-rb2b-secret", json=payload
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["duplicate"] is False
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    listed = client.get("/api/visitors?days=365&source=rb2b")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Dana Okafor"
    assert body["items"][0]["last_path"] == "/pricing"
    assert body["items"][0]["intent_score"] == 35
    assert body["summary"]["provider_matches"] == 1
    detail = client.get(f"/api/visitors/{accepted.json()['visitor_id']}")
    assert detail.status_code == 200
    assert detail.json()["events"][0]["referrer"] == "www.google.com"

    pilot = client.get("/api/visitors/pilot?days=365")
    assert pilot.status_code == 200
    assert pilot.json()["deliveries"] == 1
    assert pilot.json()["repeat_visitors"] == 1
    alert.assert_awaited_once()


def test_rb2b_adapter_accepts_published_repeat_and_timestamp_variants():
    signal = Rb2bAdapter().normalize(
        {
            "LinkedIn URL": "https://www.linkedin.com/in/rb2b-test/",
            "First Name": "RB2B",
            "Captured URL": "https://churnary.example/pricing",
            "Seen At": "2026-07-30T12:34:56:00.00+00.00",
            "is_repeat_visit": True,
        }
    )

    assert signal.repeat_visitor is True
    assert signal.seen_at == datetime(2026, 7, 30, 12, 34, 56, tzinfo=UTC)


async def test_rb2b_webhook_rejects_non_object_or_oversized_payload(visitor_client):
    client, _ = visitor_client
    endpoint = "/api/visitors/webhooks/rb2b?key=test-rb2b-secret"

    not_an_object = client.post(
        endpoint,
        content=b"[]",
        headers={"content-type": "application/json"},
    )
    oversized = client.post(
        endpoint,
        content=b'{"padding":"' + (b"x" * 64_001) + b'"}',
        headers={"content-type": "application/json"},
    )
    missing_identity = client.post(
        endpoint,
        json={"Captured URL": "https://churnary.com/pricing"},
    )

    assert not_an_object.status_code == 422
    assert oversized.status_code == 413
    assert missing_identity.status_code == 422


async def test_suppression_erases_identity_history_and_blocks_rehydration(
    visitor_client,
):
    client, session_local = visitor_client
    payload = {
        "LinkedIn URL": "https://www.linkedin.com/in/dana/",
        "First Name": "Dana",
        "Business Email": "dana@example.com",
        "Company Name": "Bluebird",
        "Seen At": "2026-07-30T12:34:56+00:00",
        "Captured URL": "https://churnary.com/",
        "City": "Fremont",
        "State": "California",
        "Zipcode": "94538",
    }
    created = client.post(
        "/api/visitors/webhooks/rb2b?key=test-rb2b-secret", json=payload
    ).json()
    visitor_id = created["visitor_id"]

    suppressed = client.post(f"/api/visitors/{visitor_id}/suppress")
    repeated = client.post(
        "/api/visitors/webhooks/rb2b?key=test-rb2b-secret",
        json={**payload, "Seen At": "2026-07-30T13:34:56+00:00"},
    )
    assert suppressed.status_code == 204
    assert repeated.status_code == 200
    assert repeated.json()["visitor_id"] is None

    async with session_local() as db:
        profile = await db.get(VisitorProfile, uuid.UUID(visitor_id))
        event_count = (
            await db.execute(
                select(func.count(VisitorEvent.id)).where(
                    VisitorEvent.visitor_id == profile.id
                )
            )
        ).scalar_one()
    assert profile is not None
    assert profile.suppressed is True
    assert profile.primary_email is None
    assert profile.full_name is None
    assert event_count == 0
    assert client.get(f"/api/visitors/{visitor_id}").status_code == 404


async def test_tenant_owner_cannot_read_platform_visitor_data(
    visitor_client, monkeypatch
):
    client, _ = visitor_client
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "supabase_url", "https://configured.supabase.co")
    monkeypatch.setattr(settings, "visitor_admin_emails", "")

    async def owner():
        return CurrentUser(
            user_id="tenant-owner",
            email="owner@tenant.example",
            business_id="tenant",
            role="owner",
        )

    fastapi_app.dependency_overrides[get_current_user] = owner
    try:
        response = client.get("/api/visitors")
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 403


async def test_integration_status_and_discord_test_are_admin_only(
    visitor_client, monkeypatch
):
    client, _ = visitor_client
    monkeypatch.setattr(settings, "api_base_url", "https://api.churnary.example")
    monkeypatch.setattr(settings, "discord_application_id", "123")
    monkeypatch.setattr(settings, "discord_public_key", "a" * 64)
    monkeypatch.setattr(settings, "discord_guild_id", "456")
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/x")
    delivery = AsyncMock(return_value="channel webhook")
    monkeypatch.setattr("app.api.visitors.send_discord_test_alert", delivery)

    status_response = client.get("/api/visitors/integrations/status")
    test_response = client.post("/api/visitors/integrations/discord/test")

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["rb2b_webhook_configured"] is True
    assert body["discord_alerts_configured"] is True
    assert body["discord_commands_configured"] is True
    assert "test-rb2b-secret" not in body["rb2b_webhook_endpoint"]
    assert test_response.json() == {
        "delivered": True,
        "transport": "channel webhook",
    }
    delivery.assert_awaited_once()


def test_cors_allows_visitor_session_header():
    response = TestClient(app).options(
        "/api/analytics/landing",
        headers={
            "Origin": settings.frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": VISITOR_SESSION_ID_HEADER,
        },
    )
    assert response.status_code == 200
    assert (
        VISITOR_SESSION_ID_HEADER.casefold()
        in response.headers["access-control-allow-headers"].casefold()
    )
