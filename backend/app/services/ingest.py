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

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Business,
    Customer,
    IntegrationConnection,
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


def _event_external_id(
    kind: str, ext: str | None, email: str | None, phone: str | None,
    occurred_at: datetime, amount: object = "",
) -> str:
    """Stable id for events that lack one (CSV rows) so re-imports don't duplicate."""
    if ext:
        return ext
    raw = f"{kind}|{email or phone or '?'}|{occurred_at.isoformat()}|{amount}"
    return "h-" + hashlib.sha1(raw.encode()).hexdigest()[:24]


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

    # ── existing customers: index by identity for dedupe ────────────────────
    existing = (
        (await db.execute(select(Customer).where(Customer.business_id == bid)))
        .scalars()
        .all()
    )
    by_key: dict[str, Customer] = {}
    for c in existing:
        if c.email:
            by_key[f"email:{c.email}"] = c
        if c.phone:
            by_key[f"phone:{c.phone}"] = c
        if c.external_id:
            by_key[f"ext:{c.source}:{c.external_id}"] = c

    def _find(nc: NormalizedCustomer) -> Customer | None:
        for key in (
            f"email:{nc.email}" if nc.email else None,
            f"phone:{nc.phone}" if nc.phone else None,
            f"ext:{source}:{nc.external_id}" if nc.external_id else None,
        ):
            if key and key in by_key:
                return by_key[key]
        return None

    n_customers = 0
    for nc in sync.customers:
        row = _find(nc)
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
        else:  # merge: fill blanks, never clobber
            row.first_name = row.first_name or nc.first_name
            row.last_name = row.last_name or nc.last_name
            row.email = row.email or nc.email
            row.phone = row.phone or nc.phone
            row.joined_at = row.joined_at or nc.created_at
            row.favorite_item = row.favorite_item or nc.favorite_item
        for key in (
            f"email:{row.email}" if row.email else None,
            f"phone:{row.phone}" if row.phone else None,
            f"ext:{source}:{row.external_id}" if row.external_id else None,
        ):
            if key:
                by_key[key] = row

    def _resolve(email: str | None, phone: str | None, ext: str | None) -> Customer | None:
        for key in (
            f"ext:{source}:{ext}" if ext else None,
            f"email:{email}" if email else None,
            f"phone:{phone}" if phone else None,
        ):
            if key and key in by_key:
                return by_key[key]
        return None

    # ── transactions / visits: insert-if-new by external id ─────────────────
    seen_tx = {
        x
        for (x,) in await db.execute(
            select(Transaction.external_id).where(Transaction.business_id == bid)
        )
        if x
    }
    n_tx = 0
    for t in sync.transactions:
        ext = _event_external_id(
            "tx", t.external_id, t.customer_email, t.customer_phone, t.occurred_at, t.amount
        )
        if ext in seen_tx:
            continue
        cust = _resolve(t.customer_email, t.customer_phone, t.customer_external_id)
        if cust is None:
            continue  # payment from someone not in the customer list
        db.add(
            Transaction(
                business_id=bid,
                customer_id=cust.id,
                source=source,
                external_id=ext,
                amount=t.amount,
                currency=t.currency,
                occurred_at=t.occurred_at,
            )
        )
        seen_tx.add(ext)
        n_tx += 1

    seen_visits = {
        x
        for (x,) in await db.execute(
            select(Visit.external_id).where(Visit.business_id == bid)
        )
        if x
    }
    n_visits = 0
    for v in sync.visits:
        ext = _event_external_id(
            "visit", v.external_id, v.customer_email, v.customer_phone, v.occurred_at
        )
        if ext in seen_visits:
            continue
        cust = _resolve(v.customer_email, v.customer_phone, v.customer_external_id)
        if cust is None:
            continue
        db.add(
            Visit(
                business_id=bid,
                customer_id=cust.id,
                source=source,
                external_id=ext,
                occurred_at=v.occurred_at,
            )
        )
        seen_visits.add(ext)
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
                currency=t.currency,
                occurred_at=t.occurred_at,
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
    import json

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
                    reasons=json.dumps(s.result.reasons),
                    signals=json.dumps(s.result.signals),
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
    for model in (RiskScore, Visit, Transaction, Customer, SyncRun):
        await db.execute(delete(model).where(model.business_id == bid))
    await db.flush()


async def upsert_connection(
    db: AsyncSession,
    business_id: str,
    source: str,
    token_enc: str | None,
    refresh_enc: str | None = None,
) -> IntegrationConnection:
    bid = _uuid(business_id)
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
    conn.last_synced_at = datetime.now(UTC)
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
