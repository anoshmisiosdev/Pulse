"""Construct configured pricing providers behind narrow stage interfaces."""

from __future__ import annotations

from typing import Protocol

from app.core.config import settings
from app.services.competitor_prices.foursquare_places import FoursquarePlacesClient
from app.services.competitor_prices.google_places import GooglePlacesClient
from app.services.competitor_prices.page_fetcher import PageFetchResult
from app.services.competitor_prices.perplexity_client import (
    PerplexitySearchClient,
    PerplexitySearchResult,
)
from app.services.competitor_prices.schemas import DiscoveredCompetitor
from app.services.competitor_prices.web_providers import (
    ExaClient,
    FirecrawlClient,
    TavilyClient,
)


class PlaceProvider(Protocol):
    requests_made: int

    async def discover(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_miles: float,
        business_category: str,
        max_results: int,
    ) -> list[DiscoveredCompetitor]: ...


class SearchProvider(Protocol):
    requests_made: int
    duration_ms_total: int

    async def search(
        self,
        query: str | list[str],
        *,
        max_results: int,
        search_domain_filter: list[str] | None = None,
        search_after_date_filter: str | None = None,
    ) -> list[PerplexitySearchResult]: ...


class ContentProvider(Protocol):
    requests_made: int
    duration_ms_total: int

    async def fetch(self, url: str) -> PageFetchResult: ...


def build_place_provider() -> PlaceProvider:
    if settings.pricing_place_provider == "foursquare":
        return FoursquarePlacesClient()
    return GooglePlacesClient()


def build_search_provider() -> SearchProvider:
    if settings.pricing_search_provider == "tavily":
        return TavilyClient()
    if settings.pricing_search_provider == "exa":
        return ExaClient()
    return PerplexitySearchClient()


def build_content_fallback() -> ContentProvider | None:
    if settings.pricing_content_fallback == "tavily":
        return TavilyClient()
    if settings.pricing_content_fallback == "exa":
        return ExaClient()
    if settings.pricing_content_fallback == "firecrawl":
        return FirecrawlClient()
    return None
