"""Schemas for competitor price research.

The public route intentionally uses camelCase aliases because this workflow is
consumed directly by the React app and mirrors the product-facing API contract.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

PriceType = Literal["fixed", "range", "starts_at", "hourly", "package", "quote_based", "unknown"]
SourceType = Literal[
    "official_site",
    "booking_page",
    "google_maps",
    "directory",
    "marketplace",
    "social",
    "unknown",
]
MatchQuality = Literal["exact", "close", "weak"]
PriceChannel = Literal["in_store", "delivery", "unknown"]
RetrievalMethod = Literal["direct_fetch", "perplexity_content", "search_snippet", "none"]
ExtractionMethod = Literal[
    "json_ld",
    "visible_text",
    "search_snippet",
    "sonar",
    "tokenmart",
    "method_consensus",
]
FreshnessStatus = Literal["current", "stale", "unknown", "expired"]
DiscoveryProvider = Literal["google_places", "perplexity"]


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)


class LocationIn(CamelModel):
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = Field(default=None, alias="zip")
    country: str = "US"
    latitude: float | None = None
    longitude: float | None = None

    @property
    def label(self) -> str:
        if self.city and self.state:
            return f"{self.city}, {self.state}"
        if self.address:
            return self.address
        if self.latitude is not None and self.longitude is not None:
            return f"{self.latitude:.4f}, {self.longitude:.4f}"
        return self.country

    @property
    def search_label(self) -> str:
        parts = [self.address, self.city, self.state, self.zip_code, self.country]
        label = ", ".join(part.strip() for part in parts if part and part.strip())
        if self.has_geo:
            coordinates = f"{self.latitude:.6f}, {self.longitude:.6f}"
            return f"{label} ({coordinates})" if label else coordinates
        return label or self.label

    @property
    def has_geo(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class CompetitorPriceResearchRequest(CamelModel):
    business_name: str | None = Field(default=None, alias="businessName")
    business_website: str | None = Field(default=None, alias="businessWebsite")
    business_phone: str | None = Field(default=None, alias="businessPhone")
    business_category: str = Field(alias="businessCategory", min_length=1)
    target_offer: str = Field(alias="targetOffer", min_length=1)
    location: LocationIn
    radius_miles: float = Field(default=5, alias="radiusMiles", gt=0)
    max_competitors: int = Field(default=5, alias="maxCompetitors", ge=1)
    max_sources_per_competitor: int = Field(default=3, alias="maxSourcesPerCompetitor", ge=1)
    current_price: float | None = Field(default=None, alias="currentPrice", ge=0)

    @field_validator("business_category", "target_offer")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field cannot be blank")
        return cleaned

    @field_validator("radius_miles")
    @classmethod
    def cap_radius(cls, value: float) -> float:
        return min(value, 25.0)

    @field_validator("max_competitors")
    @classmethod
    def cap_competitors(cls, value: int) -> int:
        return min(value, 10)

    @field_validator("max_sources_per_competitor")
    @classmethod
    def cap_sources(cls, value: int) -> int:
        return min(value, 5)

    @model_validator(mode="after")
    def require_location(self) -> CompetitorPriceResearchRequest:
        has_city_state = bool(self.location.city and self.location.state)
        if not has_city_state and not self.location.has_geo:
            raise ValueError("location must include city/state or latitude/longitude")
        return self


class QueryOut(CamelModel):
    business_category: str = Field(alias="businessCategory")
    target_offer: str = Field(alias="targetOffer")
    location_label: str = Field(alias="locationLabel")
    radius_miles: float = Field(alias="radiusMiles")


class PriceObservationOut(CamelModel):
    offer_name: str = Field(alias="offerName")
    normalized_offer_name: str = Field(alias="normalizedOfferName")
    price_min: float | None = Field(alias="priceMin")
    price_max: float | None = Field(alias="priceMax")
    currency: str = "USD"
    price_type: PriceType = Field(alias="priceType")
    source_url: str = Field(alias="sourceUrl")
    source_title: str | None = Field(default=None, alias="sourceTitle")
    evidence_text: str = Field(alias="evidenceText")
    observed_at: str = Field(alias="observedAt")
    confidence: float
    confidence_reasons: list[str] = Field(default_factory=list, alias="confidenceReasons")
    match_quality: MatchQuality = Field(default="weak", alias="matchQuality")
    price_channel: PriceChannel = Field(default="unknown", alias="priceChannel")
    corroborated: bool = False
    included_in_market_summary: bool = Field(default=False, alias="includedInMarketSummary")
    source_published_at: str | None = Field(default=None, alias="sourcePublishedAt")
    source_updated_at: str | None = Field(default=None, alias="sourceUpdatedAt")
    verified_at: str | None = Field(default=None, alias="verifiedAt")
    retrieval_method: RetrievalMethod = Field(default="search_snippet", alias="retrievalMethod")
    extraction_method: ExtractionMethod = Field(default="search_snippet", alias="extractionMethod")
    freshness_status: FreshnessStatus = Field(default="unknown", alias="freshnessStatus")
    needs_review: bool = Field(default=False, alias="needsReview")


class CompetitorOut(CamelModel):
    name: str
    address: str | None = None
    website: str | None = None
    distance_miles: float | None = Field(default=None, alias="distanceMiles")
    rating: float | None = None
    review_count: int | None = Field(default=None, alias="reviewCount")
    prices: list[PriceObservationOut] = Field(default_factory=list)
    confidence: float = 0.0
    radius_verified: bool = Field(default=False, alias="radiusVerified")
    exclusion_reasons: list[str] = Field(default_factory=list, alias="exclusionReasons")
    place_id: str | None = Field(default=None, alias="placeId")
    discovery_provider: DiscoveryProvider = Field(default="perplexity", alias="discoveryProvider")


class MarketSummaryOut(CamelModel):
    sample_size: int = Field(alias="sampleSize")
    price_low: float | None = Field(alias="priceLow")
    price_median: float | None = Field(alias="priceMedian")
    price_high: float | None = Field(alias="priceHigh")
    price_average: float | None = Field(default=None, alias="priceAverage")
    price_iqr: float | None = Field(default=None, alias="priceIqr")
    currency: str = "USD"
    recommended_positioning: str = Field(alias="recommendedPositioning")
    confidence: float


class ChannelSummariesOut(CamelModel):
    in_store: MarketSummaryOut = Field(alias="inStore")
    delivery: MarketSummaryOut


class ResearchStatsOut(CamelModel):
    competitors_discovered: int = Field(default=0, alias="competitorsDiscovered")
    competitors_included: int = Field(default=0, alias="competitorsIncluded")
    sources_discovered: int = Field(default=0, alias="sourcesDiscovered")
    sources_checked: int = Field(default=0, alias="sourcesChecked")
    sources_accepted: int = Field(default=0, alias="sourcesAccepted")
    corroborated_competitors: int = Field(default=0, alias="corroboratedCompetitors")
    pages_fetched: int = Field(default=0, alias="pagesFetched")
    pages_parsed: int = Field(default=0, alias="pagesParsed")
    deterministic_extractions: int = Field(default=0, alias="deterministicExtractions")
    ai_extractions: int = Field(default=0, alias="aiExtractions")
    stale_exclusions: int = Field(default=0, alias="staleExclusions")
    conflicting_exclusions: int = Field(default=0, alias="conflictingExclusions")


class ProviderStatsOut(CamelModel):
    google_places_requests: int = Field(default=0, alias="googlePlacesRequests")
    google_geocoding_requests: int = Field(default=0, alias="googleGeocodingRequests")
    perplexity_requests: int = Field(default=0, alias="perplexityRequests")
    perplexity_model: str | None = Field(default=None, alias="perplexityModel")
    perplexity_usage: dict[str, int] = Field(default_factory=dict, alias="perplexityUsage")
    page_fetch_requests: int = Field(default=0, alias="pageFetchRequests")
    tokenmart_requests: int = Field(default=0, alias="tokenmartRequests")
    duration_ms_by_provider: dict[str, int] = Field(
        default_factory=dict, alias="durationMsByProvider"
    )
    tokenmart_gateway: str | None = Field(default=None, alias="tokenmartGateway")
    tokenmart_requested_model: str | None = Field(default=None, alias="tokenmartRequestedModel")
    tokenmart_returned_models: list[str] = Field(
        default_factory=list, alias="tokenmartReturnedModels"
    )
    tokenmart_usage: dict[str, int] = Field(default_factory=dict, alias="tokenmartUsage")


class GroundingUsedOut(CamelModel):
    google_search: bool = Field(default=False, alias="googleSearch")
    google_maps: bool = Field(default=False, alias="googleMaps")
    url_context: bool = Field(default=False, alias="urlContext")
    perplexity_search: bool = Field(default=False, alias="perplexitySearch")
    perplexity_sonar: bool = Field(default=False, alias="perplexitySonar")
    sonar_extraction: bool = Field(default=False, alias="sonarExtraction")
    sonar_research: bool = Field(default=False, alias="sonarResearch")
    deepseek_extraction: bool = Field(default=False, alias="deepseekExtraction")
    deepseek_research: bool = Field(default=False, alias="deepseekResearch")
    google_geocoding: bool = Field(default=False, alias="googleGeocoding")
    google_places: bool = Field(default=False, alias="googlePlaces")


class MetadataOut(CamelModel):
    models_used: list[str] = Field(default_factory=list, alias="modelsUsed")
    grounding_used: GroundingUsedOut = Field(alias="groundingUsed")
    generated_at: datetime = Field(alias="generatedAt")
    cached: bool = False
    duration_ms: int | None = Field(default=None, alias="durationMs")
    research_stats: ResearchStatsOut = Field(
        default_factory=ResearchStatsOut, alias="researchStats"
    )
    provider_stats: ProviderStatsOut = Field(
        default_factory=ProviderStatsOut, alias="providerStats"
    )


class CompetitorPriceResearchResponse(CamelModel):
    query: QueryOut
    competitors: list[CompetitorOut] = Field(default_factory=list)
    market_summary: MarketSummaryOut = Field(alias="marketSummary")
    channel_summaries: ChannelSummariesOut | None = Field(default=None, alias="channelSummaries")
    warnings: list[str] = Field(default_factory=list)
    metadata: MetadataOut


class PriceHistoryItemOut(CamelModel):
    id: str
    target_offer: str = Field(alias="targetOffer")
    business_category: str = Field(alias="businessCategory")
    generated_at: datetime = Field(alias="generatedAt")
    price_median: float | None = Field(alias="priceMedian")
    sample_size: int = Field(alias="sampleSize")
    confidence: float
    change_percent: float | None = Field(default=None, alias="changePercent")


class PriceWatchIn(CamelModel):
    enabled: bool = True
    interval_hours: int = Field(default=24, alias="intervalHours", ge=2, le=168)
    request: CompetitorPriceResearchRequest


class PriceWatchOut(PriceWatchIn):
    last_run_at: datetime | None = Field(default=None, alias="lastRunAt")
    next_run_at: datetime = Field(alias="nextRunAt")


class DiscoveredCompetitor(CamelModel):
    name: str
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    rating: float | None = None
    review_count: int | None = Field(default=None, alias="reviewCount")
    distance_miles: float | None = Field(default=None, alias="distanceMiles")
    latitude: float | None = None
    longitude: float | None = None
    relevance_reason: str = Field(default="", alias="relevanceReason")
    source_urls: list[str] = Field(default_factory=list, alias="sourceUrls")
    radius_verified: bool = Field(default=False, alias="radiusVerified")
    exclusion_reasons: list[str] = Field(default_factory=list, alias="exclusionReasons")
    place_id: str | None = Field(default=None, alias="placeId")
    discovery_provider: DiscoveryProvider = Field(default="perplexity", alias="discoveryProvider")


class CompetitorDiscoveryResult(CamelModel):
    competitors: list[DiscoveredCompetitor] = Field(default_factory=list)


class DiscoveredSource(CamelModel):
    url: str
    title: str | None = None
    snippet: str | None = None
    source_type: SourceType = Field(default="unknown", alias="sourceType")
    relevance: float = 0.0
    published_at: str | None = Field(default=None, alias="publishedAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    retrieved_at: datetime | None = Field(default=None, alias="retrievedAt")
    retrieval_method: RetrievalMethod = Field(default="search_snippet", alias="retrievalMethod")
    http_status: int | None = Field(default=None, alias="httpStatus")
    content_type: str | None = Field(default=None, alias="contentType")
    content_hash: str | None = Field(default=None, alias="contentHash")

    @field_validator("url")
    @classmethod
    def validate_urlish(cls, value: str) -> str:
        parsed = HttpUrl(value)
        return str(parsed)


class ExtractedPrice(CamelModel):
    offer_name: str = Field(alias="offerName")
    normalized_offer_name: str = Field(alias="normalizedOfferName")
    price_min: float | None = Field(default=None, alias="priceMin")
    price_max: float | None = Field(default=None, alias="priceMax")
    currency: str = "USD"
    price_type: PriceType = Field(default="unknown", alias="priceType")
    source_url: str = Field(alias="sourceUrl")
    source_title: str | None = Field(default=None, alias="sourceTitle")
    evidence_text: str = Field(alias="evidenceText")
    observed_at: date = Field(alias="observedAt")
    match_quality: MatchQuality = Field(default="weak", alias="matchQuality")
    notes: str | None = None
    source_published_at: str | None = Field(default=None, alias="sourcePublishedAt")
    source_updated_at: str | None = Field(default=None, alias="sourceUpdatedAt")
    verified_at: str | None = Field(default=None, alias="verifiedAt")
    retrieval_method: RetrievalMethod = Field(default="search_snippet", alias="retrievalMethod")
    extraction_method: ExtractionMethod = Field(default="search_snippet", alias="extractionMethod")
    freshness_status: FreshnessStatus = Field(default="unknown", alias="freshnessStatus")
    needs_review: bool = Field(default=False, alias="needsReview")


class PriceExtractionResult(CamelModel):
    prices: list[ExtractedPrice] = Field(default_factory=list)


class ResearchCallMetadata(CamelModel):
    models_used: set[str] = Field(default_factory=set, alias="modelsUsed")
    google_search_used: bool = Field(default=False, alias="googleSearchUsed")
    google_maps_used: bool = Field(default=False, alias="googleMapsUsed")
    url_context_used: bool = Field(default=False, alias="urlContextUsed")
    perplexity_search_used: bool = Field(default=False, alias="perplexitySearchUsed")
    perplexity_sonar_used: bool = Field(default=False, alias="perplexitySonarUsed")
    sonar_extraction_used: bool = Field(default=False, alias="sonarExtractionUsed")
    sonar_research_used: bool = Field(default=False, alias="sonarResearchUsed")
    deepseek_extraction_used: bool = Field(default=False, alias="deepseekExtractionUsed")
    deepseek_research_used: bool = Field(default=False, alias="deepseekResearchUsed")
    google_geocoding_used: bool = Field(default=False, alias="googleGeocodingUsed")
    google_places_used: bool = Field(default=False, alias="googlePlacesUsed")
    google_places_requests: int = 0
    google_geocoding_requests: int = 0
    perplexity_requests: int = 0
    page_fetch_requests: int = 0
    tokenmart_requests: int = 0
    pages_fetched: int = 0
    pages_parsed: int = 0
    deterministic_extractions: int = 0
    ai_extractions: int = 0
    stale_exclusions: int = 0
    conflicting_exclusions: int = 0
    duration_ms_by_provider: dict[str, int] = Field(default_factory=dict)
