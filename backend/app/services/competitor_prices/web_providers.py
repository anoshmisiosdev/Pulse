"""Search and difficult-page retrieval adapters for pricing pipeline v2."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.services.competitor_prices.page_fetcher import PageFetchResult
from app.services.competitor_prices.perplexity_client import PerplexitySearchResult


class WebProviderError(Exception):
    pass


class WebProviderConfigurationError(WebProviderError):
    pass


class _BaseWebProvider:
    api_key = ""
    base_url = ""
    provider_name = "unknown"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None):
        self.http_client = http_client
        self.requests_made = 0
        self.duration_ms_total = 0
        self.cost_usd_total = 0.0

    async def _post(
        self,
        path: str,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise WebProviderConfigurationError(
                f"Set {self.provider_name.upper()}_API_KEY to use {self.provider_name}."
            )
        client = self.http_client or httpx.AsyncClient(timeout=timeout)
        started = time.perf_counter()
        self.requests_made += 1
        try:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise WebProviderError(f"Unexpected {self.provider_name} response.")
            self.cost_usd_total += _reported_cost_usd(data, self.provider_name)
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise WebProviderError(f"{self.provider_name} request failed: {exc}") from exc
        finally:
            if self.http_client is None:
                await client.aclose()
            self.duration_ms_total += round((time.perf_counter() - started) * 1000)


class TavilyClient(_BaseWebProvider):
    provider_name = "tavily"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        super().__init__(http_client=http_client)
        self.api_key = api_key if api_key is not None else settings.tavily_api_key
        self.base_url = base_url or settings.tavily_base_url

    async def search(
        self,
        query: str | list[str],
        *,
        max_results: int,
        search_domain_filter: list[str] | None = None,
        search_after_date_filter: str | None = None,
    ) -> list[PerplexitySearchResult]:
        output: list[PerplexitySearchResult] = []
        for item in [query] if isinstance(query, str) else query:
            payload: dict[str, Any] = {
                "query": item,
                "search_depth": "basic",
                "max_results": min(20, max(1, max_results)),
                "include_answer": False,
                "include_raw_content": False,
            }
            if search_domain_filter:
                payload["include_domains"] = search_domain_filter
            if search_after_date_filter:
                payload["start_date"] = _iso_date(search_after_date_filter)
            data = await self._post(
                "/search",
                payload=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            for row in data.get("results", []):
                if not isinstance(row, dict) or not row.get("url"):
                    continue
                output.append(
                    PerplexitySearchResult(
                        title=str(row.get("title") or ""),
                        url=str(row["url"]),
                        snippet=str(row.get("content") or ""),
                        date=str(row.get("published_date") or "") or None,
                    )
                )
        return output

    async def fetch(self, url: str) -> PageFetchResult:
        data = await self._post(
            "/extract",
            payload={
                "urls": [url],
                "extract_depth": "advanced",
                "format": "markdown",
                "timeout": 30,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        rows = data.get("results", [])
        if not rows or not isinstance(rows[0], dict):
            return PageFetchResult(url=url, error="Tavily could not extract this page.")
        return _content_result(
            url=str(rows[0].get("url") or url),
            content=str(rows[0].get("raw_content") or ""),
            content_type="text/markdown",
        )


class ExaClient(_BaseWebProvider):
    provider_name = "exa"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        super().__init__(http_client=http_client)
        self.api_key = api_key if api_key is not None else settings.exa_api_key
        self.base_url = base_url or settings.exa_base_url

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "Content-Type": "application/json"}

    async def search(
        self,
        query: str | list[str],
        *,
        max_results: int,
        search_domain_filter: list[str] | None = None,
        search_after_date_filter: str | None = None,
    ) -> list[PerplexitySearchResult]:
        output: list[PerplexitySearchResult] = []
        for item in [query] if isinstance(query, str) else query:
            payload: dict[str, Any] = {
                "query": item,
                "type": "auto",
                "numResults": min(20, max(1, max_results)),
                "contents": {"highlights": {"maxCharacters": 1200}},
            }
            if search_domain_filter:
                payload["includeDomains"] = search_domain_filter
            if search_after_date_filter:
                payload["startPublishedDate"] = (
                    f"{_iso_date(search_after_date_filter)}T00:00:00.000Z"
                )
            data = await self._post("/search", payload=payload, headers=self._headers)
            for row in data.get("results", []):
                if not isinstance(row, dict) or not row.get("url"):
                    continue
                highlights = (
                    row.get("highlights") if isinstance(row.get("highlights"), list) else []
                )
                output.append(
                    PerplexitySearchResult(
                        title=str(row.get("title") or ""),
                        url=str(row["url"]),
                        snippet=" ".join(str(value) for value in highlights)
                        or str(row.get("text") or ""),
                        date=str(row.get("publishedDate") or "") or None,
                    )
                )
        return output

    async def fetch(self, url: str) -> PageFetchResult:
        data = await self._post(
            "/contents",
            payload={"urls": [url], "text": True, "maxAgeHours": 24},
            headers=self._headers,
        )
        rows = data.get("results", [])
        if not rows or not isinstance(rows[0], dict):
            return PageFetchResult(url=url, error="Exa could not retrieve this page.")
        return _content_result(
            url=str(rows[0].get("url") or url),
            content=str(rows[0].get("text") or ""),
            content_type="text/plain",
        )


class FirecrawlClient(_BaseWebProvider):
    provider_name = "firecrawl"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        super().__init__(http_client=http_client)
        self.api_key = api_key if api_key is not None else settings.firecrawl_api_key
        self.base_url = base_url or settings.firecrawl_base_url

    async def fetch(self, url: str) -> PageFetchResult:
        data = await self._post(
            "/scrape",
            payload={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "parsers": ["pdf"],
                "timeout": 30_000,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=45.0,
        )
        row = data.get("data") if isinstance(data.get("data"), dict) else {}
        content = str(row.get("markdown") or "")
        if not content:
            return PageFetchResult(url=url, error="Firecrawl could not scrape this page.")
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        return _content_result(
            url=str(metadata.get("sourceURL") or url),
            content=content,
            content_type="text/markdown",
        )


def _content_result(*, url: str, content: str, content_type: str) -> PageFetchResult:
    if not content.strip():
        return PageFetchResult(url=url, error="Provider returned empty content.")
    return PageFetchResult(
        url=url,
        content=content,
        status_code=200,
        content_type=content_type,
        retrieved_at=datetime.now(UTC),
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _iso_date(value: str) -> str:
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def _reported_cost_usd(payload: dict[str, Any], provider_name: str) -> float:
    cost = payload.get("costDollars")
    if isinstance(cost, dict):
        try:
            return max(0.0, float(cost.get("total") or 0))
        except (TypeError, ValueError):
            return 0.0
    usage = payload.get("usage")
    if provider_name == "tavily" and isinstance(usage, dict):
        try:
            return max(0.0, float(usage.get("credits") or 0) * 0.008)
        except (TypeError, ValueError):
            return 0.0
    return 0.0
