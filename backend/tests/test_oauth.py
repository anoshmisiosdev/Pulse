"""OAuth flow plumbing: signed state, availability gating, callback error paths.

No network calls — the exchange itself is exercised only through failure paths.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.security import decrypt_state, encrypt_state
from app.main import app
from app.services.oauth import (
    authorize_url,
    availability,
    redirect_uri,
    refresh_access_token,
)

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
    state = parse_qs(urlparse(url).query)["state"][0]
    assert decrypt_state(state)["u"] == "demo-user"


def test_authorize_url_stripe(monkeypatch):
    monkeypatch.setattr(settings, "stripe_connect_client_id", "ca_test")
    url = authorize_url("stripe", "STATE123")
    assert url.startswith("https://connect.stripe.com/oauth/authorize?")
    assert "client_id=ca_test" in url and "state=STATE123" in url
    assert redirect_uri("stripe").endswith("/api/integrations/oauth/stripe/callback")


def test_square_sandbox_omits_session_false(monkeypatch):
    """Regression: Square's docs say "Only session=true (default) is supported"
    in the Sandbox. We sent session=false unconditionally, which left the
    sandbox authorize page hanging with no error."""
    monkeypatch.setattr(settings, "square_app_id", "sandbox-sq0idb-test")
    monkeypatch.setattr(settings, "square_environment", "sandbox")
    url = authorize_url("square", "STATE")
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://connect.squareupsandbox.com/oauth2/authorize?")
    assert "session" not in query


def test_square_production_forces_explicit_sign_in(monkeypatch):
    """Production keeps session=false — Square recommends it, so a shared
    browser can't silently connect whichever seller happens to be logged in."""
    monkeypatch.setattr(settings, "square_app_id", "sq0idp-test")
    monkeypatch.setattr(settings, "square_environment", "production")
    query = parse_qs(urlparse(authorize_url("square", "STATE")).query)
    assert query["session"] == ["false"]


@pytest.mark.parametrize(
    ("key", "usable"),
    [
        ("sk_test_abc", True),
        ("sk_live_abc", True),
        ("rk_test_abc", True),  # restricted keys work server-side too
        ("pk_test_abc", False),  # the paste mistake this guards against
        ("pk_live_abc", False),
        ("", False),
        ("garbage", False),
    ],
)
def test_only_secret_keys_count_as_usable(monkeypatch, key, usable):
    monkeypatch.setattr(settings, "stripe_secret_key", key)
    assert settings.stripe_secret_key_usable is usable


def test_a_publishable_key_disables_stripe_connect_with_a_clear_reason(monkeypatch):
    """Regression: a pk_ key in STRIPE_SECRET_KEY made "Connect with Stripe" look
    available, then fail after the consent screen at token exchange. It now
    reads as unconfigured up front, and the startup log names the cause."""
    monkeypatch.setattr(settings, "stripe_connect_client_id", "ca_test")
    monkeypatch.setattr(settings, "stripe_secret_key", "pk_test_abc")
    assert availability()["stripe"] is False
    assert "publishable" in settings.stripe_key_problem
    assert "sk_test_" in settings.stripe_key_problem

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_abc")
    assert availability()["stripe"] is True
    assert settings.stripe_key_problem is None


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


async def test_square_refresh_uses_sandbox_and_preserves_refresh_token(monkeypatch):
    monkeypatch.setattr(settings, "square_app_id", "sq-app")
    monkeypatch.setattr(settings, "square_app_secret", "sq-secret")
    captured = {}

    async def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "merchant_id": "merchant-1",
                "expires_at": "2026-09-01T00:00:00Z",
            },
        )

    monkeypatch.setattr("app.services.oauth._post", fake_post)
    result = await refresh_access_token("square", "existing-refresh", "sandbox")

    assert captured["url"] == "https://connect.squareupsandbox.com/oauth2/token"
    assert captured["json"]["grant_type"] == "refresh_token"
    assert captured["json"]["refresh_token"] == "existing-refresh"
    assert result["access_token"] == "new-access"
    assert result["refresh_token"] == "existing-refresh"
    assert result["account_id"] == "merchant-1"
