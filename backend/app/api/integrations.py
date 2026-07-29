"""Integration endpoints: connect Stripe/Square (pull real customer data), import a
CSV, or preview one in memory. Connected data persists per tenant in Postgres."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.security import decrypt_state, decrypt_token, encrypt_state, encrypt_token
from app.integrations.base import IntegrationError
from app.integrations.csv_adapter import parse_csv, template_csv
from app.integrations.registry import get_adapter_class
from app.schemas.api import (
    ConnectIn,
    ConnectionOut,
    CSVPreviewOut,
    PortfolioOut,
    PortfolioSummaryOut,
)
from app.schemas.normalized import SyncResult
from app.services import ingest, oauth
from app.services.activity import build_scored_customers, monthly_revenue_series, summarize
from app.services.portfolio_service import build_portfolio, to_risk

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
    await ingest.persist_sync(db, user.business_id, source, sync)
    return await build_portfolio(db, user)


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
        customers=to_risk(scored),
        warnings=sync.warnings,
    )


@router.get("/oauth/availability")
async def oauth_availability() -> dict[str, bool]:
    """Which providers can offer a "Connect with …" button (OAuth app configured)."""
    return oauth.availability()


@router.get("/oauth/{provider}/start")
async def oauth_start(
    provider: str,
    vertical: str = Query("other"),
    business_name: str = Query(""),
    return_to: str = Query(""),
    user: CurrentUser = CurrentUserDep,
) -> dict:
    """Return the provider authorize URL. The signed state carries the tenant so
    the (unauthenticated) callback knows who the data belongs to."""
    provider = provider.lower()
    if provider not in LIVE_PROVIDERS:
        raise HTTPException(422, detail="provider must be 'stripe' or 'square'")
    if not oauth.availability().get(provider):
        raise HTTPException(
            422, detail=f"OAuth for {provider} isn't configured — paste an API key instead"
        )
    # Only send users back to origins we trust.
    if return_to and return_to.rstrip("/") not in [o.rstrip("/") for o in settings.cors_origins]:
        return_to = ""
    state = encrypt_state(
        {
            "b": user.business_id,
            "n": business_name or user.business_name,
            "v": vertical,
            "r": return_to or settings.frontend_origin,
            "p": provider,
        }
    )
    return {"url": oauth.authorize_url(provider, state)}


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Provider redirects here after approval. Exchange the code, pull the data,
    then send the browser back to the app."""
    provider = provider.lower()

    def bounce(target: str, ok: bool, msg: str = "") -> RedirectResponse:
        qs = f"connected={provider}" if ok else f"error={quote(msg[:200])}"
        return RedirectResponse(f"{target.rstrip('/')}/setup?{qs}", status_code=303)

    fallback = settings.frontend_origin
    try:
        claims = decrypt_state(state or "")
    except ValueError:
        return bounce(fallback, ok=False, msg="Sign-in link expired — try connecting again")
    target = claims.get("r") or fallback

    if error:  # user hit "Deny" on the provider's consent screen
        return bounce(target, ok=False, msg=f"{provider.title()} connection was declined")
    if not code or claims.get("p") != provider:
        return bounce(target, ok=False, msg="Missing authorization code")

    try:
        tokens = await oauth.exchange_code(provider, code)
        adapter = get_adapter_class(provider)()
        await adapter.connect(
            {"access_token": tokens["access_token"], "environment": settings.square_environment}
        )
        sync = await _run_sync(adapter)
    except IntegrationError as exc:
        return bounce(target, ok=False, msg=str(exc))

    if not sync.customers:
        return bounce(
            target, ok=False, msg=f"Connected, but no customers found on this {provider} account"
        )

    await ingest.ensure_business(
        db, claims["b"], claims.get("n") or "My Business", claims.get("v") or "other"
    )
    await ingest.upsert_connection(
        db,
        claims["b"],
        provider,
        encrypt_token(tokens["access_token"]),
        refresh_enc=encrypt_token(tokens["refresh_token"]) if tokens.get("refresh_token") else None,
    )
    await ingest.persist_sync(db, claims["b"], provider, sync)
    return bounce(target, ok=True)


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
        customers=to_risk(scored),
        warnings=[],
    )
