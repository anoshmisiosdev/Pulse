"""The assistant endpoint: ask a question, get an answer grounded in own data.

Conversations persist so an owner can close the tab and come back, and so a
turn that queued real outreach has a record of the exchange that produced it.

Streaming is offered as Server-Sent Events alongside the plain JSON endpoint.
The agent loop isn't token-streamed - it can't be, since it may run several
tool steps before it has anything to say - so the stream emits progress events
("Reading your at-risk customers…") and then the finished answer. That's more
honest than faking a typing effect over a request that's actually doing
database work, and it's the part owners want to see: which of their data the
answer came from.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.guard import EntitlementsDep
from app.billing.limits import Entitlements
from app.chat.agent import AgentReply, answer
from app.chat.tools import ToolContext
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.posthog_client import capture_event
from app.models import Business, ChatConversation, ChatMessage
from app.schemas.chat import (
    ChatAskIn,
    ChatAskOut,
    ChatMessageOut,
    ConversationDetailOut,
    ConversationOut,
    SuggestionsOut,
    ToolCallOut,
)
from app.services.generation_log import record_generation
from app.services.ingest import _uuid

logger = logging.getLogger("pulse.api.chat")
router = APIRouter(prefix="/chat", tags=["chat"])

# Turns of prior conversation loaded as context for a new question.
HISTORY_LIMIT = 16

_SUGGESTIONS = (
    "Who's about to stop coming in?",
    "How much revenue is at risk right now?",
    "Draft a win-back email for my highest-risk customers",
    "How many customers have we won back, and what was that worth?",
    "What's waiting for my approval?",
)


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _message_out(row: ChatMessage) -> ChatMessageOut:
    calls = row.tool_calls or []
    return ChatMessageOut(
        id=str(row.id),
        role=row.role,
        content=row.content,
        tool_calls=[
            ToolCallOut(tool=str(c.get("tool", "")), summary=str(c.get("summary", "")))
            for c in calls
            if isinstance(c, dict)
        ],
        generated_by=row.generated_by,
        model=row.model,
        created_at=_iso(row.created_at),
    )


def _title_from(message: str) -> str:
    """A scannable thread title from the first question."""
    cleaned = " ".join(message.split())
    return (cleaned[:57] + "…") if len(cleaned) > 58 else (cleaned or "New conversation")


async def _resolve_conversation(
    db: AsyncSession, user: CurrentUser, conversation_id: str | None, first_message: str
) -> ChatConversation:
    if conversation_id:
        try:
            parsed = _uuid(conversation_id)
        except (ValueError, AttributeError):
            raise HTTPException(404, "Conversation not found") from None
        conversation = await db.get(ChatConversation, parsed)
        if conversation is None or conversation.business_id != _uuid(user.business_id):
            raise HTTPException(404, "Conversation not found")
        return conversation

    conversation = ChatConversation(
        business_id=_uuid(user.business_id),
        title=_title_from(first_message),
        created_by_user_id=user.user_id,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _history(
    db: AsyncSession, conversation: ChatConversation
) -> list[tuple[str, str]]:
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return [(row.role, row.content) for row in reversed(rows)]


async def _run_turn(
    db: AsyncSession,
    user: CurrentUser,
    ent: Entitlements,
    payload: ChatAskIn,
) -> tuple[ChatConversation, ChatMessage, AgentReply]:
    """Persist the question, run the agent, persist the answer."""
    conversation = await _resolve_conversation(
        db, user, payload.conversation_id, payload.message
    )
    history = await _history(db, conversation)

    db.add(
        ChatMessage(
            business_id=_uuid(user.business_id),
            conversation_id=conversation.id,
            role="user",
            content=payload.message,
            generated_by="owner",
        )
    )
    await db.flush()

    biz = await db.get(Business, _uuid(user.business_id))
    ctx = ToolContext(db=db, user=user, entitlements=ent)
    reply = await answer(
        ctx,
        question=payload.message,
        history=history,
        business_name=(biz.name if biz else user.business_name),
        vertical=(biz.vertical if biz else "local business"),
    )

    assistant = ChatMessage(
        business_id=_uuid(user.business_id),
        conversation_id=conversation.id,
        role="assistant",
        content=reply.text,
        tool_calls=[call.as_dict() for call in reply.tool_calls] or None,
        model=reply.model,
        generated_by=reply.generated_by,
    )
    db.add(assistant)
    # Touch the conversation so the thread list sorts by real activity.
    conversation.title = conversation.title or _title_from(payload.message)
    await db.flush()

    await record_generation(
        db,
        business_id=user.business_id,
        purpose="chat_reply",
        system_prompt="[chat agent]",
        user_prompt=payload.message,
        raw_output=reply.text,
        model=reply.model,
        generated_by=reply.generated_by,
        attempts=max(1, reply.steps),
        latency_ms=reply.latency_ms,
        error=reply.error,
    )
    capture_event(
        "chat_message_sent",
        distinct_id=user.user_id,
        properties={
            "generated_by": reply.generated_by,
            "steps": reply.steps,
            "tools_used": [call.tool for call in reply.tool_calls],
            "drafted_campaign": bool(reply.drafted_campaign_id),
        },
    )
    return conversation, assistant, reply


@router.get("/suggestions", response_model=SuggestionsOut)
async def suggestions(_user: CurrentUser = CurrentUserDep) -> SuggestionsOut:
    return SuggestionsOut(suggestions=list(_SUGGESTIONS))


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[ConversationOut]:
    rows = (
        (
            await db.execute(
                select(ChatConversation)
                .where(ChatConversation.business_id == _uuid(user.business_id))
                .order_by(ChatConversation.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    counts = dict(
        (
            await db.execute(
                select(ChatMessage.conversation_id, func.count())
                .where(ChatMessage.conversation_id.in_([r.id for r in rows]))
                .group_by(ChatMessage.conversation_id)
            )
        ).all()
    )
    return [
        ConversationOut(
            id=str(row.id),
            title=row.title,
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
            message_count=counts.get(row.id, 0),
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> ConversationDetailOut:
    try:
        parsed = _uuid(conversation_id)
    except (ValueError, AttributeError):
        raise HTTPException(404, "Conversation not found") from None
    conversation = await db.get(ChatConversation, parsed)
    if conversation is None or conversation.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Conversation not found")

    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return ConversationDetailOut(
        id=str(conversation.id),
        title=conversation.title,
        created_at=_iso(conversation.created_at),
        updated_at=_iso(conversation.updated_at),
        message_count=len(rows),
        messages=[_message_out(row) for row in rows],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> None:
    try:
        parsed = _uuid(conversation_id)
    except (ValueError, AttributeError):
        raise HTTPException(404, "Conversation not found") from None
    conversation = await db.get(ChatConversation, parsed)
    if conversation is None or conversation.business_id != _uuid(user.business_id):
        raise HTTPException(404, "Conversation not found")
    # Messages are removed explicitly rather than leaning on the FK's
    # ON DELETE CASCADE: Postgres enforces it, SQLite doesn't unless
    # `PRAGMA foreign_keys` is on, and a delete that only works on one of our
    # two dialects is the kind of difference that shows up as orphaned rows in
    # a data-deletion request.
    await db.execute(
        delete(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
    )
    await db.delete(conversation)
    await db.commit()


@router.post("/ask", response_model=ChatAskOut)
async def ask(
    payload: ChatAskIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> ChatAskOut:
    """Ask a question. Answers only from this tenant's own data."""
    conversation, assistant, reply = await _run_turn(db, user, ent, payload)
    await db.commit()
    return ChatAskOut(
        conversation_id=str(conversation.id),
        message=_message_out(assistant),
        drafted_campaign_id=reply.drafted_campaign_id,
    )


