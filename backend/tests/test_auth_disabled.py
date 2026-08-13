"""AUTH_DISABLED: the dev-only demo-tenant bypass, and its production guard.

Exists because the previous way to get an unauthenticated local run — blanking
SUPABASE_URL for one process — isn't portable. PowerShell deletes an env var when
you assign "" to it, so the override vanished, settings fell back to the .env
value, and every request 401'd with nothing obviously wrong.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.deps import demo_tenant_allowed


def test_bypass_when_supabase_is_simply_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "auth_disabled", False)
    assert demo_tenant_allowed() is True


def test_no_bypass_when_supabase_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "supabase_url", "https://abc.supabase.co")
    monkeypatch.setattr(settings, "auth_disabled", False)
    assert demo_tenant_allowed() is False


def test_auth_disabled_overrides_a_configured_supabase(monkeypatch):
    """The case that matters: .env has real Supabase settings, but this local run
    wants the demo tenant."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "supabase_url", "https://abc.supabase.co")
    monkeypatch.setattr(settings, "auth_disabled", True)
    assert demo_tenant_allowed() is True


@pytest.mark.parametrize("auth_disabled", [True, False])
def test_production_never_bypasses(monkeypatch, auth_disabled):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "auth_disabled", auth_disabled)
    assert demo_tenant_allowed() is False


def test_production_refuses_to_boot_with_auth_disabled():
    """Belt and braces: even if demo_tenant_allowed were wrong, the app won't start."""
    with pytest.raises(ValidationError, match="AUTH_DISABLED must not be set in production"):
        Settings(
            environment="production",
            auth_disabled=True,
            fernet_key="x" * 44,
            supabase_url="https://abc.supabase.co",
            # Also required in production by the pricing pipeline's validator.
            google_maps_server_api_key="test-key",
            perplexity_api_key="test-key",
            _env_file=None,
        )


def test_production_still_boots_without_it():
    ok = Settings(
        environment="production",
        auth_disabled=False,
        fernet_key="x" * 44,
        supabase_url="https://abc.supabase.co",
        google_maps_server_api_key="test-key",
        perplexity_api_key="test-key",
        _env_file=None,
    )
    assert ok.is_production
    assert ok.auth_disabled is False
