"""Local competitor price research endpoints."""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.services.competitor_prices.competitor_research_service import (
    CompetitorResearchService,
    FreeTierRateLimitError,
    ResearchConfigurationError,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekConfigurationError,
    DeepSeekError,
    DeepSeekQuotaError,
)
from app.services.competitor_prices.schemas import (
    CompetitorPriceResearchRequest,
    CompetitorPriceResearchResponse,
)

router = APIRouter(prefix="/competitor-prices", tags=["competitor-prices"])
logger = logging.getLogger("pulse.competitor_prices")


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
    except (ResearchConfigurationError, DeepSeekConfigurationError) as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeepSeekQuotaError as exc:
        _log_research_failure(started_at, payload, exc)
        raise HTTPException(
            status_code=429,
            detail=f"{exc} Try again after the DeepSeek project quota resets.",
        ) from exc
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
