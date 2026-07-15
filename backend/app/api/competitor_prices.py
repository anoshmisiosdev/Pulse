"""Local competitor price research endpoints."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.models.competitor_price import CompetitorPriceResearchRun, CompetitorPriceWatch
from app.services.competitor_prices.competitor_research_service import (
    CompetitorResearchService,
    FreeTierRateLimitError,
    ResearchConfigurationError,
    _stable_business_uuid,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekConfigurationError,
    DeepSeekError,
    DeepSeekQuotaError,
)
from app.services.competitor_prices.perplexity_client import (
    PerplexityConfigurationError,
    PerplexityError,
    PerplexityQuotaError,
)
from app.services.competitor_prices.schemas import (
    CompetitorPriceResearchRequest,
    CompetitorPriceResearchResponse,
    PriceHistoryItemOut,
    PriceWatchIn,
    PriceWatchOut,
)

router = APIRouter(prefix="/competitor-prices", tags=["competitor-prices"])
logger = logging.getLogger("pulse.competitor_prices")


@router.get("/latest", response_model=CompetitorPriceResearchResponse | None)
async def latest_competitor_prices(
    target_offer: str | None = Query(default=None, alias="targetOffer"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CompetitorPriceResearchResponse | None:
    stmt = select(CompetitorPriceResearchRun).where(
        CompetitorPriceResearchRun.business_id == _stable_business_uuid(current_user.business_id)
    )
    if target_offer:
        stmt = stmt.where(CompetitorPriceResearchRun.target_offer.ilike(target_offer.strip()))
    result = await db.execute(stmt.order_by(CompetitorPriceResearchRun.created_at.desc()).limit(1))
    run = result.scalars().first()
    return CompetitorPriceResearchResponse.model_validate_json(run.response_json) if run else None


@router.get("/history", response_model=list[PriceHistoryItemOut])
async def competitor_price_history(
    limit: int = Query(default=12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[PriceHistoryItemOut]:
    rows = (
        (
            await db.execute(
                select(CompetitorPriceResearchRun)
                .where(
                    CompetitorPriceResearchRun.business_id
                    == _stable_business_uuid(current_user.business_id)
                )
                .order_by(CompetitorPriceResearchRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    history: list[PriceHistoryItemOut] = []
    previous_by_offer: dict[str, float | None] = {}
    for run in reversed(rows):
        response = CompetitorPriceResearchResponse.model_validate_json(run.response_json)
        median = response.market_summary.price_median
        previous = previous_by_offer.get(run.target_offer.lower())
        change = (
            round((median - previous) / previous * 100, 1)
            if median is not None and previous
            else None
        )
        history.append(
            PriceHistoryItemOut(
                id=str(run.id),
                targetOffer=run.target_offer,
                businessCategory=run.business_category,
                generatedAt=run.created_at,
                priceMedian=median,
                sampleSize=response.market_summary.sample_size,
                confidence=response.market_summary.confidence,
                changePercent=change,
            )
        )
        previous_by_offer[run.target_offer.lower()] = median
    return list(reversed(history))


@router.get("/watch", response_model=PriceWatchOut | None)
async def get_price_watch(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> PriceWatchOut | None:
    watch = (
        (
            await db.execute(
                select(CompetitorPriceWatch).where(
                    CompetitorPriceWatch.business_id
                    == _stable_business_uuid(current_user.business_id)
                )
            )
        )
        .scalars()
        .first()
    )
    return _watch_out(watch) if watch else None


@router.put("/watch", response_model=PriceWatchOut)
async def upsert_price_watch(
    payload: PriceWatchIn,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> PriceWatchOut:
    business_id = _stable_business_uuid(current_user.business_id)
    watch = (
        (
            await db.execute(
                select(CompetitorPriceWatch).where(CompetitorPriceWatch.business_id == business_id)
            )
        )
        .scalars()
        .first()
    )
    next_run = datetime.now(UTC) + timedelta(hours=payload.interval_hours)
    if watch is None:
        watch = CompetitorPriceWatch(
            business_id=business_id,
            user_id=current_user.user_id,
            request_json=payload.request.model_dump_json(by_alias=True),
            interval_hours=payload.interval_hours,
            enabled=payload.enabled,
            next_run_at=next_run,
        )
        db.add(watch)
    else:
        watch.user_id = current_user.user_id
        watch.request_json = payload.request.model_dump_json(by_alias=True)
        watch.interval_hours = payload.interval_hours
        watch.enabled = payload.enabled
        watch.next_run_at = next_run
    await db.flush()
    return _watch_out(watch)


def _watch_out(watch: CompetitorPriceWatch) -> PriceWatchOut:
    return PriceWatchOut(
        enabled=watch.enabled,
        intervalHours=watch.interval_hours,
        request=json.loads(watch.request_json),
        lastRunAt=watch.last_run_at,
        nextRunAt=watch.next_run_at,
    )


@router.post("/research", response_model=CompetitorPriceResearchResponse)
async def research_competitor_prices(
    payload: CompetitorPriceResearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CompetitorPriceResearchResponse:
    started_at = perf_counter()
    service = CompetitorResearchService(db)
    try:
        response = await service.research(payload, current_user)
        duration_ms = _elapsed_ms(started_at)
        response.metadata.duration_ms = duration_ms
        logger.info(
            "Competitor price research completed in %.2fs cached=%s competitors=%s prices=%s "
            "models=%s offer=%r location=%r",
            duration_ms / 1000,
            response.metadata.cached,
            len(response.competitors),
            sum(len(competitor.prices) for competitor in response.competitors),
            ",".join(response.metadata.models_used),
            payload.target_offer,
            payload.location.label,
        )
        return response
    except FreeTierRateLimitError as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (
        ResearchConfigurationError,
        DeepSeekConfigurationError,
        PerplexityConfigurationError,
    ) as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeepSeekQuotaError as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(
            status_code=429,
            detail=f"{exc} Try again after the DeepSeek project quota resets.",
        ) from exc
    except PerplexityQuotaError as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(
            status_code=429,
            detail=f"{exc} Try again after the Perplexity project quota resets.",
        ) from exc
    except PerplexityError as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DeepSeekError as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


def _log_research_failure(
    started_at: float,
    payload: CompetitorPriceResearchRequest,
    exc: Exception,
) -> None:
    duration_ms = _elapsed_ms(started_at)
    logger.warning(
        "Competitor price research failed in %.2fs error=%s offer=%r location=%r",
        duration_ms / 1000,
        exc.__class__.__name__,
        payload.target_offer,
        payload.location.label,
    )
