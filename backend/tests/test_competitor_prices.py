"""Competitor price research guardrails."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser
from app.main import app, fastapi_app
from app.services.competitor_prices.competitor_research_service import (
    CompetitorResearchService,
    ResearchConfigurationError,
    _cached_response_missing_configured_provider,
    _CandidatePrice,
    _dedupe_and_rank_sources,
    _finalize_candidates,
    _has_corroborating_pair,
    _is_self_competitor,
    _representatives_for_channel,
    build_cache_key,
)
from app.services.competitor_prices.confidence_scoring import (
    ConfidenceInput,
    build_market_summary,
    canonicalize_offer_label,
    evidence_contains_price,
    evidence_supports_price,
    score_price_confidence,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekClient,
    DeepSeekError,
    DeepSeekJSONResult,
    extract_chat_content,
)
from app.services.competitor_prices.geocoding import (
    Coordinates,
    GeocodingConfigurationError,
    GoogleGeocodingClient,
    distance_miles,
)
from app.services.competitor_prices.perplexity_client import PerplexitySearchResult
from app.services.competitor_prices.pricing_extraction_service import PricingExtractionService
from app.services.competitor_prices.schemas import (
    CompetitorDiscoveryResult,
    CompetitorPriceResearchRequest,
    CompetitorPriceResearchResponse,
    DiscoveredCompetitor,
    DiscoveredSource,
    ExtractedPrice,
    GroundingUsedOut,
    MarketSummaryOut,
    MetadataOut,
    PriceExtractionResult,
    QueryOut,
    ResearchCallMetadata,
)


def _price(**overrides) -> ExtractedPrice:
    base = {
        "offerName": "Women's Haircut",
        "normalizedOfferName": "women's haircut",
        "priceMin": 65,
        "priceMax": 65,
        "currency": "USD",
        "priceType": "fixed",
        "sourceUrl": "https://example.com/services",
        "sourceTitle": "Services",
        "evidenceText": "Women's haircut $65",
        "observedAt": date.today().isoformat(),
        "matchQuality": "exact",
    }
    base.update(overrides)
    return ExtractedPrice.model_validate(base)


def test_fixed_price_schema_validation():
    price = _price(evidenceText="Women's haircut $65", priceMin=65, priceMax=65)
    assert price.price_min == 65
    assert price.price_max == 65
    assert price.price_type == "fixed"
    assert evidence_supports_price(price)


def test_range_price_schema_validation():
    price = _price(
        evidenceText="Haircuts from $65-$85",
        priceMin=65,
        priceMax=85,
        priceType="range",
    )
    assert price.price_min == 65
    assert price.price_max == 85
    assert price.price_type == "range"
    assert evidence_supports_price(price)


def test_rejects_unsupported_price():
    price = _price(evidenceText="Women's haircut available Tuesday", priceMin=65, priceMax=65)
    assert not evidence_supports_price(price)


def test_rejects_google_yelp_price_tier():
    price = _price(evidenceText="Price: $$", priceMin=2, priceMax=2)
    assert not evidence_supports_price(price)


def test_confidence_scoring_official_exact_source_is_high():
    result = score_price_confidence(
        ConfidenceInput(
            price=_price(),
            target_offer="women's haircut",
            source_type="official_site",
            source_location_matches=True,
        )
    )
    assert result.score >= 0.9
    assert "Exact service match" in result.reasons


def test_market_summary_math():
    prices = [
        (_price(priceMin=50, priceMax=50, evidenceText="Women's haircut $50"), 0.9),
        (_price(priceMin=70, priceMax=70, evidenceText="Women's haircut $70"), 0.8),
        (_price(priceMin=90, priceMax=90, evidenceText="Women's haircut $90"), 0.7),
    ]
    summary = build_market_summary(prices, current_price=75)
    assert summary.sample_size == 3
    assert summary.price_low == 50
    assert summary.price_median == 70
    assert summary.price_high == 90
    assert "above" in summary.recommended_positioning.lower()


def test_cache_key_normalizes_request():
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": " Hair Salon ",
            "targetOffer": "Women's Haircut",
            "location": {"city": "Austin", "state": "TX"},
            "radiusMiles": 5,
        }
    )
    cache_key = build_cache_key(payload)
    assert cache_key.startswith("v4|")
    assert "|hair salon|women's haircut|" in cache_key


def test_offer_canonicalization_fixes_capuccino_typo():
    assert canonicalize_offer_label("Capuccino") == "Cappuccino"

    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Capuccino",
            "location": {"city": "Fremont", "state": "CA"},
            "radiusMiles": 10,
        }
    )
    assert "|cappuccino|" in build_cache_key(payload)


def test_cache_guard_skips_pre_perplexity_cached_response(monkeypatch):
    monkeypatch.setattr(settings, "enable_perplexity_search", True)
    monkeypatch.setattr(settings, "perplexity_api_key", "test-key")
    response = CompetitorPriceResearchResponse(
        query=QueryOut(
            businessCategory="Coffee Shop",
            targetOffer="Cappuccino",
            locationLabel="Fremont, CA",
            radiusMiles=10,
        ),
        competitors=[],
        marketSummary=MarketSummaryOut(
            sampleSize=0,
            priceLow=None,
            priceMedian=None,
            priceHigh=None,
            priceAverage=None,
            priceIqr=None,
            currency="USD",
            recommendedPositioning="No public competitor prices were found.",
            confidence=0,
        ),
        warnings=[],
        metadata=MetadataOut(
            modelsUsed=["deepseek-v4-flash"],
            groundingUsed=GroundingUsedOut(
                googleSearch=True,
                googleMaps=False,
                urlContext=False,
                perplexitySearch=False,
                deepseekExtraction=False,
            ),
            generatedAt=datetime.now(UTC),
            cached=False,
        ),
    )

    assert _cached_response_missing_configured_provider(response)


def test_source_ranking_prefers_first_party_source():
    ranked = _dedupe_and_rank_sources(
        [
            DiscoveredSource(
                url="https://example.com",
                title="Official home",
                snippet="View our menu.",
                sourceType="official_site",
                relevance=0.8,
            ),
            DiscoveredSource(
                url="https://maps.example.com/menu",
                title="Menu",
                snippet="Cappuccino. $6.00. 12oz hot.",
                sourceType="google_maps",
                relevance=0.1,
            ),
        ],
        target_offer="Capuccino",
    )

    assert ranked[0].url == "https://example.com/"


async def test_competitor_discovery_uses_perplexity_evidence_and_deepseek(monkeypatch):
    monkeypatch.setattr(settings, "enable_perplexity_search", True)

    class FakePerplexity:
        async def search(self, _query, *, max_results):
            assert max_results == settings.perplexity_max_results
            return [
                PerplexitySearchResult(
                    title="Hops & Beans Cafe",
                    url="https://hops.example/menu",
                    snippet="Hops & Beans Cafe, 4000 Bay St, Fremont, serves cappuccino.",
                )
            ]

    class FakeDeepSeek:
        async def generate_json(self, **_kwargs):
            return DeepSeekJSONResult(
                data=CompetitorDiscoveryResult(
                    competitors=[
                        DiscoveredCompetitor(
                            name="Hops & Beans Cafe",
                            address="4000 Bay St, Fremont, CA",
                            sourceUrls=["https://hops.example/menu"],
                        ),
                        DiscoveredCompetitor(
                            name="Invented Cafe",
                            sourceUrls=["https://invented.example"],
                        ),
                    ]
                ),
                model="deepseek-v4-flash",
            )

    service = CompetitorResearchService(
        db=None,
        deepseek_client=FakeDeepSeek(),  # type: ignore[arg-type]
        perplexity_client=FakePerplexity(),  # type: ignore[arg-type]
    )
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Cappuccino",
            "location": {"city": "Fremont", "state": "CA"},
        }
    )
    metadata = ResearchCallMetadata()
    result = await service.discover_competitors(payload, [], metadata)
    assert [competitor.name for competitor in result.competitors] == ["Hops & Beans Cafe"]
    assert metadata.perplexity_search_used
    assert metadata.deepseek_research_used
    assert metadata.models_used == {"perplexity-search", "deepseek-v4-flash"}


async def test_competitor_discovery_refuses_ungrounded_fallback(monkeypatch):
    monkeypatch.setattr(settings, "enable_perplexity_search", False)
    service = CompetitorResearchService(db=None, deepseek_client=object())  # type: ignore[arg-type]
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Cappuccino",
            "location": {"city": "Fremont", "state": "CA"},
        }
    )
    with pytest.raises(ResearchConfigurationError):
        await service.discover_competitors(payload, [], ResearchCallMetadata())


async def test_perplexity_source_discovery_returns_grounded_sources(monkeypatch):
    monkeypatch.setattr(settings, "enable_perplexity_search", True)
    monkeypatch.setattr(settings, "perplexity_max_queries_per_competitor", 1)
    monkeypatch.setattr(settings, "perplexity_max_results", 3)

    class FakePerplexity:
        async def search(self, query, *, max_results):
            assert "Cappuccino" in query
            assert max_results == 3
            return [
                PerplexitySearchResult(
                    title="Devout Coffee Menu",
                    url="https://devout-coffee-niles.square.site/s/order",
                    snippet="Cappuccino. $6.00. 12oz hot.",
                )
            ]

    service = CompetitorResearchService(
        db=None,
        deepseek_client=object(),  # type: ignore[arg-type]
        perplexity_client=FakePerplexity(),  # type: ignore[arg-type]
    )
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Capuccino",
            "location": {"city": "Fremont", "state": "CA"},
        }
    )
    metadata = ResearchCallMetadata()
    sources = await service.discover_sources(
        DiscoveredCompetitor(
            name="Devout Coffee",
            address="37323 Niles Blvd, Fremont, CA",
            relevanceReason="Coffee shop",
        ),
        payload,
        warnings=[],
        metadata=metadata,
    )

    assert sources[0].source_type == "booking_page"
    assert "Cappuccino" in (sources[0].snippet or "")
    assert metadata.perplexity_search_used
    assert "perplexity-search" in metadata.models_used


async def test_extraction_uses_grounded_snippet_before_deepseek():
    class FakeDeepSeek:
        async def generate_json(self, **_kwargs):
            raise AssertionError("DeepSeek should not be called for an exact price snippet")

    service = PricingExtractionService(FakeDeepSeek())  # type: ignore[arg-type]
    result = await service.extract_prices(
        competitor=DiscoveredCompetitor(
            name="Devout Coffee",
            address="37323 Niles Blvd, Fremont, CA 94536, USA",
            relevanceReason="Coffee shop",
        ),
        source=DiscoveredSource(
            url="https://example.com/devout-menu",
            title="Devout Coffee - Fremont, CA",
            snippet="Cappuccino. $6.00. 12oz hot.",
            sourceType="google_maps",
        ),
        target_offer="Capuccino",
    )

    assert len(result.data.prices) == 1
    price = result.data.prices[0]
    assert price.offer_name == "Cappuccino"
    assert price.price_min == 6
    assert price.price_max == 6
    assert price.evidence_text == "Cappuccino. $6.00. 12oz hot"


def test_deepseek_openai_response_content_parser():
    content = extract_chat_content(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"prices":[]}',
                    }
                }
            ]
        }
    )

    assert content == '{"prices":[]}'


def test_tokenmart_configuration_is_preferred(monkeypatch):
    monkeypatch.setattr(settings, "tokenmart_api_key", "tm-test-key")
    monkeypatch.setattr(settings, "tokenmart_base_url", "https://model.service-inference.ai/v1")
    monkeypatch.setattr(settings, "tokenmart_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "deepseek_api_key", "legacy-key")
    client = DeepSeekClient()
    assert client.api_key == "tm-test-key"
    assert client.base_url == "https://model.service-inference.ai/v1"
    assert client.model == "deepseek-v4-flash"
    assert client._chat_url() == "https://model.service-inference.ai/v1/chat/completions"


async def test_extraction_uses_deepseek(monkeypatch):
    monkeypatch.setattr(settings, "enable_deepseek_extraction", True)

    class FakeDeepSeek:
        async def generate_json(self, **_kwargs):
            return DeepSeekJSONResult(
                data=PriceExtractionResult(
                    prices=[
                        _price(
                            offerName="Cappuccino",
                            normalizedOfferName="cappuccino",
                            priceMin=6,
                            priceMax=6,
                            sourceUrl="https://example.com/menu",
                            sourceTitle="Menu",
                            evidenceText="Cappuccino $6.00",
                            matchQuality="exact",
                        )
                    ]
                ),
                model="deepseek-v4-flash",
            )

    service = PricingExtractionService(FakeDeepSeek())  # type: ignore[arg-type]
    result = await service.extract_prices(
        competitor=DiscoveredCompetitor(
            name="Devout Coffee",
            address="37323 Niles Blvd, Fremont, CA",
            relevanceReason="Coffee shop",
        ),
        source=DiscoveredSource(
            url="https://example.com/menu",
            title="Menu",
            snippet="View our menu.",
            sourceType="official_site",
        ),
        target_offer="Cappuccino",
    )

    assert result.data.prices[0].price_min == 6
    assert result.model == "deepseek-v4-flash"
    assert "deepseek_extraction" in result.tools_used


def test_api_route_uses_mocked_service(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")

    async def fake_db():
        yield None

    class FakeService:
        def __init__(self, db):
            self.db = db

        async def research(self, payload, current_user):
            return CompetitorPriceResearchResponse(
                query=QueryOut(
                    businessCategory=payload.business_category,
                    targetOffer=payload.target_offer,
                    locationLabel=payload.location.label,
                    radiusMiles=payload.radius_miles,
                ),
                competitors=[],
                marketSummary=MarketSummaryOut(
                    sampleSize=0,
                    priceLow=None,
                    priceMedian=None,
                    priceHigh=None,
                    priceAverage=None,
                    priceIqr=None,
                    currency="USD",
                    recommendedPositioning="No public competitor prices were found.",
                    confidence=0,
                ),
                warnings=[],
                metadata=MetadataOut(
                    modelsUsed=["deepseek-v4-flash"],
                    groundingUsed=GroundingUsedOut(
                        googleSearch=False,
                        googleMaps=False,
                        urlContext=False,
                    ),
                    generatedAt=datetime.now(UTC),
                    cached=False,
                ),
            )

    import app.api.competitor_prices as route

    monkeypatch.setattr(route, "CompetitorResearchService", FakeService)
    fastapi_app.dependency_overrides[get_db] = fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/competitor-prices/research",
            json={
                "businessCategory": "hair salon",
                "targetOffer": "women's haircut",
                "location": {"city": "Austin", "state": "TX"},
            },
        )
    finally:
        fastapi_app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["metadata"]["modelsUsed"] == ["deepseek-v4-flash"]
    assert isinstance(response.json()["metadata"]["durationMs"], int)


def test_price_detection_rejects_non_monetary_numbers():
    assert not evidence_contains_price("37324 Fremont Blvd")
    assert not evidence_contains_price("Call (510) 573-1058")
    assert not evidence_contains_price("Rated from 200 reviews")
    assert not evidence_contains_price("Cappuccino 12 oz", "Cappuccino")
    assert not evidence_contains_price(
        "Cappuccino at 37324 Fremont Blvd with 200 reviews and rating 4.75",
        "Cappuccino",
    )
    assert evidence_contains_price("Cappuccino $4.75", "Cappuccino")
    assert evidence_contains_price("Cappuccino 4.75", "Cappuccino")


def test_evidence_amount_must_match_extracted_price():
    assert not evidence_supports_price(
        _price(
            offerName="Cappuccino",
            priceMin=6,
            priceMax=6,
            evidenceText="Cappuccino $4.75",
        )
    )


def test_v4_cache_key_separates_all_research_inputs():
    base = {
        "businessName": "Suju's Coffee",
        "businessWebsite": "https://sujuscoffee.com",
        "businessPhone": "510-555-0199",
        "businessCategory": "Coffee Shop",
        "targetOffer": "Cappuccino",
        "location": {
            "address": "3602 Thornton Ave",
            "city": "Fremont",
            "state": "CA",
            "zip": "94536",
            "latitude": 37.56,
            "longitude": -122.01,
        },
        "radiusMiles": 10,
        "maxCompetitors": 3,
        "maxSourcesPerCompetitor": 3,
        "currentPrice": 4,
    }
    original = CompetitorPriceResearchRequest.model_validate(base)
    assert build_cache_key(original).startswith("v4|")
    variants = [
        {**base, "businessName": "Another Coffee"},
        {**base, "businessWebsite": "https://another.example"},
        {**base, "businessPhone": "510-555-0100"},
        {**base, "currentPrice": 8},
        {**base, "maxSourcesPerCompetitor": 2},
        {**base, "location": {**base["location"], "address": "1 Main St"}},
        {**base, "location": {**base["location"], "latitude": 40.71}},
    ]
    assert all(
        build_cache_key(CompetitorPriceResearchRequest.model_validate(variant))
        != build_cache_key(original)
        for variant in variants
    )


def _candidate(
    *,
    competitor: DiscoveredCompetitor,
    source_url: str,
    source_type: str,
    amount: float,
    currency: str = "USD",
    channel: str = "in_store",
) -> _CandidatePrice:
    source = DiscoveredSource(
        url=source_url,
        title="Menu",
        snippet=f"Cappuccino ${amount:.2f}",
        sourceType=source_type,
    )
    price = _price(
        offerName="Cappuccino",
        normalizedOfferName="cappuccino",
        priceMin=amount,
        priceMax=amount,
        currency=currency,
        sourceUrl=source_url,
        evidenceText=f"Cappuccino ${amount:.2f}",
    )
    return _CandidatePrice(
        competitor=competitor,
        source=source,
        price=price,
        confidence=0.8,
        reasons=[],
        channel=channel,
        snippet_only=False,
    )


def test_aggregation_uses_one_representative_per_competitor_and_caps_confidence():
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Cappuccino",
            "location": {"city": "Fremont", "state": "CA"},
        }
    )
    competitor = DiscoveredCompetitor(
        name="Hops & Beans",
        address="4000 Bay St, Fremont, CA",
        radiusVerified=True,
    )
    candidates = [
        _candidate(
            competitor=competitor,
            source_url="https://hops.example/menu",
            source_type="official_site",
            amount=4.75,
        ),
        _candidate(
            competitor=competitor,
            source_url="https://maps.example/hops",
            source_type="google_maps",
            amount=4.85,
        ),
    ]
    representatives = _finalize_candidates(candidates, payload, [])
    in_store = _representatives_for_channel(representatives, "in_store", candidates, [])
    summary = build_market_summary(
        [(candidate.price, candidate.confidence) for candidate in in_store]
    )
    assert len(representatives) == 1
    assert summary.sample_size == 1
    assert summary.price_median == 4.8
    assert summary.confidence <= 0.35
    assert all(candidate.corroborated for candidate in candidates)


def test_mixed_currency_and_delivery_are_not_blended():
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Cappuccino",
            "location": {"city": "Fremont", "state": "CA"},
        }
    )
    usd_competitor = DiscoveredCompetitor(name="USD Cafe", radiusVerified=True)
    eur_competitor = DiscoveredCompetitor(name="EUR Cafe", radiusVerified=True)
    candidates = [
        _candidate(
            competitor=usd_competitor,
            source_url="https://usd.example/menu",
            source_type="official_site",
            amount=5,
        ),
        _candidate(
            competitor=eur_competitor,
            source_url="https://eur.example/menu",
            source_type="official_site",
            amount=6,
            currency="EUR",
        ),
        _candidate(
            competitor=usd_competitor,
            source_url="https://delivery.example/menu",
            source_type="marketplace",
            amount=7,
            channel="delivery",
        ),
    ]
    warnings: list[str] = []
    representatives = _finalize_candidates(candidates, payload, warnings)
    in_store = _representatives_for_channel(representatives, "in_store", candidates, warnings)
    delivery = _representatives_for_channel(representatives, "delivery", candidates, warnings)
    assert [candidate.price.currency for candidate in in_store] == ["USD"]
    assert len(delivery) == 1
    assert any("not in USD" in warning for warning in warnings)


def test_self_competitor_matching_uses_name_and_address():
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessName": "Suju's Coffee",
            "businessWebsite": "https://sujuscoffee.com",
            "businessPhone": "(510) 555-0199",
            "businessCategory": "Coffee Shop",
            "targetOffer": "Cappuccino",
            "location": {
                "address": "3602 Thornton Ave",
                "city": "Fremont",
                "state": "CA",
            },
        }
    )
    assert _is_self_competitor(DiscoveredCompetitor(name="Sujus Coffee"), payload)
    assert _is_self_competitor(
        DiscoveredCompetitor(name="Other", address="3602 Thornton Ave, Fremont, CA"), payload
    )
    assert _is_self_competitor(
        DiscoveredCompetitor(name="Other", website="https://www.sujuscoffee.com/menu"), payload
    )
    assert _is_self_competitor(DiscoveredCompetitor(name="Other", phone="510-555-0199"), payload)
    assert not _is_self_competitor(DiscoveredCompetitor(name="Devout Coffee"), payload)


async def test_source_fallback_checks_three_unique_domains_and_stops_on_corroboration(monkeypatch):
    class FakeGeocoder:
        async def geocode(self, _address):
            return Coordinates(37.56, -122.01)

    class FakeExtractor:
        async def extract_prices(self, *, source, **_kwargs):
            if "first" in source.url:
                return DeepSeekJSONResult(data=PriceExtractionResult(prices=[]), tools_used=set())
            amount = 4.75 if "second" in source.url else 4.8
            return DeepSeekJSONResult(
                data=PriceExtractionResult(
                    prices=[
                        _price(
                            offerName="Cappuccino",
                            normalizedOfferName="cappuccino",
                            priceMin=amount,
                            priceMax=amount,
                            sourceUrl=source.url,
                            evidenceText=f"Cappuccino ${amount:.2f}",
                        )
                    ]
                )
            )

    service = CompetitorResearchService(
        db=None,
        deepseek_client=object(),  # type: ignore[arg-type]
        geocoding_client=FakeGeocoder(),  # type: ignore[arg-type]
    )
    service.extractor = FakeExtractor()  # type: ignore[assignment]
    sources = [
        DiscoveredSource(url="https://first.example/menu", sourceType="official_site"),
        DiscoveredSource(url="https://second.example/menu", sourceType="google_maps"),
        DiscoveredSource(url="https://third.example/menu", sourceType="directory"),
    ]

    async def fake_discover_sources(*_args, **_kwargs):
        return sources

    monkeypatch.setattr(service, "discover_sources", fake_discover_sources)
    payload = CompetitorPriceResearchRequest.model_validate(
        {
            "businessCategory": "Coffee Shop",
            "targetOffer": "Cappuccino",
            "location": {
                "city": "Fremont",
                "state": "CA",
                "latitude": 37.56,
                "longitude": -122.01,
            },
            "maxSourcesPerCompetitor": 3,
        }
    )
    work = await service._research_competitor(
        DiscoveredCompetitor(name="Hops", address="4000 Bay St, Fremont, CA"),
        payload,
        [],
        ResearchCallMetadata(),
    )
    assert [attempt.status for attempt in work.attempts] == [
        "checked_no_price",
        "accepted",
        "accepted",
    ]
    assert _has_corroborating_pair(work.candidates)


async def test_deepseek_failure_does_not_report_success(monkeypatch):
    monkeypatch.setattr(settings, "enable_deepseek_extraction", True)

    class FakeDeepSeek:
        async def generate_json(self, **_kwargs):
            raise DeepSeekError("unauthorized")

    service = PricingExtractionService(FakeDeepSeek())  # type: ignore[arg-type]
    with pytest.raises(DeepSeekError):
        await service.extract_prices(
            competitor=DiscoveredCompetitor(name="Test", address="Fremont, CA"),
            source=DiscoveredSource(
                url="https://example.com/menu",
                snippet="View menu",
                sourceType="official_site",
            ),
            target_offer="Cappuccino",
        )


async def test_google_geocoder_success_zero_results_and_missing_key():
    responses = [
        {"status": "OK", "results": [{"geometry": {"location": {"lat": 37.5, "lng": -122.0}}}]},
        {"status": "ZERO_RESULTS", "results": []},
    ]

    async def handler(_request):
        return httpx.Response(200, json=responses.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        geocoder = GoogleGeocodingClient(api_key="test", http_client=client)
        assert await geocoder.geocode("Fremont") == Coordinates(37.5, -122.0)
        assert await geocoder.geocode("Missing") is None

    with pytest.raises(GeocodingConfigurationError):
        await GoogleGeocodingClient(api_key="").geocode("Fremont")
    assert 6 < distance_miles(Coordinates(37.5, -122.0), Coordinates(37.6, -122.0)) < 8


async def test_prefilled_fremont_fixture_separates_channels_and_excludes_self(monkeypatch):
    class FakeGeocoder:
        async def geocode(self, address):
            if "3602 Thornton" in address:
                return Coordinates(37.559, -122.014)
            if "4000 Bay" in address:
                return Coordinates(37.548, -121.989)
            if "Philz" in address:
                return Coordinates(37.55, -121.99)
            return None

    class FakeExtractor:
        async def extract_prices(self, *, source, **_kwargs):
            prices = {
                "https://hops.example/menu": 4.75,
                "https://delivery.example/hops": 6.05,
                "https://maps.example/hops": 4.80,
            }
            amount = prices.get(source.url.rstrip("/"))
            if amount is None:
                return DeepSeekJSONResult(data=PriceExtractionResult(prices=[]), tools_used=set())
            return DeepSeekJSONResult(
                data=PriceExtractionResult(
                    prices=[
                        _price(
                            offerName="Cappuccino",
                            normalizedOfferName="cappuccino",
                            priceMin=amount,
                            priceMax=amount,
                            sourceUrl=source.url,
                            evidenceText=f"Cappuccino ${amount:.2f}",
                        )
                    ]
                )
            )

    service = CompetitorResearchService(
        db=None,
        deepseek_client=object(),  # type: ignore[arg-type]
        geocoding_client=FakeGeocoder(),  # type: ignore[arg-type]
    )
    service.extractor = FakeExtractor()  # type: ignore[assignment]

    async def fake_discover_competitors(*_args, **_kwargs):
        return CompetitorDiscoveryResult(
            competitors=[
                DiscoveredCompetitor(
                    name="Suju's Coffee",
                    address="3602 Thornton Ave, Fremont, CA",
                ),
                DiscoveredCompetitor(
                    name="Hops & Beans",
                    address="4000 Bay St, Fremont, CA",
                ),
                DiscoveredCompetitor(
                    name="Philz Coffee",
                    address="Philz, Fremont, CA",
                ),
            ]
        )

    async def fake_discover_sources(competitor, *_args, **_kwargs):
        if competitor.name == "Hops & Beans":
            return [
                DiscoveredSource(url="https://hops.example/menu", sourceType="official_site"),
                DiscoveredSource(url="https://delivery.example/hops", sourceType="marketplace"),
                DiscoveredSource(url="https://maps.example/hops", sourceType="google_maps"),
            ]
        return [
            DiscoveredSource(url=f"https://philz{index}.example/menu", sourceType="official_site")
            for index in range(1, 4)
        ]

    monkeypatch.setattr(service, "discover_competitors", fake_discover_competitors)
    monkeypatch.setattr(service, "discover_sources", fake_discover_sources)
    response = await service.research(
        CompetitorPriceResearchRequest.model_validate(
            {
                "businessName": "Suju's Coffee",
                "businessCategory": "Coffee Shop",
                "targetOffer": "Cappuccino",
                "location": {
                    "address": "3602 Thornton Ave",
                    "city": "Fremont",
                    "state": "CA",
                    "zip": "94536",
                },
                "radiusMiles": 10,
                "maxCompetitors": 3,
                "maxSourcesPerCompetitor": 3,
                "currentPrice": 4,
            }
        ),
        CurrentUser(
            user_id="test-user",
            email="test@example.com",
            business_id="00000000-0000-0000-0000-000000000001",
        ),
    )
    assert [competitor.name for competitor in response.competitors] == [
        "Hops & Beans",
        "Philz Coffee",
    ]
    assert response.market_summary.sample_size == 1
    assert response.market_summary.price_median == 4.78
    assert response.channel_summaries is not None
    assert response.channel_summaries.delivery.price_median == 6.05
    assert response.metadata.research_stats.sources_checked == 6
    assert response.metadata.research_stats.corroborated_competitors == 1
