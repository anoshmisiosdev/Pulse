"""A brand-new tenant -- signed in, nothing imported, so no `businesses` row
yet -- must be able to use everything that doesn't need customer data.

Postgres enforces foreign keys; SQLite doesn't unless asked. Several tables
reference `businesses.id` (subscriptions, team_invites), so code that writes
them for a tenant with no business row passed every SQLite test and would 500
in production -- on the "sign up, then pay" path from the Definition of Done.
This file runs on an SQLite engine with foreign keys switched on so that
class of bug fails here first.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import Business, Subscription, TeamInvite

NEW_TENANT = uuid.uuid4()


@pytest.fixture
async def strict_sessions(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'strict.db'}", poolclass=NullPool
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys_on(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def client(strict_sessions):
    async def _db():
        async with strict_sessions() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="new-owner",
        email="new@owner.com",
        business_id=str(NEW_TENANT),
        business_name="Brand New Studio",
        role="owner",
    )
    yield TestClient(app)
    fastapi_app.dependency_overrides.clear()


async def test_the_engine_really_enforces_foreign_keys(strict_sessions):
    """Guard for the guard: if this ever passes silently, every test below is
    meaningless."""
    from sqlalchemy.exc import IntegrityError

    async with strict_sessions() as db:
        db.add(Subscription(business_id=uuid.uuid4(), tier="starter", status="trialing"))
        with pytest.raises(IntegrityError):
            await db.flush()


def test_a_new_tenant_can_see_their_plan(client):
    resp = client.get("/api/billing/subscription")
    assert resp.status_code == 200
    assert resp.json()["status"] == "trialing"


def test_a_new_tenant_can_see_the_price_list(client):
    assert client.get("/api/billing/plans").status_code == 200


def test_a_new_tenant_can_ask_the_assistant(client):
    """Every entitlement-gated endpoint resolves the plan first."""
    resp = client.post("/api/chat/ask", json={"message": "Who is at risk?"})
    assert resp.status_code == 200


def test_a_new_owner_can_invite_a_teammate_before_importing_data(client):
    resp = client.post("/api/team/invites", json={"email": "first.hire@x.com"})
    assert resp.status_code == 201


async def test_a_placeholder_business_is_created_without_clobbering_a_later_import(
    client, strict_sessions
):
    """The row created so billing works must yield to the real import's name
    and vertical (ingest.ensure_business treats "My Business" as a placeholder)."""
    from app.services import ingest

    client.get("/api/billing/subscription")
    async with strict_sessions() as db:
        await ingest.ensure_business(db, str(NEW_TENANT), "Glow Studio", "salon")
        await db.commit()
        biz = await db.get(Business, NEW_TENANT)
    assert biz.name == "Glow Studio"
    assert biz.vertical == "salon"


async def test_stripe_checkout_for_a_tenant_with_no_business_row_is_recorded(
    client, strict_sessions, monkeypatch
):
    """Paying before importing anything must not 500 the webhook -- Stripe would
    retry it for days and the plan would never activate."""
    secret = "whsec_parity"
    monkeypatch.setattr(settings, "stripe_webhook_secret", secret)
    event_body = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(NEW_TENANT),
                    "customer": "cus_new",
                    "subscription": "sub_new",
                }
            },
        }
    ).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + event_body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/billing/webhook",
        content=event_body,
        headers={"stripe-signature": f"t={ts},v1={sig}"},
    )
    assert resp.status_code == 202
    async with strict_sessions() as db:
        sub = (
            await db.execute(select(Subscription).where(Subscription.business_id == NEW_TENANT))
        ).scalar_one()
    assert sub.stripe_customer_id == "cus_new"


async def test_invites_land_under_the_new_tenant(client, strict_sessions):
    client.post("/api/team/invites", json={"email": "first.hire@x.com"})
    async with strict_sessions() as db:
        invites = (await db.execute(select(TeamInvite))).scalars().all()
    assert [i.business_id for i in invites] == [NEW_TENANT]


async def test_a_subscription_event_arriving_before_checkout_still_activates_the_plan(
    client, strict_sessions, monkeypatch
):
    """Stripe doesn't guarantee event order, and customer.subscription.created
    routinely beats checkout.session.completed. It used to be ignored when no
    row existed yet, leaving a paid Growth plan on Starter until the next
    renewal. Here there's no business row either."""
    secret = "whsec_parity"
    monkeypatch.setattr(settings, "stripe_webhook_secret", secret)
    monkeypatch.setattr(settings, "stripe_price_growth", "price_growth_m")
    body = json.dumps(
        {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_first",
                    "customer": "cus_first",
                    "status": "active",
                    "metadata": {"business_id": str(NEW_TENANT)},
                    "items": {"data": [{"price": {"id": "price_growth_m"}}]},
                }
            },
        }
    ).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/billing/webhook", content=body, headers={"stripe-signature": f"t={ts},v1={sig}"}
    )
    assert resp.status_code == 202
    assert resp.json()["outcome"] == "status=active,tier=growth"
    plan = client.get("/api/billing/subscription").json()
    assert plan["tier"] == "growth"
    assert plan["status"] == "active"


def test_a_long_square_location_name_fits_the_column():
    """Square allows 255-character names; the column is 120. On Postgres one
    overlong name failed the whole sync."""
    from app.integrations.square_adapter import parse_square_payment

    tx = parse_square_payment(
        {
            "id": "p1",
            "status": "COMPLETED",
            "amount_money": {"amount": 500, "currency": "USD"},
            "location_id": "L1",
        },
        {"L1": "Downtown " + "x" * 240},
    )
    assert tx.location is not None
    assert len(tx.location) <= 120
    assert tx.location.startswith("Downtown")


def test_an_overlong_ai_subject_is_bounded():
    """CampaignSend.subject is String(512); Postgres rejects longer values."""
    from app.campaigns.generator import SUBJECT_MAX_CHARS, parse_model_json

    copy = parse_model_json(json.dumps({"subject": "S" * 5000, "body": "Hi"}), "email")
    assert len(copy.subject) == SUBJECT_MAX_CHARS
    assert SUBJECT_MAX_CHARS <= 512
