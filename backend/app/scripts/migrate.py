"""Run `alembic upgrade head` under a Postgres advisory lock.

App Runner (and any platform that can boot more than one instance for a
single deploy) starts each container independently — nothing coordinates
their `alembic upgrade head` calls. Two instances beginning migrations at
the same moment both read the database as behind, both start applying the
same pending migration, and the second one hits a DuplicateTableError (or
similar) when it tries to create something the first one just committed.
Seen in production: 20260712_0003 (business_knowledge) racing like this
during a rollout, crashing the new instance and triggering a rollback.

A session-level advisory lock serializes this: the second instance blocks
until the first finishes and releases, then runs `alembic upgrade head`
against an already-current database — a correct no-op, not a race.

    uv run python -m app.scripts.migrate
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import sqlalchemy as sa

# Arbitrary but fixed for this app — two different apps sharing a Postgres
# instance could theoretically collide on the same lock id, but nothing else
# in this codebase takes advisory locks, so any stable constant is fine.
_LOCK_ID = 0x5075_6C73_654D_6967  # "PulseMig" packed into an int64


async def _run_locked() -> int:
    from app.core.database import engine

    async with engine.connect() as conn:
        # Blocking acquire — the second instance waits, it doesn't fail.
        await conn.execute(sa.text("SELECT pg_advisory_lock(:id)"), {"id": _LOCK_ID})
        try:
            result = subprocess.run(["uv", "run", "alembic", "upgrade", "head"])
            return result.returncode
        finally:
            # Release on the same connection that acquired it — session-level
            # advisory locks are tied to the connection, not the transaction.
            await conn.execute(sa.text("SELECT pg_advisory_unlock(:id)"), {"id": _LOCK_ID})


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_locked()))
