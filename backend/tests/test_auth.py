"""Auth: session-token round-trip + endpoint guards (no live Convex needed)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.security import create_session_token, decode_session_token
from app.main import app

client = TestClient(app)


@pytest.fixture
def convex_unconfigured(monkeypatch):
    """Force the 'no Convex' code paths regardless of the local .env."""
    monkeypatch.setattr(settings, "convex_url", "")
    monkeypatch.setattr(settings, "convex_api_key", "")


def test_session_token_roundtrip():
    token = create_session_token(
        user_id="u1", business_id="biz-1", email="o@x.com",
        business_name="Acme", role="owner",
    )
    claims = decode_session_token(token)
    assert claims["sub"] == "u1"
    assert claims["business_id"] == "biz-1"
    assert claims["business_name"] == "Acme"
    assert claims["iss"] == "pulse"


def test_decode_rejects_tampered_token():
    token = create_session_token(user_id="u1", business_id="b", email=None)
    with pytest.raises(ValueError):
        decode_session_token(token + "x")


def test_me_dev_demo_fallback_without_auth(convex_unconfigured):
    # With no auth configured, dev falls back to a demo tenant.
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["business_name"]


def test_me_with_valid_token_returns_tenant():
    token = create_session_token(
        user_id="u9", business_id="biz-9", email="owner@cafe.com",
        business_name="Bean There", role="owner",
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["business_id"] == "biz-9"
    assert body["business_name"] == "Bean There"


def test_me_rejects_garbage_token():
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_login_503_when_convex_unconfigured(convex_unconfigured):
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "x"})
    assert r.status_code == 503


def test_register_requires_admin_key():
    r = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "x", "business_name": "Acme"},
    )
    assert r.status_code == 403
