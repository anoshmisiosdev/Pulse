"""Put the demo tenant on a plan, without Stripe. Local development only.

Webhooks need Growth and the per-location views need Pro, so on the default
Starter trial those screens only show an upgrade prompt. Real plan changes
arrive through the Stripe subscription webhook; this writes the same row
directly so the gated features can be seen and tested locally.

    cd backend
    .venv/Scripts/python.exe -m app.scripts.set_plan pro
    .venv/Scripts/python.exe -m app.scripts.set_plan starter --status canceled

**It overrides billing state**, so like ``demo_recovery`` it refuses to run
against anything but a local database unless you pass ``--force``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.billing.store import ensure_subscription
from app.billing.tiers import TIERS
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.deps import DEMO_BUSINESS_ID
from app.models import Business
from app.services.ingest import _uuid

_LOCAL_MARKERS = ("sqlite", "localhost", "127.0.0.1", "@postgres:", "@db:")
STATUSES = ("trialing", "active", "past_due", "canceled")


def _is_local_database(url: str) -> bool:
    return any(marker in url.lower() for marker in _LOCAL_MARKERS)


async def run(tier: str, status: str, business_id: str) -> int:
    async with SessionLocal() as db:
        if await db.get(Business, _uuid(business_id)) is None:
            print(
                "No business found for that tenant yet. Import customers first\n"
                "  (Setup screen, or POST /api/integrations/csv/import), then re-run."
            )
            return 1
        sub = await ensure_subscription(db, business_id=business_id)
        before = f"{sub.tier}/{sub.status}"
        sub.tier = tier
        sub.status = status
        await db.commit()
    print(f"Plan changed: {before} -> {tier}/{status}. Reload the app to see it.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tier", choices=sorted(TIERS))
    parser.add_argument("--status", choices=STATUSES, default="active")
    parser.add_argument(
        "--business-id",
        default=DEMO_BUSINESS_ID,
        help="Tenant to change (default: the AUTH_DISABLED demo tenant).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Allow a non-local database. Don't."
    )
    args = parser.parse_args()

    # Production is refused outright, --force or not: plan state there belongs
    # to Stripe, and a script overriding it would hand out paid features.
    if settings.is_production:
        print("Refusing: ENVIRONMENT is production. Plans change through Stripe there.")
        sys.exit(2)
    if not args.force and not _is_local_database(settings.database_url):
        print(
            "Refusing: this overrides billing state and DATABASE_URL doesn't look local.\n"
            "Point DATABASE_URL at your local SQLite file, or pass --force if you\n"
            "really mean it."
        )
        sys.exit(2)
    sys.exit(asyncio.run(run(args.tier, args.status, args.business_id)))


if __name__ == "__main__":
    main()
