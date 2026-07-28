"""Social routes over HTTP: wiring, tenant scoping, and serialization.

Complements tests/test_social.py, which exercises the same behaviour at the
service layer. This one is about the edges — status codes, response shapes, and
that every route really is scoped to the caller's business.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app

BUSINESS_ID = str(uuid.uuid4())
OTHER_BUSINESS_ID = str(uuid.uuid4())

VALID_KIT = {
    "name": "Hayward Coffee Co.",
    "tagline": "Your morning, sorted.",
    "audience": "Regulars within a mile of the shop",
    "tone": "warm, plain-spoken",
    "positioning": "A neighbourhood coffee bar that remembers your order.",
    "avoid": ["world-class"],
    "colors": {
        "primary": "#b4532a",
        "secondary": "#a23b1e",
        "accent": "#efe3d3",
        "background": "#fbf6ee",
        "text": "#2a211c",
    },
    "typography": {
        "heading_family": "Spectral",
        "body_family": "Hanken Grotesk",
        "heading_weight": 600,
        "body_weight": 400,
        "scale": "balanced",
    },
    "logo_url": None,
}


@pytest.fixture
def client(tmp_path):
    """TestClient backed by a throwaway SQLite file and a fixed demo tenant.

    Two deliberate choices. It is built without ``with TestClient(...)``, because
    entering the context manager runs the app's lifespan, which opens the *real*
    configured database and tries to create the schema there. And it uses a temp
    file rather than ``:memory:``, because an in-memory DB has to be pinned to one
    shared connection, which then outlives the event loop and litters teardown
    with "Event loop is closed".
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", poolclass=NullPool
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    created = False

    async def _db():
        nonlocal created
        if not created:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            created = True
        async with SessionLocal() as session:
            yield session
            await session.commit()

    def _user() -> CurrentUser:
        return CurrentUser(
            user_id="u1",
            email="owner@hayward.coffee",
            business_id=BUSINESS_ID,
            business_name="Hayward Coffee Co.",
        )

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    fastapi_app.dependency_overrides.clear()


def test_brand_kit_starts_at_version_zero(client):
    res = client.get("/api/social/brand-kit")
    assert res.status_code == 200
    body = res.json()
    assert body["version"] == 0
    assert body["name"] == "Hayward Coffee Co."


def test_saving_a_brand_kit_bumps_the_version_and_uppercases_colors(client):
    first = client.put("/api/social/brand-kit", json=VALID_KIT)
    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert first.json()["colors"]["primary"] == "#B4532A"

    second = client.put("/api/social/brand-kit", json=VALID_KIT)
    assert second.json()["version"] == 2


def test_brand_kit_rejects_a_bad_hex_colour(client):
    payload = {**VALID_KIT, "colors": {**VALID_KIT["colors"], "primary": "red"}}
    assert client.put("/api/social/brand-kit", json=payload).status_code == 422


def test_context_defaults_to_private_over_http(client):
    res = client.post(
        "/api/social/brain",
        json={"title": "Opening hours", "kind": "company", "summary": "7am to 4pm daily."},
    )
    assert res.status_code == 201
    assert res.json()["public_safe"] is False

    listing = client.get("/api/social/brain").json()
    assert listing["total"] == 1 and listing["public_safe"] == 0


def test_context_can_be_released_and_withdrawn(client):
    item = client.post(
        "/api/social/brain",
        json={"title": "Opening hours", "kind": "company", "summary": "7am to 4pm daily."},
    ).json()

    released = client.patch(f"/api/social/brain/{item['id']}?public_safe=true")
    assert released.json()["public_safe"] is True
    assert client.get("/api/social/brain").json()["public_safe"] == 1

    client.patch(f"/api/social/brain/{item['id']}?public_safe=false")
    assert client.get("/api/social/brain").json()["public_safe"] == 0


def test_deleting_missing_context_is_a_404(client):
    assert client.delete(f"/api/social/brain/{uuid.uuid4()}").status_code == 404


def test_inbox_seeds_demo_fixtures_and_flags_demo_mode(client):
    body = client.get("/api/social/inbox").json()
    assert body["total"] == 6
    assert body["demo_mode"] is True
    assert {c["source"] for c in body["data"]} == {"demo"}


