"""Append-only log of every LLM generation, and of owner actions worth auditing.

CLAUDE.md requires logging prompt + output + model version for every
generation. Two reasons it's load-bearing rather than nice-to-have: when an
owner asks "why did it say that about my customer?" the answer has to be
retrievable, and when copy quality regresses the only way to tell a prompt
change from a model change is to have both recorded.

Both tables are append-only. Nothing in the app updates or deletes a row here
except the per-business data-deletion endpoint, which must erase everything.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDMixin

# What asked for the generation. Keeps the log readable when several features
# share one LLM path.
GENERATION_PURPOSES = (
    "campaign_email",
    "campaign_sms",
    "campaign_batch",
    "risk_summary",
    "chat_reply",
    "social_post",
    "inbox_reply",
    "digest_summary",
)


class GenerationLog(UUIDMixin, Base):
    """One LLM call: what we asked, what came back, and which model answered."""

    __tablename__ = "generation_logs"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    # The exact strings sent. Stored verbatim: a paraphrase is useless for
    # reproducing a bad generation.
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    # Raw model text before parsing, so a parse failure is diagnosable.
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # claude | fallback — whether the static template ended up being used.
    generated_by: Mapped[str] = mapped_column(String(16), default="claude")
    # How many model calls this took, including retries. >1 means the first
    # response didn't parse.
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Loose back-references: null for generations not tied to a row, and no FK
    # constraint, because the log must outlive the send it describes.
    campaign_send_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


# Actions recorded for the audit trail. Deliberately short: this is "who
# authorized outreach and who changed consent", not a generic event firehose.
AUDIT_ACTIONS = (
    "send_approved",
    "send_edited",
    "send_cancelled",
    "campaign_created",
    "campaign_launched",
    "rule_created",
    "rule_updated",
    "rule_deleted",
    "customer_consent_changed",
    "data_export_requested",
    "data_deleted",
    "plan_changed",
)


class AuditLog(UUIDMixin, Base):
    """Who did what, when. Append-only.

    Exists because approve-to-send is a human decision with legal weight: under
    CAN-SPAM and TCPA, "who authorized this message" is a question that can be
    asked months later, and `CampaignSend.status` alone can't answer it.
    """

    __tablename__ = "audit_logs"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    # The authenticated subject. Stored as the Supabase user id plus the email
    # as it was at the time — resolving an id to a person years later may not
    # be possible, and the email at the time of the action is the useful fact.
    actor_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # What was acted on: table name + id, kept as loose strings so this table
    # never needs a migration when a new auditable object appears.
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
