"""Strict price extraction from Perplexity snippets with DeepSeek."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.core.config import settings
from app.services.competitor_prices.confidence_scoring import (
    canonicalize_offer_label,
    evidence_supports_price,
    normalize_offer,
)
from app.services.competitor_prices.deepseek_client import (
    DeepSeekClient,
    DeepSeekJSONResult,
)
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
    def __init__(self, deepseek: DeepSeekClient | None = None):
        self.deepseek = deepseek or DeepSeekClient()

    async def extract_prices(
        self,
        *,
        competitor: DiscoveredCompetitor,
        source: DiscoveredSource,
        target_offer: str,
    ) -> DeepSeekJSONResult[PriceExtractionResult]:
        today = datetime.now(UTC).date().isoformat()
        target_offer = canonicalize_offer_label(target_offer)
        snippet_result = _extract_price_from_snippet(
            source=source,
            target_offer=target_offer,
            today=today,
        )
        if snippet_result.data.prices:
            return snippet_result

        prompt = f"""Return json with prices only for the target offer or a close equivalent.
Do not infer prices from typical menus or general knowledge.

Target offer: {target_offer}
Competitor: {competitor.name}
Competitor address: {competitor.address or "unknown"}
Source URL: {source.url}
Source title: {source.title or "unknown"}
Source type: {source.source_type}
Known source snippet:
{source.snippet or "(no snippet available)"}

Return JSON with prices only for the target offer or a close equivalent.
Use observedAt="{today}" unless the source explicitly shows a different observed date.
sourceUrl must be the source URL above.
"""
        if not settings.enable_deepseek_extraction:
            return DeepSeekJSONResult(
                data=PriceExtractionResult(prices=[]),
                warnings=[
                    "DeepSeek extraction is disabled; only deterministic snippets were used."
                ],
                tools_used=set(),
            )

        result = await self.deepseek.generate_json(
            system=STRICT_PRICE_SYSTEM,
            prompt=prompt,
            response_model=PriceExtractionResult,
        )
        result.data.prices = _valid_source_prices(result.data.prices, source)
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
                "observedAt": today,
                "matchQuality": "exact",
                "notes": "Extracted deterministically from grounded source snippet.",
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
