"""Non-persisting pricing canary with one stable, human-verifiable example.

Run from ``backend/``:

    uv run python -m scripts.pricing_canary --mode extraction
    uv run python -m scripts.pricing_canary --mode full --json

``extraction`` downloads the public Fremont Coffee Company menu and proves the
deterministic parser can bind "Big Breakfast Burrito" to 12.95. ``full`` also
exercises the configured place/search/extraction providers, but never receives
a database session and therefore cannot write research data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.core.deps import CurrentUser
from app.services.competitor_prices.competitor_research_service import (
    CompetitorResearchService,
)
from app.services.competitor_prices.page_fetcher import SafePageFetcher
from app.services.competitor_prices.pricing_extraction_service import (
    PricingExtractionService,
)
from app.services.competitor_prices.schemas import (
    CompetitorPriceResearchRequest,
    DiscoveredCompetitor,
    DiscoveredSource,
)
from app.services.competitor_prices.url_utils import canonical_domain

CANARY_URL = "https://www.fremontcoffeeco.com/food-menu"
CANARY_OFFER = "Big Breakfast Burrito"
CANARY_PRICE = 12.95
CANARY_DOMAIN = "fremontcoffeeco.com"
CANARY_LATITUDE = 37.5483
CANARY_LONGITUDE = -121.9886


@dataclass(frozen=True)
class CanaryResult:
    mode: str
    passed: bool
    expected_price: float
    observed_prices: list[float]
    source_domains: list[str]
    status: str
    duration_ms: int | None = None
    provider_cost_usd: float = 0.0
    failure: str | None = None


def _observed_values(prices: list[Any]) -> list[float]:
    values: list[float] = []
    for price in prices:
        value = price.price_min if price.price_min is not None else price.price_max
        if value is not None:
            values.append(round(float(value), 2))
    return values


def _passes(values: list[float], domains: list[str], expected_price: float) -> bool:
    return any(abs(value - expected_price) <= 0.01 for value in values) and any(
        domain == CANARY_DOMAIN or domain.endswith(f".{CANARY_DOMAIN}")
        for domain in domains
    )


async def extraction_canary(expected_price: float) -> CanaryResult:
    page = await SafePageFetcher().fetch(CANARY_URL)
    if not page.succeeded:
        return CanaryResult(
            mode="extraction",
            passed=False,
            expected_price=expected_price,
            observed_prices=[],
            source_domains=[],
            status="unavailable",
            failure=page.error or "The canary page could not be fetched.",
        )
    source = DiscoveredSource(url=page.url, sourceType="official_site")
    extracted = await PricingExtractionService(allow_structured_ai=False).extract_prices(
        competitor=DiscoveredCompetitor(name="Fremont Coffee Company"),
        source=source,
        target_offer=CANARY_OFFER,
        page=page,
        allow_ai=False,
    )
    values = _observed_values(extracted.data.prices)
    domains = sorted({canonical_domain(price.source_url) for price in extracted.data.prices})
    return CanaryResult(
        mode="extraction",
        passed=_passes(values, domains, expected_price),
        expected_price=expected_price,
        observed_prices=values,
        source_domains=domains,
        status="complete" if values else "no_evidence",
    )


async def full_canary(expected_price: float, max_cost_usd: float) -> CanaryResult:
    request = CompetitorPriceResearchRequest.model_validate(
        {
            "businessName": "PulseQ Pricing Canary",
            "businessCategory": "Coffee Shop",
            "targetOffer": CANARY_OFFER,
            "location": {
                "city": "Fremont",
                "state": "CA",
                "latitude": CANARY_LATITUDE,
                "longitude": CANARY_LONGITUDE,
            },
            "radiusMiles": 3,
            "maxCompetitors": 4,
            "maxSourcesPerCompetitor": 3,
        }
    )
    response = await CompetitorResearchService(db=None).research(
        request,
        CurrentUser(
            user_id="pricing-canary",
            email=None,
            business_id="00000000-0000-0000-0000-00000000ca11",
            business_name="PulseQ Pricing Canary",
        ),
    )
    prices = [price for competitor in response.competitors for price in competitor.prices]
    values = _observed_values(prices)
    domains = sorted({canonical_domain(price.source_url) for price in prices})
    within_cost = response.metadata.provider_cost_usd <= max_cost_usd
    return CanaryResult(
        mode="full",
        passed=_passes(values, domains, expected_price) and within_cost,
        expected_price=expected_price,
        observed_prices=values,
        source_domains=domains,
        status=response.status,
        duration_ms=response.metadata.duration_ms,
        provider_cost_usd=response.metadata.provider_cost_usd,
        failure=None if within_cost else f"Provider cost exceeded ${max_cost_usd:.2f}.",
    )


async def _main(args: argparse.Namespace) -> int:
    try:
        result = (
            await extraction_canary(args.expected_price)
            if args.mode == "extraction"
            else await full_canary(args.expected_price, args.max_cost_usd)
        )
    except Exception as exc:  # noqa: BLE001 - CLI must turn provider errors into a result
        result = CanaryResult(
            mode=args.mode,
            passed=False,
            expected_price=args.expected_price,
            observed_prices=[],
            source_domains=[],
            status="unavailable",
            failure=f"{exc.__class__.__name__}: {exc}",
        )
    payload = asdict(result)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        outcome = "PASS" if result.passed else "FAIL"
        print(
            f"{outcome} mode={result.mode} expected=${result.expected_price:.2f} "
            f"observed={result.observed_prices} status={result.status} "
            f"cost=${result.provider_cost_usd:.4f}"
        )
        if result.failure:
            print(result.failure)
    return 0 if result.passed else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("extraction", "full"), default="extraction")
    parser.add_argument("--expected-price", type=float, default=CANARY_PRICE)
    parser.add_argument("--max-cost-usd", type=float, default=0.10)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
