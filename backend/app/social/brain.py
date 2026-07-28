"""Company brain: the facts AI copy is allowed to draw on.

The safety property of this module is one line long — anything that builds a
prompt must call :func:`list_public` and never :func:`list_all`. Records default
to ``public_safe=False``, so an owner has to deliberately release a fact before
it can appear in a post or a public reply.

This sits alongside Pulse's existing ``BusinessKnowledge`` RAG store rather than
replacing it: that one is embedding-backed and feeds win-back email generation,
this one is owner-curated with an explicit publication gate and feeds outward-
facing social copy. Merging them would mean either putting private notes one
retrieval hop away from a public post, or bolting a gate onto a store that has
never had one.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social import CompanyContextItem
from app.schemas.social import ContextItemIn
from app.social.inbox_rules import ContextItem

_TOKEN = re.compile(r"[^a-z0-9_]+")
_STOPWORDS = {"recent", "from", "the", "and", "for", "with", "company"}


async def list_all(db: AsyncSession, *, business_id: str) -> list[CompanyContextItem]:
    """Every record, public-safe or not. For the management screen only."""
    result = await db.execute(
        select(CompanyContextItem)
        .where(CompanyContextItem.business_id == uuid.UUID(business_id))
        .order_by(CompanyContextItem.created_at.desc())
    )
    return list(result.scalars())


async def list_public(db: AsyncSession, *, business_id: str) -> list[CompanyContextItem]:
    """The only accessor generation and reply drafting may use."""
    result = await db.execute(
        select(CompanyContextItem)
        .where(
            CompanyContextItem.business_id == uuid.UUID(business_id),
            CompanyContextItem.public_safe.is_(True),
        )
        .order_by(CompanyContextItem.created_at.desc())
    )
    return list(result.scalars())


async def public_count(db: AsyncSession, *, business_id: str) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(CompanyContextItem)
            .where(
                CompanyContextItem.business_id == uuid.UUID(business_id),
                CompanyContextItem.public_safe.is_(True),
            )
        )
    ) or 0


async def drafting_context(db: AsyncSession, *, business_id: str) -> list[ContextItem]:
    """Public-safe records reduced to what the reply drafter reads."""
    rows = await list_public(db, business_id=business_id)
    return [ContextItem(title=row.title, summary=row.summary) for row in rows]


def search(rows: list[CompanyContextItem], term: str) -> list[CompanyContextItem]:
    """Case-insensitive keyword match over title, kind, summary, and tags.

    An empty query returns everything, which is what the topic picker wants
    when the owner hasn't narrowed anything down.
    """
    terms = [t for t in _TOKEN.split(term.lower()) if len(t) > 2 and t not in _STOPWORDS]
    if not terms:
        return rows
    matches = []
    for row in rows:
        haystack = f"{row.title} {row.kind} {row.summary} {' '.join(row.tags or [])}".lower()
        if any(t in haystack for t in terms):
            matches.append(row)
    return matches


async def add(
    db: AsyncSession, *, business_id: str, payload: ContextItemIn
) -> CompanyContextItem:
    row = CompanyContextItem(
        business_id=uuid.UUID(business_id),
        title=payload.title,
        kind=payload.kind,
        summary=payload.summary,
        source=payload.source,
        occurred_on=payload.date,
        tags=payload.tags,
        public_safe=payload.public_safe,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get(
    db: AsyncSession, *, business_id: str, item_id: str
) -> CompanyContextItem | None:
    try:
        parsed = uuid.UUID(item_id)
    except ValueError:
        return None
    result = await db.execute(
        select(CompanyContextItem).where(
            CompanyContextItem.id == parsed,
            CompanyContextItem.business_id == uuid.UUID(business_id),
        )
    )
    return result.scalar_one_or_none()


async def set_public_safe(
    db: AsyncSession, *, business_id: str, item_id: str, public_safe: bool
) -> CompanyContextItem | None:
    """Release or withdraw a record.

    Splay had no update path at all — flipping the flag meant delete and re-add.
    Since this is the gate that decides what can be said in public, it deserves
    to be reversible without losing the record.
    """
    row = await get(db, business_id=business_id, item_id=item_id)
    if row is None:
        return None
    row.public_safe = public_safe
    await db.flush()
    return row


async def delete(db: AsyncSession, *, business_id: str, item_id: str) -> bool:
    row = await get(db, business_id=business_id, item_id=item_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True
