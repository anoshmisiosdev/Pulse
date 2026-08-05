"""Competitor price research orchestration."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser
from app.models.competitor_price import (
    CompetitorPriceCompetitor,
    CompetitorPriceObservation,
    CompetitorPriceResearchRun,
    CompetitorPriceSource,
)
from app.services.competitor_prices.confidence_scoring import (
    ConfidenceInput,
    build_market_summary,
    canonicalize_offer_label,
    evidence_contains_price,
    evidence_supports_price,
    likely_wrong_location,
    location_matches,
    normalize_offer,
    score_price_confidence,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekClient,
    DeepSeekError,
    DeepSeekJSONResult,
)
from app.services.competitor_prices.foursquare_places import FoursquarePlacesError
from app.services.competitor_prices.geocoding import (
    Coordinates,
    GeocodingConfigurationError,
    GeocodingError,
    GoogleGeocodingClient,
    distance_miles,
)
from app.services.competitor_prices.google_places import GooglePlacesError
from app.services.competitor_prices.page_fetcher import SafePageFetcher
from app.services.competitor_prices.perplexity_client import (
    PerplexityConfigurationError,
    PerplexityError,
    PerplexitySearchClient,
    PerplexitySearchResult,
    discover_sources_with_search,
    infer_source_type,
)
from app.services.competitor_prices.pricing_extraction_service import PricingExtractionService
from app.services.competitor_prices.provider_registry import (
    ContentProvider,
    PlaceProvider,
    SearchProvider,
    build_content_fallback,
    build_place_provider,
    build_search_provider,
)
from app.services.competitor_prices.schemas import (
    ChannelSummariesOut,
    CompetitorDiscoveryResult,
    CompetitorOut,
    CompetitorPriceResearchRequest,
    CompetitorPriceResearchResponse,
    DiscoveredCompetitor,
    DiscoveredSource,
    EstimateSummaryOut,
    ExtractedPrice,
    GroundingUsedOut,
    MarketSummaryOut,
    MetadataOut,
    PriceExtractionResult,
    PriceObservationOut,
    PricingIssueOut,
    PricingQuotaOut,
    ProviderStatsOut,
    QueryOut,
    ResearchCallMetadata,
    ResearchStatsOut,
    StageResultOut,
)
from app.services.competitor_prices.url_utils import canonical_domain, canonicalize_url
from app.services.competitor_prices.web_providers import WebProviderError

STRICT_FREE_TIER_MAX_COMPETITORS = 3
STRICT_FREE_TIER_MAX_SOURCES_PER_COMPETITOR = 3
# Public compatibility constant used by older tests/callers. Runtime TTLs are
# status-aware and read from settings.
CACHE_TTL = timedelta(hours=2)


@dataclass
class _CandidatePrice:
    competitor: DiscoveredCompetitor
    source: DiscoveredSource
    price: ExtractedPrice
    confidence: float
    reasons: list[str]
    channel: str
    snippet_only: bool
    corroborated: bool = False
    included_in_summary: bool = False


@dataclass
class _SourceAttempt:
    source: DiscoveredSource
    checked: bool = False
    status: str = "discovered"
    failure_reason: str | None = None


@dataclass
class _CompetitorWork:
    competitor: DiscoveredCompetitor
    sources: list[DiscoveredSource]
    attempts: list[_SourceAttempt]
    candidates: list[_CandidatePrice]


class FreeTierRateLimitError(Exception):
    """Strict-free-tier request budget exhausted for this tenant."""


class ResearchConfigurationError(Exception):
    """The grounded research pipeline is not fully configured."""


class ResearchUnavailableError(Exception):
    """A required stage failed, so an empty result would be misleading."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: str,
        retryable: bool = True,
    ):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable


