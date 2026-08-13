"""Per-tenant persistence: normalized records <-> Supabase Postgres.

`persist_sync` upserts a SyncResult into the tenant's tables (deduping customers by
email/phone/external-id) and refreshes denormalized scores + the RiskScore log.
`load_sync` rebuilds a SyncResult from the DB so the same pure scoring pipeline
(`services/activity.py`) powers dashboards for CSV, Stripe and Square alike.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError
from app.models import (
    Business,
    Customer,
    CustomerIdentity,
    IntegrationConnection,
    ProviderWebhookEvent,
    RiskScore,
    SyncRun,
    Transaction,
    Visit,
)
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)
from app.services.activity import build_scored_customers


def _uuid(value: str) -> uuid.UUID:
    """Coerce an auth-provided id (Supabase sub) to a UUID, derived if malformed."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"pulse:{value}")


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _event_external_id(
    kind: str, ext: str | None, email: str | None, phone: str | None,
    occurred_at: datetime, amount: object = "",
) -> str:
    """Stable id for events that lack one (CSV rows) so re-imports don't duplicate."""
    if ext:
        return ext
    raw = f"{kind}|{email or phone or '?'}|{occurred_at.isoformat()}|{amount}"
    return "h-" + hashlib.sha1(raw.encode()).hexdigest()[:24]


def _chunks(values: list, size: int = 500):
    for i in range(0, len(values), size):
        yield values[i : i + size]


async def ensure_business(
    db: AsyncSession, business_id: str, name: str, vertical: str
) -> Business:
    bid = _uuid(business_id)
    biz = await db.get(Business, bid)
    if biz is None:
        biz = Business(id=bid, name=name, vertical=vertical)
        db.add(biz)
    else:
        if name and name != "My Business":
            biz.name = name
        if vertical:
            biz.vertical = vertical
    await db.flush()
    return biz