@router.post("/stream")
async def ask_streaming(
    payload: ChatAskIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> StreamingResponse:
    """Same turn, as Server-Sent Events, so the UI can show progress.

    Events: ``status`` (what it's doing), ``tool`` (what it read), ``message``
    (the finished answer), ``error``. The turn is executed in a background task
    while the generator forwards whatever the task has published, so a slow
    tool chain shows progress instead of a spinner.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def publish(event: str, data: dict) -> None:
        queue.put_nowait(f"event: {event}\ndata: {json.dumps(data)}\n\n")

    async def run() -> None:
        try:
            publish("status", {"message": "Looking at your customer data…"})
            conversation, assistant, reply = await _run_turn(db, user, ent, payload)
            await db.commit()
            for call in reply.tool_calls:
                publish("tool", {"tool": call.tool, "summary": call.summary})
            publish(
                "message",
                {
                    "conversation_id": str(conversation.id),
                    "message": _message_out(assistant).model_dump(),
                    "drafted_campaign_id": reply.drafted_campaign_id,
                },
            )
        except HTTPException as exc:
            publish("error", {"detail": exc.detail})
        except Exception as exc:
            logger.exception("chat stream failed")
            publish(
                "error",
                {"detail": f"Something went wrong answering that ({type(exc).__name__})."},
            )
        finally:
            queue.put_nowait(None)

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            # A client that disconnects mid-turn must not leave the turn (and
            # its transaction) running unattended.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
