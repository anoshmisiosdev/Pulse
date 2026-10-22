"""Celery app + beat schedule.

Task bodies open their own DB session (SessionLocal) since a Celery worker
process doesn't share the FastAPI app's per-request session, then bridge into
the async services via ``asyncio.run`` — Celery tasks themselves are sync.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

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
        "pricing-monitors": {
            "task": "app.workers.celery_app.run_pricing_monitors",
            "schedule": 10 * 60.0,
        },
        "dispatch-automations": {
            "task": "app.workers.celery_app.dispatch_automations_tick",
            "schedule": settings.automation_dispatch_interval_seconds,
        },
        "detect-recoveries": {
            "task": "app.workers.celery_app.detect_recoveries_tick",
            # Hourly. Recovery is measured in days-to-weeks, so this only needs to
            # be frequent enough that the dashboard isn't visibly stale — and it
            # re-reads the same rows every run, so there's no reason to hammer it.
            "schedule": 60 * 60.0,
        },
        "sync-payment-integrations": {
            "task": "app.workers.celery_app.sync_payment_integrations_tick",
            "schedule": settings.payment_sync_interval_seconds,
        },
        "queue-review-requests": {
            "task": "app.workers.celery_app.queue_review_requests_tick",
            # Hourly. It only drafts pending requests, and the delay setting is
            # in days, so anything more frequent would be wasted work.
            "schedule": 60 * 60.0,
        },
        "deliver-webhooks": {
            "task": "app.workers.celery_app.deliver_webhooks_tick",
            # Every minute. Due deliveries are cheap to find (indexed on
            # status + next_attempt_at) and backoff spaces the retries.
            "schedule": 60.0,
        },
        "weekly-owner-digest": {
            "task": "app.workers.celery_app.send_weekly_digests",
            # Weekly. The beat interval is the cadence, not the content window:
            # the digest always reports the last 7 days, so a missed or
            # restarted beat shifts when it arrives without changing what it
            # says or double-counting anything.
            "schedule": settings.digest_interval_seconds,
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
    """Re-score every tenant's customers and persist band changes."""
    from app.services.ingest import refresh_scores

    results = asyncio.run(_for_every_business(lambda db, bid: refresh_scores(db, bid)))
    logger.info("nightly_rescore complete: %d businesses", len(results))
    return {"status": "ok", "businesses": len(results)}


@celery.task
def run_pricing_monitors() -> dict:
    return asyncio.run(_run_pricing_monitors())


async def _run_pricing_monitors() -> dict:
    from app.core.database import SessionLocal
    from app.core.deps import CurrentUser
    from app.models.competitor_price import CompetitorPriceWatch
    from app.services.competitor_prices.competitor_research_service import CompetitorResearchService
    from app.services.competitor_prices.schemas import CompetitorPriceResearchRequest

    if not settings.pricing_monitoring_enabled:
        return {"status": "disabled", "researched": 0}

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


@celery.task
def detect_recoveries_tick() -> dict:
    """Close the loop: credit customers who came back after we contacted them.

    Idempotent by design (see app/services/attribution.py) — a customer already
    holding a RecoveryAttribution row is excluded from matching, so re-running
    can't double-count revenue.
    """
    from app.services.attribution import detect_recoveries

    async def _detect(db, bid: str) -> dict:
        summary = await detect_recoveries(db, bid)
        return {
            "recoveries_found": summary.recoveries_found,
            "revenue_recovered": summary.revenue_recovered,
        }

    results = asyncio.run(_for_every_business(_detect))
    found = sum(r["recoveries_found"] for r in results.values() if isinstance(r, dict))
    revenue = sum(r["revenue_recovered"] for r in results.values() if isinstance(r, dict))
    logger.info(
        "detect_recoveries_tick complete: %d recoveries, %.2f recovered", found, revenue
    )
    return {
        "status": "ok",
        "businesses": len(results),
        "recoveries_found": found,
        "revenue_recovered": round(revenue, 2),
    }


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


@celery.task
def sync_payment_integrations_tick() -> dict:
    """Incrementally refresh every connected Stripe/Square account."""
    from app.models import IntegrationConnection
    from app.services.payment_sync import sync_connection

    async def _sync(db, bid: str) -> dict:
        connections = (
            await db.execute(
                select(IntegrationConnection).where(
                    IntegrationConnection.business_id == uuid.UUID(bid),
                    IntegrationConnection.source.in_(("stripe", "square")),
                    IntegrationConnection.access_token_enc.is_not(None),
                )
            )
        ).scalars().all()
        synced = 0
        errors = 0
        for connection in connections:
            try:
                await sync_connection(db, connection)
                synced += 1
            except Exception:
                errors += 1
                logger.exception("Payment sync failed for connection %s", connection.id)
        return {"synced": synced, "errors": errors}

    results = asyncio.run(_for_every_business(_sync))
    synced = sum(row["synced"] for row in results.values() if isinstance(row, dict))
    errors = sum(row["errors"] for row in results.values() if isinstance(row, dict))
    logger.info("sync_payment_integrations complete: %d synced, %d errors", synced, errors)
    return {"status": "ok", "synced": synced, "errors": errors}


@celery.task
def send_weekly_digests() -> dict:
    """Email every owner their weekly recovery digest.

    The "3 customers recovered, ~$640 saved" email from the Definition of Done.
    Businesses with nothing to report are skipped rather than sent an empty
    summary — see app/services/digest.py for why that's the product decision.
    """
    from app.services.digest import send_digest_for_business

    if not settings.digest_enabled:
        logger.info("weekly digest disabled by configuration")
        return {"status": "disabled"}

    async def _digest(db, bid: str) -> dict:
        return {"outcome": await send_digest_for_business(db, business_id=bid)}

    results = asyncio.run(_for_every_business(_digest))
    outcomes: dict[str, int] = {}
    for result in results.values():
        key = result.get("outcome", "error") if isinstance(result, dict) else "error"
        outcomes[key] = outcomes.get(key, 0) + 1
    logger.info("send_weekly_digests complete: %s", outcomes)
    return {"status": "ok", "businesses": len(results), "outcomes": outcomes}


@celery.task
def deliver_webhooks_tick() -> dict:
    """Deliver every due outbound webhook, across all tenants."""
    from app.core.database import SessionLocal
    from app.services.outbound_webhooks import deliver_pending

    async def _run() -> dict:
        async with SessionLocal() as db:
            counts = await deliver_pending(db)
            await db.commit()
            return counts

    counts = asyncio.run(_run())
    if any(counts.values()):
        logger.info("deliver_webhooks_tick: %s", counts)
    return {"status": "ok", **counts}


@celery.task
def queue_review_requests_tick() -> dict:
    """Draft review requests for recently recovered customers (approve-to-send)."""
    from app.campaigns.reviews import queue_review_requests

    async def _queue(db, bid: str) -> dict:
        summary = await queue_review_requests(db, business_id=bid)
        return {"queued": summary.queued}

    results = asyncio.run(_for_every_business(_queue))
    total = sum(r.get("queued", 0) for r in results.values() if isinstance(r, dict))
    if total:
        logger.info("queue_review_requests_tick: %d drafted", total)
    return {"status": "ok", "queued": total}