async def persist_sync(
    db: AsyncSession, business_id: str, source: str, sync: SyncResult
) -> SyncRun:
    """Upsert a normalized sync into the tenant's tables. Returns the SyncRun row."""
    bid = _uuid(business_id)
    run = SyncRun(business_id=bid, source=source, status="running")
    db.add(run)
    await db.flush()

    source = source.lower().strip()

    # ── canonical customers + provider identities ───────────────────────────
    # Memory stays bounded by the sync batch. Provider ids live in
    # CustomerIdentity so a cross-source email merge does not discard either
    # Stripe's or Square's customer id.
    emails = sorted(
        {c.email for c in sync.customers if c.email}
        | {t.customer_email for t in sync.transactions if t.customer_email}
        | {v.customer_email for v in sync.visits if v.customer_email}
    )
    phones = sorted(
        {c.phone for c in sync.customers if c.phone}
        | {t.customer_phone for t in sync.transactions if t.customer_phone}
        | {v.customer_phone for v in sync.visits if v.customer_phone}
    )
    exts = sorted(
        {c.external_id for c in sync.customers if c.external_id}
        | {t.customer_external_id for t in sync.transactions if t.customer_external_id}
        | {v.customer_external_id for v in sync.visits if v.customer_external_id}
    )
    existing: dict[uuid.UUID, Customer] = {}
    for f in [Customer.email.in_(b) for b in _chunks(emails)] + [
        Customer.phone.in_(b) for b in _chunks(phones)
    ]:
        rows = (
            (await db.execute(select(Customer).where(Customer.business_id == bid, f)))
            .scalars()
            .all()
        )
        existing.update({c.id: c for c in rows})
    by_key: dict[str, Customer] = {}
    for c in existing.values():
        if c.email:
            by_key[f"email:{c.email}"] = c
        if c.phone:
            by_key[f"phone:{c.phone}"] = c
    by_identity: dict[str, Customer] = {}
    persisted_identity_exts: set[str] = set()
    for batch in _chunks(exts):
        rows = (
            await db.execute(
                select(CustomerIdentity, Customer)
                .join(Customer, Customer.id == CustomerIdentity.customer_id)
                .where(
                    CustomerIdentity.business_id == bid,
                    CustomerIdentity.source == source,
                    CustomerIdentity.external_id.in_(batch),
                )
            )
        ).all()
        for identity, customer in rows:
            existing[customer.id] = customer
            by_identity[identity.external_id] = customer
            persisted_identity_exts.add(identity.external_id)

    # Backward compatibility for rows created before CustomerIdentity existed.
    for batch in _chunks(exts):
        rows = (
            await db.execute(
                select(Customer).where(
                    Customer.business_id == bid,
                    Customer.source == source,
                    Customer.external_id.in_(batch),
                )
            )
        ).scalars().all()
        for customer in rows:
            existing[customer.id] = customer
            if customer.external_id:
                by_identity.setdefault(customer.external_id, customer)

    def _find(nc: NormalizedCustomer) -> Customer | None:
        if nc.external_id and nc.external_id in by_identity:
            return by_identity[nc.external_id]
        for key in (
            f"email:{nc.email}" if nc.email else None,
            f"phone:{nc.phone}" if nc.phone else None,
        ):
            if key and key in by_key:
                return by_key[key]
        return None

    def _remember(row: Customer) -> None:
        if row.email:
            by_key[f"email:{row.email}"] = row
        if row.phone:
            by_key[f"phone:{row.phone}"] = row

    def _attach_identity(row: Customer, external_id: str | None) -> None:
        if not external_id or external_id in persisted_identity_exts:
            return
        mapped = by_identity.get(external_id)
        if mapped is not None and mapped.id != row.id:
            return
        db.add(
            CustomerIdentity(
                business_id=bid,
                customer_id=row.id,
                source=source,
                external_id=external_id,
            )
        )
        by_identity[external_id] = row
        persisted_identity_exts.add(external_id)

    n_customers = 0
    for nc in sync.customers:
        row = _find(nc)
        matched_by_identity = bool(
            row is not None
            and nc.external_id
            and by_identity.get(nc.external_id) is row
        )
        if row is None:
            row = Customer(
                business_id=bid,
                source=source,
                external_id=nc.external_id,
                first_name=nc.first_name,
                last_name=nc.last_name,
                email=nc.email,
                phone=nc.phone,
                joined_at=nc.created_at,
                favorite_item=nc.favorite_item,
            )
            db.add(row)
            await db.flush()
            n_customers += 1
        elif matched_by_identity:
            # A provider identity is stronger than contact information, so its
            # customer.updated event may safely replace a changed email/phone.
            old_email, old_phone = row.email, row.phone
            row.first_name = nc.first_name or row.first_name
            row.last_name = nc.last_name or row.last_name
            row.email = nc.email or row.email
            row.phone = nc.phone or row.phone
            if old_email and old_email != row.email:
                by_key.pop(f"email:{old_email}", None)
            if old_phone and old_phone != row.phone:
                by_key.pop(f"phone:{old_phone}", None)
            row.joined_at = row.joined_at or nc.created_at
            row.favorite_item = nc.favorite_item or row.favorite_item
        else:  # weaker email/phone merge: fill blanks, never clobber
            row.first_name = row.first_name or nc.first_name
            row.last_name = row.last_name or nc.last_name
            row.email = row.email or nc.email
            row.phone = row.phone or nc.phone
            row.joined_at = row.joined_at or nc.created_at
            row.favorite_item = row.favorite_item or nc.favorite_item
        _remember(row)
        _attach_identity(row, nc.external_id)

    def _resolve(email: str | None, phone: str | None, ext: str | None) -> Customer | None:
        if ext and ext in by_identity:
            return by_identity[ext]
        for key in (f"email:{email}" if email else None, f"phone:{phone}" if phone else None):
            if key and key in by_key:
                return by_key[key]
        return None

    # Guest checkout payments often carry contact details without a provider
    # Customer object. Materialize a minimal canonical customer so valuable
    # history is not silently dropped.
    for event in [*sync.transactions, *sync.visits]:
        email = event.customer_email
        phone = event.customer_phone
        ext = event.customer_external_id
        row = _resolve(email, phone, ext)
        if row is None and (email or phone):
            name = getattr(event, "customer_name", None) or ""
            first, last = (name.split(" ", 1) + [None])[:2] if name else (None, None)
            row = Customer(
                business_id=bid,
                source=source,
                external_id=ext,
                first_name=first or None,
                last_name=last or None,
                email=email,
                phone=phone,
                joined_at=event.occurred_at,
            )
            db.add(row)
            await db.flush()
            n_customers += 1
            _remember(row)
        if row is not None:
            _attach_identity(row, ext)

    # ── payment lifecycle upsert ─────────────────────────────────────────────
    tx_exts = sorted(
        {
            _event_external_id(
                "tx", t.external_id, t.customer_email, t.customer_phone,
                t.occurred_at, t.amount,
            )
            for t in sync.transactions
        }
    )
    existing_tx: dict[str, Transaction] = {}
    for batch in _chunks(tx_exts):
        rows = (
            await db.execute(
                select(Transaction).where(
                    Transaction.business_id == bid,
                    Transaction.source == source,
                    Transaction.external_id.in_(batch),
                )
            )
        ).scalars().all()
        existing_tx.update({row.external_id: row for row in rows if row.external_id})
    n_tx = 0
    for t in sync.transactions:
        ext = _event_external_id(
            "tx", t.external_id, t.customer_email, t.customer_phone, t.occurred_at, t.amount
        )
        cust = _resolve(t.customer_email, t.customer_phone, t.customer_external_id)
        if cust is None:
            continue  # payment from someone not in the customer list
        gross = t.gross_amount if t.gross_amount is not None else t.amount + t.refunded_amount
        row = existing_tx.get(ext)
        if row is None:
            row = Transaction(
                business_id=bid,
                customer_id=cust.id,
                source=source,
                external_id=ext,
                amount=t.amount,
                gross_amount=gross,
                refunded_amount=t.refunded_amount,
                currency=t.currency,
                status=t.status,
                provider_updated_at=t.updated_at,
                failure_code=t.failure_code,
                occurred_at=t.occurred_at,
            )
            db.add(row)
            existing_tx[ext] = row
            n_tx += 1
            continue

        # Webhook events carry an update timestamp. Ignore an older delivery so
        # a retried "succeeded" event cannot undo a newer refund event.
        stored_updated = _aware_utc(row.provider_updated_at)
        incoming_updated = _aware_utc(t.updated_at)
        if stored_updated and incoming_updated and incoming_updated < stored_updated:
            continue
        changed = any(
            (
                row.customer_id != cust.id,
                Decimal(row.amount) != t.amount,
                (Decimal(row.gross_amount) if row.gross_amount is not None else None) != gross,
                Decimal(row.refunded_amount or 0) != t.refunded_amount,
                row.currency != t.currency,
                row.status != t.status,
                stored_updated != incoming_updated and incoming_updated is not None,
                row.failure_code != t.failure_code,
            )
        )
        if changed:
            row.customer_id = cust.id
            row.amount = t.amount
            row.gross_amount = gross
            row.refunded_amount = t.refunded_amount
            row.currency = t.currency
            row.status = t.status
            row.provider_updated_at = t.updated_at or row.provider_updated_at
            row.failure_code = t.failure_code
            row.occurred_at = t.occurred_at
            n_tx += 1

    visit_exts = sorted(
        {
            _event_external_id(
                "visit", v.external_id, v.customer_email, v.customer_phone, v.occurred_at
            )
            for v in sync.visits
        }
    )
    existing_visits: dict[str, Visit] = {}
    for batch in _chunks(visit_exts):
        rows = (
            await db.execute(
                select(Visit).where(
                    Visit.business_id == bid,
                    Visit.source == source,
                    Visit.external_id.in_(batch),
                )
            )
        ).scalars().all()
        existing_visits.update({row.external_id: row for row in rows if row.external_id})

    # Include visits that might need to be removed after a full refund/failure.
    derived_exts = [f"visit-{t.external_id}" for t in sync.transactions if t.external_id]
    missing_derived = [ext for ext in derived_exts if ext not in existing_visits]
    for batch in _chunks(missing_derived):
        rows = (
            await db.execute(
                select(Visit).where(
                    Visit.business_id == bid,
                    Visit.source == source,
                    Visit.external_id.in_(batch),
                )
            )
        ).scalars().all()
        existing_visits.update({row.external_id: row for row in rows if row.external_id})
    n_visits = 0
    for v in sync.visits:
        ext = _event_external_id(
            "visit", v.external_id, v.customer_email, v.customer_phone, v.occurred_at
        )
        cust = _resolve(v.customer_email, v.customer_phone, v.customer_external_id)
        if cust is None:
            continue
        row = existing_visits.get(ext)
        if row is None:
            row = Visit(
                business_id=bid,
                customer_id=cust.id,
                source=source,
                external_id=ext,
                occurred_at=v.occurred_at,
            )
            db.add(row)
            existing_visits[ext] = row
            n_visits += 1
        elif row.customer_id != cust.id or _aware_utc(row.occurred_at) != _aware_utc(v.occurred_at):
            row.customer_id = cust.id
            row.occurred_at = v.occurred_at
            n_visits += 1

    for t in sync.transactions:
        if not t.external_id or t.is_revenue:
            continue
        ext = f"visit-{t.external_id}"
        stale = existing_visits.get(ext)
        if stale is not None:
            await db.delete(stale)
            existing_visits.pop(ext, None)
            n_visits += 1

    run.status = "success"
    run.customers_synced = n_customers
    run.transactions_synced = n_tx
    run.visits_synced = n_visits
    run.finished_at = datetime.now(UTC)
    await db.flush()

    await refresh_scores(db, business_id)
    return run


