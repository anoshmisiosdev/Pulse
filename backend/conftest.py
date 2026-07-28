"""Root conftest — its presence puts the backend dir on sys.path for `import app`."""

from datetime import datetime

import pytest

# A fixed "now" so time-based scoring assertions are deterministic.
NOW = datetime(2026, 6, 26)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    """Never let the suite call a real model.

    Settings load from the repo's own .env, so a developer with working
    credentials would otherwise have tests firing paid, slow, non-deterministic
    requests — and assertions about the static fallback would flip depending on
    whose machine ran them. Tests that want the LLM path monkeypatch a key back
    on and stub ``complete_text``.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "token_router_api_key", "")
    monkeypatch.setattr(settings, "token_router_base_url", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
