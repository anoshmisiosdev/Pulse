"""Celery app + beat schedule.

Task bodies open their own DB session (SessionLocal) since a Celery worker
process doesn't share the FastAPI app's per-request session, then bridge into
the async services via ``asyncio.run`` — Celery tasks themselves are sync.
"""

from __future__ import annotations

import asyncio
import logging

from celery import Celery
from sqlalchemy import select

from app.core.config import settings
from app.core.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("pulse.workers")

celery = Celery(
    "pulse",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_hijack_root_logger=False,  # keep our JSON/plain formatter
    beat_schedule={
        "nightly-rescore": {
            "task": "app.workers.celery_app.nightly_rescore",
            "schedule": 24 * 60 * 60.0,  # once a day; refine to a cron later
        },
        "dispatch-automations": {
            "task": "app.workers.celery_app.dispatch_automations_tick",
            "schedule": settings.automation_dispatch_interval_seconds,
        },
    },
)


@celery.task
def ping() -> str:
    return "pong"


async def _for_every_business(fn) -> dict:
    """Run an async per-business callback against every tenant, in its own
    session per business so one tenant's error can't roll back another's."""
    from app.core.database import SessionLocal
    from app.models import Business

    results: dict[str, object] = {}
    async with SessionLocal() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()

    for bid in business_ids:
        async with SessionLocal() as db:
            try:
                results[str(bid)] = await fn(db, str(bid))
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("task failed for business %s", bid)
                results[str(bid)] = "error"
    return results


@celery.task
def nightly_rescore() -> dict:
    """Re-score every tenant's customers, updating denormalized bands/scores
    and appending to the RiskScore log on any band change."""
    from app.services.ingest import refresh_scores

    results = asyncio.run(_for_every_business(lambda db, bid: refresh_scores(db, bid)))
    logger.info("nightly_rescore complete: %d businesses", len(results))
    return {"status": "ok", "businesses": len(results)}


@celery.task
def dispatch_automations_tick() -> dict:
    """Evaluate every business's enabled AutomationRules and queue/send
    outreach. Runs every ``automation_dispatch_interval_seconds`` — frequent
    enough to feel automated, infrequent enough that quiet-hours skips
    (app/services/compliance.py) get re-evaluated soon after they lift."""
    from app.services.automations import dispatch_automations

    async def _dispatch(db, bid: str) -> dict:
        summary = await dispatch_automations(db, bid)
        return {"sends_created": summary.sends_created, "skipped": summary.skipped}

    results = asyncio.run(_for_every_business(_dispatch))
    total_sends = sum(r["sends_created"] for r in results.values() if isinstance(r, dict))
    logger.info("dispatch_automations_tick complete: %d sends queued/sent", total_sends)
    return {"status": "ok", "businesses": len(results), "sends_created": total_sends}