async def load_sync(db: AsyncSession, business_id: str) -> SyncResult:
    """Rebuild a SyncResult from the tenant's rows (external_id = row PK)."""
    bid = _uuid(business_id)
    customers = (
        (await db.execute(select(Customer).where(Customer.business_id == bid)))
        .scalars()
        .all()
    )
    txs = (
        (await db.execute(select(Transaction).where(Transaction.business_id == bid)))
        .scalars()
        .all()
    )
    visits = (
        (await db.execute(select(Visit).where(Visit.business_id == bid))).scalars().all()
    )
    return SyncResult(
        customers=[
            NormalizedCustomer(
                external_id=str(c.id),
                source=c.source,
                first_name=c.first_name,
                last_name=c.last_name,
                email=c.email,
                phone=c.phone,
                created_at=c.joined_at,
                favorite_item=c.favorite_item,
            )
            for c in customers
        ],
        transactions=[
            NormalizedTransaction(
                external_id=t.external_id,
                source=t.source,
                customer_external_id=str(t.customer_id),
                amount=t.amount,
                gross_amount=t.gross_amount,
                refunded_amount=t.refunded_amount,
                currency=t.currency,
                status=t.status,
                occurred_at=t.occurred_at,
                updated_at=t.provider_updated_at,
                failure_code=t.failure_code,
            )
            for t in txs
        ],
        visits=[
            NormalizedVisit(
                external_id=v.external_id,
                source=v.source,
                customer_external_id=str(v.customer_id),
                occurred_at=v.occurred_at,
            )
            for v in visits
        ],
    )


