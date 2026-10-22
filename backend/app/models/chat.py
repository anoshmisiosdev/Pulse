"""Conversations with the in-product assistant.

Persisted rather than kept in the browser so an owner can close the tab and
come back to the thread, and so a reply that queued real outreach has a record
of the exchange that produced it.

``tool_calls`` stores what the assistant actually ran for a turn. It's the
honesty mechanism in the chat UI: "I found 12 customers at risk" is only
trustworthy if the interface can show that the number came from a query over
the owner's own rows rather than from the model's imagination.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.models.mixins import UUIDMixin

# JSONB on Postgres, plain JSON on SQLite (tests). Same pattern the social
# models use for their list columns.
_JSON = JSON().with_variant(JSONB(), "postgresql")


class ChatConversation(UUIDMixin, Base):
    __tablename__ = "chat_conversations"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    # Derived from the first user message, so the thread list is scannable.
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    # Who started it. Not a tenant boundary — business_id is — but it keeps one
    # owner's threads out of another staff member's sidebar once teams exist.
    created_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ChatMessage(UUIDMixin, Base):
    __tablename__ = "chat_messages"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # [{"tool": "...", "args": {...}, "summary": "..."}] — what ran for this
    # turn, shown in the UI as the citation for the answer.
    tool_calls: Mapped[list | None] = mapped_column(_JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "claude" | "fallback" — a fallback reply came from the deterministic
    # responder, not the model (same convention as CampaignSend).
    generated_by: Mapped[str] = mapped_column(String(16), default="claude")
