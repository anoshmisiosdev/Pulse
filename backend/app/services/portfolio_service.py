"""Shared portfolio shaping: scored rows -> API payloads.

Lives in services so API routers don't import each other's privates.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models import Business
from app.schemas.api import ConnectionOut, CustomerRisk, PortfolioOut, PortfolioSummaryOut
from app.services import ingest
from app.services.activity import (
    ScoredCustomer,
    build_scored_customers,
    monthly_revenue_series,
    summarize,
)


def to_risk(scored: list[ScoredCustomer]) -> list[CustomerRisk]:
    rows = [
        CustomerRisk(
            customer_id=s.result.customer_id,
            name=s.customer.full_name,
            email=s.customer.email,
            phone=s.customer.phone,
            score=s.result.score,
            band=s.result.band,
            reasons=s.result.reasons,
            estimated_annual_value=s.estimated_annual_value,
            days_since_last_visit=s.days_since_last_visit,
            last_visit=s.last_visit,
            visit_count=s.visit_count,
            total_spend=s.total_spend,
            segment=s.segment,
            pattern=s.pattern,
            confidence=s.confidence,
            trend_pct=s.trend_pct,
            favorite_item=s.customer.favorite_item,
        )
        for s in scored
    ]
    # Most at-risk first — that's the work queue.
    rows.sort(key=lambda r: r.score, reverse=True)
    return rows


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
        )

    scored = build_scored_customers(sync, vertical=vertical)
    summary = summarize(scored, monthly_revenue_series(sync))
    return PortfolioOut(
        status="ready",
        business_name=name,
        vertical=vertical,
        summary=PortfolioSummaryOut(**summary.__dict__),
        customers=to_risk(scored),
        connections=connections,
    )
