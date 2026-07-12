"""Per-business knowledge base: services, brand voice, past campaign examples —
retrieved into campaign generation (see app/services/rag/)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.models.knowledge import KNOWLEDGE_KINDS
from app.schemas.api import KnowledgeIn, KnowledgeOut
from app.services.rag import knowledge_store
from app.services.rag.embeddings import EmbeddingError

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _to_out(row) -> KnowledgeOut:
    return KnowledgeOut(
        id=str(row.id),
        kind=row.kind,
        content=row.content,
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=list[KnowledgeOut])
async def list_knowledge(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> list[KnowledgeOut]:
    rows = await knowledge_store.list_knowledge(db, business_id=user.business_id)
    return [_to_out(r) for r in rows]


@router.post("", response_model=KnowledgeOut, status_code=201)
async def add_knowledge(
    payload: KnowledgeIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> KnowledgeOut:
    if payload.kind not in KNOWLEDGE_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {KNOWLEDGE_KINDS}")
    try:
        row = await knowledge_store.add_knowledge(
            db, business_id=user.business_id, kind=payload.kind, content=payload.content
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=f"Could not embed content: {exc}") from exc
    return _to_out(row)


@router.delete("/{knowledge_id}", status_code=204)
async def delete_knowledge(
    knowledge_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> None:
    try:
        deleted = await knowledge_store.delete_knowledge(
            db, business_id=user.business_id, knowledge_id=knowledge_id
        )
    except ValueError:
        deleted = False
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
