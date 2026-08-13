"""Force one lap of the retention loop so the dashboard has real recovery data.

Local dev has no Resend key, so approving a send marks it "failed" — and a failed
send correctly earns no attribution credit. That makes the recovery loop
impossible to exercise through the UI alone. This script fakes only the two steps
a real deployment would do for you:

  1. mark some queued sends as actually delivered (backdated)
  2. have a few of those customers come back and spend

...then runs the real attribution (``app/services/attribution.py``) over the result.

    cd backend
    DATABASE_URL="sqlite+aiosqlite:///./dev.db" uv run python -m app.scripts.demo_recovery

Requires customers already imported for the demo tenant — upload a CSV through
onboarding first. Safe to re-run: attribution is idempotent per customer, so the
recovered count and revenue stay put.

**This writes fabricated sends, visits and transactions.** It therefore refuses to
run against anything but a local database unless you pass ``--force``.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.deps import DEMO_BUSINESS_ID
from app.models import (
    AutomationRule,
    Business,
    CampaignSend,
    Customer,
    Transaction,
    Visit,
)
from app.services.attribution import detect_recoveries
from app.services.automations import dispatch_automations
from app.services.ingest import _uuid

SENDS_TO_DELIVER = 5
CUSTOMERS_WHO_RETURN = 3
RETURN_SPEND = 34.0

# Substrings that mark a database as a throwaway. Anything else is assumed to be
# real (staging or production) and needs --force.
_LOCAL_MARKERS = ("sqlite", "localhost", "127.0.0.1", "@postgres:", "@db:")


def _is_local_database(url: str) -> bool:
    return any(marker in url.lower() for marker in _LOCAL_MARKERS)


async def run() -> int:
    bid = _uuid(DEMO_BUSINESS_ID)

    async with SessionLocal() as db:
        biz = await db.get(Business, bid)
        if biz is None:
            print(
                "No demo business found. Import customers through onboarding first\n"
                "  (http://localhost:5173/setup), then re-run this script."
            )
            return 1

        customer_count = len(
            (await db.execute(select(Customer.id).where(Customer.business_id == bid)))
            .scalars()
            .all()
        )
        if customer_count == 0:
            print("Demo business exists but has no customers — import a CSV first.")
            return 1
        print(f"Tenant: {biz.name} — {customer_count} customers, vertical={biz.vertical}")

        # 1. Make sure a rule exists, then queue outreach for high-risk customers.
        existing_rules = (
            (await db.execute(select(AutomationRule).where(AutomationRule.business_id == bid)))
            .scalars()
            .all()
        )
        if not existing_rules:
            db.add(
                AutomationRule(
                    business_id=bid,
                    name="Win back high risk (dev)",
                    trigger_band="high",
                    channel="email",
                    mode="approve",
                    incentive="a free pastry",
                )
            )
            await db.commit()
            print("Created a high-risk email rule (approve-to-send).")

        summary = await dispatch_automations(db, DEMO_BUSINESS_ID)
        await db.commit()
        print(f"Dispatch: {summary.sends_created} queued (skipped: {summary.skipped or 'none'})")

        # 2. Pretend the owner approved them and they were delivered 12 days ago.
        pending = (
            (
                await db.execute(
                    select(CampaignSend)
                    .where(CampaignSend.business_id == bid, CampaignSend.status == "pending")
                    .limit(SENDS_TO_DELIVER)
                )
            )
            .scalars()
            .all()
        )
        if not pending:
            print(
                "Nothing pending to deliver. Either every high-risk customer is inside a\n"
                "cooldown window, or this script already ran. Attribution below is still live."
            )
        sent_at = datetime.now(UTC) - timedelta(days=12)
        for send in pending:
            send.status = "sent"
            send.sent_at = sent_at
        await db.commit()
        if pending:
            print(f"Marked {len(pending)} sends delivered (12 days ago).")

        # 3. Some of those customers come back and spend, 4 days ago.
        returners = pending[:CUSTOMERS_WHO_RETURN]
        returned_at = datetime.now(UTC) - timedelta(days=4)
        for send in returners:
            db.add(
                Visit(
                    business_id=bid,
                    customer_id=send.customer_id,
                    source="dev",
                    occurred_at=returned_at,
                )
            )
            db.add(
                Transaction(
                    business_id=bid,
                    customer_id=send.customer_id,
                    source="dev",
                    amount=RETURN_SPEND,
                    occurred_at=returned_at,
                )
            )
        await db.commit()
        if returners:
            print(f"{len(returners)} of them came back and spent ${RETURN_SPEND:.2f} each.")

        # 4. Real attribution over the result.
        rec = await detect_recoveries(db, DEMO_BUSINESS_ID)
        await db.commit()
        print(
            f"\nAttribution: {rec.recoveries_found} newly recovered, "
            f"${rec.revenue_recovered:,.2f} observed "
            f"(considered {rec.sends_considered} delivered sends)"
        )
        print("\nReload the dashboard — 'Revenue retained' should show that revenue.")
        print("Open one of those customers from Retention to see their timeline.")
    return 0


def main() -> None:
    force = "--force" in sys.argv
    if not _is_local_database(settings.database_url) and not force:
        print(
            "Refusing to run: DATABASE_URL doesn't look like a local database, and this\n"
            "script writes fabricated sends, visits and transactions.\n\n"
            "Point it at a throwaway DB instead, e.g.\n"
            '  DATABASE_URL="sqlite+aiosqlite:///./dev.db" '
            "uv run python -m app.scripts.demo_recovery\n\n"
            "Pass --force only if you genuinely mean to write demo data where it is pointed."
        )
        raise SystemExit(2)
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