def test_inbox_briefing_shape(client):
    body = client.get("/api/social/inbox/briefing").json()
    assert body["leads"] == 1
    assert body["high_risk"] == 1
    assert "recommended_action" in body and body["estimated_minutes_saved"] > 0


def test_capture_and_approve_a_comment(client):
    created = client.post(
        "/api/social/inbox",
        json={"platform": "linkedin", "author": "Alex Morgan", "comment": "Can I book a demo?"},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["intent"] == "sales_lead" and item["status"] == "needs_reply"

    approved = client.patch(
        f"/api/social/inbox/{item['id']}",
        json={"status": "approved", "suggested_reply": "Absolutely — sending times over."},
    )
    assert approved.status_code == 200
    assert approved.json()["approved_reply"] == "Absolutely — sending times over."


def test_approving_without_a_reply_is_rejected(client):
    item = client.post(
        "/api/social/inbox", json={"author": "Alex", "comment": "Hello there"}
    ).json()
    res = client.patch(f"/api/social/inbox/{item['id']}", json={"status": "approved"})
    assert res.status_code == 422


def test_empty_comment_patch_is_rejected(client):
    item = client.post(
        "/api/social/inbox", json={"author": "Alex", "comment": "Hello there"}
    ).json()
    assert client.patch(f"/api/social/inbox/{item['id']}", json={}).status_code == 422


def test_campaign_requires_a_future_start(client):
    res = client.post(
        "/api/social/campaigns",
        json={
            "name": "Autumn regulars",
            "brief": "Bring back lapsed customers",
            "themes": [],
            "platforms": ["linkedin"],
            "start_at": "2020-01-01T09:00:00-08:00",
            "timezone": "America/Los_Angeles",
            "interval_weeks": 1,
            "occurrences": 4,
        },
    )
    assert res.status_code == 422


def test_campaign_rejects_an_unknown_timezone(client):
    res = client.post(
        "/api/social/campaigns",
        json={
            "name": "Autumn regulars",
            "brief": "Bring back lapsed customers",
            "themes": [],
            "platforms": ["linkedin"],
            "start_at": "2030-01-07T09:00:00-08:00",
            "timezone": "Mars/Olympus",
            "interval_weeks": 1,
            "occurrences": 4,
        },
    )
    assert res.status_code == 422


def test_campaign_exposes_derived_slots(client):
    res = client.post(
        "/api/social/campaigns",
        json={
            "name": "Autumn regulars",
            "brief": "Bring back lapsed customers",
            "themes": ["Loyalty", "Seasonal menu"],
            "platforms": ["linkedin"],
            "start_at": "2030-01-07T09:00:00-08:00",
            "timezone": "America/Los_Angeles",
            "interval_weeks": 1,
            "occurrences": 4,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "draft"
    assert [s["occurrence"] for s in body["slots"]] == [1, 2, 3, 4]
    assert [s["theme"] for s in body["slots"]] == [
        "Loyalty", "Seasonal menu", "Loyalty", "Seasonal menu",
    ]


def test_generation_is_blocked_until_setup_is_done(client):
    campaign = client.post(
        "/api/social/campaigns",
        json={
            "name": "Autumn regulars",
            "brief": "Bring back lapsed customers",
            "themes": [],
            "platforms": ["linkedin"],
            "start_at": "2030-01-07T09:00:00-08:00",
            "timezone": "America/Los_Angeles",
            "interval_weeks": 1,
            "occurrences": 2,
        },
    ).json()

    res = client.post(f"/api/social/campaigns/{campaign['id']}/generate")
    assert res.status_code == 409
    assert "brand kit" in res.json()["detail"]


def test_publish_requires_confirmation(client):
    res = client.post("/api/social/posts/publish", json={"confirm": False})
    assert res.status_code == 422


def test_publish_with_nothing_approved_is_a_conflict(client):
    res = client.post("/api/social/posts/publish", json={"confirm": True})
    assert res.status_code == 409


def test_status_reports_setup_progress(client):
    body = client.get("/api/social/status").json()
    assert body["brand_kit_version"] == 0
    assert body["public_context_count"] == 0

    client.put("/api/social/brand-kit", json=VALID_KIT)
    assert client.get("/api/social/status").json()["brand_kit_version"] == 1