async def refresh_scores(db: AsyncSession, business_id: str) -> None:
    """Re-score the tenant and update denormalized fields + append the RiskScore log."""
    bid = _uuid(business_id)
    biz = await db.get(Business, bid)
    sync = await load_sync(db, business_id)
    if not sync.customers:
        return
    scored = build_scored_customers(sync, vertical=biz.vertical if biz else "other")
    rows = {
        str(c.id): c
        for c in (
            (await db.execute(select(Customer).where(Customer.business_id == bid)))
            .scalars()
            .all()
        )
    }
    for s in scored:
        row = rows.get(s.customer.external_id or "")
        if row is None:
            continue
        band_changed = row.current_band != s.result.band
        row.current_score = s.result.score
        row.current_band = s.result.band
        if band_changed:  # append-only log, one row per band change
            db.add(
                RiskScore(
                    business_id=bid,
                    customer_id=row.id,
                    score=s.result.score,
                    band=s.result.band,
                    reasons=s.result.reasons,
                    signals=s.result.signals,
                )
            )
    await db.flush()


async def has_data(db: AsyncSession, business_id: str) -> bool:
    bid = _uuid(business_id)
    row = await db.execute(select(Customer.id).where(Customer.business_id == bid).limit(1))
    return row.first() is not None


async def wipe_business_data(db: AsyncSession, business_id: str) -> None:
    """Per-tenant data deletion (also the CCPA/GDPR endpoint's workhorse)."""
    bid = _uuid(business_id)
    for model in (
        ProviderWebhookEvent,
        RiskScore,
        Visit,
        Transaction,
        CustomerIdentity,
        Customer,
        SyncRun,
    ):
        await db.execute(delete(model).where(model.business_id == bid))
    await db.flush()


