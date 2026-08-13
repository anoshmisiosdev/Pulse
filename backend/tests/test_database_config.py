"""Engine connect-args are Postgres-only.

Regression: pointing DATABASE_URL at SQLite for local dev while .env still said
DB_USE_PGBOUNCER=true passed asyncpg's ``statement_cache_size`` to aiosqlite,
which raises "'statement_cache_size' is an invalid keyword argument for
Connection()" — an error that names nothing relevant to the actual mistake.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.database import engine_connect_args, is_postgres


def test_sqlite_gets_no_asyncpg_args(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./dev.db")
    monkeypatch.setattr(settings, "db_use_pgbouncer", True)
    monkeypatch.setattr(settings, "db_ssl", "require")
    assert engine_connect_args() == {}


def test_postgres_still_gets_pooler_and_ssl_args(monkeypatch):
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://u:p@db.example.co:6543/postgres"
    )
    monkeypatch.setattr(settings, "db_use_pgbouncer", True)
    monkeypatch.setattr(settings, "db_ssl", "require")
    assert engine_connect_args() == {"statement_cache_size": 0, "ssl": "require"}


def test_postgres_without_pooler_or_ssl_gets_nothing(monkeypatch):
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://u:p@localhost:5432/pulse"
    )
    monkeypatch.setattr(settings, "db_use_pgbouncer", False)
    monkeypatch.setattr(settings, "db_ssl", "")
    assert engine_connect_args() == {}


def test_is_postgres_detection(monkeypatch):
    assert is_postgres("postgresql+asyncpg://u:p@h/db")
    assert not is_postgres("sqlite+aiosqlite:///./dev.db")
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite://")
    assert not is_postgres()  # falls back to the configured URL
