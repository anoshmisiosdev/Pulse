"""add pricing evidence pipeline provenance

Revision ID: 20260710_0003
Revises: 20260709_0002
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260710_0003"
down_revision: str | None = "20260709_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing(
        "competitor_price_competitors", sa.Column("place_id", sa.String(255))
    )
    _add_column_if_missing(
        "competitor_price_competitors",
        sa.Column("discovery_provider", sa.String(32), nullable=False, server_default="perplexity"),
    )
    for name, column in [
        ("published_at", sa.String(64)),
        ("source_updated_at", sa.String(64)),
        ("retrieved_at", sa.DateTime(timezone=True)),
        ("retrieval_method", sa.String(32)),
        ("http_status", sa.Integer()),
        ("content_type", sa.String(128)),
        ("content_hash", sa.String(64)),
    ]:
        nullable = name != "retrieval_method"
        default = "search_snippet" if name == "retrieval_method" else None
        _add_column_if_missing(
            "competitor_price_sources",
            sa.Column(name, column, nullable=nullable, server_default=default),
        )
    for name, column, default in [
        ("source_published_at", sa.String(64), None),
        ("source_updated_at", sa.String(64), None),
        ("verified_at", sa.String(64), None),
        ("retrieval_method", sa.String(32), "search_snippet"),
        ("extraction_method", sa.String(32), "search_snippet"),
        ("freshness_status", sa.String(16), "unknown"),
        ("needs_review", sa.Boolean(), sa.false()),
    ]:
        _add_column_if_missing(
            "competitor_price_observations",
            sa.Column(name, column, nullable=default is None, server_default=default),
        )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if context.is_offline_mode():
        op.add_column(table_name, column)
        return
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def downgrade() -> None:
    for name in [
        "needs_review",
        "freshness_status",
        "extraction_method",
        "retrieval_method",
        "verified_at",
        "source_updated_at",
        "source_published_at",
    ]:
        op.drop_column("competitor_price_observations", name)
    for name in [
        "content_hash",
        "content_type",
        "http_status",
        "retrieval_method",
        "retrieved_at",
        "source_updated_at",
        "published_at",
    ]:
        op.drop_column("competitor_price_sources", name)
    op.drop_column("competitor_price_competitors", "discovery_provider")
    op.drop_column("competitor_price_competitors", "place_id")
