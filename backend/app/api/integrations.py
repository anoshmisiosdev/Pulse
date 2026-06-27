"""Integration endpoints. CSV is the v1 hero: upload → scored risk list in <2 min."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from app.integrations.base import IntegrationError
from app.integrations.csv_adapter import parse_csv, template_csv
from app.schemas.api import (
    CSVPreviewOut,
    CustomerRisk,
    PortfolioSummaryOut,
)
from app.services.activity import (
    ScoredCustomer,
    build_scored_customers,
    monthly_revenue_series,
    summarize,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _to_risk(scored: list[ScoredCustomer]) -> list[CustomerRisk]:
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


@router.get("/csv/template", response_class=PlainTextResponse)
async def csv_template() -> str:
    """Downloadable CSV template handed to owners during onboarding."""
    return template_csv()


@router.post("/csv/preview", response_model=CSVPreviewOut)
async def csv_preview(
    file: UploadFile = File(...),
    vertical: str = Query("other"),
    business_name: str = Query("Your Business"),
) -> CSVPreviewOut:
    """Parse + score an uploaded CSV entirely in memory (no persistence).

    This is the onboarding "money screen" path — it works fully offline.
    """
    raw = await file.read()
    try:
        sync = parse_csv(raw.decode("utf-8-sig"))
    except IntegrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File is not valid UTF-8 text") from exc

    scored = build_scored_customers(sync, vertical=vertical)
    summary = summarize(scored, monthly_revenue_series(sync))
    return CSVPreviewOut(
        business_name=business_name,
        vertical=vertical,
        summary=PortfolioSummaryOut(**summary.__dict__),
        customers=_to_risk(scored),
        warnings=sync.warnings,
    )


@router.post("/demo", response_model=CSVPreviewOut)
async def demo(count: int = Query(50, ge=1, le=2000)) -> CSVPreviewOut:
    """Instant demo: the seeded "Hayward Coffee Co." cafe, scored — no upload needed."""
    from app.scripts.demo_data import DEMO_BUSINESS_NAME, DEMO_VERTICAL, generate_sync

    sync = generate_sync(n=count)
    scored = build_scored_customers(sync, vertical=DEMO_VERTICAL)
    summary = summarize(scored, monthly_revenue_series(sync))
    return CSVPreviewOut(
        business_name=DEMO_BUSINESS_NAME,
        vertical=DEMO_VERTICAL,
        summary=PortfolioSummaryOut(**summary.__dict__),
        customers=_to_risk(scored),
        warnings=[],
    )
