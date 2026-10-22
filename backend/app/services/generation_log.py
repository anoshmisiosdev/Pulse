"""Recording LLM generations and auditable owner actions.

Both writers follow the same rule: **logging must never break the thing it is
logging**. A failed insert here is swallowed and logged locally, because losing
an audit row is bad and failing an owner's send because the audit row wouldn't
write is worse. Callers therefore don't need to wrap these in try/except.

Neither function commits. They flush into the caller's transaction so the log
row and the thing it describes land together, or not at all.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models import AuditLog, GenerationLog

logger = logging.getLogger("pulse.generation_log")

# Prompts and outputs are stored verbatim, but a pathological case (a huge
# knowledge base retrieved into one prompt) shouldn't write a megabyte per
# send. Truncation is marked so a trimmed row is never mistaken for the real
# prompt when reproducing a generation.
_MAX_FIELD_CHARS = 20_000
_TRUNCATION_NOTE = "\n\n[truncated by pulse.generation_log]"


def _clip(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= _MAX_FIELD_CHARS:
        return value
    return value[:_MAX_FIELD_CHARS] + _TRUNCATION_NOTE


async def record_generation(
    db: AsyncSession,
    *,
    business_id: str | uuid.UUID,
    purpose: str,
    system_prompt: str,
    user_prompt: str,
    raw_output: str | None = None,
    model: str | None = None,
    generated_by: str = "claude",
    attempts: int = 1,
    latency_ms: int | None = None,
    error: str | None = None,
    campaign_send_id: str | uuid.UUID | None = None,
    customer_id: str | uuid.UUID | None = None,
) -> GenerationLog | None:
    """Append one generation to the log. Returns None if it couldn't be written."""

    def _as_uuid(value):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

    try:
        row = GenerationLog(
            business_id=_as_uuid(business_id),
            purpose=purpose,
            system_prompt=_clip(system_prompt) or "",
            user_prompt=_clip(user_prompt) or "",
            raw_output=_clip(raw_output),
            model=model,
            generated_by=generated_by,
            attempts=attempts,
            latency_ms=latency_ms,
            error=_clip(error),
            campaign_send_id=_as_uuid(campaign_send_id),
            customer_id=_as_uuid(customer_id),
        )
        db.add(row)
        await db.flush()
        return row
    except Exception as exc:  # never break a send over a log row
        logger.warning("Could not record generation (%s): %s", purpose, exc)
        return None


async def record_audit(
    db: AsyncSession,
    *,
    business_id: str | uuid.UUID,
    action: str,
    summary: str,
    actor: CurrentUser | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
) -> AuditLog | None:
    """Append one auditable action. Returns None if it couldn't be written."""
    try:
        row = AuditLog(
            business_id=(
                business_id
                if isinstance(business_id, uuid.UUID)
                else uuid.UUID(str(business_id))
            ),
            action=action,
            actor_user_id=actor.user_id if actor else None,
            actor_email=actor.email if actor else None,
            subject_type=subject_type,
            subject_id=subject_id,
            summary=summary,
        )
        db.add(row)
        await db.flush()
        return row
    except Exception as exc:
        logger.warning("Could not record audit action (%s): %s", action, exc)
        return None


async def list_generations(
    db: AsyncSession,
    *,
    business_id: str,
    purpose: str | None = None,
    limit: int = 50,
) -> list[GenerationLog]:
    stmt = (
        select(GenerationLog)
        .where(GenerationLog.business_id == uuid.UUID(business_id))
        .order_by(GenerationLog.created_at.desc())
        .limit(min(limit, 200))
    )
    if purpose:
        stmt = stmt.where(GenerationLog.purpose == purpose)
    return list((await db.execute(stmt)).scalars().all())


async def list_audit(
    db: AsyncSession, *, business_id: str, action: str | None = None, limit: int = 100
) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id))
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 500))
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list((await db.execute(stmt)).scalars().all())
