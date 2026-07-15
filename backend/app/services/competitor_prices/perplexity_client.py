"""Perplexity Search and Sonar clients for grounded pricing research."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.services.competitor_prices.confidence_scoring import (
    canonicalize_offer_label,
    evidence_contains_price,
    normalize_offer,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekError,
    DeepSeekJSONResult,
    extract_chat_content,
    parse_json_text,
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
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.perplexity_api_key
        self.base_url = (base_url or settings.perplexity_search_base_url).rstrip("/")
        self.http_client = http_client
        self.requests_made = 0
        self.duration_ms_total = 0
        self.model = settings.perplexity_sonar_model
        self.returned_models: set[str] = set()
        self.usage_totals: dict[str, int] = {}

    async def generate_json[T: BaseModel](
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        max_tokens: int | None = None,
    ) -> DeepSeekJSONResult[T]:
        """Generate grounded structured output with Sonar's JSON Schema mode."""
        if not self.api_key:
            raise PerplexityConfigurationError("Set PERPLEXITY_API_KEY to use Perplexity Sonar.")
        if not settings.enable_perplexity_sonar:
            raise PerplexityConfigurationError(
                "Perplexity Sonar is disabled. Set ENABLE_PERPLEXITY_SONAR=true."
            )

        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens or settings.perplexity_sonar_max_tokens,
            "temperature": 0,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "schema": response_model.model_json_schema(by_alias=True),
                },
            },
            "web_search_options": {
                "search_context_size": settings.perplexity_search_context_size,
            },
        }
        data = await self._post("/v1/sonar", payload, operation="Sonar")
        try:
            parsed = parse_json_text(extract_chat_content(data), response_model)
        except (DeepSeekError, ValidationError) as exc:
            raise PerplexityError(
                "Perplexity Sonar returned structured output that did not match the schema."
            ) from exc

        returned_model = str(data.get("model") or self.model)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        integer_usage = {key: value for key, value in usage.items() if isinstance(value, int)}
        self.returned_models.add(returned_model)
        for key, value in integer_usage.items():
            self.usage_totals[key] = self.usage_totals.get(key, 0) + value
        return DeepSeekJSONResult(
            data=parsed,
            tools_used={"sonar_extraction"},
            model=returned_model,
            usage=integer_usage,
            citations=[str(url) for url in (data.get("citations") or []) if isinstance(url, str)],
            search_results=[
                item for item in (data.get("search_results") or []) if isinstance(item, dict)
            ],
        )

    async def search(
        self,
        query: str | list[str],
        *,
        max_results: int,
        search_domain_filter: list[str] | None = None,
        search_after_date_filter: str | None = None,
    ) -> list[PerplexitySearchResult]:
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
        if settings.perplexity_max_tokens_per_page:
            payload["max_tokens_per_page"] = settings.perplexity_max_tokens_per_page
        elif settings.perplexity_search_context_size:
            payload["search_context_size"] = settings.perplexity_search_context_size
        if search_domain_filter:
            payload["search_domain_filter"] = search_domain_filter[:20]
        if search_after_date_filter:
            payload["search_after_date_filter"] = search_after_date_filter

        data = await self._post("/search", payload, operation="Search")
        results = data.get("results", [])
        if not isinstance(results, list):
            raise PerplexityError(f"Unexpected Perplexity Search response: {data}")

        parsed: list[PerplexitySearchResult] = []
        flattened = (
            [nested for item in results for nested in item]
            if results and all(isinstance(item, list) for item in results)
            else results
        )
        for item in flattened:
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

    async def _post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        operation: str,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        self.requests_made += 1
        try:
            if self.http_client is not None:
                response = await self.http_client.post(
                    f"{self.base_url}{path}", headers=headers, json=payload
                )
            else:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    response = await client.post(
                        f"{self.base_url}{path}", headers=headers, json=payload
                    )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise PerplexityQuotaError(
                    f"Perplexity {operation} quota exhausted or rate limited."
                ) from exc
            raise PerplexityError(
                f"Perplexity {operation} request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise PerplexityError(f"Perplexity {operation} request failed: {exc}") from exc
        finally:
            self.duration_ms_total += round((time.perf_counter() - started) * 1000)
        data = response.json()
        if not isinstance(data, dict):
            raise PerplexityError(f"Unexpected Perplexity {operation} response: {data}")
        return data


async def discover_sources_with_perplexity(
    *,
    client: PerplexitySearchClient,
    competitor: DiscoveredCompetitor,
    payload: CompetitorPriceResearchRequest,
) -> list[DiscoveredSource]:
    sources: list[DiscoveredSource] = []
    queries = _pricing_queries(competitor, payload)
    domain = _domain(competitor.website or "")
    if domain:
        official_results = await client.search(
            f'site:{domain} "{canonicalize_offer_label(payload.target_offer)}" price menu',
            max_results=settings.perplexity_max_results,
            search_domain_filter=[domain],
        )
        sources.extend(
            source
            for result in official_results
            if (
                source := _source_from_result(
                    result=result,
                    competitor=competitor,
                    target_offer=payload.target_offer,
                    query_index=0,
                )
            )
        )
    general_queries = [query for query in queries if not query.startswith("site:")]
    if general_queries:
        cutoff = datetime.now(UTC) - timedelta(
            days=max(1, settings.third_party_freshness_months) * 30
        )
        results = await client.search(
            general_queries[:5],
            max_results=settings.perplexity_max_results,
            search_after_date_filter=cutoff.strftime("%m/%d/%Y"),
        )
        sources.extend(
            source
            for result in results
            if (
                source := _source_from_result(
                    result=result,
                    competitor=competitor,
                    target_offer=payload.target_offer,
                    query_index=1,
                )
            )
        )
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
            publishedAt=result.date,
            updatedAt=result.last_updated,
            retrievalMethod="perplexity_content",
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
