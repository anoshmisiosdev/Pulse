"""Deterministic validation and confidence scoring for price observations."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from app.services.competitor_prices.schemas import ExtractedPrice, MarketSummaryOut

_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:[$€£]\s*\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?|"
    r"\b(?:USD|EUR|GBP|CAD|AUD)\s*\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?|"
    r"\b\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|CAD|AUD)\b)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<![\d.])\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?(?![\d.])")
_MENU_DECIMAL_RE = re.compile(r"(?<![\d.])\d{1,4}\.\d{2}(?![\d.])")
_TIER_RE = re.compile(r"(?:^|\b)(?:price\s*:?\s*)?\${2,4}(?:\b|$)", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")
_CAPUCCINO_RE = re.compile(r"\bcapuccino\b", re.IGNORECASE)


@dataclass(frozen=True)
class ConfidenceInput:
    price: ExtractedPrice
    target_offer: str
    source_type: str
    source_location_matches: bool
    multiple_sources_support: bool = False
    snippet_only: bool = False
    possible_location_ambiguity: bool = False


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    reasons: list[str]


def normalize_offer(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.lower()))


def canonicalize_offer_label(value: str) -> str:
    cleaned = " ".join(value.strip().split())

    def replace_capuccino(match: re.Match[str]) -> str:
        original = match.group(0)
        return "Cappuccino" if original[:1].isupper() else "cappuccino"

    return _CAPUCCINO_RE.sub(replace_capuccino, cleaned)


def evidence_price_amounts(evidence: str, target_offer: str | None = None) -> list[float]:
    if not evidence or _TIER_RE.search(evidence):
        return []
    offer_spans = _offer_token_spans(evidence, target_offer) if target_offer else []
    if target_offer and not offer_spans:
        return []
    spans: list[tuple[int, int]] = []
    for match in _CURRENCY_AMOUNT_RE.finditer(evidence):
        if not offer_spans or _near_offer(match.span(), offer_spans):
            spans.append(match.span())

    if target_offer:
        spans.extend(
            match.span()
            for match in _MENU_DECIMAL_RE.finditer(evidence)
            if _near_offer(match.span(), offer_spans)
        )

    amounts: list[float] = []
    seen: set[tuple[int, int]] = set()
    for start, end in spans:
        if (start, end) in seen:
            continue
        seen.add((start, end))
        for match in _NUMBER_RE.finditer(evidence[start:end]):
            try:
                amounts.append(float(match.group(0).replace(",", "")))
            except ValueError:
                continue
    return amounts


def _offer_token_spans(evidence: str, target_offer: str | None) -> list[tuple[int, int]]:
    tokens = {
        token.removesuffix("s")
        for token in normalize_offer(canonicalize_offer_label(target_offer or "")).split()
        if len(token.removesuffix("s")) >= 4
    }
    spans: list[tuple[int, int]] = []
    for token in tokens:
        spans.extend(
            match.span()
            for match in re.finditer(rf"\b{re.escape(token)}s?\b", evidence, re.IGNORECASE)
        )
    return spans


def _near_offer(amount_span: tuple[int, int], offer_spans: list[tuple[int, int]]) -> bool:
    start, end = amount_span
    return any(
        max(offer_start - end, start - offer_end, 0) <= 32 for offer_start, offer_end in offer_spans
    )


def evidence_contains_price(evidence: str, target_offer: str | None = None) -> bool:
    return bool(evidence_price_amounts(evidence, target_offer))


def evidence_supports_price(price: ExtractedPrice) -> bool:
    if not price.source_url or not price.evidence_text.strip():
        return False
    if price.price_type == "quote_based":
        return True
    if price.price_min is None and price.price_max is None:
        return False
    amounts = evidence_price_amounts(price.evidence_text, price.offer_name)
    expected = [value for value in (price.price_min, price.price_max) if value is not None]
    return bool(amounts) and all(
        any(abs(amount - expected_value) <= 0.01 for amount in amounts)
        for expected_value in expected
    )


def location_matches(address: str | None, city: str | None, state: str | None) -> bool:
    if not address:
        return False
    text = address.lower()
    return bool((not city or city.lower() in text) and (not state or state.lower() in text))


def likely_wrong_location(address: str | None, city: str | None, state: str | None) -> bool:
    if not address or not city or not state:
        return False
    text = address.lower()
    has_state = state.lower() in text
    has_city = city.lower() in text
    return has_state and not has_city


def source_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def score_price_confidence(input_: ConfidenceInput) -> ConfidenceResult:
    price = input_.price
    score = 0.50
    reasons: list[str] = []

    if input_.source_type in ("official_site", "booking_page"):
        score += 0.20
        reasons.append("Source appears to be competitor-owned or booking page")
    if price.match_quality == "exact":
        score += 0.15
        reasons.append("Exact service match")
    target = normalize_offer(input_.target_offer)
    evidence = normalize_offer(price.evidence_text)
    if target and (target in evidence or target in normalize_offer(price.offer_name)):
        score += 0.10
        reasons.append("Evidence names the target offer")
    if input_.source_location_matches:
        score += 0.10
        reasons.append("Source location matches target city/state")
    if str(price.observed_at) == date.today().isoformat():
        score += 0.05
        reasons.append("Observed today")
    if input_.multiple_sources_support:
        score += 0.05
        reasons.append("Multiple sources support a similar price")

    if input_.source_type in ("directory", "social", "unknown"):
        score -= 0.20
        reasons.append("Source is a directory, social page, or unknown")
    if price.match_quality == "weak":
        score -= 0.20
        reasons.append("Weak offer match")
    if price.price_type == "package":
        score -= 0.15
        reasons.append("Package price may not map cleanly to the target offer")
    if input_.snippet_only:
        score -= 0.10
        reasons.append("Only snippet text was available")
    if input_.possible_location_ambiguity:
        score -= 0.25
        reasons.append("Possible location ambiguity")

    return ConfidenceResult(score=round(max(0.0, min(1.0, score)), 2), reasons=reasons)


def price_midpoint(price: ExtractedPrice) -> float | None:
    if price.price_min is None and price.price_max is None:
        return None
    if price.price_min is None:
        return price.price_max
    if price.price_max is None:
        return price.price_min
    return (price.price_min + price.price_max) / 2


def build_market_summary(
    prices: list[tuple[ExtractedPrice, float]],
    current_price: float | None = None,
) -> MarketSummaryOut:
    values = [v for p, _confidence in prices if (v := price_midpoint(p)) is not None]
    if not values:
        return MarketSummaryOut(
            sampleSize=0,
            priceLow=None,
            priceMedian=None,
            priceHigh=None,
            priceAverage=None,
            priceIqr=None,
            currency="USD",
            recommendedPositioning="No public competitor prices were found.",
            confidence=0.0,
        )

    ordered = sorted(values)
    median = statistics.median(ordered)
    iqr = None
    if len(ordered) >= 4:
        q = statistics.quantiles(ordered, n=4, method="inclusive")
        iqr = round(q[2] - q[0], 2)

    avg_confidence = statistics.mean(confidence for _p, confidence in prices)
    exact_ratio = sum(1 for p, _c in prices if p.match_quality == "exact") / len(prices)
    sample_component = min(0.35, len(values) * 0.06)
    confidence = min(1.0, sample_component + 0.35 * avg_confidence + 0.30 * exact_ratio)
    confidence_cap = (
        0.35
        if len(values) == 1
        else 0.55
        if len(values) == 2
        else 0.75
        if len(values) == 3
        else 0.90
    )
    confidence = round(min(confidence, confidence_cap), 2)

    low = min(ordered)
    high = max(ordered)
    if current_price is None:
        positioning = (
            f"We found {len(values)} public competitor prices. "
            f"The observed local range is ${low:,.0f}-${high:,.0f}; median is ${median:,.0f}."
        )
    elif current_price > median * 1.05:
        positioning = "Your current price appears above the observed local median."
    elif current_price < median * 0.95:
        positioning = "Your current price appears below the observed local median."
    else:
        positioning = "Your current price appears near the observed local median."

    return MarketSummaryOut(
        sampleSize=len(values),
        priceLow=round(low, 2),
        priceMedian=round(float(median), 2),
        priceHigh=round(high, 2),
        priceAverage=round(statistics.mean(ordered), 2),
        priceIqr=iqr,
        currency=prices[0][0].currency if prices else "USD",
        recommendedPositioning=positioning,
        confidence=confidence,
    )


def now_utc() -> datetime:
    return datetime.now(UTC)
