"""Retrieved business-knowledge snippets must reach the generation prompt,
and must not add empty clutter when there's nothing to retrieve."""

from __future__ import annotations

from app.campaigns.generator import CampaignContext, _build_prompt


def _ctx(**overrides) -> CampaignContext:
    defaults = dict(
        business_name="Hayward Coffee Co.",
        business_type="coffee shop",
        customer_name="Priya",
        channel="email",
        risk_reasons=["Last visit 24 days ago"],
    )
    defaults.update(overrides)
    return CampaignContext(**defaults)


def test_knowledge_snippets_included_in_prompt():
    ctx = _ctx(
        knowledge_snippets=[
            "Always sign off with 'stay caffeinated!'",
            "Best-seller is the brown sugar oat milk latte.",
        ]
    )
    _, user = _build_prompt(ctx)
    assert "stay caffeinated" in user
    assert "brown sugar oat milk latte" in user


def test_no_knowledge_block_when_nothing_retrieved():
    ctx = _ctx(knowledge_snippets=[])
    _, user = _build_prompt(ctx)
    assert "About this business" not in user
