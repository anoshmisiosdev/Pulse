"""Async SQLAlchemy engine, session factory, and declarative base."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.core.config import settings


def is_postgres(url: str | None = None) -> bool:
    return (url or settings.database_url).startswith("postgresql")


def engine_connect_args() -> dict:
    """asyncpg connect args. Supabase's pooler needs the statement cache off, and
    remote Postgres needs SSL (``sslmode`` in the URL isn't understood by asyncpg).

    Both are asyncpg-only. They're skipped for any other driver so that pointing
    ``DATABASE_URL`` at SQLite for local dev works on its own, without also having
    to unset ``DB_USE_PGBOUNCER``/``DB_SSL`` — passing ``statement_cache_size`` to
    aiosqlite raises a TypeError that says nothing about the real cause.
    """
    args: dict = {}
    if not is_postgres():
        return args
    if settings.db_use_pgbouncer:
        args["statement_cache_size"] = 0
    if settings.db_ssl:
        args["ssl"] = settings.db_ssl
    return args


# Supabase's transaction pooler (pgBouncer) doesn't do server-side pooling, so use
# a NullPool and let pgBouncer pool.
_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if settings.db_use_pgbouncer and is_postgres():
    _engine_kwargs["poolclass"] = NullPool
_connect_args = engine_connect_args()
if _connect_args:
    _engine_kwargs["connect_args"] = _connect_args

engine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with created/updated timestamps available to all models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # onupdate is a Python callable, not func.now(). A SQL-side onupdate makes
    # SQLAlchemy expire the attribute after every UPDATE, so the next read of
    # updated_at — typically serializing the row you just changed — triggers a
    # lazy load, which raises MissingGreenlet under asyncio. Computing it here
    # keeps the value on the instance and costs one fewer round trip.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
