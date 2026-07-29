"""Resend webhook: verifies signature, creates EngagementEvent rows, and
unsubscribes on bounce/complaint. Uses the real ASGI app over an in-memory
SQLite DB — these three routes (resend/webhook, twilio/inbound, twilio/status)
take no auth dependency, so no JWT/demo-tenant setup is needed."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

import app.core.database as database_module
from app.core.config import settings
from app.core.database import Base, get_db
from app.main import fastapi_app
from app.models import Business, Campaign, CampaignSend, Customer, EngagementEvent
from conftest import TEST_DATABASE_URL

SECRET = "whsec_" + base64.b64encode(b"test-signing-key-32-bytes-long!!").decode()


def _sign(payload: bytes, svix_id: str, svix_timestamp: str) -> str:
    key = base64.b64decode(SECRET.split("_", 1)[1])
    signed_content = f"{svix_id}.{svix_timestamp}.".encode() + payload
    sig = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()
    return f"v1,{sig}"


@pytest.fixture(autouse=True)
def _resend_secret(monkeypatch):
    monkeypatch.setattr(settings, "resend_webhook_secret", SECRET)


@pytest.fixture
async def seeded(monkeypatch):
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    # The app's lifespan (app/main.py) does its own `from app.core.database
    # import engine` on every startup and runs create_all/column_patches
    # against it — pointed at the real DATABASE_URL from .env by default,
    # which TestClient's startup event would otherwise try to reach over the
    # network (and hang, since it's a private RDS instance from here). Point
    # it at this same in-memory engine instead; create_all is idempotent and
    # SQLite tolerates the "ADD COLUMN IF NOT EXISTS" patches fine.
    monkeypatch.setattr(database_module, "engine", engine)

    business_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    campaign_id = uuid.uuid4()
    send_id = uuid.uuid4()

    async with SessionLocal() as db:
        db.add(Business(id=business_id, name="Test Cafe", vertical="cafe"))
        db.add(
            Customer(id=customer_id, business_id=business_id, source="csv", email="a@example.com")
        )
        db.add(Campaign(id=campaign_id, business_id=business_id, name="Win back", channel="email"))
        db.add(
            CampaignSend(
                id=send_id,
                business_id=business_id,
                campaign_id=campaign_id,
                customer_id=customer_id,
                channel="email",
                subject="We miss you",
                body="Come back!",
                status="sent",
                provider_message_id="resend_email_123",
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield SessionLocal, business_id, customer_id, send_id
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


def _post_event(client: TestClient, event_type: str, email_id: str = "resend_email_123", **data):
    body = json.dumps({"type": event_type, "data": {"email_id": email_id, **data}}).encode()
    svix_id, ts = "msg_test", str(int(time.time()))
    return client.post(
        "/api/automations/resend/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "svix-id": svix_id,
            "svix-timestamp": ts,
            "svix-signature": _sign(body, svix_id, ts),
        },
    )


async def test_opened_event_creates_engagement_row(seeded):
    SessionLocal, _, _, send_id = seeded
    with TestClient(fastapi_app) as client:
        resp = _post_event(client, "email.opened")
    assert resp.status_code == 200

    async with SessionLocal() as db:
        rows = (await db.execute(EngagementEvent.__table__.select())).fetchall()
    assert len(rows) == 1
    assert rows[0].kind == "email_open"
    assert rows[0].campaign_send_id == send_id


async def test_clicked_event_records_link_url(seeded):
    SessionLocal, *_ = seeded
    with TestClient(fastapi_app) as client:
        resp = _post_event(client, "email.clicked", click={"link": "https://example.com/offer"})
    assert resp.status_code == 200

    async with SessionLocal() as db:
        rows = (await db.execute(EngagementEvent.__table__.select())).fetchall()
    assert rows[0].kind == "email_click"
    assert rows[0].detail == "https://example.com/offer"


async def test_bounce_unsubscribes_customer_and_fails_send(seeded):
    SessionLocal, _, customer_id, send_id = seeded
    with TestClient(fastapi_app) as client:
        resp = _post_event(client, "email.bounced")
    assert resp.status_code == 200

    async with SessionLocal() as db:
        customer = await db.get(Customer, customer_id)
        send = await db.get(CampaignSend, send_id)
    assert customer.unsubscribed_email is True
    assert send.status == "failed"
    assert send.failure_reason == "bounced"


async def test_invalid_signature_rejected(seeded):
    with TestClient(fastapi_app) as client:
        resp = client.post(
            "/api/automations/resend/webhook",
            content=b'{"type":"email.opened","data":{"email_id":"resend_email_123"}}',
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1750000000",
                "svix-signature": "v1,not_a_real_signature",
            },
        )
    assert resp.status_code == 403


async def test_unknown_email_id_is_ignored_not_errored(seeded):
    with TestClient(fastapi_app) as client:
        resp = _post_event(client, "email.opened", email_id="some-other-email-id")
    assert resp.status_code == 200
