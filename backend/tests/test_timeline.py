"""The customer timeline endpoint: it merges every stream, orders it, and stays
inside the caller's tenant.

Client fixture follows tests/test_social_api.py — no lifespan, temp SQLite file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import (
    Business,
    Campaign,
    CampaignSend,
    Customer,
    EngagementEvent,
    RecoveryAttribution,
    RiskScore,
    Transaction,
    Visit,
)

BUSINESS_ID = uuid.uuid4()
OTHER_BUSINESS_ID = uuid.uuid4()
NOW = datetime(2026, 6, 26)


@pytest.fixture
async def client(tmp_path):
    """TestClient over a throwaway SQLite file, plus the sessionmaker so tests can
    seed directly. Async (unlike tests/test_social_api.py's) because these tests
    seed rows *before* the first request, so the schema has to exist up front
    rather than being created lazily by the first ``get_db`` call."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    def _user() -> CurrentUser:
        return CurrentUser(
            user_id="u1",
            email="owner@hayward.coffee",
            business_id=str(BUSINESS_ID),
            business_name="Hayward Coffee Co.",
        )

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = _user
    yield TestClient(app), SessionLocal
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


async def _seed(SessionLocal, business_id=BUSINESS_ID) -> str:
    """One customer with something from every stream. Returns their id."""
    async with SessionLocal() as db:
        db.add(Business(id=business_id, name="Hayward Coffee Co.", vertical="cafe"))
        customer = Customer(
            business_id=business_id,
            source="csv",
            first_name="Dana",
            last_name="Reyes",
            email="dana@example.com",
        )
        db.add(customer)
        await db.flush()

        campaign = Campaign(
            business_id=business_id, name="Win back", channel="email", status="sending"
        )
        db.add(campaign)
        await db.flush()
        send = CampaignSend(
            business_id=business_id,
            campaign_id=campaign.id,
            customer_id=customer.id,
            channel="email",
            subject="We miss you",
            body="Come back",
            status="sent",
            sent_at=NOW - timedelta(days=10),
        )
        db.add(send)
        await db.flush()

        db.add_all(
            [
                Visit(
                    business_id=business_id,
                    customer_id=customer.id,
                    source="csv",
                    occurred_at=NOW - timedelta(days=40),
                ),
                Transaction(
                    business_id=business_id,
                    customer_id=customer.id,
                    source="csv",
                    amount=89,
                    occurred_at=NOW - timedelta(days=40),
                ),
                EngagementEvent(
                    business_id=business_id,
                    customer_id=customer.id,
                    kind="email_open",
                    occurred_at=NOW - timedelta(days=9),
                    campaign_send_id=send.id,
                ),
                RiskScore(
                    business_id=business_id,
                    customer_id=customer.id,
                    score=82,
                    band="high",
                    reasons=["Last visit 30 days ago — 3.2× their usual 9-day gap"],
                    signals={"recency": 0.9},
                ),
                RecoveryAttribution(
                    business_id=business_id,
                    customer_id=customer.id,
                    campaign_send_id=send.id,
                    estimated_value=64,
                    recovered_at=NOW - timedelta(days=3),
                ),
            ]
        )
        await db.commit()
        return str(customer.id)


async def test_timeline_merges_every_stream(client):
    http, SessionLocal = client
    customer_id = await _seed(SessionLocal)

    res = http.get(f"/api/customers/{customer_id}/timeline")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Dana Reyes"

    kinds = {e["kind"] for e in body["entries"]}
    assert kinds == {"visit", "purchase", "engagement", "risk_change", "outreach", "recovered"}


async def test_timeline_is_newest_first(client):
    http, SessionLocal = client
    customer_id = await _seed(SessionLocal)

    entries = http.get(f"/api/customers/{customer_id}/timeline").json()["entries"]
    timestamps = [e["at"] for e in entries]
    assert timestamps == sorted(timestamps, reverse=True)

    # Relative order of the back-dated fixtures: recovered (3d) newer than the
    # send (10d), newer than the original visit (40d). RiskScore isn't checked
    # here — it has no occurred_at column, so the timeline dates it by insertion
    # time, which is the real clock rather than the fixture's.
    order = [e["kind"] for e in entries]
    assert order.index("recovered") < order.index("outreach") < order.index("visit")
    recovered = next(e for e in entries if e["kind"] == "recovered")
    assert recovered["amount"] == 64.0


async def test_timeline_entries_read_as_plain_english(client):
    http, SessionLocal = client
    customer_id = await _seed(SessionLocal)

    entries = http.get(f"/api/customers/{customer_id}/timeline").json()["entries"]
    titles = [e["title"] for e in entries]
    assert "Opened the email" in titles
    assert "Risk became high (82/100)" in titles
    assert any("Win-back message sent" in t for t in titles)
    # No raw event names or snake_case leaking into the owner-facing copy.
    assert not any("_" in t for t in titles)


async def test_risk_change_carries_its_reasons(client):
    http, SessionLocal = client
    customer_id = await _seed(SessionLocal)

    entries = http.get(f"/api/customers/{customer_id}/timeline").json()["entries"]
    risk = next(e for e in entries if e["kind"] == "risk_change")
    assert "usual 9-day gap" in risk["detail"]


async def test_another_tenants_customer_is_a_404(client):
    """The whole point of the business_id check — a valid UUID from another
    tenant must not be readable."""
    http, SessionLocal = client
    await _seed(SessionLocal)
    foreign_id = await _seed(SessionLocal, business_id=OTHER_BUSINESS_ID)

    assert http.get(f"/api/customers/{foreign_id}/timeline").status_code == 404


async def test_unknown_and_malformed_ids_are_404_not_500(client):
    http, SessionLocal = client
    await _seed(SessionLocal)

    assert http.get(f"/api/customers/{uuid.uuid4()}/timeline").status_code == 404
    assert http.get("/api/customers/not-a-uuid/timeline").status_code == 404


async def test_limit_caps_the_response(client):
    http, SessionLocal = client
    customer_id = await _seed(SessionLocal)

    entries = http.get(f"/api/customers/{customer_id}/timeline?limit=2").json()["entries"]
    assert len(entries) == 2


async def test_a_customer_with_no_activity_returns_an_empty_timeline(client):
    http, SessionLocal = client
    await _seed(SessionLocal)
    async with SessionLocal() as db:
        bare = Customer(business_id=BUSINESS_ID, source="csv", email="bare@example.com")
        db.add(bare)
        await db.commit()
        bare_id = str(bare.id)

    body = http.get(f"/api/customers/{bare_id}/timeline").json()
    assert body["entries"] == []
    # No name on file — falls back to something displayable rather than blank.
    assert body["name"] == "bare@example.com"


async def test_portfolio_exposes_recovery_totals_and_row_ids(client):
    """The dashboard's "Revenue retained" tile and the drawer's timeline link both
    depend on these two additions to the portfolio payload."""
    http, SessionLocal = client
    customer_id = await _seed(SessionLocal)

    body = http.get("/api/portfolio").json()
    assert body["summary"]["recovered_count"] == 1
    assert body["summary"]["revenue_recovered"] == 64.0

    row = next(c for c in body["customers"] if c["db_customer_id"] == customer_id)
    assert row["recommended_action"]
    assert row["action_reason"]


async def test_csv_preview_has_no_row_ids(client):
    """Nothing is persisted on the demo/preview path, so there's no row to link to
    and the UI must not offer a timeline."""
    http, _ = client
    body = http.post("/api/integrations/demo?count=20").json()
    assert all(c["db_customer_id"] is None for c in body["customers"])
    assert body["summary"]["recovered_count"] == 0


async def test_attribution_endpoint_is_idempotent_over_http(client):
    http, SessionLocal = client
    await _seed(SessionLocal)

    # The seeded attribution already covers this customer, so a fresh run finds
    # nothing new — and definitely doesn't write a second row.
    first = http.post("/api/automations/attribute").json()
    assert first["recoveries_found"] == 0

    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(RecoveryAttribution).where(
                        RecoveryAttribution.business_id == BUSINESS_ID
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
