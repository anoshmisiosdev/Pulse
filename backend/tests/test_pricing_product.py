"""Saved pricing state, history, monitoring, and cache-contract tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.competitor_prices import (
    competitor_price_history,
    get_price_watch,
    latest_competitor_prices,
    upsert_price_watch,
)
from app.core.database import Base
from app.core.deps import CurrentUser
from app.models.competitor_price import CompetitorPriceResearchRun
from app.services.competitor_prices.competitor_research_service import CACHE_TTL
from app.services.competitor_prices.schemas import (
    CompetitorPriceResearchResponse,
    GroundingUsedOut,
    MarketSummaryOut,
    MetadataOut,
    PriceWatchIn,
    QueryOut,
)

BUSINESS_ID = uuid.uuid4()
USER = CurrentUser(
    user_id="pricing-user",
    email="pricing@example.com",
    business_id=str(BUSINESS_ID),
    business_name="Test Cafe",
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _response(median: float = 5.25) -> CompetitorPriceResearchResponse:
    return CompetitorPriceResearchResponse(
        query=QueryOut(
            businessCategory="Coffee Shop",
            targetOffer="Cappuccino",
            locationLabel="Fremont, CA",
            radiusMiles=5,
        ),
        competitors=[],
        marketSummary=MarketSummaryOut(
            sampleSize=2,
            priceLow=5,
            priceMedian=median,
            priceHigh=5.5,
            priceAverage=median,
            priceIqr=0.5,
            recommendedPositioning="Near the market median.",
            confidence=0.7,
        ),
        warnings=[],
        metadata=MetadataOut(
            modelsUsed=[],
            groundingUsed=GroundingUsedOut(
                googleSearch=False,
                googleMaps=False,
                urlContext=False,
            ),
            generatedAt=datetime.now(UTC),
            cached=False,
        ),
    )


async def test_latest_history_and_watch_round_trip(db):
    response = _response()
    db.add(
        CompetitorPriceResearchRun(
            business_id=BUSINESS_ID,
            user_id=USER.user_id,
            cache_key="test",
            business_category="Coffee Shop",
            target_offer="Cappuccino",
            location_json="{}",
            radius_miles=5,
            models_used_json="[]",
            warnings_json="[]",
            response_json=response.model_dump_json(by_alias=True),
            expires_at=datetime.now(UTC) + CACHE_TTL,
        )
    )
    await db.flush()

    latest = await latest_competitor_prices(None, db, USER)
    history = await competitor_price_history(12, db, USER)
    watch = await upsert_price_watch(
        PriceWatchIn(
            enabled=True,
            intervalHours=2,
            request={
                "businessCategory": "Coffee Shop",
                "targetOffer": "Cappuccino",
                "location": {"city": "Fremont", "state": "CA"},
            },
        ),
        db,
        USER,
    )
    saved_watch = await get_price_watch(db, USER)

    assert latest and latest.market_summary.price_median == 5.25
    assert history[0].target_offer == "Cappuccino"
    assert history[0].sample_size == 2
    assert watch.enabled and watch.interval_hours == 2
    assert saved_watch and saved_watch.request.target_offer == "Cappuccino"


def test_pricing_cache_contract_is_two_hours():
    assert CACHE_TTL == timedelta(hours=2)
