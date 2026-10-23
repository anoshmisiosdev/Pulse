"""Auth: Supabase JWT verification + tenant resolution."""

from __future__ import annotations

import uuid

import jwt
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import _tenant_from_claims
from app.core.security import verify_supabase_jwt
from app.main import app, fastapi_app
from app.models import Business, User

client = TestClient(app)
SECRET = "test-supabase-jwt-secret"


def _hs256_token(secret: str = SECRET, **overrides) -> str:
    payload = {
        "sub": "user-123",
        "email": "owner@hayward.coffee",
        "aud": "authenticated",
        "user_metadata": {"business_name": "Hayward Coffee Co."},
        "app_metadata": {},
        **overrides,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
async def isolated_db():
    """An in-memory database for every request these tests make.

    Since team membership is read per request (core/deps.py), a real token
    goes through a `users` lookup. Without this override that lookup used the
    app's own DATABASE_URL -- in local runs, whatever .env points at, which
    can be a live database. Tests must never reach one.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with factory() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = _db
    yield factory
    fastapi_app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.fixture
def supabase_hs256(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://demo.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)


@pytest.fixture
def supabase_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")


# ── token verification ────────────────────────────────────────────────────────
def test_verify_valid_hs256_token(supabase_hs256):
    claims = verify_supabase_jwt(_hs256_token())
    assert claims["sub"] == "user-123"
    assert claims["email"] == "owner@hayward.coffee"


def test_verify_rejects_wrong_secret(supabase_hs256):
    with pytest.raises(ValueError):
        verify_supabase_jwt(_hs256_token(secret="not-the-secret"))


def test_verify_requires_configuration(supabase_unconfigured):
    with pytest.raises(ValueError):
        verify_supabase_jwt(_hs256_token())


# ── tenant resolution ─────────────────────────────────────────────────────────
def test_tenant_defaults_business_id_to_user_id():
    user = _tenant_from_claims(
        {"sub": "abc", "email": "a@b.com", "user_metadata": {"business_name": "Acme"}}
    )
    assert user.business_id == "abc"
    assert user.business_name == "Acme"


def test_tenant_honors_app_metadata_business_id():
    user = _tenant_from_claims(
        {
            "sub": "abc",
            "email": "a@b.com",
            "app_metadata": {"business_id": "biz-9", "role": "staff"},
        }
    )
    assert user.business_id == "biz-9"
    assert user.role == "staff"


# ── /api/auth/me ──────────────────────────────────────────────────────────────
def test_me_with_valid_token_returns_tenant(supabase_hs256):
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_hs256_token()}"})
    assert r.status_code == 200
    assert r.json()["business_name"] == "Hayward Coffee Co."


async def test_me_resolves_a_team_member_to_the_inviting_business(
    supabase_hs256, isolated_db
):
    """End to end through the real token path: a membership row written when
    an invite was accepted is what decides the tenant, not the token's `sub`."""
    biz_id = uuid.uuid4()
    async with isolated_db() as db:
        db.add(Business(id=biz_id, name="Glow Studio", vertical="salon"))
        db.add(
            User(
                business_id=biz_id,
                supabase_user_id="user-123",
                email="owner@hayward.coffee",
                role="staff",
            )
        )
        await db.commit()

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_hs256_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["business_id"] == str(biz_id)
    assert body["business_name"] == "Glow Studio"
    assert body["role"] == "staff"


def test_me_rejects_garbage_token(supabase_hs256):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_me_demo_fallback_when_unconfigured(supabase_unconfigured):
    # No Supabase + no auth header in dev -> demo tenant so the dashboard works.
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["business_name"]


# ── /api/health ───────────────────────────────────────────────────────────────
def test_health_reports_the_build_revision(monkeypatch):
    """The deploy workflow polls this field to confirm a rollout actually replaced
    the running container — a successful `docker push` is not the same thing as new
    code serving traffic. Falls back to "unknown" when running from source."""
    monkeypatch.setattr(settings, "app_revision", "abc1234")
    body = client.get("/api/health").json()
    assert body["revision"] == "abc1234"
    assert body["status"] == "ok"


def test_health_revision_is_unknown_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "app_revision", "")
    assert client.get("/api/health").json()["revision"] == "unknown"