class CompetitorResearchService:
    def __init__(
        self,
        db: AsyncSession | None,
        deepseek_client: DeepSeekClient | None = None,
        perplexity_client: PerplexitySearchClient | None = None,
        geocoding_client: GoogleGeocodingClient | None = None,
        places_client: PlaceProvider | None = None,
        page_fetcher: SafePageFetcher | None = None,
        search_client: SearchProvider | None = None,
        content_fallback: ContentProvider | None = None,
    ):
        self.db = db
        self.perplexity = perplexity_client or PerplexitySearchClient()
        self.deepseek = deepseek_client or (
            DeepSeekClient() if settings.pricing_extraction_provider == "deepseek" else None
        )
        self.structured_ai = self.deepseek or self.perplexity
        self.geocoder = geocoding_client or GoogleGeocodingClient()
        self.places = places_client or build_place_provider()
        self.search = search_client or perplexity_client or build_search_provider()
        self.page_fetcher = page_fetcher or SafePageFetcher()
        self.content_fallback = content_fallback or build_content_fallback()
        self.extractor = PricingExtractionService(
            self.structured_ai,
            allow_structured_ai=settings.pricing_extraction_provider != "deterministic",
        )
        self._fallback_budget_lock = asyncio.Lock()
        self._ai_fallbacks_claimed = 0
        self._content_fallbacks_claimed = 0
        self._geocoding_requests_claimed = 0

    async def research(
        self,
        payload: CompetitorPriceResearchRequest,
        current_user: CurrentUser,
    ) -> CompetitorPriceResearchResponse:
        business_id = _stable_business_uuid(current_user.business_id)
        warnings: list[str] = []
        payload = _canonical_payload(payload, warnings)
        if (
            settings.pricing_pipeline_v2_enabled
            and payload.max_competitors > settings.pricing_max_competitors_per_run
        ):
            warnings.append(
                "Competitor count was capped to keep this run within its provider budget."
            )
            payload = payload.model_copy(
                update={
                    "max_competitors": max(1, settings.pricing_max_competitors_per_run)
                }
            )
        if settings.strict_free_tier:
            payload = _strict_free_tier_payload(payload, warnings)

        metadata = ResearchCallMetadata()
        pipeline_started = time.perf_counter()
        origin_was_supplied = payload.location.has_geo
        payload = await self._resolve_origin(payload, warnings, metadata)
        cache_key = build_cache_key(payload)

        cached = await self._cached_response(business_id, cache_key)
        if cached:
            cached.warnings = _merge_warnings(warnings, cached.warnings)
            cached.quota = await self.quota(business_id)
            return cached
        used_before = await self._enforce_rate_limit(business_id)

        try:
            discovered = await asyncio.wait_for(
                self.discover_competitors(payload, warnings, metadata),
                timeout=_remaining_deadline(pipeline_started),
            )
        except TimeoutError:
            raise ResearchUnavailableError(
                "Nearby competitor discovery reached the research deadline.",
                code="PRICING_DISCOVERY_TIMEOUT",
                stage="place_discovery",
            ) from None

        without_self = [
            competitor
            for competitor in discovered.competitors
            if not _is_self_competitor(competitor, payload)
        ]
        eligible = without_self[: payload.max_competitors]
        removed_self = len(discovered.competitors) - len(without_self)
        if removed_self:
            warnings.append("Excluded the business being researched from competitor results.")

        semaphore = asyncio.Semaphore(3)

        async def run_competitor(competitor: DiscoveredCompetitor) -> _CompetitorWork:
            async with semaphore:
                return await self._research_competitor(competitor, payload, warnings, metadata)

        tasks = [asyncio.create_task(run_competitor(competitor)) for competitor in eligible]
        work: list[_CompetitorWork] = []
        if tasks:
            done, pending = await asyncio.wait(
                tasks,
                timeout=_remaining_deadline(pipeline_started),
            )
            work = [
                task.result()
                for task in tasks
                if task in done and not task.cancelled() and not task.exception()
            ]
            if pending:
                warnings.append("Source validation reached the 60-second research deadline.")
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        work = [
            item
            for item in work
            if "Outside requested radius" not in item.competitor.exclusion_reasons
        ]
        displayed = [item.competitor for item in work]
        all_candidates = [candidate for item in work for candidate in item.candidates]
        representatives = _finalize_candidates(all_candidates, payload, warnings)
        in_store = _representatives_for_channel(
            representatives, "in_store", all_candidates, warnings
        )
        delivery = _representatives_for_channel(
            representatives, "delivery", all_candidates, warnings
        )
        raw_market_summary = build_market_summary(
            [(candidate.price, candidate.confidence) for candidate in in_store],
            current_price=payload.current_price,
        )
        market_summary = _require_benchmark_sample(raw_market_summary)
        delivery_summary = build_market_summary(
            [(candidate.price, candidate.confidence) for candidate in delivery],
            current_price=None,
        )
        competitors = _build_competitor_outputs(displayed, all_candidates)
        attempts_by_competitor = {item.competitor.name: item.attempts for item in work}
        sources_by_competitor = {item.competitor.name: item.sources for item in work}
        stats = ResearchStatsOut(
            competitorsDiscovered=len(discovered.competitors),
            competitorsIncluded=len({c.competitor.name for c in in_store}),
            sourcesDiscovered=sum(len(item.sources) for item in work),
            sourcesChecked=sum(1 for item in work for attempt in item.attempts if attempt.checked),
            sourcesAccepted=len(
                {
                    canonicalize_url(candidate.source.url)
                    for candidate in all_candidates
                    if candidate.price.match_quality != "weak"
                }
            ),
            corroboratedCompetitors=len(
                {
                    candidate.competitor.name
                    for candidate in all_candidates
                    if candidate.corroborated
                }
            ),
            pagesFetched=metadata.pages_fetched,
            pagesParsed=metadata.pages_parsed,
            deterministicExtractions=metadata.deterministic_extractions,
            aiExtractions=metadata.ai_extractions,
            staleExclusions=sum(
                1 for candidate in all_candidates if candidate.price.freshness_status == "stale"
            ),
            conflictingExclusions=sum(
                1 for candidate in all_candidates if candidate.price.needs_review
            ),
        )
        estimate_summary = None
        if market_summary.sample_size < 2:
            estimate_summary = await self._verified_peer_estimate(
                business_id=business_id,
                payload=payload,
                current_candidates=all_candidates,
            )
        issues = _issues_from_warnings(warnings)
        status = _research_status(
            exact_businesses=market_summary.sample_size,
            estimate=estimate_summary,
            issues=issues,
        )
        duration_ms = round((time.perf_counter() - pipeline_started) * 1000)
        provider_cost_usd = _estimated_provider_cost(
            metadata=metadata,
            places=self.places,
            search=self.search,
            content_fallback=self.content_fallback,
        )
        if provider_cost_usd > settings.pricing_max_provider_cost_usd:
            issue = PricingIssueOut(
                code="PRICING_COST_BUDGET_EXCEEDED",
                stage="aggregation",
                severity="warning",
                retryable=False,
                message=(
                    f"Provider cost ${provider_cost_usd:.3f} exceeded the configured "
                    f"${settings.pricing_max_provider_cost_usd:.2f} item budget."
                ),
            )
            issues.append(issue)
            warnings.append(issue.message)
            if status == "complete":
                status = "partial"
        quota = _quota_from_used(used_before + 1)

        response = CompetitorPriceResearchResponse(
            status=status,
            query=QueryOut(
                businessCategory=payload.business_category,
                targetOffer=payload.target_offer,
                locationLabel=payload.location.label,
                radiusMiles=payload.radius_miles,
                currentPrice=payload.current_price,
            ),
            competitors=competitors,
            marketSummary=market_summary,
            estimateSummary=estimate_summary,
            channelSummaries=ChannelSummariesOut(
                inStore=market_summary,
                delivery=delivery_summary,
            ),
            issues=issues,
            quota=quota,
            warnings=warnings,
            metadata=MetadataOut(
                modelsUsed=sorted(metadata.models_used),
                groundingUsed=GroundingUsedOut(
                    googleSearch=metadata.google_search_used,
                    googleMaps=metadata.google_maps_used,
                    urlContext=metadata.url_context_used,
                    perplexitySearch=metadata.perplexity_search_used,
                    perplexitySonar=metadata.perplexity_sonar_used,
                    sonarExtraction=metadata.sonar_extraction_used,
                    sonarResearch=metadata.sonar_research_used,
                    deepseekExtraction=metadata.deepseek_extraction_used,
                    deepseekResearch=metadata.deepseek_research_used,
                    googleGeocoding=metadata.google_geocoding_used,
                    googlePlaces=metadata.google_places_used,
                ),
                generatedAt=datetime.now(UTC),
                cached=False,
                durationMs=duration_ms,
                researchStats=stats,
                providerStats=ProviderStatsOut(
                    googlePlacesRequests=getattr(self.places, "requests_made", 0),
                    googleGeocodingRequests=metadata.google_geocoding_requests,
                    perplexityRequests=getattr(self.perplexity, "requests_made", 0),
                    perplexityModel=getattr(self.perplexity, "model", None),
                    perplexityUsage=getattr(self.perplexity, "usage_totals", {}),
                    pageFetchRequests=getattr(self.page_fetcher, "requests_made", 0),
                    tokenmartRequests=getattr(self.deepseek, "requests_made", 0),
                    durationMsByProvider={
                        **metadata.duration_ms_by_provider,
                        "perplexity": getattr(self.perplexity, "duration_ms_total", 0),
                        "tokenmart": getattr(self.deepseek, "duration_ms_total", 0),
                    },
                    tokenmartGateway=(
                        settings.tokenmart_base_url if settings.tokenmart_api_key else None
                    ),
                    tokenmartRequestedModel=(
                        getattr(self.deepseek, "model", None)
                        if settings.tokenmart_api_key
                        else None
                    ),
                    tokenmartReturnedModels=sorted(
                        getattr(self.deepseek, "returned_models", set())
                    ),
                    tokenmartUsage=getattr(self.deepseek, "usage_totals", {}),
                ),
                stages=_stage_results(
                    origin_was_supplied=origin_was_supplied,
                    metadata=metadata,
                    stats=stats,
                    warnings=warnings,
                    place_provider=getattr(
                        self.places, "provider_name", settings.pricing_place_provider
                    ),
                    search_provider=getattr(
                        self.search, "provider_name", settings.pricing_search_provider
                    ),
                ),
                providerCostUsd=provider_cost_usd,
                pipelineVersion="v2.1",
            ),
        )

        await self._persist_response(
            business_id=business_id,
            user_id=current_user.user_id,
            payload=payload,
            cache_key=cache_key,
            response=response,
            discovered=displayed,
            sources_by_competitor=sources_by_competitor,
            attempts_by_competitor=attempts_by_competitor,
            candidates=all_candidates,
        )
        return response

    async def _claim_fallback_budget(self, kind: str) -> bool:
        """Atomically reserve one bounded provider fallback for this research run."""
        async with self._fallback_budget_lock:
            if kind == "ai":
                limit = max(0, settings.pricing_max_ai_fallbacks_per_run)
                if self._ai_fallbacks_claimed >= limit:
                    return False
                self._ai_fallbacks_claimed += 1
                return True
            limit = max(0, settings.pricing_max_content_fallbacks_per_run)
            if self._content_fallbacks_claimed >= limit:
                return False
            self._content_fallbacks_claimed += 1
            return True

    async def _claim_geocoding_budget(self) -> bool:
        """Reserve a geocode call so missing place coordinates cannot burst cost."""
        async with self._fallback_budget_lock:
            limit = max(0, settings.pricing_max_geocoding_requests_per_run)
            if self._geocoding_requests_claimed >= limit:
                return False
            self._geocoding_requests_claimed += 1
            return True

    async def _resolve_origin(
        self,
        payload: CompetitorPriceResearchRequest,
        warnings: list[str],
        metadata: ResearchCallMetadata,
    ) -> CompetitorPriceResearchRequest:
        if payload.location.has_geo:
            return payload
        if not await self._claim_geocoding_budget():
            raise ResearchUnavailableError(
                "The pricing run has no geocoding request available for its origin.",
                code="PRICING_GEOCODE_BUDGET_EXHAUSTED",
                stage="geocode",
                retryable=False,
            )
        metadata.google_geocoding_requests += 1
        geocode_started = time.perf_counter()
        try:
            coordinates = await self.geocoder.geocode(payload.location.search_label)
        except GeocodingConfigurationError as exc:
            if settings.pricing_pipeline_v2_enabled:
                raise ResearchUnavailableError(
                    str(exc),
                    code="PRICING_GEOCODE_UNAVAILABLE",
                    stage="geocode",
                    retryable=False,
                ) from exc
            warnings.append(str(exc))
            return payload
        except GeocodingError as exc:
            if settings.pricing_pipeline_v2_enabled:
                raise ResearchUnavailableError(
                    f"Business address could not be geocoded: {exc}",
                    code="PRICING_GEOCODE_UNAVAILABLE",
                    stage="geocode",
                ) from exc
            warnings.append(f"Business address could not be geocoded: {exc}")
            return payload
        finally:
            metadata.duration_ms_by_provider["google_geocoding"] = (
                metadata.duration_ms_by_provider.get("google_geocoding", 0)
                + round((time.perf_counter() - geocode_started) * 1000)
            )
        if not coordinates:
            if settings.pricing_pipeline_v2_enabled:
                raise ResearchUnavailableError(
                    "Business address could not be geocoded.",
                    code="PRICING_GEOCODE_NOT_FOUND",
                    stage="geocode",
                    retryable=False,
                )
            warnings.append("Business address could not be geocoded; radius is unverified.")
            return payload
        metadata.google_geocoding_used = True
        location = payload.location.model_copy(
            update={
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
            }
        )
        return payload.model_copy(update={"location": location})

    async def _research_competitor(
        self,
        competitor: DiscoveredCompetitor,
        payload: CompetitorPriceResearchRequest,
        warnings: list[str],
        metadata: ResearchCallMetadata,
    ) -> _CompetitorWork:
        await self._verify_radius(competitor, payload, warnings, metadata)
        if "Outside requested radius" in competitor.exclusion_reasons:
            return _CompetitorWork(competitor, [], [], [])

        sources = await self.discover_sources(competitor, payload, warnings, metadata)
        selected = _select_source_attempts(sources, payload.max_sources_per_competitor)
        attempts = [_SourceAttempt(source=source) for source in selected]
        candidates: list[_CandidatePrice] = []
        ai_fallback_used = False
        for attempt in attempts:
            attempt.checked = True
            page = None
            if settings.enable_direct_source_fetch:
                fetch_started = time.perf_counter()
                metadata.page_fetch_requests += 1
                page = await self.page_fetcher.fetch(attempt.source.url)
                metadata.duration_ms_by_provider["page_fetch"] = (
                    metadata.duration_ms_by_provider.get("page_fetch", 0)
                    + round((time.perf_counter() - fetch_started) * 1000)
                )
                if page.succeeded:
                    metadata.pages_fetched += 1
                    metadata.pages_parsed += 1
                elif page.error:
                    attempt.failure_reason = page.error
            use_content_fallback = (
                (not page or not page.succeeded)
                and self.content_fallback is not None
                and await self._claim_fallback_budget("content")
            )
            if use_content_fallback:
                fallback_started = time.perf_counter()
                fallback_requests_before = _provider_request_count(self.content_fallback)
                try:
                    fallback_page = await self.content_fallback.fetch(attempt.source.url)
                except WebProviderError as exc:
                    fallback_page = None
                    attempt.failure_reason = str(exc)
                finally:
                    metadata.content_fallback_requests += max(
                        0,
                        _provider_request_count(self.content_fallback)
                        - fallback_requests_before,
                    )
                metadata.duration_ms_by_provider[
                    f"{settings.pricing_content_fallback}_content"
                ] = metadata.duration_ms_by_provider.get(
                    f"{settings.pricing_content_fallback}_content", 0
                ) + round((time.perf_counter() - fallback_started) * 1000)
                if fallback_page and fallback_page.succeeded:
                    page = fallback_page
                    attempt.source.retrieval_method = {
                        "tavily": "tavily_extract",
                        "exa": "exa_contents",
                        "firecrawl": "firecrawl_scrape",
                    }.get(settings.pricing_content_fallback, "direct_fetch")
                    metadata.pages_fetched += 1
                    metadata.pages_parsed += 1
            source_content = (
                page.content
                if page and page.succeeded and page.content
                else " ".join(
                    part
                    for part in [
                        attempt.source.title,
                        attempt.source.snippet,
                        attempt.source.url,
                    ]
                    if part
                )
            )
            if not _source_matches_competitor(
                competitor=competitor,
                source=attempt.source,
                content=source_content,
            ):
                attempt.status = "checked_wrong_business"
                attempt.failure_reason = "Source content does not identify this competitor."
                continue
            extraction_started = time.perf_counter()
            metadata.price_extraction_attempts += 1
            try:
                # Deterministic evidence gets the first chance. A second pass may
                # claim one of the run's globally bounded structured-AI fallbacks.
                extraction = await self.extractor.extract_prices(
                    competitor=competitor,
                    source=attempt.source,
                    target_offer=payload.target_offer,
                    page=page,
                    allow_ai=False,
                )
                if (
                    not extraction.data.prices
                    and not ai_fallback_used
                    and settings.pricing_extraction_provider != "deterministic"
                    and await self._claim_fallback_budget("ai")
                ):
                    ai_fallback_used = True
                    ai_requests_before = _provider_request_count(self.structured_ai)
                    try:
                        extraction = await self.extractor.extract_prices(
                            competitor=competitor,
                            source=attempt.source,
                            target_offer=payload.target_offer,
                            page=page,
                            allow_ai=True,
                        )
                    finally:
                        metadata.ai_extraction_requests += max(
                            0,
                            _provider_request_count(self.structured_ai)
                            - ai_requests_before,
                        )
            except (DeepSeekError, PerplexityError) as exc:
                attempt.status = "failed"
                attempt.failure_reason = str(exc)
                warnings.append(
                    f"Price extraction failed for {attempt.source.url}; tried the next source."
                )
                continue
            finally:
                metadata.duration_ms_by_provider["price_extraction"] = (
                    metadata.duration_ms_by_provider.get("price_extraction", 0)
                    + round((time.perf_counter() - extraction_started) * 1000)
                )

            self._record_call(extraction, metadata, warnings)
            if {"deepseek_extraction", "sonar_extraction"} & extraction.tools_used:
                ai_fallback_used = True
            snippet_only = not bool(page and page.succeeded)
            if extraction.data.prices:
                if {"deepseek_extraction", "sonar_extraction"} & extraction.tools_used:
                    metadata.ai_extractions += len(extraction.data.prices)
                else:
                    metadata.deterministic_extractions += len(extraction.data.prices)
            accepted = 0
            for price in extraction.data.prices:
                if price.match_quality == "weak" or likely_wrong_location(
                    competitor.address, payload.location.city, payload.location.state
                ):
                    continue
                confidence = _score_candidate(
                    competitor=competitor,
                    source=attempt.source,
                    price=price,
                    payload=payload,
                    snippet_only=snippet_only,
                    multiple_sources_support=False,
                )
                candidates.append(
                    _CandidatePrice(
                        competitor=competitor,
                        source=attempt.source,
                        price=price,
                        confidence=confidence.score,
                        reasons=confidence.reasons,
                        channel=_price_channel(attempt.source),
                        snippet_only=snippet_only,
                    )
                )
                accepted += 1
            attempt.status = "accepted" if accepted else "checked_no_price"
            if _has_corroborating_pair(candidates):
                break
        return _CompetitorWork(competitor, sources, attempts, candidates)

    async def _research_competitor_with_sonar(
        self,
        competitor: DiscoveredCompetitor,
        payload: CompetitorPriceResearchRequest,
        warnings: list[str],
        metadata: ResearchCallMetadata,
    ) -> _CompetitorWork:
        """Use one grounded Sonar call instead of a search/fetch/extract chain."""
        today = datetime.now(UTC).date().isoformat()
        prompt = f"""Research the currently published price of this exact offer.

Competitor: {competitor.name}
Address: {competitor.address or "unknown"}
Website: {competitor.website or "unknown"}
Target offer: {payload.target_offer}
Requested market: {payload.location.search_label}

Search current official menus, ordering pages, and reputable menu listings. Return a price
only when the numeric amount and target offer are explicitly supported by a web source.
sourceUrl must be copied exactly from a source used by your web search. Do not estimate,
average, or substitute a general price tier. Use observedAt={today} unless the source gives
a specific date. Keep evidenceText under 12 words and include the item and numeric price.
Return an empty prices array when no source explicitly publishes the target price.
"""
        started = time.perf_counter()
        try:
            result = await self.perplexity.generate_json(
                system=(
                    "You are a grounded local price researcher. Return only source-backed "
                    "structured data and never invent prices or URLs."
                ),
                prompt=prompt,
                response_model=PriceExtractionResult,
            )
        except PerplexityError as exc:
            warnings.append(
                f"Sonar price research failed for {competitor.name}; tried published pages "
                f"instead ({exc})."
            )
            return _CompetitorWork(competitor, [], [], [])

        result.tools_used = {"sonar_extraction"}
        self._record_call(result, metadata, warnings)
        metadata.duration_ms_by_provider["perplexity"] = metadata.duration_ms_by_provider.get(
            "perplexity", 0
        ) + round((time.perf_counter() - started) * 1000)

        search_by_url = {
            canonicalize_url(str(item.get("url") or "")): item
            for item in result.search_results
            if item.get("url")
        }
        grounded_urls = {
            *{canonicalize_url(url) for url in result.citations},
            *search_by_url.keys(),
        }
        sources: list[DiscoveredSource] = []
        attempts: list[_SourceAttempt] = []
        candidates: list[_CandidatePrice] = []
        for price in result.data.prices:
            source_url = canonicalize_url(price.source_url)
            if (
                source_url not in grounded_urls
                or price.match_quality == "weak"
                or not evidence_supports_price(price)
            ):
                continue
            source_data = search_by_url.get(source_url, {})
            source = DiscoveredSource(
                url=price.source_url,
                title=str(source_data.get("title") or price.source_title or "") or None,
                snippet=(str(source_data.get("snippet") or price.evidence_text or "") or None),
                sourceType=infer_source_type(price.source_url, competitor=competitor),
                relevance=1.0,
                publishedAt=str(source_data.get("date") or "") or None,
                updatedAt=str(source_data.get("last_updated") or "") or None,
                retrievalMethod="perplexity_content",
            )
            grounded_price = price.model_copy(
                update={
                    "source_title": source.title,
                    "source_published_at": source.published_at,
                    "source_updated_at": source.updated_at,
                    "verified_at": today,
                    "retrieval_method": "perplexity_content",
                    "extraction_method": "sonar",
                }
            )
            confidence = _score_candidate(
                competitor=competitor,
                source=source,
                price=grounded_price,
                payload=payload,
                snippet_only=True,
                multiple_sources_support=False,
            )
            sources.append(source)
            attempts.append(_SourceAttempt(source=source, checked=True, status="accepted"))
            candidates.append(
                _CandidatePrice(
                    competitor=competitor,
                    source=source,
                    price=grounded_price,
                    confidence=confidence.score,
                    reasons=confidence.reasons,
                    channel=_price_channel(source),
                    snippet_only=True,
                )
            )
        metadata.ai_extractions += len(candidates)
        return _CompetitorWork(competitor, sources, attempts, candidates)

    async def _verify_radius(
        self,
        competitor: DiscoveredCompetitor,
        payload: CompetitorPriceResearchRequest,
        warnings: list[str],
        metadata: ResearchCallMetadata,
    ) -> None:
        if not payload.location.has_geo:
            competitor.exclusion_reasons.append("Distance could not be verified")
            warnings.append(
                f"Excluded {competitor.name} from market summaries because its distance "
                "is unverified."
            )
            return
        if competitor.latitude is not None and competitor.longitude is not None:
            origin = Coordinates(
                latitude=payload.location.latitude,
                longitude=payload.location.longitude,
            )
            destination = Coordinates(
                latitude=competitor.latitude,
                longitude=competitor.longitude,
            )
            competitor.distance_miles = distance_miles(origin, destination)
            competitor.radius_verified = True
            if competitor.distance_miles > payload.radius_miles:
                competitor.exclusion_reasons.append("Outside requested radius")
            return
        if not await self._claim_geocoding_budget():
            competitor.exclusion_reasons.append("Distance could not be verified")
            warnings.append(
                f"Excluded {competitor.name} because its place record omitted coordinates; "
                "the run-wide geocoding budget was already used."
            )
            return
        metadata.google_geocoding_requests += 1
        try:
            lookup_address = competitor.address or (
                f"{competitor.name}, {payload.location.search_label}"
            )
            destination = await self.geocoder.geocode(lookup_address)
        except GeocodingError:
            destination = None
        if not destination:
            competitor.exclusion_reasons.append("Distance could not be verified")
            warnings.append(
                f"Excluded {competitor.name} from market summaries because its distance "
                "is unverified."
            )
            return
        metadata.google_geocoding_used = True
        origin = Coordinates(
            latitude=payload.location.latitude,
            longitude=payload.location.longitude,
        )
        competitor.latitude = destination.latitude
        competitor.longitude = destination.longitude
        competitor.distance_miles = distance_miles(origin, destination)
        competitor.radius_verified = True
        if competitor.distance_miles > payload.radius_miles:
            competitor.exclusion_reasons.append("Outside requested radius")

    async def discover_competitors(
        self,
        payload: CompetitorPriceResearchRequest,
        warnings: list[str],
        metadata: ResearchCallMetadata,
    ) -> CompetitorDiscoveryResult:
        if settings.pricing_pipeline_v2_enabled:
            if not payload.location.has_geo:
                raise ResearchUnavailableError(
                    "Nearby discovery requires a verified origin.",
                    code="PRICING_GEOCODE_UNAVAILABLE",
                    stage="geocode",
                    retryable=False,
                )
            provider_name = getattr(
                self.places, "provider_name", settings.pricing_place_provider
            )
            started = time.perf_counter()
            requests_before = _provider_request_count(self.places)
            try:
                competitors = await self.places.discover(
                    latitude=payload.location.latitude,
                    longitude=payload.location.longitude,
                    radius_miles=payload.radius_miles,
                    business_category=payload.business_category,
                    max_results=payload.max_competitors,
                )
            except (GooglePlacesError, FoursquarePlacesError) as exc:
                raise ResearchUnavailableError(
                    f"{provider_name} nearby-business discovery failed: {exc}",
                    code="PRICING_DISCOVERY_UNAVAILABLE",
                    stage="place_discovery",
                ) from exc
            finally:
                metadata.place_discovery_requests += max(
                    0, _provider_request_count(self.places) - requests_before
                )
                metadata.duration_ms_by_provider[provider_name] = round(
                    (time.perf_counter() - started) * 1000
                )
            if provider_name == "google_places":
                metadata.google_places_used = True
            return CompetitorDiscoveryResult(competitors=competitors)

        if settings.enable_google_places_discovery and payload.location.has_geo:
            started = time.perf_counter()
            try:
                competitors = await self.places.discover(
                    latitude=payload.location.latitude,
                    longitude=payload.location.longitude,
                    radius_miles=payload.radius_miles,
                    business_category=payload.business_category,
                    max_results=payload.max_competitors,
                )
                metadata.google_places_used = True
                metadata.duration_ms_by_provider["google_places"] = round(
                    (time.perf_counter() - started) * 1000
                )
                if competitors:
                    return CompetitorDiscoveryResult(competitors=competitors)
                warnings.append(
                    "Google Places found no matching nearby businesses; "
                    "used grounded web discovery."
                )
            except GooglePlacesError as exc:
                warnings.append(f"{exc} Used grounded web discovery instead.")
        if not settings.enable_perplexity_search:
            raise ResearchConfigurationError(
                "Perplexity Search must be enabled for grounded competitor discovery."
            )
        evidence: list[PerplexitySearchResult] = []
        perplexity_started = time.perf_counter()
        try:
            evidence.extend(
                await self.perplexity.search(
                    _competitor_search_queries(payload),
                    max_results=settings.perplexity_max_results,
                )
            )
        except PerplexityConfigurationError as exc:
            raise ResearchConfigurationError(
                "Set PERPLEXITY_API_KEY for grounded competitor discovery."
            ) from exc
        except PerplexityError as exc:
            raise ResearchConfigurationError(
                "Perplexity competitor discovery failed; no ungrounded results were generated."
            ) from exc

        metadata.perplexity_search_used = True
        metadata.models_used.add("perplexity-search")
        metadata.duration_ms_by_provider["perplexity"] = metadata.duration_ms_by_provider.get(
            "perplexity", 0
        ) + round((time.perf_counter() - perplexity_started) * 1000)
        if not evidence:
            warnings.append("Perplexity Search found no source-backed local competitors.")
            return CompetitorDiscoveryResult(competitors=[])

        evidence_payload = [
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "date": item.date,
            }
            for item in evidence
        ]
        prompt = f"""Convert the supplied Perplexity search evidence into at most
{payload.max_competitors} local competitors for {payload.business_category} offering
{payload.target_offer} near {payload.location.search_label}.

Use only facts explicitly present in the evidence. Do not invent names, addresses, ratings,
phone numbers, websites, or distances. Every competitor must include at least one sourceUrls
entry copied exactly from the evidence. Omit results in the wrong city or unrelated businesses.
Do not include the business being researched: {payload.business_name or "unknown"}.

Evidence JSON:
{json.dumps(evidence_payload)}
"""
        result = await self.structured_ai.generate_json(
            system=(
                "You structure grounded competitor-search evidence. Return only valid JSON and "
                "never add facts that are absent from the supplied evidence."
            ),
            prompt=prompt,
            response_model=CompetitorDiscoveryResult,
        )
        result.tools_used = (
            {"sonar_research"} if self.structured_ai is self.perplexity else {"deepseek_research"}
        )
        self._record_call(result, metadata, warnings)
        allowed_urls = {canonicalize_url(item.url) for item in evidence}
        result.data.competitors = [
            competitor
            for competitor in result.data.competitors
            if any(canonicalize_url(url) in allowed_urls for url in competitor.source_urls)
        ]
        if not result.data.competitors:
            warnings.append("Sonar found no competitors fully supported by search evidence.")
        return result.data

    async def discover_sources(
        self,
        competitor: DiscoveredCompetitor,
        payload: CompetitorPriceResearchRequest,
        warnings: list[str],
        metadata: ResearchCallMetadata,
    ) -> list[DiscoveredSource]:
        known_sources = _known_competitor_sources(competitor)
        if settings.pricing_pipeline_v2_enabled or settings.enable_perplexity_search:
            provider_name = getattr(
                self.search, "provider_name", settings.pricing_search_provider
            )
            started = time.perf_counter()
            requests_before = _provider_request_count(self.search)
            try:
                sources = await discover_sources_with_search(
                    client=self.search,
                    competitor=competitor,
                    payload=payload,
                )
                if sources:
                    if provider_name == "perplexity":
                        metadata.perplexity_search_used = True
                    metadata.models_used.add(f"{provider_name}-search")
                    return _dedupe_and_rank_sources(
                        [*sources, *known_sources],
                        payload.target_offer,
                    )
            except (PerplexityConfigurationError, WebProviderError):
                warnings.append(
                    f"{provider_name} source search is unavailable; "
                    "source discovery used known first-party URLs only."
                )
            except PerplexityError:
                warnings.append(
                    f"{provider_name} source search failed; "
                    "source discovery used known first-party URLs only."
                )
            finally:
                metadata.source_search_requests += max(
                    0, _provider_request_count(self.search) - requests_before
                )
                metadata.duration_ms_by_provider[provider_name] = (
                    metadata.duration_ms_by_provider.get(provider_name, 0)
                    + round((time.perf_counter() - started) * 1000)
                )
        if not known_sources:
            warnings.append(f"No source-backed pricing pages were found for {competitor.name}.")
        return _dedupe_and_rank_sources(known_sources, payload.target_offer)

    def _record_call(
        self,
        result: DeepSeekJSONResult[Any],
        metadata: ResearchCallMetadata,
        warnings: list[str],
    ) -> None:
        if result.model:
            metadata.models_used.add(result.model)
        metadata.perplexity_sonar_used = metadata.perplexity_sonar_used or bool(
            {"sonar_extraction", "sonar_research"} & result.tools_used
        )
        metadata.sonar_extraction_used = (
            metadata.sonar_extraction_used or "sonar_extraction" in result.tools_used
        )
        metadata.sonar_research_used = (
            metadata.sonar_research_used or "sonar_research" in result.tools_used
        )
        metadata.deepseek_extraction_used = (
            metadata.deepseek_extraction_used or "deepseek_extraction" in result.tools_used
        )
        metadata.deepseek_research_used = (
            metadata.deepseek_research_used or "deepseek_research" in result.tools_used
        )
        warnings.extend(w for w in result.warnings if w not in warnings)

    async def _cached_response(
        self, business_id: uuid.UUID, cache_key: str
    ) -> CompetitorPriceResearchResponse | None:
        if self.db is None:
            return None
        now = datetime.now(UTC)
        stmt = (
            select(CompetitorPriceResearchRun)
            .where(
                CompetitorPriceResearchRun.business_id == business_id,
                CompetitorPriceResearchRun.cache_key == cache_key,
                CompetitorPriceResearchRun.expires_at.is_not(None),
                CompetitorPriceResearchRun.expires_at > now,
            )
            .order_by(CompetitorPriceResearchRun.created_at.desc())
            .limit(1)
        )
        run = (await self.db.execute(stmt)).scalars().first()
        if not run:
            return None
        response = CompetitorPriceResearchResponse.model_validate(run.response_json)
        if _cached_response_missing_configured_provider(response):
            return None
        response.metadata.cached = True
        return response

    async def quota(self, business_id: uuid.UUID) -> PricingQuotaOut:
        used = await self._fresh_runs_used(business_id)
        return _quota_from_used(used)

    async def _fresh_runs_used(self, business_id: uuid.UUID) -> int:
        if self.db is None:
            return 0
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        count = await self.db.scalar(
            select(func.count())
            .select_from(CompetitorPriceResearchRun)
            .where(
                CompetitorPriceResearchRun.business_id == business_id,
                CompetitorPriceResearchRun.created_at >= start,
            )
        )
        return int(count or 0)

    async def _enforce_rate_limit(self, business_id: uuid.UUID) -> int:
        used = await self._fresh_runs_used(business_id)
        if (
            settings.pricing_daily_fresh_run_limit > 0
            and used >= settings.pricing_daily_fresh_run_limit
        ):
            raise FreeTierRateLimitError(
                "Daily pricing research limit reached. Cached reports remain available."
            )
        return used

    async def _verified_peer_estimate(
        self,
        *,
        business_id: uuid.UUID,
        payload: CompetitorPriceResearchRequest,
        current_candidates: list[_CandidatePrice],
    ) -> EstimateSummaryOut | None:
        """Build a fallback range from verified observations, never model guesses."""
        values_by_business: dict[str, float] = {}
        for candidate in sorted(
            current_candidates, key=lambda item: item.confidence, reverse=True
        ):
            if (
                candidate.channel != "in_store"
                or candidate.price.match_quality not in {"exact", "close"}
                or candidate.price.freshness_status in {"stale", "expired"}
                or candidate.price.needs_review
                or candidate.price.currency.upper() != "USD"
            ):
                continue
            midpoint = _price_midpoint(candidate.price)
            if midpoint is not None:
                values_by_business.setdefault(candidate.competitor.name.casefold(), midpoint)

        if self.db is not None:
            cutoff = datetime.now(UTC) - timedelta(days=180)
            stmt = (
                select(
                    CompetitorPriceCompetitor.name,
                    CompetitorPriceObservation.price_min,
                    CompetitorPriceObservation.price_max,
                )
                .join(
                    CompetitorPriceSource,
                    CompetitorPriceObservation.source_id == CompetitorPriceSource.id,
                )
                .join(
                    CompetitorPriceCompetitor,
                    CompetitorPriceSource.competitor_id == CompetitorPriceCompetitor.id,
                )
                .join(
                    CompetitorPriceResearchRun,
                    CompetitorPriceCompetitor.run_id == CompetitorPriceResearchRun.id,
                )
                .where(
                    CompetitorPriceResearchRun.business_id == business_id,
                    func.lower(CompetitorPriceResearchRun.business_category)
                    == payload.business_category.casefold(),
                    func.lower(CompetitorPriceResearchRun.target_offer)
                    == payload.target_offer.casefold(),
                    CompetitorPriceObservation.observed_at >= cutoff,
                    CompetitorPriceObservation.price_channel == "in_store",
                    CompetitorPriceObservation.match_quality.in_(["exact", "close"]),
                    CompetitorPriceObservation.currency == "USD",
                    CompetitorPriceObservation.needs_review.is_(False),
                    CompetitorPriceCompetitor.distance_miles.is_not(None),
                    CompetitorPriceCompetitor.distance_miles <= payload.radius_miles,
                )
                .order_by(CompetitorPriceObservation.observed_at.desc())
                .limit(200)
            )
            rows = (await self.db.execute(stmt)).all()
            for name, low, high in rows:
                numeric = [float(value) for value in (low, high) if value is not None]
                if numeric:
                    values_by_business.setdefault(str(name).casefold(), statistics.mean(numeric))

        values = sorted(values_by_business.values())
        if len(values) < 3:
            return None
        q1 = _percentile(values, 0.25)
        q3 = _percentile(values, 0.75)
        iqr = q3 - q1
        filtered = [
            value
            for value in values
            if q1 - 1.5 * iqr <= value <= q3 + 1.5 * iqr
        ]
        if len(filtered) < 3:
            return None
        return EstimateSummaryOut(
            sampleSize=len(filtered),
            priceLow=round(_percentile(filtered, 0.25), 2),
            priceMedian=round(_percentile(filtered, 0.5), 2),
            priceHigh=round(_percentile(filtered, 0.75), 2),
            currency="USD",
            maxAgeDays=180,
            basis="close_equivalent",
        )

    async def _persist_response(
        self,
        *,
        business_id: uuid.UUID,
        user_id: str,
        payload: CompetitorPriceResearchRequest,
        cache_key: str,
        response: CompetitorPriceResearchResponse,
        discovered: list[DiscoveredCompetitor],
        sources_by_competitor: dict[str, list[DiscoveredSource]],
        attempts_by_competitor: dict[str, list[_SourceAttempt]],
        candidates: list[_CandidatePrice],
    ) -> None:
        if self.db is None:
            return
        cache_minutes = (
            settings.pricing_no_evidence_cache_minutes
            if response.status == "no_evidence"
            else settings.pricing_complete_cache_minutes
        )
        run = CompetitorPriceResearchRun(
            business_id=business_id,
            user_id=user_id,
            cache_key=cache_key,
            business_category=payload.business_category,
            target_offer=payload.target_offer,
            location_json=payload.location.model_dump(by_alias=True, mode="json"),
            radius_miles=payload.radius_miles,
            models_used_json=response.metadata.models_used,
            warnings_json=response.warnings,
            response_json=response.model_dump(by_alias=True, mode="json"),
            status=response.status,
            pipeline_version=response.metadata.pipeline_version,
            provider_cost_usd=Decimal(str(response.metadata.provider_cost_usd)),
            duration_ms=response.metadata.duration_ms,
            failure_code=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=max(1, cache_minutes)),
        )
        self.db.add(run)
        await self.db.flush()

        candidates_by_source_url: dict[tuple[str, str], list[_CandidatePrice]] = {}
        for candidate in candidates:
            candidates_by_source_url.setdefault(
                (candidate.competitor.name, canonicalize_url(candidate.source.url)), []
            ).append(candidate)
        for competitor in discovered:
            output = next((c for c in response.competitors if c.name == competitor.name), None)
            comp_row = CompetitorPriceCompetitor(
                run_id=run.id,
                name=competitor.name,
                address=competitor.address,
                website=competitor.website,
                phone=competitor.phone,
                distance_miles=competitor.distance_miles,
                rating=competitor.rating,
                review_count=competitor.review_count,
                confidence=output.confidence if output else 0.0,
                relevance_reason=competitor.relevance_reason,
                source_urls_json=competitor.source_urls,
                place_id=competitor.place_id,
                discovery_provider=competitor.discovery_provider,
            )
            self.db.add(comp_row)
            await self.db.flush()
            for source in sources_by_competitor.get(competitor.name, []):
                attempt = next(
                    (
                        item
                        for item in attempts_by_competitor.get(competitor.name, [])
                        if canonicalize_url(item.source.url) == canonicalize_url(source.url)
                    ),
                    None,
                )
                source_row = CompetitorPriceSource(
                    competitor_id=comp_row.id,
                    url=source.url,
                    title=source.title,
                    source_type=source.source_type,
                    snippet=source.snippet,
                    fetched_at=datetime.now(UTC),
                    attempted_at=datetime.now(UTC) if attempt and attempt.checked else None,
                    attempt_status=attempt.status if attempt else "discovered",
                    failure_reason=attempt.failure_reason if attempt else None,
                    published_at=source.published_at,
                    source_updated_at=source.updated_at,
                    retrieved_at=source.retrieved_at,
                    retrieval_method=source.retrieval_method,
                    http_status=source.http_status,
                    content_type=source.content_type,
                    content_hash=source.content_hash,
                )
                self.db.add(source_row)
                await self.db.flush()
                source_candidates = candidates_by_source_url.get(
                    (competitor.name, canonicalize_url(source.url))
                )
                if not source_candidates:
                    continue
                for candidate in source_candidates:
                    self.db.add(
                        CompetitorPriceObservation(
                            source_id=source_row.id,
                            offer_name=candidate.price.offer_name,
                            normalized_offer_name=candidate.price.normalized_offer_name,
                            price_min=candidate.price.price_min,
                            price_max=candidate.price.price_max,
                            currency=candidate.price.currency,
                            price_type=candidate.price.price_type,
                            evidence_text=candidate.price.evidence_text,
                            observed_at=datetime.combine(
                                candidate.price.observed_at, datetime.min.time(), UTC
                            ),
                            confidence=candidate.confidence,
                            confidence_reasons_json=candidate.reasons,
                            price_channel=candidate.channel,
                            match_quality=candidate.price.match_quality,
                            match_score=candidate.price.match_score,
                            match_reason=candidate.price.match_reason,
                            corroborated=candidate.corroborated,
                            included_in_summary=candidate.included_in_summary,
                            source_published_at=candidate.price.source_published_at,
                            source_updated_at=candidate.price.source_updated_at,
                            verified_at=candidate.price.verified_at,
                            retrieval_method=candidate.price.retrieval_method,
                            extraction_method=candidate.price.extraction_method,
                            freshness_status=candidate.price.freshness_status,
                            needs_review=candidate.price.needs_review,
                        )
                    )


