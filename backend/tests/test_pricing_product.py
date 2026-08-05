"""Saved pricing state, history, monitoring, and cache-contract tests."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.competitor_prices import (
    competitor_price_history,
    competitor_price_portfolio,
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


async def test_latest_history_and_watch_round_trip(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.pricing_monitoring_enabled", True)
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
            # Postgres JSONB returns a mapping, not a serialized JSON string.
            response_json=response.model_dump(by_alias=True, mode="json"),
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


async def test_monitoring_is_unavailable_without_a_scheduler(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.pricing_monitoring_enabled", False)
    with pytest.raises(HTTPException) as exc_info:
        await get_price_watch(db, USER)
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["errorCode"] == "PRICING_MONITORING_NOT_AVAILABLE"


async def test_portfolio_returns_only_latest_report_per_offer(db):
    now = datetime.now(UTC)
    for offer, median, created_at in [
        ("Cappuccino", 4.75, now - timedelta(minutes=2)),
        ("Cold Brew", 5.5, now - timedelta(minutes=1)),
        ("cappuccino", 5.25, now),
    ]:
        response = _response(median)
        response.query.target_offer = offer
        db.add(
            CompetitorPriceResearchRun(
                business_id=BUSINESS_ID,
                user_id=USER.user_id,
                cache_key=f"test-{offer}-{median}",
                business_category="Coffee Shop",
                target_offer=offer,
                location_json="{}",
                radius_miles=5,
                models_used_json="[]",
                warnings_json="[]",
                response_json=response.model_dump_json(by_alias=True),
                expires_at=now + CACHE_TTL,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    await db.flush()

    portfolio = await competitor_price_portfolio(24, db, USER)

    assert [report.query.target_offer for report in portfolio] == ["cappuccino", "Cold Brew"]
    assert portfolio[0].market_summary.price_median == 5.25


def test_pricing_cache_contract_is_two_hours():
    assert CACHE_TTL == timedelta(hours=2)


@pytest.mark.skipif(
    not os.environ.get("PRICING_TEST_POSTGRES_URL"),
    reason="Set PRICING_TEST_POSTGRES_URL to run the real JSONB round trip.",
)
async def test_postgres_jsonb_response_round_trip_returns_a_mapping():
    engine = create_async_engine(os.environ["PRICING_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: CompetitorPriceResearchRun.__table__.create(
                sync_connection, checkfirst=True
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    response = _response()
    async with session_factory() as session:
        session.add(
            CompetitorPriceResearchRun(
                business_id=BUSINESS_ID,
                user_id=USER.user_id,
                cache_key="postgres-jsonb",
                business_category="Coffee Shop",
                target_offer="Cappuccino",
                location_json={"city": "Fremont", "state": "CA"},
                radius_miles=5,
                models_used_json=[],
                warnings_json=[],
                response_json=response.model_dump(by_alias=True, mode="json"),
                expires_at=datetime.now(UTC) + CACHE_TTL,
            )
        )
        await session.commit()
        saved = await latest_competitor_prices(None, session, USER)
        raw = await session.scalar(
            select(CompetitorPriceResearchRun.response_json).where(
                CompetitorPriceResearchRun.cache_key == "postgres-jsonb"
            )
        )

    await engine.dispose()
    assert isinstance(raw, dict)
    assert saved and saved.market_summary.price_median == 5.25
