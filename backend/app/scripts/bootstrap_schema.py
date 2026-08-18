"""Bootstrap a brand-new database: create the full current schema in one shot
and tell Alembic it's already at head, instead of replaying migration history
against it.

`app/main.py`'s lifespan runs `create_all` (idempotent, never ALTERs) on every
app startup. The container/deploy entrypoints run `alembic upgrade head`
*before* the app ever starts (docker-compose's `api` service, render.yaml's
preDeployCommand), so on a fresh database neither ordering alone works:

- alembic-first: early migrations replay fine, but later ones ALTER tables
  (e.g. `20260714_0004` on `customers`) that only `create_all` ever creates —
  `UndefinedTableError`.
- create_all-first: `create_all` builds the *current* schema in one shot, so
  any later `CREATE TABLE` migration (e.g. `20260712_0003` on
  `business_knowledge`) then collides with a table that already exists —
  `DuplicateTableError`.

So: detect a fresh database (no `alembic_version` table yet), create the
extension `create_all` can't issue itself, run `create_all`, then `alembic
stamp head` so Alembic considers migration history already applied — exactly
what create_all just did in bulk. An existing database (has `alembic_version`)
is untouched here; the normal `alembic upgrade head` that runs right after
this script handles it as before.

    uv run python -m app.scripts.bootstrap_schema
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import sqlalchemy as sa


async def _is_fresh_database() -> bool:
    from app.core.database import engine

    async with engine.connect() as conn:
        exists = await conn.scalar(
            sa.text("SELECT to_regclass('public.alembic_version')")
        )
    return exists is None


async def _create_schema() -> None:
    from app import models  # noqa: F401 — register tables on metadata
    from app.core.database import Base, engine

    async with engine.begin() as conn:
        # business_knowledge (app/models/knowledge.py) has a VECTOR column —
        # create_all can't issue CREATE EXTENSION itself, and the Alembic
        # migration that normally creates it (20260712_0003) hasn't run yet.
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    if not await _is_fresh_database():
        print("DB already initialized (alembic_version exists) — nothing to bootstrap")
        return

    await _create_schema()
    print("DB schema created")

    subprocess.run(["uv", "run", "alembic", "stamp", "head"], check=True)
    print("Stamped alembic at head")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
