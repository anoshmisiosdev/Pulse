"""Automation rule engine: matches customers by band, respects compliance
flags and cooldown. Uses email (not sms) throughout to stay deterministic —
sms dispatch also depends on quiet-hours/wall-clock time, covered separately
and non-flakily in test_compliance.py's pure is_quiet_hours tests."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models import AutomationRule, CampaignSend, Customer
from app.scripts.demo_data import generate_sync
from app.services import automations, ingest

NOW = datetime(2026, 6, 26)
BUSINESS_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _no_rag(monkeypatch):
    # search_knowledge hits Bedrock (real network call) and pgvector's <=>
    # operator (not supported by the in-memory SQLite these tests run
    # against) — stub it out, same reasoning as not configuring a real LLM
    # key for the fallback-copy tests in test_activity.py.
    async def _empty(*args, **kwargs):
        return []

    monkeypatch.setattr(automations, "search_knowledge", _empty)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _seed(db) -> None:
    await ingest.ensure_business(db, BUSINESS_ID, "Test Cafe", "fitness")
    sync = generate_sync(n=60, seed=7, now=NOW)
    await ingest.persist_sync(db, BUSINESS_ID, "csv", sync)
    await db.commit()


async def _make_rule(db, **overrides) -> AutomationRule:
    defaults = dict(
        business_id=uuid.UUID(BUSINESS_ID),
        name="Win back high-risk",
        trigger_band="high",
        channel="email",
        mode="approve",
        enabled=True,
        cooldown_days=14,
    )
    defaults.update(overrides)
    rule = AutomationRule(**defaults)
    db.add(rule)
    await db.flush()
    return rule


async def test_dispatch_queues_pending_sends_for_matching_band(db):
    await _seed(db)
    await _make_rule(db)

    summary = await automations.dispatch_automations(db, BUSINESS_ID, now=NOW)
    await db.commit()

    assert summary.rules_evaluated == 1
    assert summary.sends_created > 0

    sends = (await db.execute(select(CampaignSend))).scalars().all()
    assert len(sends) == summary.sends_created
    assert all(s.status == "pending" for s in sends)
    assert all(s.channel == "email" for s in sends)
    assert all(s.body for s in sends)


async def test_dispatch_skips_do_not_contact(db):
    await _seed(db)
    await _make_rule(db)

    for c in (await db.execute(select(Customer))).scalars().all():
        c.do_not_contact = True
    await db.flush()

    summary = await automations.dispatch_automations(db, BUSINESS_ID, now=NOW)
    await db.commit()

    assert summary.sends_created == 0
    assert summary.skipped.get("do_not_contact", 0) > 0


async def test_dispatch_respects_cooldown_on_repeat_run(db):
    await _seed(db)
    await _make_rule(db)

    first = await automations.dispatch_automations(db, BUSINESS_ID, now=NOW)
    await db.commit()
    assert first.sends_created > 0

    second = await automations.dispatch_automations(db, BUSINESS_ID, now=NOW)
    await db.commit()

    assert second.sends_created == 0
    assert second.skipped.get("cooldown", 0) == first.sends_created


async def test_dispatch_ignores_disabled_rules(db):
    await _seed(db)
    await _make_rule(db, enabled=False)

    summary = await automations.dispatch_automations(db, BUSINESS_ID, now=NOW)
    await db.commit()

    assert summary.rules_evaluated == 0
    assert summary.sends_created == 0
