"""Contract tests for swappable pricing provider adapters."""

from __future__ import annotations

import json

import httpx

from app.services.competitor_prices.foursquare_places import FoursquarePlacesClient
from app.services.competitor_prices.web_providers import ExaClient, FirecrawlClient, TavilyClient


async def test_tavily_search_and_extract_contract_tracks_reported_credits():
    async def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer tavily-test"
        if request.url.path == "/search":
            assert payload["search_depth"] == "basic"
            assert payload["start_date"] == "2026-01-15"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Cafe menu",
                            "url": "https://cafe.example/menu",
                            "content": "Cappuccino $5.00",
                        }
                    ],
                    "usage": {"credits": 1},
                },
            )
        assert request.url.path == "/extract"
        assert payload["urls"] == ["https://cafe.example/menu"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://cafe.example/menu",
                        "raw_content": "Cappuccino 5.00",
                    }
                ],
                "usage": {"credits": 0.4},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilyClient(api_key="tavily-test", http_client=client)
        results = await provider.search(
            "cafe menu",
            max_results=5,
            search_after_date_filter="01/15/2026",
        )
        page = await provider.fetch("https://cafe.example/menu")

    assert results[0].snippet == "Cappuccino $5.00"
    assert page.succeeded and "5.00" in page.content
    assert provider.requests_made == 2
    assert provider.cost_usd_total == 0.0112


async def test_exa_uses_current_freshness_parameter_and_reports_cost():
    async def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert request.headers["x-api-key"] == "exa-test"
        if request.url.path == "/search":
            assert payload["startPublishedDate"] == "2026-01-15T00:00:00.000Z"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Cafe menu",
                            "url": "https://cafe.example/menu",
                            "highlights": ["Cappuccino $5.00"],
                        }
                    ],
                    "costDollars": {"total": 0.007},
                },
            )
        assert request.url.path == "/contents"
        assert payload["maxAgeHours"] == 24
        assert "livecrawl" not in payload
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://cafe.example/menu", "text": "Cappuccino $5.00"}
                ],
                "costDollars": {"total": 0.003},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ExaClient(api_key="exa-test", http_client=client)
        results = await provider.search(
            "cafe menu",
            max_results=5,
            search_after_date_filter="01/15/2026",
        )
        page = await provider.fetch("https://cafe.example/menu")

    assert results[0].snippet == "Cappuccino $5.00"
    assert page.succeeded
    assert provider.cost_usd_total == 0.01


async def test_firecrawl_v2_scrape_contract():
    async def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert request.url.path == "/v2/scrape"
        assert request.headers["authorization"] == "Bearer firecrawl-test"
        assert payload["formats"] == ["markdown"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "markdown": "Cappuccino $5.00",
                    "metadata": {"sourceURL": "https://cafe.example/menu"},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await FirecrawlClient(
            api_key="firecrawl-test", http_client=client
        ).fetch("https://cafe.example/menu")
    assert page.succeeded
    assert page.url == "https://cafe.example/menu"


async def test_foursquare_new_places_api_contract():
    async def handler(request: httpx.Request):
        assert request.url.path == "/places/search"
        assert request.headers["authorization"] == "Bearer foursquare-test"
        assert request.headers["x-places-api-version"] == "2025-06-17"
        assert request.url.params["query"] == "Coffee Shop"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "fsq_place_id": "fsq-1",
                        "name": "Foursquare Cafe",
                        "location": {"formatted_address": "1 Main St, Fremont, CA"},
                        "geocodes": {
                            "main": {"latitude": 37.56, "longitude": -122.01}
                        },
                        "distance": 1609.344,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FoursquarePlacesClient(api_key="foursquare-test", http_client=client)
        places = await provider.discover(
            latitude=37.56,
            longitude=-122.01,
            radius_miles=5,
            business_category="Coffee Shop",
            max_results=4,
        )

    assert places[0].place_id == "fsq-1"
    assert places[0].discovery_provider == "foursquare"
    assert places[0].distance_miles == 1
