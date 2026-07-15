"""Convert JSON-in-Text columns to JSONB.

Existing rows hold valid JSON text, so a ::jsonb cast migrates them in place.

Revision ID: 20260714_0005
Revises: 20260714_0004
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("risk_scores", "reasons"),
    ("risk_scores", "signals"),
    ("competitor_price_research_runs", "location_json"),
    ("competitor_price_research_runs", "models_used_json"),
    ("competitor_price_research_runs", "warnings_json"),
    ("competitor_price_research_runs", "response_json"),
    ("competitor_price_competitors", "source_urls_json"),
    ("competitor_price_observations", "confidence_reasons_json"),
]


def upgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE JSONB "
            f"USING {column}::jsonb"
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TEXT")