def build_cache_key(payload: CompetitorPriceResearchRequest) -> str:
    parts = [
        "v6",
        "places" if settings.enable_google_places_discovery else "web",
        f"fresh-{settings.third_party_freshness_months}",
        normalize_offer(payload.business_name or ""),
        _source_domain(payload.business_website or ""),
        "".join(character for character in (payload.business_phone or "") if character.isdigit()),
        payload.business_category.strip().lower(),
        canonicalize_offer_label(payload.target_offer).strip().lower(),
        (payload.location.address or "").strip().lower(),
        (payload.location.city or "").strip().lower(),
        (payload.location.state or "").strip().lower(),
        (payload.location.zip_code or "").strip().lower(),
        payload.location.country.strip().lower(),
        _cache_number(payload.location.latitude, 6),
        _cache_number(payload.location.longitude, 6),
        _cache_number(payload.radius_miles, 1),
        str(payload.max_competitors),
        str(payload.max_sources_per_competitor),
        _cache_number(payload.current_price, 2),
    ]
    return "|".join(parts)


def _cache_number(value: float | None, digits: int) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _stable_business_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"pulse-business:{value}")


def _canonical_payload(
    payload: CompetitorPriceResearchRequest,
    warnings: list[str],
) -> CompetitorPriceResearchRequest:
    canonical_offer = canonicalize_offer_label(payload.target_offer)
    if canonical_offer == payload.target_offer:
        return payload
    warnings.append(
        f"Normalized target offer from {payload.target_offer!r} to {canonical_offer!r}."
    )
    return payload.model_copy(update={"target_offer": canonical_offer})


