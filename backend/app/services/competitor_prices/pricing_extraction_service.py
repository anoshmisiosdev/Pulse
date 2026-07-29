"""Strict price extraction from grounded pages and Perplexity Sonar."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import extruct
from dateutil.parser import parse as parse_date
from lxml import html

from app.core.config import settings
from app.services.competitor_prices.confidence_scoring import (
    canonicalize_offer_label,
    evidence_contains_price,
    evidence_supports_price,
    normalize_offer,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekClient,
    DeepSeekJSONResult,
)
from app.services.competitor_prices.page_fetcher import PageFetchResult
from app.services.competitor_prices.perplexity_client import PerplexitySearchClient
from app.services.competitor_prices.schemas import (
    DiscoveredCompetitor,
    DiscoveredSource,
    ExtractedPrice,
    PriceExtractionResult,
)

_PRICE_RE = re.compile(
    r"(?<!\w)(?:[$]\s*)(?P<min>\d{1,4}(?:,\d{3})?(?:\.\d{1,2})?)"
    r"(?:\s*[-\u2013]\s*(?:[$]\s*)?(?P<max>\d{1,4}(?:,\d{3})?(?:\.\d{1,2})?))?"
)
_TIER_RE = re.compile(r"(?:^|\b)(?:price\s*:?\s*)?\${2,4}(?:\b|$)", re.IGNORECASE)

STRICT_PRICE_SYSTEM = """You are a price extraction engine.
Extract only prices explicitly present in the provided source content.
Do not infer, estimate, average, or invent prices.
If the source does not contain a price for the target offer, return an empty prices array.
Every extracted price must include short source-backed evidenceText with the item name
and numeric price.
Keep evidenceText under 12 words. Do not copy long menu descriptions, policies, or promotional text.
If the evidence does not directly support the price, omit the price.
Do not treat Google/Yelp "$$" price tiers as exact prices.
"""


class PricingExtractionService:
    def __init__(
        self,
        structured_client: DeepSeekClient | PerplexitySearchClient | None = None,
    ):
        # Explicit DeepSeek injection remains supported for legacy unit tests.
        # Production defaults to the same Perplexity client used by research.
        self.structured_client = structured_client or PerplexitySearchClient()
        self.uses_sonar = structured_client is None or isinstance(
            self.structured_client, PerplexitySearchClient
        )

    async def extract_prices(
        self,
        *,
        competitor: DiscoveredCompetitor,
        source: DiscoveredSource,
        target_offer: str,
        page: PageFetchResult | None = None,
        allow_ai: bool = True,
    ) -> DeepSeekJSONResult[PriceExtractionResult]:
        today = datetime.now(UTC).date().isoformat()
        target_offer = canonicalize_offer_label(target_offer)
        if page and page.succeeded and page.content:
            source.retrieved_at = page.retrieved_at
            source.retrieval_method = "direct_fetch"
            source.http_status = page.status_code
            source.content_type = page.content_type
            source.content_hash = page.content_hash
            json_ld_prices = _extract_json_ld_prices(
                content=page.content,
                source=source,
                target_offer=target_offer,
                today=today,
            )
            visible_prices = _extract_visible_text_prices(
                content=page.content,
                source=source,
                target_offer=target_offer,
                today=today,
            )
            deterministic = _resolve_method_votes(json_ld_prices, visible_prices)
            if deterministic:
                return DeepSeekJSONResult(
                    data=PriceExtractionResult(prices=deterministic),
                    tools_used=set(),
                )

        snippet_result = _extract_price_from_snippet(
            source=source,
            target_offer=target_offer,
            today=today,
        )
        if snippet_result.data.prices:
            return snippet_result

        content = page.content if page and page.content else source.snippet or ""
        candidate_content = _candidate_content(content, target_offer)
        if not candidate_content:
            return DeepSeekJSONResult(data=PriceExtractionResult(prices=[]), tools_used=set())
        if not allow_ai:
            return DeepSeekJSONResult(data=PriceExtractionResult(prices=[]), tools_used=set())

        prompt = f"""Return json with prices only for the target offer or a close equivalent.
Do not infer prices from typical menus or general knowledge.

Target offer: {target_offer}
Competitor: {competitor.name}
Competitor address: {competitor.address or "unknown"}
Source URL: {source.url}
Source title: {source.title or "unknown"}
Source type: {source.source_type}
Bounded source evidence:
{candidate_content}

