"""Assistant conversation shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallOut(BaseModel):
    tool: str
    summary: str


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    # What the assistant actually ran for this turn. The UI shows these as the
    # citation for the answer, so a number is visibly sourced from the owner's
    # own rows rather than asserted.
    tool_calls: list[ToolCallOut] = []
    generated_by: str
    model: str | None = None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class ConversationDetailOut(ConversationOut):
    messages: list[ChatMessageOut] = []


class ChatAskIn(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    # Omit to start a new thread.
    conversation_id: str | None = None


class ChatAskOut(BaseModel):
    conversation_id: str
    message: ChatMessageOut
    # Set when the turn drafted a campaign, so the UI can link straight to it.
    drafted_campaign_id: str | None = None


class SuggestionsOut(BaseModel):
    """Opening prompts, so an empty chat box isn't a blank stare."""

    suggestions: list[str]
