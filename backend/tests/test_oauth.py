"""OAuth flow plumbing: signed state, availability gating, callback error paths.

No network calls — the exchange itself is exercised only through failure paths.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.security import decrypt_state, encrypt_state
from app.main import app
from app.services.oauth import authorize_url, availability, redirect_uri

client = TestClient(app)


# ── signed state ─────────────────────────────────────────────────────────────


def test_state_round_trips():
    payload = {"b": "biz-1", "n": "Cafe", "v": "cafe", "r": "http://localhost:5173"}
    token = encrypt_state(payload)
    assert decrypt_state(token) == payload


def test_state_rejects_tampering():
    token = encrypt_state({"b": "biz-1"})
    with pytest.raises(ValueError):
        decrypt_state(token[:-4] + "AAAA")


def test_state_rejects_expiry():
    token = encrypt_state({"b": "biz-1"})
    with pytest.raises(ValueError):
        decrypt_state(token, max_age_seconds=-1)


# ── availability / start gating ──────────────────────────────────────────────


def test_availability_off_without_app_credentials(monkeypatch):
    monkeypatch.setattr(settings, "stripe_connect_client_id", "")
    monkeypatch.setattr(settings, "square_app_id", "")
    assert availability() == {"stripe": False, "square": False}
    r = client.get("/api/integrations/oauth/availability")
    assert r.status_code == 200
    assert r.json() == {"stripe": False, "square": False}


def test_start_422_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")  # demo-tenant auth fallback
    monkeypatch.setattr(settings, "square_app_id", "")
    monkeypatch.setattr(settings, "square_app_secret", "")
    r = client.get("/api/integrations/oauth/square/start")
    assert r.status_code == 422
    assert "paste an API key" in r.json()["detail"]


def test_start_returns_authorize_url_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")  # demo-tenant auth fallback
    monkeypatch.setattr(settings, "square_app_id", "sq0idp-test")
    monkeypatch.setattr(settings, "square_app_secret", "secret")
    monkeypatch.setattr(settings, "square_environment", "production")
    r = client.get(
        "/api/integrations/oauth/square/start?vertical=cafe&business_name=Test%20Cafe"
    )
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.startswith("https://connect.squareup.com/oauth2/authorize?")
    assert "client_id=sq0idp-test" in url
    assert "CUSTOMERS_READ" in url
    assert "state=" in url


def test_authorize_url_stripe(monkeypatch):
    monkeypatch.setattr(settings, "stripe_connect_client_id", "ca_test")
    url = authorize_url("stripe", "STATE123")
    assert url.startswith("https://connect.stripe.com/oauth/authorize?")
    assert "client_id=ca_test" in url and "state=STATE123" in url
    assert redirect_uri("stripe").endswith("/api/integrations/oauth/stripe/callback")


# ── callback error paths (no provider round-trip needed) ─────────────────────


def test_callback_bad_state_redirects_with_error():
    r = client.get(
        "/api/integrations/oauth/square/callback?code=x&state=garbage",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/setup?error=" in r.headers["location"]


def test_callback_user_denied_redirects_with_error():
    state = encrypt_state({"b": "biz-1", "r": "http://localhost:5173", "p": "square"})
    r = client.get(
        f"/api/integrations/oauth/square/callback?error=access_denied&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "declined" in r.headers["location"]


def test_callback_missing_code_redirects_with_error():
    state = encrypt_state({"b": "biz-1", "r": "http://localhost:5173", "p": "square"})
    r = client.get(
        f"/api/integrations/oauth/square/callback?state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
