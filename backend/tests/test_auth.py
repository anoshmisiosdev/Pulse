"""Auth: Supabase JWT verification + tenant resolution."""

from __future__ import annotations

import jwt
import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.deps import _tenant_from_claims
from app.core.security import verify_supabase_jwt
from app.main import app

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


def test_me_rejects_garbage_token(supabase_hs256):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_me_demo_fallback_when_unconfigured(supabase_unconfigured):
    # No Supabase + no auth header in dev -> demo tenant so the dashboard works.
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["business_name"]
