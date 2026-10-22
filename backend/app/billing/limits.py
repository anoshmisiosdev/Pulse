"""Usage limits and the nag that goes with them.

Pure functions over plain inputs — same discipline as ``scoring/engine.py`` and
``social/inbox_rules.py``, and for the same reason: this decides what an owner
is allowed to do, so it has to be exhaustively testable without a database or a
Stripe account.

The product rule from CLAUDE.md is "nag at 90%, never hard-block". So nothing
here returns "denied" for *volume*. Going over your customer count produces a
louder warning and an upgrade prompt, never a locked dashboard — a studio owner
who imported 1,100 customers on the Starter plan has a bigger list than they
paid for, not a reason to lose access to it mid-campaign.

Channel and automation entitlements are different: those are hard gates. They
aren't a volume overage, they're a feature the plan doesn't include, and
silently sending SMS on an email-only plan would mean billing someone for
something they never agreed to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.billing.tiers import ACTIVE_STATUSES, Tier, get_tier

NAG_THRESHOLD = 0.9

Severity = Literal["ok", "approaching", "over"]


@dataclass(frozen=True)
class UsageMeter:
    """One metered dimension, already evaluated."""

    key: str
    label: str
    used: int
    limit: int | None  # None = unlimited
    severity: Severity
    message: str | None

    @property
    def fraction(self) -> float | None:
        if self.limit is None or self.limit <= 0:
            return None
        return self.used / self.limit


@dataclass(frozen=True)
class Entitlements:
    tier: Tier
    status: str
    active: bool
    channels: frozenset[str]
    automation: bool
    multi_location: bool
    meters: tuple[UsageMeter, ...]

    @property
    def nags(self) -> tuple[UsageMeter, ...]:
        return tuple(m for m in self.meters if m.severity != "ok")


def _meter(key: str, label: str, used: int, limit: int | None, noun: str) -> UsageMeter:
    if limit is None:
        return UsageMeter(key, label, used, None, "ok", None)
    if used > limit:
        return UsageMeter(
            key,
            label,
            used,
            limit,
            "over",
            f"You're using {used:,} of {limit:,} {noun} on this plan. "
            "Nothing is turned off — upgrade when you're ready.",
        )
    if limit > 0 and used / limit >= NAG_THRESHOLD:
        return UsageMeter(
            key,
            label,
            used,
            limit,
            "approaching",
            f"You're at {used:,} of {limit:,} {noun} — about {round(used / limit * 100)}% "
            "of this plan.",
        )
    return UsageMeter(key, label, used, limit, "ok", None)


def evaluate(
    *,
    tier_name: str | None,
    status: str,
    customer_count: int,
    integration_count: int,
) -> Entitlements:
    """What this business may do right now, plus any limits worth nagging about."""
    tier = get_tier(tier_name)
    active = status in ACTIVE_STATUSES
    return Entitlements(
        tier=tier,
        status=status,
        active=active,
        channels=tier.channels,
        automation=tier.automation,
        multi_location=tier.multi_location,
        meters=(
            _meter("customers", "Customers", customer_count, tier.max_customers, "customers"),
            _meter(
                "integrations",
                "Connected sources",
                integration_count,
                tier.max_integrations,
                "integrations",
            ),
        ),
    )


def channel_denial(ent: Entitlements, channel: str) -> str | None:
    """Why this channel can't be used, or None if it can.

    A hard gate, unlike the volume meters — see the module docstring.
    """
    if channel in ent.channels:
        return None
    if channel == "sms":
        return (
            f"SMS isn't included in {ent.tier.label}. Upgrade to Growth to text customers."
        )
    return f"{channel} isn't included in {ent.tier.label}."


def automation_denial(ent: Entitlements) -> str | None:
    """Why automation rules can't run, or None if they can."""
    if ent.automation:
        return None
    return (
        f"Automation rules aren't included in {ent.tier.label}. "
        "Upgrade to Growth to let Churnary send win-backs for you. "
        "You can still approve each one by hand."
    )