def _strict_free_tier_payload(
    payload: CompetitorPriceResearchRequest,
    warnings: list[str],
) -> CompetitorPriceResearchRequest:
    max_competitors = min(payload.max_competitors, STRICT_FREE_TIER_MAX_COMPETITORS)
    max_sources = min(
        payload.max_sources_per_competitor,
        STRICT_FREE_TIER_MAX_SOURCES_PER_COMPETITOR,
    )
    if (
        max_competitors == payload.max_competitors
        and max_sources == payload.max_sources_per_competitor
    ):
        return payload
    warnings.append(_strict_free_tier_warning(max_competitors, max_sources))
    return payload.model_copy(
        update={
            "max_competitors": max_competitors,
            "max_sources_per_competitor": max_sources,
        }
    )


def _strict_free_tier_warning(max_competitors: int, max_sources: int) -> str:
    return (
        "Strict free-tier mode limited this run to "
        f"{max_competitors} competitors and {max_sources} sources per competitor."
    )


def _merge_warnings(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    for warning in [*primary, *secondary]:
        if warning not in merged:
            merged.append(warning)
    return merged


def _cached_response_missing_configured_provider(
    response: CompetitorPriceResearchResponse,
) -> bool:
    grounding = response.metadata.grounding_used
    if (
        settings.enable_perplexity_search
        and settings.perplexity_api_key
        and not grounding.perplexity_search
    ):
        return True
    if (
        settings.enable_perplexity_sonar
        and settings.perplexity_api_key
        and not grounding.perplexity_sonar
    ):
        return True
    return False


def _competitor_search_queries(payload: CompetitorPriceResearchRequest) -> list[str]:
    offer = canonicalize_offer_label(payload.target_offer)
    location = (
        " ".join(
            part
            for part in [
                payload.location.city,
                payload.location.state,
                payload.location.zip_code,
            ]
            if part
        )
        or payload.location.search_label
    )
    exclude_business = f'-"{payload.business_name.strip()}"' if payload.business_name else ""
    return [
        (
            f'{payload.business_category} competitors "{offer}" near "{location}" '
            f"{exclude_business} address official website"
        ),
        (
            f'local alternatives {payload.business_category} "{offer}" in "{location}" '
            f"{exclude_business} menu price"
        ),
    ]


def _known_competitor_sources(competitor: DiscoveredCompetitor) -> list[DiscoveredSource]:
    sources: list[DiscoveredSource] = []
    if competitor.website:
        try:
            sources.append(
                DiscoveredSource(
                    url=competitor.website,
                    title=f"{competitor.name} website",
                    snippet=competitor.relevance_reason,
                    sourceType="official_site",
                    relevance=0.7,
                )
            )
        except ValueError:
            pass
    for url in competitor.source_urls:
        try:
            sources.append(
                DiscoveredSource(
                    url=url,
                    title=None,
                    snippet=competitor.relevance_reason,
                    sourceType="unknown",
                    relevance=0.4,
                )
            )
        except ValueError:
            pass
    return sources


def _dedupe_and_rank_sources(
    sources: list[DiscoveredSource],
    target_offer: str,
) -> list[DiscoveredSource]:
    by_url: dict[str, DiscoveredSource] = {}
    for source in sources:
        key = canonicalize_url(source.url)
        existing = by_url.get(key)
        if existing is None or _source_rank(source, target_offer) > _source_rank(
            existing, target_offer
        ):
            by_url[key] = source
    return sorted(
        by_url.values(),
        key=lambda source: _source_rank(source, target_offer),
        reverse=True,
    )


def _source_rank(source: DiscoveredSource, target_offer: str) -> float:
    type_bonus = {
        "official_site": 3.0,
        "booking_page": 2.5,
        "google_maps": 2.0,
        "marketplace": 1.25,
        "directory": 1.0,
        "social": 0.5,
        "unknown": 0.25,
    }.get(source.source_type, 0.25)
    return (
        type_bonus
        + min(1.0, max(0.0, source.relevance))
        + _price_snippet_bonus(source, target_offer)
    )


def _source_matches_competitor(
    *, competitor: DiscoveredCompetitor, source: DiscoveredSource, content: str
) -> bool:
    competitor_domain = _source_domain(competitor.website or "")
    source_domain = _source_domain(source.url)
    if competitor_domain and (
        source_domain == competitor_domain or source_domain.endswith(f".{competitor_domain}")
    ):
        return True
    common = {
        "cafe",
        "coffee",
        "company",
        "shop",
        "restaurant",
        "gallery",
        "room",
        "fremont",
    }
    tokens = [
        token
        for token in normalize_offer(competitor.name).split()
        if len(token) >= 3 and token not in common
    ]
    haystack = normalize_offer(
        " ".join(part for part in [source.title, source.snippet, source.url, content] if part)
    )
    return bool(tokens and any(token in haystack.split() for token in tokens))


def _price_snippet_bonus(source: DiscoveredSource, target_offer: str) -> float:
    snippet = source.snippet or ""
    title = source.title or ""
    target = normalize_offer(canonicalize_offer_label(target_offer))
    searchable = normalize_offer(f"{title} {snippet}")
    has_target = bool(target and target in searchable)
    has_price = evidence_contains_price(snippet, target_offer)
    if has_target and has_price:
        return 1.0
    if has_price:
        return 0.25
    if has_target:
        return 0.5
    return 0.0


def _select_source_attempts(
    sources: list[DiscoveredSource], max_sources: int
) -> list[DiscoveredSource]:
    selected: list[DiscoveredSource] = []
    domains: set[str] = set()
    for source in sources:
        domain = _source_domain(source.url)
        if domain and domain in domains:
            continue
        selected.append(source)
        if domain:
            domains.add(domain)
        if len(selected) >= max_sources:
            break
    return selected


def _source_domain(url: str) -> str:
    return canonical_domain(url)


def _price_channel(source: DiscoveredSource) -> str:
    if source.source_type == "marketplace":
        return "delivery"
    if source.source_type in {
        "official_site",
        "booking_page",
        "google_maps",
        "directory",
    }:
        return "in_store"
    return "unknown"


def _prices_agree(left: _CandidatePrice, right: _CandidatePrice) -> bool:
    if (
        left.channel != right.channel
        or left.price.currency.upper() != right.price.currency.upper()
        or _source_domain(left.source.url) == _source_domain(right.source.url)
    ):
        return False
    left_value = _price_midpoint(left.price)
    right_value = _price_midpoint(right.price)
    if left_value is None or right_value is None:
        return False
    tolerance = max(0.50, max(left_value, right_value) * 0.10)
    return abs(left_value - right_value) <= tolerance


def _price_midpoint(price: ExtractedPrice) -> float | None:
    if price.price_min is None and price.price_max is None:
        return None
    if price.price_min is None:
        return price.price_max
    if price.price_max is None:
        return price.price_min
    return (price.price_min + price.price_max) / 2


def _has_corroborating_pair(candidates: list[_CandidatePrice]) -> bool:
    exact = [candidate for candidate in candidates if candidate.price.match_quality == "exact"]
    return any(
        _prices_agree(left, right)
        for index, left in enumerate(exact)
        for right in exact[index + 1 :]
    )


def _score_candidate(
    *,
    competitor: DiscoveredCompetitor,
    source: DiscoveredSource,
    price: ExtractedPrice,
    payload: CompetitorPriceResearchRequest,
    snippet_only: bool,
    multiple_sources_support: bool,
):
    return score_price_confidence(
        ConfidenceInput(
            price=price,
            target_offer=payload.target_offer,
            source_type=source.source_type,
            source_location_matches=location_matches(
                competitor.address, payload.location.city, payload.location.state
            ),
            multiple_sources_support=multiple_sources_support,
            snippet_only=snippet_only,
            possible_location_ambiguity=not competitor.radius_verified,
        )
    )


def _finalize_candidates(
    candidates: list[_CandidatePrice],
    payload: CompetitorPriceResearchRequest,
    warnings: list[str],
) -> list[_CandidatePrice]:
    groups: dict[tuple[str, str, str], list[_CandidatePrice]] = {}
    for candidate in candidates:
        if (
            candidate.price.match_quality != "exact"
            or candidate.channel == "unknown"
            or candidate.price.freshness_status != "current"
            or candidate.price.needs_review
        ):
            continue
        key = (
            candidate.competitor.name,
            candidate.channel,
            candidate.price.currency.upper(),
        )
        groups.setdefault(key, []).append(candidate)

    representatives: list[_CandidatePrice] = []
    for (competitor_name, channel, _currency), rows in groups.items():
        if not rows[0].competitor.radius_verified:
            continue

        clusters = [
            [other for other in rows if other is row or _prices_agree(row, other)] for row in rows
        ]
        corroborating = max(clusters, key=len)
        if len(corroborating) >= 2:
            for candidate in corroborating:
                candidate.corroborated = True
                candidate.included_in_summary = True
                rescored = _score_candidate(
                    competitor=candidate.competitor,
                    source=candidate.source,
                    price=candidate.price,
                    payload=payload,
                    snippet_only=candidate.snippet_only,
                    multiple_sources_support=True,
                )
                candidate.confidence = rescored.score
                candidate.reasons = rescored.reasons
            values = sorted(
                value
                for candidate in corroborating
                if (value := _price_midpoint(candidate.price)) is not None
            )
            median = statistics.median(values)
            closest = min(
                corroborating,
                key=lambda candidate: abs((_price_midpoint(candidate.price) or median) - median),
            )
            representative = _CandidatePrice(
                competitor=closest.competitor,
                source=closest.source,
                price=closest.price.model_copy(update={"price_min": median, "price_max": median}),
                confidence=round(
                    statistics.mean(candidate.confidence for candidate in corroborating), 2
                ),
                reasons=closest.reasons,
                channel=channel,
                snippet_only=closest.snippet_only,
                corroborated=True,
                included_in_summary=True,
            )
            representatives.append(representative)
            continue

        if len(rows) == 1:
            if rows[0].source.source_type in {"official_site", "booking_page"}:
                rows[0].included_in_summary = True
                representatives.append(rows[0])
            else:
                warnings.append(
                    f"Excluded the uncorroborated third-party {channel.replace('_', '-')} "
                    f"price for {competitor_name}."
                )
            continue

        first_party = [
            candidate
            for candidate in rows
            if candidate.source.source_type in {"official_site", "booking_page"}
        ]
        if first_party:
            chosen = max(first_party, key=lambda candidate: candidate.confidence)
            chosen.included_in_summary = True
            representatives.append(chosen)
            warnings.append(
                f"Conflicting {channel.replace('_', '-')} prices for {competitor_name}; "
                "used the first-party source."
            )
        else:
            warnings.append(
                f"Conflicting third-party {channel.replace('_', '-')} prices for "
                f"{competitor_name}; excluded that business from the channel summary."
            )
    return representatives


def _representatives_for_channel(
    representatives: list[_CandidatePrice],
    channel: str,
    candidates: list[_CandidatePrice],
    warnings: list[str],
) -> list[_CandidatePrice]:
    rows = [candidate for candidate in representatives if candidate.channel == channel]
    if not rows:
        return []
    counts = Counter(candidate.price.currency.upper() for candidate in rows)
    currency = sorted(counts, key=lambda item: (-counts[item], item != "USD", item))[0]
    excluded = [candidate for candidate in rows if candidate.price.currency.upper() != currency]
    if excluded:
        warnings.append(
            f"Excluded {len(excluded)} {channel.replace('_', '-')} competitor price(s) "
            f"from the summary because they were not in {currency}."
        )
        excluded_keys = {
            (candidate.competitor.name, candidate.channel, candidate.price.currency.upper())
            for candidate in excluded
        }
        for candidate in candidates:
            key = (
                candidate.competitor.name,
                candidate.channel,
                candidate.price.currency.upper(),
            )
            if key in excluded_keys:
                candidate.included_in_summary = False
    return [candidate for candidate in rows if candidate.price.currency.upper() == currency]


def _is_self_competitor(
    competitor: DiscoveredCompetitor, payload: CompetitorPriceResearchRequest
) -> bool:
    business_name = normalize_offer(payload.business_name or "")
    competitor_name = normalize_offer(competitor.name)
    if business_name and competitor_name:
        if SequenceMatcher(None, business_name, competitor_name).ratio() >= 0.88:
            return True
    business_address = normalize_offer(payload.location.address or "")
    competitor_address = normalize_offer(competitor.address or "")
    if business_address and competitor_address and business_address in competitor_address:
        return True
    business_domain = _source_domain(payload.business_website or "")
    competitor_domain = _source_domain(competitor.website or "")
    if business_domain and business_domain == competitor_domain:
        return True
    business_phone = "".join(
        character for character in (payload.business_phone or "") if character.isdigit()
    )
    competitor_phone = "".join(
        character for character in (competitor.phone or "") if character.isdigit()
    )
    return bool(
        len(business_phone) >= 7
        and len(competitor_phone) >= 7
        and business_phone[-7:] == competitor_phone[-7:]
    )


def _build_competitor_outputs(
    discovered: list[DiscoveredCompetitor],
    candidates: list[_CandidatePrice],
) -> list[CompetitorOut]:
    grouped: dict[str, list[_CandidatePrice]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.competitor.name, []).append(candidate)

    outputs: list[CompetitorOut] = []
    for competitor in discovered:
        rows = grouped.get(competitor.name, [])
        prices = [
            PriceObservationOut(
                offerName=c.price.offer_name,
                normalizedOfferName=c.price.normalized_offer_name,
                priceMin=c.price.price_min,
                priceMax=c.price.price_max,
                currency=c.price.currency,
                priceType=c.price.price_type,
                sourceUrl=c.price.source_url,
                sourceTitle=c.price.source_title or c.source.title,
                evidenceText=c.price.evidence_text,
                observedAt=str(c.price.observed_at),
                confidence=c.confidence,
                confidenceReasons=c.reasons,
                matchQuality=c.price.match_quality,
                matchScore=c.price.match_score,
                matchReason=c.price.match_reason,
                priceChannel=c.channel,
                corroborated=c.corroborated,
                includedInMarketSummary=c.included_in_summary,
                sourcePublishedAt=c.price.source_published_at,
                sourceUpdatedAt=c.price.source_updated_at,
                verifiedAt=c.price.verified_at,
                retrievalMethod=c.price.retrieval_method,
                extractionMethod=c.price.extraction_method,
                freshnessStatus=c.price.freshness_status,
                needsReview=c.price.needs_review,
            )
            for c in rows
        ]
        confidence = round(statistics.mean(c.confidence for c in rows), 2) if rows else 0.0
        outputs.append(
            CompetitorOut(
                name=competitor.name,
                address=competitor.address,
                website=competitor.website,
                distanceMiles=competitor.distance_miles,
                rating=competitor.rating,
                reviewCount=competitor.review_count,
                prices=prices,
                confidence=confidence,
                radiusVerified=competitor.radius_verified,
                exclusionReasons=competitor.exclusion_reasons,
                placeId=competitor.place_id,
                discoveryProvider=competitor.discovery_provider,
            )
        )
    return outputs


def _require_benchmark_sample(summary: MarketSummaryOut) -> MarketSummaryOut:
    if summary.sample_size >= 2:
        return summary
    return summary.model_copy(
        update={
            "price_low": None,
            "price_median": None,
            "price_high": None,
            "price_average": None,
            "price_iqr": None,
            "recommended_positioning": (
                "At least two unique verified businesses are required for market positioning."
            ),
            "confidence": 0.0,
        }
    )


def _issues_from_warnings(warnings: list[str]) -> list[PricingIssueOut]:
    issues: list[PricingIssueOut] = []
    seen: set[tuple[str, str]] = set()
    for warning in warnings:
        lowered = warning.casefold()
        code = "PRICING_INFORMATION"
        stage = "aggregation"
        severity = "info"
        retryable = False
        if "source search" in lowered:
            code = "PRICING_SOURCE_SEARCH_UNAVAILABLE"
            stage = "source_search"
            severity = "warning"
            retryable = True
        elif "source validation reached" in lowered or "deadline" in lowered:
            code = "PRICING_DEADLINE_EXCEEDED"
            stage = "content_fetch"
            severity = "warning"
            retryable = True
        elif "price extraction failed" in lowered:
            code = "PRICING_EXTRACTION_DEGRADED"
            stage = "price_extraction"
            severity = "warning"
            retryable = True
        elif "retrieval failed" in lowered:
            code = "PRICING_CONTENT_FETCH_DEGRADED"
            stage = "content_fetch"
            severity = "warning"
            retryable = True
        key = (code, warning)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            PricingIssueOut(
                code=code,
                stage=stage,
                severity=severity,
                retryable=retryable,
                message=warning,
            )
        )
    return issues


