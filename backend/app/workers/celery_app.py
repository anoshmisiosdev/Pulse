"""Celery app + beat schedule.

The worker boots with a nightly customer re-score placeholder and a real hourly
competitor-pricing monitor that executes due saved watches.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import select

from app.core.config import settings

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
    beat_schedule={
        "nightly-rescore": {
            "task": "app.workers.celery_app.nightly_rescore",
            "schedule": 24 * 60 * 60.0,  # once a day; refine to a cron later
        },
        "pricing-monitors": {
            "task": "app.workers.celery_app.run_pricing_monitors",
            "schedule": 10 * 60.0,
        },
    },
)


@celery.task
def ping() -> str:
    return "pong"


@celery.task
def nightly_rescore() -> dict:
    """Re-score every tenant's customers. Wired to persistence in a later phase."""
    logger.info("nightly_rescore tick (no-op until data persistence lands)")
    return {"status": "ok", "rescored": 0}


@celery.task
def run_pricing_monitors() -> dict:
    return asyncio.run(_run_pricing_monitors())


async def _run_pricing_monitors() -> dict:
    from app.core.database import SessionLocal
    from app.core.deps import CurrentUser
    from app.models.competitor_price import CompetitorPriceWatch
    from app.services.competitor_prices.competitor_research_service import CompetitorResearchService
    from app.services.competitor_prices.schemas import CompetitorPriceResearchRequest

    now = datetime.now(UTC)
    completed = 0
    async with SessionLocal() as db:
        watches = (
            await db.execute(
                select(CompetitorPriceWatch).where(
                    CompetitorPriceWatch.enabled.is_(True),
                    CompetitorPriceWatch.next_run_at <= now,
                )
            )
        ).scalars().all()
        for watch in watches:
            try:
                payload = CompetitorPriceResearchRequest.model_validate(
                    json.loads(watch.request_json)
                )
                await CompetitorResearchService(db).research(
                    payload,
                    CurrentUser(
                        user_id=watch.user_id,
                        email=None,
                        business_id=str(watch.business_id),
                    ),
                )
                watch.last_run_at = now
                watch.next_run_at = now + timedelta(hours=watch.interval_hours)
                completed += 1
            except Exception:
                logger.exception("Pricing monitor failed for business %s", watch.business_id)
                watch.next_run_at = now + timedelta(hours=watch.interval_hours)
        await db.commit()
    return {"status": "ok", "researched": completed}