async def upsert_connection(
    db: AsyncSession,
    business_id: str,
    source: str,
    token_enc: str | None,
    refresh_enc: str | None = None,
    *,
    provider_account_id: str | None = None,
    environment: str | None = None,
    token_expires_at: datetime | None = None,
    synced_at: datetime | None = None,
) -> IntegrationConnection:
    bid = _uuid(business_id)
    if provider_account_id:
        conflict = (
            await db.execute(
                select(IntegrationConnection.id).where(
                    IntegrationConnection.source == source,
                    IntegrationConnection.provider_account_id == provider_account_id,
                    IntegrationConnection.business_id != bid,
                )
            )
        ).first()
        if conflict:
            raise IntegrationError(
                f"This {source.title()} account is already connected to another business"
            )
    conn = (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.business_id == bid,
                IntegrationConnection.source == source,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        conn = IntegrationConnection(business_id=bid, source=source)
        db.add(conn)
    conn.status = "active"
    if token_enc:
        conn.access_token_enc = token_enc
    if refresh_enc:
        conn.refresh_token_enc = refresh_enc
    if provider_account_id:
        conn.provider_account_id = provider_account_id
    if environment:
        conn.environment = environment
    if token_expires_at:
        conn.token_expires_at = token_expires_at
    conn.last_synced_at = synced_at or datetime.now(UTC)
    conn.last_error = None
    await db.flush()
    return conn


async def list_connections(db: AsyncSession, business_id: str) -> list[IntegrationConnection]:
    bid = _uuid(business_id)
    return list(
        (
            await db.execute(
                select(IntegrationConnection).where(IntegrationConnection.business_id == bid)
            )
        )
        .scalars()
        .all()
    )


async def find_connection_by_provider_account(
    db: AsyncSession, source: str, provider_account_id: str
) -> IntegrationConnection | None:
    return (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.source == source,
                IntegrationConnection.provider_account_id == provider_account_id,
            )
        )
    ).scalar_one_or_none()


async def record_sync_error(
    db: AsyncSession, connection: IntegrationConnection, error: str
) -> SyncRun:
    now = datetime.now(UTC)
    connection.status = "error"
    connection.last_error = error[:1000]
    run = SyncRun(
        business_id=connection.business_id,
        source=connection.source,
        status="error",
        error=error[:1000],
        finished_at=now,
    )
    db.add(run)
    await db.flush()
    return run