def _research_status(
    *,
    exact_businesses: int,
    estimate: EstimateSummaryOut | None,
    issues: list[PricingIssueOut],
) -> str:
    degraded = any(issue.severity in {"warning", "error"} for issue in issues)
    if exact_businesses >= 2 and not degraded:
        return "complete"
    if exact_businesses > 0 or estimate is not None or degraded:
        return "partial"
    return "no_evidence"


def _stage_results(
    *,
    origin_was_supplied: bool,
    metadata: ResearchCallMetadata,
    stats: ResearchStatsOut,
    warnings: list[str],
    place_provider: str,
    search_provider: str,
) -> list[StageResultOut]:
    source_degraded = any("source search" in value.casefold() for value in warnings)
    content_degraded = any(
        "source validation reached" in value.casefold()
        or "retrieval failed" in value.casefold()
        for value in warnings
    )
    extraction_degraded = any("price extraction failed" in value.casefold() for value in warnings)
    return [
        StageResultOut(
            stage="geocode",
            status="skipped" if origin_was_supplied else "ok",
            provider=None if origin_was_supplied else "google_geocoding",
            attempts=metadata.google_geocoding_requests,
            durationMs=metadata.duration_ms_by_provider.get("google_geocoding", 0),
        ),
        StageResultOut(
            stage="place_discovery",
            status="ok",
            provider=place_provider,
            attempts=metadata.place_discovery_requests,
            durationMs=metadata.duration_ms_by_provider.get(place_provider, 0),
        ),
        StageResultOut(
            stage="source_search",
            status=(
                "degraded"
                if source_degraded
                else ("ok" if metadata.source_search_requests else "skipped")
            ),
            provider=search_provider,
            attempts=metadata.source_search_requests,
            durationMs=metadata.duration_ms_by_provider.get(search_provider, 0),
            code="PRICING_SOURCE_SEARCH_UNAVAILABLE" if source_degraded else None,
        ),
        StageResultOut(
            stage="content_fetch",
            status=(
                "degraded"
                if content_degraded
                else "ok"
                if metadata.page_fetch_requests + metadata.content_fallback_requests
                else "skipped"
            ),
            provider=(
                f"safe_fetch+{settings.pricing_content_fallback}"
                if settings.pricing_content_fallback != "none"
                else "safe_fetch"
            ),
            attempts=metadata.page_fetch_requests + metadata.content_fallback_requests,
            durationMs=sum(
                duration
                for provider, duration in metadata.duration_ms_by_provider.items()
                if "fetch" in provider or "content" in provider
            ),
        ),
        StageResultOut(
            stage="price_extraction",
            status=(
                "degraded"
                if extraction_degraded
                else "ok"
                if metadata.price_extraction_attempts
                else "skipped"
            ),
            provider=(
                f"deterministic+{settings.pricing_extraction_provider}"
                if metadata.ai_extraction_requests
                else "deterministic"
            ),
            attempts=metadata.price_extraction_attempts,
            durationMs=metadata.duration_ms_by_provider.get("price_extraction", 0),
        ),
        StageResultOut(stage="aggregation", status="ok", provider="pulseq"),
    ]


