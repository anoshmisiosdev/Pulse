"""Celery app + beat schedule.

Minimal but real: the worker boots and the nightly re-score is scheduled. Task
bodies fill in with the scoring/sync phases; today they're safe no-ops so the
worker deploys cleanly alongside the API.
"""

from __future__ import annotations

import logging

from celery import Celery

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
