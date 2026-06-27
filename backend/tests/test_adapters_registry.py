"""The adapter registry + stub contracts. Proves a new source drops in cleanly."""

from __future__ import annotations

import pytest

from app.integrations.base import DataSourceAdapter
from app.integrations.registry import ADAPTERS, get_adapter_class


def test_registry_exposes_all_v1_sources():
    assert set(ADAPTERS) == {"csv", "square", "stripe", "mindbody"}
    for cls in ADAPTERS.values():
        assert issubclass(cls, DataSourceAdapter)


def test_get_adapter_class_is_case_insensitive():
    assert get_adapter_class("CSV") is ADAPTERS["csv"]


def test_unknown_source_raises():
    with pytest.raises(KeyError):
        get_adapter_class("hubspot")


async def test_mindbody_is_an_explicit_stub():
    adapter = ADAPTERS["mindbody"]()
    with pytest.raises(NotImplementedError):
        await adapter.connect({})


async def test_square_and_stripe_require_token_then_stub_sync():
    from app.integrations.base import IntegrationError

    for source in ("square", "stripe"):
        adapter = ADAPTERS[source]()
        with pytest.raises(IntegrationError):
            await adapter.connect({})  # no token
        await adapter.connect({"access_token": "tok"})
        with pytest.raises(NotImplementedError):
            await adapter.sync_customers()
