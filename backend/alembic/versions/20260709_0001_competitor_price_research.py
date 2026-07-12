"""competitor price research

Revision ID: 20260709_0001
Revises:
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260709_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pricing initially shipped through SQLAlchemy create_all(). Adopt databases
    # that already contain the complete legacy table set, then let later
    # revisions add any missing columns and record the Alembic head normally.
    if not context.is_offline_mode():
        existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
        legacy_tables = {
            "competitor_price_research_runs",
            "competitor_price_competitors",
            "competitor_price_sources",
            "competitor_price_observations",
        }
        if legacy_tables.issubset(existing_tables):
            return

    op.create_table(
        "competitor_price_research_runs",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("cache_key", sa.String(length=512), nullable=False),
        sa.Column("business_category", sa.String(length=255), nullable=False),
        sa.Column("target_offer", sa.String(length=255), nullable=False),
        sa.Column("location_json", sa.Text(), nullable=False),
        sa.Column("radius_miles", sa.Float(), nullable=False),
        sa.Column("models_used_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_comp_price_runs_business_cache",
        "competitor_price_research_runs",
        ["business_id", "cache_key"],
    )
    op.create_index(
        "ix_comp_price_runs_business_created",
        "competitor_price_research_runs",
        ["business_id", "created_at"],
    )
    op.create_index(
        op.f("ix_competitor_price_research_runs_business_id"),
        "competitor_price_research_runs",
        ["business_id"],
    )
    op.create_index(
        op.f("ix_competitor_price_research_runs_cache_key"),
        "competitor_price_research_runs",
        ["cache_key"],
    )

    op.create_table(
        "competitor_price_competitors",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=True),
        sa.Column("website", sa.String(length=1024), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("distance_miles", sa.Float(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("relevance_reason", sa.Text(), nullable=True),
        sa.Column("source_urls_json", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["competitor_price_research_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_competitor_price_competitors_run_id"), "competitor_price_competitors", ["run_id"]
    )

    op.create_table(
        "competitor_price_sources",
        sa.Column("competitor_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["competitor_id"], ["competitor_price_competitors.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_comp_price_sources_competitor_url", "competitor_price_sources", ["competitor_id", "url"]
    )
    op.create_index(
        op.f("ix_competitor_price_sources_competitor_id"),
        "competitor_price_sources",
        ["competitor_id"],
    )

    op.create_table(
        "competitor_price_observations",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("offer_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_offer_name", sa.String(length=255), nullable=False),
        sa.Column("price_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_type", sa.String(length=32), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_reasons_json", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_id"], ["competitor_price_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_competitor_price_observations_source_id"),
        "competitor_price_observations",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_competitor_price_observations_source_id"),
        table_name="competitor_price_observations",
    )
    op.drop_table("competitor_price_observations")
    op.drop_index(
        op.f("ix_competitor_price_sources_competitor_id"), table_name="competitor_price_sources"
    )
    op.drop_index("ix_comp_price_sources_competitor_url", table_name="competitor_price_sources")
    op.drop_table("competitor_price_sources")
    op.drop_index(
        op.f("ix_competitor_price_competitors_run_id"), table_name="competitor_price_competitors"
    )
    op.drop_table("competitor_price_competitors")
    op.drop_index(
        op.f("ix_competitor_price_research_runs_cache_key"),
        table_name="competitor_price_research_runs",
    )
    op.drop_index(
        op.f("ix_competitor_price_research_runs_business_id"),
        table_name="competitor_price_research_runs",
    )
    op.drop_index(
        "ix_comp_price_runs_business_created", table_name="competitor_price_research_runs"
    )
    op.drop_index("ix_comp_price_runs_business_cache", table_name="competitor_price_research_runs")
    op.drop_table("competitor_price_research_runs")
