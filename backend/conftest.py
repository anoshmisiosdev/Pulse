"""Root conftest — its presence puts the backend dir on sys.path for `import app`."""

import os
from datetime import datetime

import pytest

# In-memory SQLite by default. Point TEST_DATABASE_URL at a throwaway Postgres
# (postgresql+asyncpg://...) to catch dialect differences (JSONB, ON CONFLICT,
# case sensitivity) that SQLite hides.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://")

# "Now" for generating test data, anchored to the real clock (midnight, so a
# run doesn't straddle a day boundary). Scoring inside the app compares against
# datetime.now() — a fixed date would drift out of the scoring windows as real
# time advances past it.
NOW = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
async def db():
    """A session against a fresh schema; drops tables afterwards on Postgres."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()
    if not TEST_DATABASE_URL.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
