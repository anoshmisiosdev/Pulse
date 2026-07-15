"""Per-business knowledge CRUD + similarity search (the "R" in RAG).

Storing a snippet embeds it once, up front. Retrieval degrades to "no context"
rather than failing — the caller (campaign generation) must still work, just
less personalized, matching how the rest of the LLM pipeline degrades to a
static template rather than blocking a send.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessKnowledge
from app.models.knowledge import KNOWLEDGE_KINDS
from app.services.ingest import _uuid
from app.services.rag.embeddings import EmbeddingError, embed_query, embed_texts

logger = logging.getLogger("pulse.rag.knowledge_store")


async def add_knowledge(
    db: AsyncSession, *, business_id: str, kind: str, content: str
) -> BusinessKnowledge:
    if kind not in KNOWLEDGE_KINDS:
        raise ValueError(f"kind must be one of {KNOWLEDGE_KINDS}")
    content = content.strip()
    if not content:
        raise ValueError("content must not be empty")

    embedding = (await embed_texts([content], input_type="search_document"))[0]
    row = BusinessKnowledge(
        business_id=_uuid(business_id), kind=kind, content=content, embedding=embedding
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_knowledge(db: AsyncSession, *, business_id: str) -> list[BusinessKnowledge]:
    stmt = (
        select(BusinessKnowledge)
        .where(BusinessKnowledge.business_id == _uuid(business_id))
        .order_by(BusinessKnowledge.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_knowledge(db: AsyncSession, *, business_id: str, knowledge_id: str) -> bool:
    row = await db.get(BusinessKnowledge, uuid.UUID(knowledge_id))
    if row is None or row.business_id != _uuid(business_id):
        return False
    await db.delete(row)
    await db.commit()
    return True


async def search_knowledge(
    db: AsyncSession, *, business_id: str, query: str, top_k: int = 4
) -> list[BusinessKnowledge]:
    """Top-k most relevant snippets for this business, or [] if retrieval isn't
    available (no query text, Bedrock unreachable, etc.) — never raises."""
    if not query.strip():
        return []
    try:
        query_vector = await embed_query(query)
    except EmbeddingError as exc:
        logger.warning("knowledge retrieval degraded (no context injected): %s", exc)
        return []

    stmt = (
        select(BusinessKnowledge)
        .where(BusinessKnowledge.business_id == _uuid(business_id))
        .order_by(BusinessKnowledge.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
