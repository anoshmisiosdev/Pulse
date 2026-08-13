"""Signed Discord interaction and privacy-safe alert tests."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.core import database as database_module
from app.core.config import settings
from app.core.database import Base, get_db
from app.discord_bot import service as discord_service
from app.main import app, fastapi_app
from app.models.visitor import VisitorProfile


@pytest.fixture
async def discord_client(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr(settings, "posthog_disabled", True)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "discord_application_id", "123456")
    monkeypatch.setattr(settings, "discord_public_key", public_key.hex())
    monkeypatch.setattr(settings, "discord_guild_id", "654321")
    monkeypatch.setattr(settings, "discord_allowed_role_ids", "")
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
    with TestClient(app, headers={"x-forwarded-for": "198.51.100.88"}) as client:
        yield client, session_local, private_key
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


def _post_interaction(
    client: TestClient,
    private_key: Ed25519PrivateKey,
    payload: dict,
    *,
    valid_signature: bool = True,
):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = private_key.sign(timestamp.encode() + body).hex()
    if not valid_signature:
        signature = "00" * 64
    return client.post(
        "/api/discord/interactions",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": timestamp,
        },
    )


async def test_discord_ping_and_signature_validation(discord_client):
    client, _, private_key = discord_client
    payload = {"type": 1, "application_id": "123456"}

    accepted = _post_interaction(client, private_key, payload)
    rejected = _post_interaction(
        client,
        private_key,
        payload,
        valid_signature=False,
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"type": 1}
    assert rejected.status_code == 401


async def test_discord_recent_command_is_ephemeral_and_permission_gated(
    discord_client,
):
    client, session_local, private_key = discord_client
    now = datetime.now(UTC)
    async with session_local() as db:
        db.add(
            VisitorProfile(
                full_name="Dana Okafor",
                job_title="Owner",
                company_name="Bluebird Coffee",
                linkedin_url="https://www.linkedin.com/in/dana/",
                identity_level="person",
                source_provider="rb2b",
                intent_score=78,
                first_seen_at=now,
                last_seen_at=now,
                last_path="/pricing",
                tags=["ICP"],
            )
        )
        await db.commit()

    base_payload = {
        "type": 2,
        "application_id": "123456",
        "guild_id": "654321",
        "data": {
            "name": "churnary",
            "options": [{"name": "recent", "type": 1, "options": []}],
        },
    }
    denied = _post_interaction(
        client,
        private_key,
        {**base_payload, "member": {"permissions": "0", "roles": []}},
    )
    allowed = _post_interaction(
        client,
        private_key,
        {**base_payload, "member": {"permissions": "32", "roles": []}},
    )

    assert denied.status_code == 200
    assert "do not have access" in denied.json()["data"]["content"]
    body = allowed.json()
    assert body["type"] == 4
    assert body["data"]["flags"] == 64
    assert "Dana Okafor" in str(body["data"]["embeds"])
    assert "dana@" not in str(body)


async def test_discord_alert_hides_email_by_default(monkeypatch):
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/x")
    monkeypatch.setattr(settings, "discord_include_email", False)
    monkeypatch.setattr(settings, "discord_alert_min_intent_score", 25)
    captured: dict = {}

    async def capture(payload: dict) -> str:
        captured.update(payload)
        return "channel webhook"

    monkeypatch.setattr(discord_service, "deliver_discord_message", capture)
    alert = discord_service.VisitorAlert(
        visitor_id=uuid.uuid4(),
        full_name="Dana Okafor",
        job_title="Owner",
        company_name="Bluebird Coffee",
        company_domain="bluebird.example",
        primary_email="dana@bluebird.example",
        linkedin_url="https://www.linkedin.com/in/dana/",
        city="Fremont",
        state="California",
        identity_level="person",
        intent_score=78,
        last_path="/pricing",
        source_provider="rb2b",
        tags=("ICP",),
        last_seen_at=datetime.now(UTC),
    )

    delivered = await discord_service.send_visitor_alert(alert)

    assert delivered is True
    assert "dana@bluebird.example" not in str(captured)
    assert captured["allowed_mentions"] == {"parse": []}


async def test_waitlist_alert_routes_explicit_signup_to_assigned_founder(monkeypatch):
    monkeypatch.setattr(
        settings,
        "discord_webhook_url",
        "https://discord.com/api/webhooks/1/x",
    )
    captured: dict = {}

    async def capture(payload: dict) -> str:
        captured.update(payload)
        return "channel webhook"

    monkeypatch.setattr(discord_service, "deliver_discord_message", capture)
    alert = discord_service.WaitlistAlert(
        signup_id=uuid.uuid4(),
        email="dana@bluebird.example",
        name=None,
        business_name="Bluebird Coffee",
        vertical="cafe",
        assigned_founder="Aditya Kolekar",
        first_touch=(("content", "aditya_observation_a"), ("source", "linkedin")),
        created_at=datetime.now(UTC),
    )

    delivered = await discord_service.send_waitlist_alert(alert)

    assert delivered is True
    assert "Aditya Kolekar" in str(captured)
    assert "dana@bluebird.example" in str(captured)
    assert "aditya_observation_a" in str(captured)
    assert captured["allowed_mentions"] == {"parse": []}


async def test_waitlist_alert_failure_is_isolated(monkeypatch):
    monkeypatch.setattr(
        settings,
        "discord_webhook_url",
        "https://discord.com/api/webhooks/1/x",
    )

    async def fail(_payload: dict) -> str:
        raise discord_service.DiscordDeliveryError("offline")

    monkeypatch.setattr(discord_service, "deliver_discord_message", fail)
    alert = discord_service.WaitlistAlert(
        signup_id=uuid.uuid4(),
        email="dana@bluebird.example",
        name="Dana",
        business_name=None,
        vertical=None,
        assigned_founder="Soham Dogra",
        first_touch=(),
        created_at=datetime.now(UTC),
    )

    assert await discord_service.send_waitlist_alert(alert) is False
