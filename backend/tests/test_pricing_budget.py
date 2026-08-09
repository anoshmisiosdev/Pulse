"""Per-item provider budget and status contract tests."""

from __future__ import annotations

from itertools import product

from app.core.config import settings
from app.core.deps import CurrentUser
from app.services.competitor_prices.competitor_research_service import (
    CompetitorResearchService,
)
from app.services.competitor_prices.schemas import (
    CompetitorDiscoveryResult,
    CompetitorPriceResearchRequest,
    DiscoveredCompetitor,
    ResearchCallMetadata,
)
from scripts.pricing_preflight import build_checks, estimated_worst_case_cost_usd


async def test_run_wide_fallback_tokens_are_hard_capped(monkeypatch):
    monkeypatch.setattr(settings, "pricing_max_ai_fallbacks_per_run", 2)
    monkeypatch.setattr(settings, "pricing_max_content_fallbacks_per_run", 1)
    monkeypatch.setattr(settings, "pricing_max_geocoding_requests_per_run", 1)
    service = CompetitorResearchService(db=None)

    assert await service._claim_fallback_budget("ai")
    assert await service._claim_fallback_budget("ai")
    assert not await service._claim_fallback_budget("ai")
    assert await service._claim_fallback_budget("content")
    assert not await service._claim_fallback_budget("content")
    assert await service._claim_geocoding_budget()
    assert not await service._claim_geocoding_budget()


async def test_v2_caps_competitors_and_returns_honest_no_evidence(monkeypatch):
    monkeypatch.setattr(settings, "pricing_pipeline_v2_enabled", True)
    monkeypatch.setattr(settings, "pricing_max_competitors_per_run", 4)
    service = CompetitorResearchService(db=None)
    observed_max = None

    async def empty_discovery(payload, *_args, **_kwargs):
        nonlocal observed_max
        observed_max = payload.max_competitors
        return CompetitorDiscoveryResult(competitors=[])

    monkeypatch.setattr(service, "discover_competitors", empty_discovery)
    response = await service.research(
        CompetitorPriceResearchRequest.model_validate(
            {
                "businessCategory": "Coffee Shop",
                "targetOffer": "Cappuccino",
                "location": {
                    "city": "Fremont",
                    "state": "CA",
                    "latitude": 37.56,
                    "longitude": -122.01,
                },
                "maxCompetitors": 10,
            }
        ),
        CurrentUser(
            user_id="budget-test",
            email=None,
            business_id="00000000-0000-0000-0000-00000000b0d6",
        ),
    )

    assert observed_max == 4
    assert response.status == "no_evidence"
    assert response.market_summary.price_median is None
    assert response.estimate_summary is None
    assert response.quota and response.quota.remaining == 9


async def test_source_discovery_spends_one_search_request_per_competitor():
    class CountingSearch:
        provider_name = "tavily"
        requests_made = 0

        async def search(self, query, **_kwargs):
            assert isinstance(query, str)
            self.requests_made += 1
            return []

    search = CountingSearch()
    service = CompetitorResearchService(db=None, search_client=search)  # type: ignore[arg-type]
    metadata = ResearchCallMetadata()
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
        }
    )

    sources = await service.discover_sources(
        DiscoveredCompetitor(
            name="Fremont Coffee Co",
            website="https://www.fremontcoffeeco.com",
        ),
        payload,
        [],
        metadata,
    )

    assert search.requests_made == 1
    assert metadata.source_search_requests == 1
    assert [source.url for source in sources] == ["https://www.fremontcoffeeco.com/"]


def test_every_supported_provider_matrix_fits_the_item_budget(monkeypatch):
    monkeypatch.setattr(settings, "pricing_google_place_details_enabled", False)
    monkeypatch.setattr(settings, "pricing_max_competitors_per_run", 4)
    monkeypatch.setattr(settings, "pricing_max_ai_fallbacks_per_run", 2)
    monkeypatch.setattr(settings, "pricing_max_content_fallbacks_per_run", 1)
    monkeypatch.setattr(settings, "pricing_max_geocoding_requests_per_run", 1)

    combinations = product(
        ("google_places", "foursquare"),
        ("perplexity", "tavily", "exa"),
        ("none", "tavily", "exa", "firecrawl"),
        ("deterministic", "sonar", "deepseek"),
    )
    costs: list[float] = []
    for place, search, content, extraction in combinations:
        monkeypatch.setattr(settings, "pricing_place_provider", place)
        monkeypatch.setattr(settings, "pricing_search_provider", search)
        monkeypatch.setattr(settings, "pricing_content_fallback", content)
        monkeypatch.setattr(settings, "pricing_extraction_provider", extraction)
        costs.append(estimated_worst_case_cost_usd())

    assert max(costs) == 0.0992
    assert all(cost <= settings.pricing_max_provider_cost_usd for cost in costs)


def test_google_detail_fanout_fails_the_item_budget_preflight(monkeypatch):
    monkeypatch.setattr(settings, "pricing_place_provider", "google_places")
    monkeypatch.setattr(settings, "pricing_search_provider", "perplexity")
    monkeypatch.setattr(settings, "pricing_content_fallback", "none")
    monkeypatch.setattr(settings, "pricing_extraction_provider", "sonar")
    monkeypatch.setattr(settings, "pricing_google_place_details_enabled", True)
    monkeypatch.setattr(settings, "pricing_max_competitors_per_run", 4)

    assert estimated_worst_case_cost_usd() > settings.pricing_max_provider_cost_usd


def test_preflight_requires_a_present_and_separate_google_server_key(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_server_api_key", "")
    monkeypatch.setattr(settings, "google_maps_api_key", "browser-key")
    missing = {check.name: check for check in build_checks()}
    assert not missing["server-key-separation"].passed
    assert "cannot verify" in missing["server-key-separation"].message

    monkeypatch.setattr(settings, "google_maps_server_api_key", "browser-key")
    identical = {check.name: check for check in build_checks()}
    assert not identical["server-key-separation"].passed

    monkeypatch.setattr(settings, "google_maps_server_api_key", "server-key")
    separated = {check.name: check for check in build_checks()}
    assert separated["server-key-separation"].passed