Return JSON with prices only for the target offer or a close equivalent.
Use observedAt="{today}" unless the source explicitly shows a different observed date.
sourceUrl must be the source URL above.
"""
        if self.uses_sonar and not settings.enable_perplexity_sonar:
            return DeepSeekJSONResult(
                data=PriceExtractionResult(prices=[]),
                warnings=[
                    "Perplexity Sonar extraction is disabled; only deterministic sources were used."
                ],
                tools_used=set(),
            )
        if not self.uses_sonar and not settings.enable_deepseek_extraction:
            return DeepSeekJSONResult(
                data=PriceExtractionResult(prices=[]),
                warnings=[
                    "DeepSeek extraction is disabled; only deterministic snippets were used."
                ],
                tools_used=set(),
            )

        result = await self.structured_client.generate_json(
            system=STRICT_PRICE_SYSTEM,
            prompt=prompt,
            response_model=PriceExtractionResult,
        )
        result.data.prices = _valid_source_prices(result.data.prices, source)
        method = "sonar" if self.uses_sonar else "tokenmart"
        result.data.prices = [
            _with_provenance(price, source, today, method) for price in result.data.prices
        ]
        return result


def _valid_source_prices(
    prices: list[ExtractedPrice],
    source: DiscoveredSource,
) -> list[ExtractedPrice]:
    return [
        price
        for price in prices
        if price.source_url.rstrip("/") == source.url.rstrip("/") and evidence_supports_price(price)
    ]


def _extract_price_from_snippet(
    *,
    source: DiscoveredSource,
    target_offer: str,
    today: str,
) -> DeepSeekJSONResult[PriceExtractionResult]:
    snippet = source.snippet or ""
    target = normalize_offer(target_offer)
    if not snippet or not target:
        return DeepSeekJSONResult(data=PriceExtractionResult(prices=[]), tools_used=set())

    for segment in _snippet_segments(snippet):
        normalized_segment = normalize_offer(segment)
        if target not in normalized_segment or _TIER_RE.search(segment):
            continue
        match = _PRICE_RE.search(segment)
        if not match:
            continue

        price_min = _parse_price(match.group("min"))
        price_max = _parse_price(match.group("max")) if match.group("max") else price_min
        evidence = _short_evidence(segment)
        price = ExtractedPrice.model_validate(
            {
                "offerName": target_offer,
                "normalizedOfferName": normalize_offer(target_offer),
                "priceMin": price_min,
                "priceMax": price_max,
                "currency": "USD",
                "priceType": "range" if price_max != price_min else "fixed",
                "sourceUrl": source.url,
                "sourceTitle": source.title,
                "evidenceText": evidence,
                "observedAt": _observation_date(source, today),
                "matchQuality": "exact",
                "notes": "Extracted deterministically from grounded source snippet.",
                "sourcePublishedAt": source.published_at,
                "sourceUpdatedAt": source.updated_at,
                "verifiedAt": today,
                "retrievalMethod": source.retrieval_method,
                "extractionMethod": "search_snippet",
                "freshnessStatus": _freshness_status(source, today),
            }
        )
        if evidence_supports_price(price):
            return DeepSeekJSONResult(data=PriceExtractionResult(prices=[price]), tools_used=set())

    return DeepSeekJSONResult(data=PriceExtractionResult(prices=[]), tools_used=set())


def _snippet_segments(snippet: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", snippet).strip()
    if not cleaned:
        return []
    segments = [
        segment.strip(" -*\u2022")
        for segment in re.split(r"(?:\n|\r|[|\u2022]| {2,})", snippet)
        if segment.strip(" -*\u2022")
    ]
    if cleaned not in segments:
        segments.append(cleaned)
    return segments


def _parse_price(value: str) -> float:
    return float(value.replace(",", ""))


def _short_evidence(segment: str) -> str:
    cleaned = re.sub(r"\s+", " ", segment).strip(" -*\u2022.")
    words = cleaned.split()
    if len(words) <= 12:
        return cleaned
    return " ".join(words[:12])


def _extract_json_ld_prices(
    *,
    content: str,
    source: DiscoveredSource,
    target_offer: str,
    today: str,
) -> list[ExtractedPrice]:
    try:
        data = extruct.extract(
            content,
            base_url=source.url,
            syntaxes=["json-ld", "microdata"],
            uniform=True,
        )
    except Exception:
        return []
    nodes = list(_walk_structured_data(data))
    _apply_structured_dates(source, nodes)
    target = normalize_offer(target_offer)
    prices: list[ExtractedPrice] = []
    for node in nodes:
        types = node.get("@type") or node.get("type") or []
        if isinstance(types, str):
            types = [types]
        supported = {"MenuItem", "Product", "Service"}
        if not any(str(value).split("/")[-1] in supported for value in types):
            continue
        name = str(node.get("name") or "").strip()
        if not name or target not in normalize_offer(name):
            continue
        offers = node.get("offers") or node.get("offer") or []
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue
        for offer in offers:
            if not isinstance(offer, dict) or _offer_expired(offer, today):
                continue
            amount = _structured_amount(offer)
            if amount is None:
                continue
            currency = str(offer.get("priceCurrency") or "USD").upper()
            evidence = f"{name} {currency} {amount:.2f}"
            price = ExtractedPrice.model_validate(
                {
                    "offerName": name,
                    "normalizedOfferName": normalize_offer(name),
                    "priceMin": amount,
                    "priceMax": amount,
                    "currency": currency,
                    "priceType": "fixed",
                    "sourceUrl": source.url,
                    "sourceTitle": source.title,
                    "evidenceText": evidence,
                    "observedAt": _observation_date(source, today),
                    "matchQuality": "exact",
                    "sourcePublishedAt": source.published_at,
                    "sourceUpdatedAt": source.updated_at,
                    "verifiedAt": today,
                    "retrievalMethod": "direct_fetch",
                    "extractionMethod": "json_ld",
                    "freshnessStatus": _freshness_status(source, today),
                }
            )
            if evidence_supports_price(price):
                prices.append(price)
    return prices


def _extract_visible_text_prices(
    *, content: str, source: DiscoveredSource, target_offer: str, today: str
) -> list[ExtractedPrice]:
    try:
        document = html.fromstring(content)
        for blocked in document.xpath("//script|//style|//noscript|//svg"):
            blocked.drop_tree()
        visible = re.sub(r"\s+", " ", document.text_content()).strip()
    except Exception:
        return []
    candidate = _candidate_content(visible, target_offer)
    if not candidate:
        return []
    transient = source.model_copy(update={"snippet": candidate})
    result = _extract_price_from_snippet(source=transient, target_offer=target_offer, today=today)
    return [_with_provenance(price, source, today, "visible_text") for price in result.data.prices]


def _resolve_method_votes(
    structured: list[ExtractedPrice], visible: list[ExtractedPrice]
) -> list[ExtractedPrice]:
    if not structured:
        return visible[:1]
    if not visible:
        return structured[:1]
    left, right = structured[0], visible[0]
    left_value = left.price_min if left.price_min is not None else left.price_max
    right_value = right.price_min if right.price_min is not None else right.price_max
    if left_value is not None and right_value is not None and abs(left_value - right_value) <= 0.01:
        return [left.model_copy(update={"extraction_method": "method_consensus"})]
    return [
        left.model_copy(update={"needs_review": True}),
        right.model_copy(update={"needs_review": True}),
    ]


def _candidate_content(content: str, target_offer: str) -> str:
    if not content or not evidence_contains_price(content, target_offer):
        return ""
    target_tokens = [token for token in normalize_offer(target_offer).split() if len(token) >= 4]
    if not target_tokens:
        return ""
    matches = list(re.finditer(re.escape(target_tokens[0]), content, re.IGNORECASE))
    excerpts = [content[max(0, match.start() - 160) : match.end() + 220] for match in matches[:5]]
    return "\n---\n".join(excerpts)[:6000]


def _walk_structured_data(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_structured_data(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_structured_data(nested)


def _apply_structured_dates(source: DiscoveredSource, nodes: list[dict]) -> None:
    for node in nodes:
        if not source.updated_at and node.get("dateModified"):
            source.updated_at = str(node["dateModified"])
        if not source.published_at and node.get("datePublished"):
            source.published_at = str(node["datePublished"])


def _structured_amount(offer: dict) -> float | None:
    raw = offer.get("price")
    if raw is None and isinstance(offer.get("priceSpecification"), dict):
        raw = offer["priceSpecification"].get("price")
    try:
        return float(str(raw).replace(",", "")) if raw is not None else None
    except ValueError:
        return None


def _offer_expired(offer: dict, today: str) -> bool:
    value = offer.get("priceValidUntil")
    parsed = _parse_source_date(str(value)) if value else None
    return bool(parsed and parsed < date.fromisoformat(today))


def _parse_source_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return parse_date(value, fuzzy=True).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _freshness_status(source: DiscoveredSource, today: str) -> str:
    first_party = source.source_type in {"official_site", "booking_page"}
    if first_party and source.retrieval_method == "direct_fetch":
        return "current"
    evidence_date = _parse_source_date(source.updated_at) or _parse_source_date(source.published_at)
    if not evidence_date:
        return "unknown"
    cutoff = date.fromisoformat(today) - timedelta(
        days=max(1, settings.third_party_freshness_months) * 30
    )
    return "current" if evidence_date >= cutoff else "stale"


def _observation_date(source: DiscoveredSource, today: str) -> str:
    evidence_date = _parse_source_date(source.updated_at) or _parse_source_date(source.published_at)
    if source.source_type not in {"official_site", "booking_page"} and evidence_date:
        return evidence_date.isoformat()
    return today


def _with_provenance(
    price: ExtractedPrice, source: DiscoveredSource, today: str, method: str
) -> ExtractedPrice:
    return price.model_copy(
        update={
            "observed_at": date.fromisoformat(_observation_date(source, today)),
            "source_published_at": source.published_at,
            "source_updated_at": source.updated_at,
            "verified_at": today,
            "retrieval_method": source.retrieval_method,
            "extraction_method": method,
            "freshness_status": _freshness_status(source, today),
        }
    )
