"""The tenant's dashboard payload, read from their persisted data.

Returns status="empty" when the business hasn't connected a data source yet —
the frontend uses that to route the owner to the setup page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.models import Business
from app.schemas.api import ConnectionOut, PortfolioOut, PortfolioSummaryOut
from app.services import ingest
from app.services.activity import build_scored_customers, monthly_revenue_series, summarize

router = APIRouter(tags=["portfolio"])


async def build_portfolio(db: AsyncSession, user: CurrentUser) -> PortfolioOut:
    connections = [
        ConnectionOut(
            source=c.source,
            status=c.status,
            last_synced_at=c.last_synced_at.isoformat() if c.last_synced_at else None,
        )
        for c in await ingest.list_connections(db, user.business_id)
    ]

    sync = await ingest.load_sync(db, user.business_id)
    biz = await db.get(Business, ingest._uuid(user.business_id))
    name = (biz.name if biz else None) or user.business_name
    vertical = biz.vertical if biz else "other"

    if not sync.customers:
        return PortfolioOut(
            status="empty",
            business_name=name,
            vertical=vertical,
            summary=PortfolioSummaryOut(
                total_customers=0, high_risk=0, med_risk=0, low_risk=0, revenue_at_risk=0.0
            ),
            customers=[],
            connections=connections,
            location_label=biz.location_label if biz else None,
        )

    from app.api.integrations import _to_risk  # shared row shaping

    scored = build_scored_customers(sync, vertical=vertical)
    summary = summarize(scored, monthly_revenue_series(sync))
    return PortfolioOut(
        status="ready",
        business_name=name,
        vertical=vertical,
        summary=PortfolioSummaryOut(**summary.__dict__),
        customers=_to_risk(scored),
        connections=connections,
        location_label=biz.location_label if biz else None,
    )


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> PortfolioOut:
    return await build_portfolio(db, user)
