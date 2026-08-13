"""Orchestration for safe incremental Stripe/Square synchronization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_token, encrypt_token
from app.integrations.base import DataSourceAdapter, IntegrationError
from app.integrations.registry import get_adapter_class
from app.models import IntegrationConnection, SyncRun
from app.schemas.normalized import SyncResult
from app.services import ingest, oauth


async def run_adapter(
    adapter: DataSourceAdapter, since: datetime | None = None
) -> SyncResult:
    """Pull the three normalized streams while letting payment-backed visits reuse cache."""
    return SyncResult(
        customers=await adapter.sync_customers(since),
        transactions=await adapter.sync_transactions(since),
        visits=await adapter.sync_visits(since),
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _credential_for_connection(
    db: AsyncSession, connection: IntegrationConnection
) -> tuple[str, str | None, datetime | None]:
    if not connection.access_token_enc:
        raise IntegrationError(f"{connection.source.title()} connection has no access token")
    token = decrypt_token(connection.access_token_enc)
    refresh = (
        decrypt_token(connection.refresh_token_enc) if connection.refresh_token_enc else None
    )
    expires_at = _aware(connection.token_expires_at)

    # Square asks partner apps to refresh at least every seven days. A standard
    # token lives 30 days, so refresh once it has <=23 days remaining.
    should_refresh_square = bool(
        connection.source == "square"
        and refresh
        and expires_at
        and expires_at <= datetime.now(UTC) + timedelta(days=23)
    )
    if should_refresh_square:
        refreshed = await oauth.refresh_access_token(
            "square", refresh or "", connection.environment
        )
        token = refreshed["access_token"]
        refresh = refreshed.get("refresh_token") or refresh
        expires_at = refreshed.get("expires_at")
        connection.access_token_enc = encrypt_token(token)
        connection.refresh_token_enc = encrypt_token(refresh) if refresh else None
        connection.token_expires_at = expires_at
        connection.provider_account_id = (
            refreshed.get("account_id") or connection.provider_account_id
        )
        await db.flush()
    return token, refresh, expires_at


async def sync_connection(
    db: AsyncSession, connection: IntegrationConnection
) -> SyncRun:
    """Incrementally sync one persisted connection and update its audit state."""
    started_at = datetime.now(UTC)
    try:
        token, _, expires_at = await _credential_for_connection(db, connection)
        adapter = get_adapter_class(connection.source)()
        await adapter.connect(
            {"access_token": token, "environment": connection.environment or "production"}
        )
        since = _aware(connection.last_synced_at)
        if since:
            since -= timedelta(minutes=settings.payment_sync_overlap_minutes)
        sync = await run_adapter(adapter, since)
        run = await ingest.persist_sync(
            db, str(connection.business_id), connection.source, sync
        )
        await ingest.upsert_connection(
            db,
            str(connection.business_id),
            connection.source,
            None,
            provider_account_id=adapter.account_id or connection.provider_account_id,
            environment=adapter.environment or connection.environment,
            token_expires_at=expires_at,
            synced_at=started_at,
        )
        return run
    except (IntegrationError, ValueError) as exc:
        await ingest.record_sync_error(db, connection, str(exc))
        raise


async def sync_business_connections(
    db: AsyncSession, business_id: str
) -> list[SyncRun]:
    connections = await ingest.list_connections(db, business_id)
    live = [
        connection
        for connection in connections
        if connection.source in {"stripe", "square"} and connection.access_token_enc
    ]
    if not live:
        raise IntegrationError("No connected Stripe or Square integration to sync")
    runs: list[SyncRun] = []
    errors: list[str] = []
    for connection in live:
        try:
            runs.append(await sync_connection(db, connection))
        except (IntegrationError, ValueError) as exc:
            errors.append(f"{connection.source}: {exc}")
    if errors and not runs:
        raise IntegrationError("; ".join(errors))
    return runs