def _estimated_provider_cost(
    *,
    metadata: ResearchCallMetadata,
    places: Any,
    search: Any,
    content_fallback: Any,
) -> float:
    place_name = getattr(places, "provider_name", settings.pricing_place_provider)
    place_rate = 0.035 if place_name == "google_places" else 0.015
    search_name = getattr(search, "provider_name", settings.pricing_search_provider)
    search_rate = {"perplexity": 0.005, "tavily": 0.008, "exa": 0.007}.get(
        search_name, 0.0
    )
    content_name = getattr(content_fallback, "provider_name", "none")
    content_rate = {"tavily": 0.0032, "exa": 0.001, "firecrawl": 0.001}.get(
        content_name, 0.0
    )
    total = metadata.google_geocoding_requests * 0.005
    total += metadata.place_discovery_requests * place_rate
    total += metadata.source_search_requests * search_rate
    total += metadata.content_fallback_requests * content_rate
    total += metadata.ai_extraction_requests * 0.012
    return round(total, 4)


def _provider_request_count(provider: Any) -> int:
    try:
        return int(getattr(provider, "requests_made", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _quota_from_used(used: int) -> PricingQuotaOut:
    limit = max(0, settings.pricing_daily_fresh_run_limit)
    now = datetime.now(UTC)
    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return PricingQuotaOut(
        dailyLimit=limit,
        used=max(0, used),
        remaining=max(0, limit - used) if limit else 2_147_483_647,
        resetsAt=reset,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * min(1.0, max(0.0, fraction))
    lower = int(position)
    upper = min(len(values) - 1, lower + 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _remaining_deadline(started: float) -> float:
    elapsed = time.perf_counter() - started
    return max(0.1, settings.competitor_research_deadline_seconds - elapsed)
