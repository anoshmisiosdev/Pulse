"""A/B results for a campaign: which variant actually won customers back.

Pure functions over counts, with the database reads kept in one thin loader, so
the statistics are unit-testable with literal numbers.

The honesty constraint here matters more than the maths. A salon with 40 lapsed
customers running a 20/20 split does not have the sample size to detect
anything short of an enormous difference, and reporting "Variant B wins!" off
3 recoveries versus 1 would be actively harmful - the owner would rewrite their
copy on noise. So every result carries an explicit ``confident`` flag and a
plain-English ``verdict``, and the verdict says "too early to tell" unless the
numbers clear a threshold that would survive a two-proportion z-test at roughly
95%.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CampaignSend, RecoveryAttribution

# Below this many delivered messages per arm, no comparison is reported as
# meaningful regardless of the split. Chosen for a local business's real list
# sizes: it's low enough to be reachable and high enough that one lucky
# recovery can't flip the verdict.
MIN_PER_ARM = 20

# Two-sided z at ~95%.
Z_95 = 1.96


@dataclass(frozen=True)
class ArmResult:
    variant: str
    sent: int
    recovered: int
    revenue_recovered: float

    @property
    def recovery_rate(self) -> float:
        return (self.recovered / self.sent) if self.sent else 0.0


@dataclass(frozen=True)
class ExperimentResult:
    a: ArmResult
    b: ArmResult
    # Percentage-point difference in recovery rate, B minus A.
    lift_pp: float
    confident: bool
    verdict: str
    winner: str | None  # "A" | "B" | None


def _z_score(a: ArmResult, b: ArmResult) -> float | None:
    """Two-proportion z-statistic, or None when it isn't computable."""
    if not a.sent or not b.sent:
        return None
    p1, p2 = a.recovery_rate, b.recovery_rate
    pooled = (a.recovered + b.recovered) / (a.sent + b.sent)
    if pooled in (0.0, 1.0):
        return None
    se = math.sqrt(pooled * (1 - pooled) * (1 / a.sent + 1 / b.sent))
    if se == 0:
        return None
    return (p2 - p1) / se


def compare(a: ArmResult, b: ArmResult) -> ExperimentResult:
    """Decide what, if anything, this test shows."""
    lift_pp = round((b.recovery_rate - a.recovery_rate) * 100, 1)
    z = _z_score(a, b)
    enough = a.sent >= MIN_PER_ARM and b.sent >= MIN_PER_ARM
    confident = bool(enough and z is not None and abs(z) >= Z_95)

    if not enough:
        shortfall = MIN_PER_ARM - min(a.sent, b.sent)
        verdict = (
            "Too early to tell - this test needs about "
            f"{shortfall} more {'person' if shortfall == 1 else 'people'} in the smaller "
            "group before the difference means anything."
        )
        return ExperimentResult(a, b, lift_pp, False, verdict, None)

    if not confident:
        verdict = (
            "No clear winner yet. The two versions are performing closely enough "
            "that the gap could be chance - keep either one."
        )
        return ExperimentResult(a, b, lift_pp, False, verdict, None)

    winner = "B" if lift_pp > 0 else "A"
    better, worse = (b, a) if winner == "B" else (a, b)
    verdict = (
        f"Version {winner} won: {better.recovered} of {better.sent} came back "
        f"({better.recovery_rate * 100:.0f}%) versus "
        f"{worse.recovered} of {worse.sent} ({worse.recovery_rate * 100:.0f}%). "
        f"Use version {winner}'s approach next time."
    )
    return ExperimentResult(a, b, lift_pp, True, verdict, winner)


async def load_arms(
    db: AsyncSession, *, business_id: str, campaign_id: str
) -> tuple[ArmResult, ArmResult]:
    """Count delivered sends and attributed recoveries per variant.

    "Sent" counts messages that actually went out (``sent``/``delivered``), not
    rows queued - a message held back by quiet hours or skipped for consent
    never reached anyone and would dilute the denominator.
    """
    bid = uuid.UUID(business_id)
    cid = uuid.UUID(campaign_id)

    sent_rows = (
        await db.execute(
            select(CampaignSend.variant, func.count())
            .where(
                CampaignSend.business_id == bid,
                CampaignSend.campaign_id == cid,
                CampaignSend.status.in_(("sent", "delivered")),
            )
            .group_by(CampaignSend.variant)
        )
    ).all()
    sent_by_variant = {variant: count for variant, count in sent_rows}

    recovery_rows = (
        await db.execute(
            select(
                CampaignSend.variant,
                func.count(RecoveryAttribution.id),
                func.coalesce(func.sum(RecoveryAttribution.estimated_value), 0),
            )
            .join(RecoveryAttribution, RecoveryAttribution.campaign_send_id == CampaignSend.id)
            .where(CampaignSend.business_id == bid, CampaignSend.campaign_id == cid)
            .group_by(CampaignSend.variant)
        )
    ).all()
    recovered_by_variant = {
        variant: (count, float(value or 0)) for variant, count, value in recovery_rows
    }

    def arm(variant: str) -> ArmResult:
        recovered, revenue = recovered_by_variant.get(variant, (0, 0.0))
        return ArmResult(
            variant=variant,
            sent=sent_by_variant.get(variant, 0),
            recovered=recovered,
            revenue_recovered=round(revenue, 2),
        )

    return arm("A"), arm("B")


async def results_for(
    db: AsyncSession, *, business_id: str, campaign_id: str
) -> ExperimentResult:
    a, b = await load_arms(db, business_id=business_id, campaign_id=campaign_id)
    return compare(a, b)
