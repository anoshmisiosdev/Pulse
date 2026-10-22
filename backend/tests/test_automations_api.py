"""POST /automations/sends/{id}/approve — specifically the body/subject
override a 'suggest'-mode send (no AI copy) needs before it can go out.
Client fixture follows tests/test_timeline.py."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import Business, Campaign, CampaignSend, Customer, Subscription

BUSINESS_ID = uuid.uuid4()


@pytest.fixture
async def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    def _user() -> CurrentUser:
        return CurrentUser(
            user_id="u1", email="owner@hayward.coffee",
            business_id=str(BUSINESS_ID), business_name="Hayward Coffee Co.",
        )

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = _user
    yield TestClient(app), SessionLocal
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


async def _make_suggestion(SessionLocal, channel: str = "sms") -> str:
    """A pending suggest-mode send: empty body, generated_by='suggested'."""
    async with SessionLocal() as db:
        db.add(Business(id=BUSINESS_ID, name="Hayward Coffee Co.", vertical="cafe"))
        # SMS is a Growth entitlement, and approve_send re-checks it at send
        # time (app/billing/guard.py). Without a plan that includes SMS these
        # approvals are correctly refused with a 402.
        db.add(Subscription(business_id=BUSINESS_ID, tier="growth", status="active"))
        customer = Customer(
            business_id=BUSINESS_ID, source="csv", first_name="Dana",
            phone="+15551234567", email="dana@example.com",
        )
        db.add(customer)
        await db.flush()
        campaign = Campaign(
            business_id=BUSINESS_ID, name="Suggest high-risk", channel=channel, status="sending"
        )
        db.add(campaign)
        await db.flush()
        send = CampaignSend(
            business_id=BUSINESS_ID, campaign_id=campaign.id, customer_id=customer.id,
            channel=channel, subject=None, body="", status="pending", generated_by="suggested",
        )
        db.add(send)
        await db.commit()
        return str(send.id)


async def test_approving_a_suggestion_without_a_message_is_rejected(client):
    http, sessions = client
    send_id = await _make_suggestion(sessions)

    resp = http.post(f"/api/automations/sends/{send_id}/approve")

    assert resp.status_code == 422
    assert "needs a message" in resp.json()["detail"]


@pytest.fixture
def daytime(monkeypatch):
    """Pin SMS sends outside TCPA quiet hours.

    ``attempt_send`` re-checks ``is_quiet_hours`` against the business's local
    time, so without this the SMS approve tests pass or fail depending on what
    time of day the suite runs. The quiet-hours branch has its own test below.
    """
    monkeypatch.setattr("app.services.automations.is_quiet_hours", lambda _tz: False)


async def test_approving_an_sms_suggestion_with_a_message_sets_the_body(client, daytime):
    http, sessions = client
    send_id = await _make_suggestion(sessions, channel="sms")

    resp = http.post(
        f"/api/automations/sends/{send_id}/approve", json={"body": "Hey Dana, come back!"}
    )

    assert resp.status_code == 200
    assert resp.json()["body"] == "Hey Dana, come back!"
    # No Twilio configured in tests — status moves off "pending" either way,
    # proving the override was applied and attempt_send actually ran.
    assert resp.json()["status"] != "pending"


async def test_approving_an_email_suggestion_requires_a_subject_too(client):
    http, sessions = client
    send_id = await _make_suggestion(sessions, channel="email")

    resp = http.post(
        f"/api/automations/sends/{send_id}/approve", json={"body": "Come back!"}
    )

    assert resp.status_code == 422
    assert "subject" in resp.json()["detail"]


async def test_approving_an_already_drafted_send_ignores_the_payload(client, daytime):
    """Approving a normal (already AI-drafted) send can't be used to sneak
    in a different message — the payload is only honored when body is empty."""
    http, sessions = client
    send_id = await _make_suggestion(sessions, channel="sms")
    async with sessions() as db:
        send = await db.get(CampaignSend, uuid.UUID(send_id))
        send.body = "Original AI-drafted copy"
        send.generated_by = "claude"
        await db.commit()

    resp = http.post(
        f"/api/automations/sends/{send_id}/approve", json={"body": "Sneaky override"}
    )

    assert resp.status_code == 200
    assert resp.json()["body"] == "Original AI-drafted copy"


async def test_approving_an_sms_send_during_quiet_hours_is_refused(client, monkeypatch):
    """TCPA: an SMS approved outside 9am-8pm local stays pending and the owner
    is told to wait, rather than the message going out at 2am."""
    monkeypatch.setattr("app.services.automations.is_quiet_hours", lambda _tz: True)
    http, sessions = client
    send_id = await _make_suggestion(sessions, channel="sms")

    resp = http.post(
        f"/api/automations/sends/{send_id}/approve", json={"body": "Hey Dana, come back!"}
    )

    assert resp.status_code == 409
    assert "9am-8pm" in resp.json()["detail"]
    async with sessions() as db:
        send = await db.get(CampaignSend, uuid.UUID(send_id))
        assert send.status == "pending"
        # The body override still persisted, so approving later doesn't lose it.
        assert send.body == "Hey Dana, come back!"
