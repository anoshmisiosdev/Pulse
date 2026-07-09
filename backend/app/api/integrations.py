"""Integration endpoints: connect Stripe/Square (pull real customer data), import a
CSV, or preview one in memory. Connected data persists per tenant in Postgres."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.security import decrypt_token, encrypt_token
from app.integrations.base import IntegrationError
from app.integrations.csv_adapter import parse_csv, template_csv
from app.integrations.registry import get_adapter_class
from app.schemas.api import (
    ConnectIn,
    ConnectionOut,
    CSVPreviewOut,
    CustomerRisk,
    PortfolioOut,
    PortfolioSummaryOut,
)
from app.schemas.normalized import SyncResult
from app.services import ingest
from app.services.activity import (
    ScoredCustomer,
    build_scored_customers,
    monthly_revenue_series,
    summarize,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

LIVE_PROVIDERS = ("stripe", "square")


async def _run_sync(adapter) -> SyncResult:
    return SyncResult(
        customers=await adapter.sync_customers(),
        transactions=await adapter.sync_transactions(),
        visits=await adapter.sync_visits(),
    )


async def _persist_and_respond(
    db: AsyncSession, user: CurrentUser, source: str, sync: SyncResult
) -> PortfolioOut:
    from app.api.portfolio import build_portfolio

    await ingest.persist_sync(db, user.business_id, source, sync)
    return await build_portfolio(db, user)


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


@router.post("/connect", response_model=PortfolioOut)
async def connect(
    payload: ConnectIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> PortfolioOut:
    """Connect Stripe or Square with an API credential, pull everything we can
    (customers, payments), persist it for this tenant, and return the portfolio."""
    provider = payload.provider.lower().strip()
    if provider not in LIVE_PROVIDERS:
        raise HTTPException(422, detail="provider must be 'stripe' or 'square'")
    if not payload.credential.strip():
        raise HTTPException(422, detail="A Stripe secret key or Square access token is required")

    adapter = get_adapter_class(provider)()
    try:
        await adapter.connect(
            {"access_token": payload.credential.strip(), "environment": payload.environment}
        )
        sync = await _run_sync(adapter)
    except IntegrationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(422, detail=f"{provider} is not available yet") from exc

    if not sync.customers:
        raise HTTPException(
            422,
            detail=f"Connected to {provider.title()}, but found no customers on this account.",
        )

    await ingest.ensure_business(
        db, user.business_id, payload.business_name or user.business_name, payload.vertical
    )
    await ingest.upsert_connection(
        db, user.business_id, provider, encrypt_token(payload.credential.strip())
    )
    return await _persist_and_respond(db, user, provider, sync)


@router.post("/csv/import", response_model=PortfolioOut)
async def csv_import(
    file: UploadFile = File(...),
    vertical: str = Query("other"),
    business_name: str = Query(""),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> PortfolioOut:
    """Like /csv/preview, but persists the rows to this tenant."""
    raw = await file.read()
    try:
        sync = parse_csv(raw.decode("utf-8-sig"))
    except IntegrationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(422, detail="File is not valid UTF-8 text") from exc
    if not sync.customers:
        raise HTTPException(422, detail="No customers found in that CSV")

    await ingest.ensure_business(
        db, user.business_id, business_name or user.business_name, vertical
    )
    await ingest.upsert_connection(db, user.business_id, "csv", None)
    return await _persist_and_respond(db, user, "csv", sync)


@router.post("/sync", response_model=PortfolioOut)
async def resync(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> PortfolioOut:
    """Re-pull from every connected live provider using the stored (encrypted) token."""
    connections = await ingest.list_connections(db, user.business_id)
    live = [c for c in connections if c.source in LIVE_PROVIDERS and c.access_token_enc]
    if not live:
        raise HTTPException(404, detail="No connected integration to sync")

    from app.api.portfolio import build_portfolio

    for conn in live:
        adapter = get_adapter_class(conn.source)()
        try:
            await adapter.connect({"access_token": decrypt_token(conn.access_token_enc)})
            sync = await _run_sync(adapter)
        except (IntegrationError, ValueError) as exc:
            raise HTTPException(422, detail=f"{conn.source}: {exc}") from exc
        await ingest.persist_sync(db, user.business_id, conn.source, sync)
        await ingest.upsert_connection(db, user.business_id, conn.source, None)
    return await build_portfolio(db, user)


@router.get("/status", response_model=list[ConnectionOut])
async def status(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> list[ConnectionOut]:
    return [
        ConnectionOut(
            source=c.source,
            status=c.status,
            last_synced_at=c.last_synced_at.isoformat() if c.last_synced_at else None,
        )
        for c in await ingest.list_connections(db, user.business_id)
    ]


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
