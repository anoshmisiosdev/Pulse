"""Alembic environment (async). URL + metadata come from the app so migrations
stay in lockstep with the SQLAlchemy models.

Usage:
    uv run alembic revision --autogenerate -m "init"
    uv run alembic upgrade head

For Supabase, point DATABASE_URL at the *direct* connection (port 5432) when
running migrations — the transaction pooler doesn't support them.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app import models  # noqa: F401 — register all tables on Base.metadata
from app.core.config import settings
from app.core.database import Base, engine_connect_args

config = context.config
migration_url = settings.effective_database_migration_url
config.set_main_option("sqlalchemy.url", migration_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        migration_url,
        poolclass=pool.NullPool,
        connect_args=engine_connect_args(),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
