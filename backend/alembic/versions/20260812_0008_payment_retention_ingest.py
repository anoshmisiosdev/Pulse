"""payment retention ingest hardening

Revision ID: 20260812_0008
Revises: 20260804_0007
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260812_0008"
down_revision: str | None = "20260804_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OFFLINE_BASE_TABLES = {
    "businesses",
    "customers",
    "integration_connections",
    "transactions",
    "visits",
}
_OFFLINE_CREATED_TABLES = {"customer_identities", "provider_webhook_events"}
_OFFLINE_ADDED_COLUMNS = {
    "integration_connections": {
        "environment",
        "last_error",
        "provider_account_id",
        "token_expires_at",
    },
    "transactions": {
        "failure_code",
        "gross_amount",
        "provider_updated_at",
        "refunded_amount",
        "status",
    },
}
_OFFLINE_ADDED_INDEXES = {
    "integration_connections": {
        "ix_integration_connections_provider_account",
        "uq_integration_connections_business_source",
        "uq_integration_connections_source_provider_account",
    },
    "transactions": {
        "ix_transactions_customer_occurred",
        "ix_transactions_status",
        "uq_transactions_business_source_external",
    },
    "visits": {"uq_visits_business_source_external"},
}
_offline_downgrade = False


def _tables() -> set[str]:
    if context.is_offline_mode():
        tables = set(_OFFLINE_BASE_TABLES)
        if _offline_downgrade:
            tables.update(_OFFLINE_CREATED_TABLES)
        return tables
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if context.is_offline_mode():
        return set(_OFFLINE_ADDED_COLUMNS.get(table, ())) if _offline_downgrade else set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    if context.is_offline_mode():
        return set(_OFFLINE_ADDED_INDEXES.get(table, ())) if _offline_downgrade else set()
    inspector = sa.inspect(op.get_bind())
    names = {index["name"] for index in inspector.get_indexes(table)}
    names.update(constraint["name"] for constraint in inspector.get_unique_constraints(table))
    return {name for name in names if name}


def _add_column(table: str, column: sa.Column) -> None:
    if table in _tables() and column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    global _offline_downgrade
    _offline_downgrade = False
    tables = _tables()

    if {"businesses", "customers"}.issubset(tables) and "customer_identities" not in tables:
        op.create_table(
            "customer_identities",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("customer_id", sa.Uuid(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "business_id",
                "source",
                "external_id",
                name="uq_customer_identity_business_source_external",
            ),
        )
        op.create_index(
            "ix_customer_identities_business_id", "customer_identities", ["business_id"]
        )
        op.create_index(
            "ix_customer_identities_customer_id", "customer_identities", ["customer_id"]
        )
        op.create_index(
            "ix_customer_identities_customer_source",
            "customer_identities",
            ["customer_id", "source"],
        )

    _add_column("transactions", sa.Column("gross_amount", sa.Numeric(12, 2), nullable=True))
    _add_column(
        "transactions",
        sa.Column(
            "refunded_amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")
        ),
    )
    _add_column(
        "transactions",
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default=sa.text("'completed'")
        ),
    )
    _add_column(
        "transactions", sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column(
        "transactions", sa.Column("failure_code", sa.String(length=128), nullable=True)
    )
    if "transactions" in tables:
        op.execute("UPDATE transactions SET gross_amount = amount WHERE gross_amount IS NULL")
        indexes = _indexes("transactions")
        if "ix_transactions_status" not in indexes:
            op.create_index("ix_transactions_status", "transactions", ["status"])
        if "ix_transactions_customer_occurred" not in indexes:
            op.create_index(
                "ix_transactions_customer_occurred",
                "transactions",
                ["customer_id", "occurred_at"],
            )
        if "uq_transactions_business_source_external" not in indexes:
            op.execute(
                """
                DELETE FROM transactions
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY business_id, source, external_id
                            ORDER BY provider_updated_at DESC NULLS LAST, updated_at DESC
                        ) AS duplicate_rank
                        FROM transactions
                        WHERE external_id IS NOT NULL
                    ) ranked
                    WHERE duplicate_rank > 1
                )
                """
            )
            op.create_unique_constraint(
                "uq_transactions_business_source_external",
                "transactions",
                ["business_id", "source", "external_id"],
            )

    if "visits" in tables:
        indexes = _indexes("visits")
        if "uq_visits_business_source_external" not in indexes:
            op.execute(
                """
                DELETE FROM visits
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY business_id, source, external_id
                            ORDER BY updated_at DESC
                        ) AS duplicate_rank
                        FROM visits
                        WHERE external_id IS NOT NULL
                    ) ranked
                    WHERE duplicate_rank > 1
                )
                """
            )
            op.create_unique_constraint(
                "uq_visits_business_source_external",
                "visits",
                ["business_id", "source", "external_id"],
            )

    _add_column(
        "integration_connections",
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
    )
    _add_column(
        "integration_connections",
        sa.Column(
            "environment",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'production'"),
        ),
    )
    _add_column(
        "integration_connections",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column("integration_connections", sa.Column("last_error", sa.Text(), nullable=True))
    if "integration_connections" in tables:
        indexes = _indexes("integration_connections")
        if "ix_integration_connections_provider_account" not in indexes:
            op.create_index(
                "ix_integration_connections_provider_account",
                "integration_connections",
                ["source", "provider_account_id"],
            )
        if "uq_integration_connections_source_provider_account" not in indexes:
            op.create_unique_constraint(
                "uq_integration_connections_source_provider_account",
                "integration_connections",
                ["source", "provider_account_id"],
            )
        if "uq_integration_connections_business_source" not in indexes:
            op.execute(
                """
                DELETE FROM integration_connections
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY business_id, source
                            ORDER BY updated_at DESC
                        ) AS duplicate_rank
                        FROM integration_connections
                    ) ranked
                    WHERE duplicate_rank > 1
                )
                """
            )
            op.create_unique_constraint(
                "uq_integration_connections_business_source",
                "integration_connections",
                ["business_id", "source"],
            )

    if {"businesses", "integration_connections"}.issubset(tables) and (
        "provider_webhook_events" not in tables
    ):
        op.create_table(
            "provider_webhook_events",
            sa.Column("business_id", sa.Uuid(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("provider_event_id", sa.String(length=255), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=True),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="processed"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "source", "provider_event_id", name="uq_provider_webhook_source_event"
            ),
        )
        op.create_index(
            "ix_provider_webhook_events_business_id",
            "provider_webhook_events",
            ["business_id"],
        )
        op.create_index(
            "ix_provider_webhook_business_created",
            "provider_webhook_events",
            ["business_id", "created_at"],
        )


def downgrade() -> None:
    global _offline_downgrade
    _offline_downgrade = True
    tables = _tables()
    if "provider_webhook_events" in tables:
        op.drop_table("provider_webhook_events")
    if "integration_connections" in tables:
        indexes = _indexes("integration_connections")
        if "uq_integration_connections_source_provider_account" in indexes:
            op.drop_constraint(
                "uq_integration_connections_source_provider_account",
                "integration_connections",
                type_="unique",
            )
        if "uq_integration_connections_business_source" in indexes:
            op.drop_constraint(
                "uq_integration_connections_business_source",
                "integration_connections",
                type_="unique",
            )
        if "ix_integration_connections_provider_account" in indexes:
            op.drop_index(
                "ix_integration_connections_provider_account",
                table_name="integration_connections",
            )
        for name in ("last_error", "token_expires_at", "environment", "provider_account_id"):
            if name in _columns("integration_connections"):
                op.drop_column("integration_connections", name)
    if "transactions" in tables:
        indexes = _indexes("transactions")
        if "uq_transactions_business_source_external" in indexes:
            op.drop_constraint(
                "uq_transactions_business_source_external", "transactions", type_="unique"
            )
        if "ix_transactions_customer_occurred" in indexes:
            op.drop_index("ix_transactions_customer_occurred", table_name="transactions")
        if "ix_transactions_status" in indexes:
            op.drop_index("ix_transactions_status", table_name="transactions")
        for name in (
            "failure_code",
            "provider_updated_at",
            "status",
            "refunded_amount",
            "gross_amount",
        ):
            if name in _columns("transactions"):
                op.drop_column("transactions", name)
    if "customer_identities" in tables:
        op.drop_table("customer_identities")
    if "visits" in tables and "uq_visits_business_source_external" in _indexes("visits"):
        op.drop_constraint(
            "uq_visits_business_source_external", "visits", type_="unique"
        )
