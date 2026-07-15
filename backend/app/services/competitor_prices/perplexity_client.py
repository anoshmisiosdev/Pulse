"""Perplexity Search API client for pricing-source discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.http_retry import retry_transient
from app.services.competitor_prices.confidence_scoring import (
    canonicalize_offer_label,
    evidence_contains_price,
    normalize_offer,
)
from app.services.competitor_prices.schemas import (
    CompetitorPriceResearchRequest,
    DiscoveredCompetitor,
    DiscoveredSource,
)

logger = logging.getLogger("pulse.competitor_prices.perplexity")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BOOKING_DOMAINS = (
    "square.site",
    "toasttab.com",
    "clover.com",
    "order.online",
    "spoton.com",
)
_MARKETPLACE_DOMAINS = (
    "doordash.com",
    "ubereats.com",
    "postmates.com",
    "grubhub.com",
    "seamless.com",
)
_DIRECTORY_DOMAINS = (
    "yelp.com",
    "tripadvisor.com",
    "restaurantji.com",
    "restaurantguru.com",
    "google.com",
    "maps.google.com",
)
_SOCIAL_DOMAINS = ("instagram.com", "facebook.com", "tiktok.com")


class PerplexityError(Exception):
    """Base Perplexity integration error."""


class PerplexityConfigurationError(PerplexityError):
    """Perplexity cannot be called because local configuration is incomplete."""


class PerplexityQuotaError(PerplexityError):
    """The Perplexity project has exhausted quota or rate limits."""


@dataclass(frozen=True)
class PerplexitySearchResult:
    title: str
    url: str
    snippet: str
    date: str | None = None
    last_updated: str | None = None


class PerplexitySearchClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key if api_key is not None else settings.perplexity_api_key
        self.base_url = (base_url or settings.perplexity_search_base_url).rstrip("/")

    async def search(self, query: str, *, max_results: int) -> list[PerplexitySearchResult]:
        if not self.api_key:
            raise PerplexityConfigurationError(
                "Set PERPLEXITY_API_KEY to use Perplexity Search source discovery."
            )

        payload: dict[str, object] = {
            "query": query,
            "max_results": max(1, min(max_results, 20)),
        }
        if settings.perplexity_search_country:
            payload["country"] = settings.perplexity_search_country
        if settings.perplexity_search_context_size:
            payload["search_context_size"] = settings.perplexity_search_context_size

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        @retry_transient
        async def _request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            return response

        try:
            response = await _request()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise PerplexityQuotaError(
                    "Perplexity Search quota exhausted or rate limited."
                ) from exc
            raise PerplexityError(
                f"Perplexity Search request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise PerplexityError(f"Perplexity Search request failed: {exc}") from exc

        data = response.json()
        results = data.get("results", [])
        if not isinstance(results, list):
            raise PerplexityError(f"Unexpected Perplexity Search response: {data}")

        parsed: list[PerplexitySearchResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if not url:
                continue
            parsed.append(
                PerplexitySearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    date=str(item.get("date") or "") or None,
                    last_updated=str(item.get("last_updated") or "") or None,
                )
            )
        return parsed


async def discover_sources_with_perplexity(
    *,
    client: PerplexitySearchClient,
    competitor: DiscoveredCompetitor,
    payload: CompetitorPriceResearchRequest,
) -> list[DiscoveredSource]:
    sources: list[DiscoveredSource] = []
    for query_index, query in enumerate(_pricing_queries(competitor, payload)):
        try:
            results = await client.search(query, max_results=settings.perplexity_max_results)
        except PerplexityError:
            raise
        for result in results:
            source = _source_from_result(
                result=result,
                competitor=competitor,
                target_offer=payload.target_offer,
                query_index=query_index,
            )
            if source:
                sources.append(source)
    return sources


def _pricing_queries(
    competitor: DiscoveredCompetitor,
    payload: CompetitorPriceResearchRequest,
) -> list[str]:
    city_state = " ".join(
        part for part in [payload.location.city, payload.location.state] if part
    ).strip()
    name = f'"{competitor.name}"'
    offer = f'"{canonicalize_offer_label(payload.target_offer)}"'
    queries = [
        f"{name} {offer} price menu {city_state}".strip(),
        f"{name} {offer} online order menu {city_state}".strip(),
    ]

    domain = _domain(competitor.website or "")
    if domain:
        queries.append(f"site:{domain} {offer} price menu")
    else:
        queries.append(
            f"{name} {offer} square.site toasttab clover doordash menu {city_state}".strip()
        )
    return queries[: max(1, settings.perplexity_max_queries_per_competitor)]


def _source_from_result(
    *,
    result: PerplexitySearchResult,
    competitor: DiscoveredCompetitor,
    target_offer: str,
    query_index: int,
) -> DiscoveredSource | None:
    source_type = infer_source_type(result.url, competitor=competitor)
    title = result.title or None
    snippet = result.snippet or None
    relevance = _result_relevance(result, target_offer, query_index)
    try:
        return DiscoveredSource(
            url=result.url,
            title=title,
            snippet=snippet,
            sourceType=source_type,
            relevance=relevance,
        )
    except ValueError:
        logger.debug("Ignoring invalid Perplexity URL: %s", result.url)
        return None


def infer_source_type(url: str, *, competitor: DiscoveredCompetitor) -> str:
    domain = _domain(url)
    website_domain = _domain(competitor.website or "")
    if website_domain and (domain == website_domain or domain.endswith(f".{website_domain}")):
        return "official_site"
    if any(marker in domain for marker in _BOOKING_DOMAINS):
        return "booking_page"
    if any(marker in domain for marker in _MARKETPLACE_DOMAINS):
        return "marketplace"
    if any(marker in domain for marker in _DIRECTORY_DOMAINS):
        return "directory"
    if any(marker in domain for marker in _SOCIAL_DOMAINS):
        return "social"
    return "unknown"


def _result_relevance(
    result: PerplexitySearchResult,
    target_offer: str,
    query_index: int,
) -> float:
    target = normalize_offer(canonicalize_offer_label(target_offer))
    haystack = normalize_offer(f"{result.title} {result.snippet} {result.url}")
    relevance = 0.65 - (query_index * 0.08)
    if target and target in haystack:
        relevance += 0.2
    if evidence_contains_price(result.snippet, target_offer):
        relevance += 0.15
    return round(max(0.05, min(1.0, relevance)), 2)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""
