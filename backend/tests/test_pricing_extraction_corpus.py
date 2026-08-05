"""Offline regression corpus for the deterministic price evidence gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.competitor_prices.pricing_extraction_service import (
    PricingExtractionService,
)
from app.services.competitor_prices.schemas import DiscoveredCompetitor, DiscoveredSource

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "pricing_extraction_cases.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_deterministic_extraction_corpus(case):
    result = await PricingExtractionService(allow_structured_ai=False).extract_prices(
        competitor=DiscoveredCompetitor(name="Fixture Business"),
        source=DiscoveredSource(
            url=f"https://fixture.example/{case['id']}",
            title="Verified fixture menu",
            snippet=case["snippet"],
            sourceType="official_site",
        ),
        target_offer=case["target"],
        allow_ai=False,
    )
    prices = result.data.prices
    if case["expectedMin"] is None:
        assert prices == []
        return
    assert len(prices) == 1
    assert prices[0].price_min == case["expectedMin"]
    assert prices[0].price_max == case["expectedMax"]
    if expected_offer := case.get("expectedOffer"):
        assert prices[0].offer_name == expected_offer
    if expected_match := case.get("expectedMatch"):
        assert prices[0].match_quality == expected_match
        assert prices[0].match_score is not None
        assert prices[0].match_reason
    assert result.tools_used == set()
