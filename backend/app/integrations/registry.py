"""Adapter registry — the only place that knows the full set of integrations."""

from __future__ import annotations

from app.integrations.base import DataSourceAdapter
from app.integrations.csv_adapter import CSVAdapter
from app.integrations.mindbody_adapter import MindbodyAdapter
from app.integrations.square_adapter import SquareAdapter
from app.integrations.stripe_adapter import StripeAdapter

ADAPTERS: dict[str, type[DataSourceAdapter]] = {
    "csv": CSVAdapter,
    "square": SquareAdapter,
    "stripe": StripeAdapter,
    "mindbody": MindbodyAdapter,
}


def get_adapter_class(source: str) -> type[DataSourceAdapter]:
    try:
        return ADAPTERS[source.lower().strip()]
    except KeyError as exc:
        raise KeyError(f"Unknown integration source: {source!r}") from exc
