"""The price list, as data.

Pure module: no I/O, no Stripe import. The Stripe price *ids* live in settings
(they differ per environment); everything that describes what a tier *is* lives
here, so the pricing page, the limit checks, and the checkout session all read
one source of truth and can't drift apart.

Entitlements are deliberately coarse. Three tiers with four switches is
something an owner can hold in their head; per-feature SKUs are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TierName = Literal["starter", "growth", "pro"]
TIER_ORDER: tuple[TierName, ...] = ("starter", "growth", "pro")

# ``None`` means unlimited. Used for customer counts and integration slots.
Unlimited = None


@dataclass(frozen=True)
class Tier:
    name: TierName
    label: str
    monthly_price_usd: int
    # None = unlimited.
    max_customers: int | None
    max_integrations: int | None
    channels: frozenset[str]
    automation: bool
    multi_location: bool
    blurb: str
    highlights: tuple[str, ...] = field(default_factory=tuple)

    @property
    def annual_price_usd(self) -> int:
        """Annual = 2 months free, i.e. 10x the monthly rate."""
        return self.monthly_price_usd * 10

    def allows_channel(self, channel: str) -> bool:
        return channel in self.channels

    def customer_limit_label(self) -> str:
        return "Unlimited" if self.max_customers is None else f"{self.max_customers:,}"


TIERS: dict[TierName, Tier] = {
    "starter": Tier(
        name="starter",
        label="Starter",
        monthly_price_usd=199,
        max_customers=1_000,
        max_integrations=1,
        channels=frozenset({"email"}),
        automation=False,
        multi_location=False,
        blurb="See who's leaving and win them back by email.",
        highlights=(
            "1 integration",
            "Up to 1,000 customers",
            "Email win-back campaigns",
            "Risk scores with plain-English reasons",
        ),
    ),
    "growth": Tier(
        name="growth",
        label="Growth",
        monthly_price_usd=299,
        max_customers=2_500,
        max_integrations=Unlimited,
        channels=frozenset({"email", "sms"}),
        automation=True,
        multi_location=False,
        blurb="Add SMS and let the rules run outreach for you.",
        highlights=(
            "All integrations",
            "Up to 2,500 customers",
            "Email + SMS",
            "Automation rules",
        ),
    ),
    "pro": Tier(
        name="pro",
        label="Pro",
        monthly_price_usd=499,
        max_customers=Unlimited,
        max_integrations=Unlimited,
        channels=frozenset({"email", "sms"}),
        automation=True,
        multi_location=True,
        blurb="No customer ceiling, ready for a second location.",
        highlights=(
            "All integrations",
            "Unlimited customers",
            "Email + SMS",
            "Automation rules",
            "Multi-location ready",
        ),
    ),
}

TRIAL_DAYS = 14
FOUNDERS_COUPON = "founders_rate"

# Statuses in which the product stays fully usable. ``past_due`` is included on
# purpose: a failed card is a billing problem, not a reason to lock an owner out
# of the customer list they're mid-campaign on. Stripe's own dunning emails do
# the chasing; we nag in-app and keep working.
ACTIVE_STATUSES = frozenset({"trialing", "active", "past_due"})


def get_tier(name: str | None) -> Tier:
    """The tier for a stored name, falling back to Starter.

    Never raises: a subscription row with a tier string we don't recognize
    (hand-edited, or written by a newer deploy that was rolled back) must not
    take down the dashboard. Starter is the safe floor — it under-grants rather
    than handing out entitlements nobody paid for.
    """
    return TIERS.get(name or "", TIERS["starter"])


def tier_rank(name: str | None) -> int:
    tier = get_tier(name)
    return TIER_ORDER.index(tier.name)


def is_upgrade(current: str | None, target: str | None) -> bool:
    return tier_rank(target) > tier_rank(current)
