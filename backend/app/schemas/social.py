"""Request/response models for the social features.

Kept separate from ``schemas/api.py`` because this is a whole product surface
rather than a handful of endpoints. Field limits mirror the ones the Splay
frontend was written against, so the ported UI copy still fits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.social.scheduling import valid_timezone

HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
TypeScale = Literal["compact", "balanced", "editorial"]
ContextKind = Literal["company", "product", "customer", "founder", "market", "proof", "other"]
Platform = Literal["linkedin", "x"]
PostStatus = Literal["draft", "approved", "rejected", "staged", "posted", "failed"]
CampaignStatus = Literal["draft", "generating", "active", "paused", "completed"]
ReviewDecision = Literal["approve", "revise", "reject"]
CommentPlatform = Literal["linkedin", "x", "other"]
CommentStatus = Literal["needs_reply", "drafted", "approved", "resolved"]
ReplyVariant = Literal["standard", "shorter", "warmer"]


# ── Brand kit ────────────────────────────────────────────────────────────────


class BrandColors(BaseModel):
    primary: HexColor
    secondary: HexColor
    accent: HexColor
    background: HexColor
    text: HexColor

    @field_validator("*")
    @classmethod
    def _upper(cls, value: str) -> str:
        # Browser colour inputs emit lowercase; store one canonical casing so
        # "did the brand change?" comparisons don't fire on a case flip.
        return value.upper()


class BrandTypography(BaseModel):
    heading_family: str = Field(min_length=1, max_length=80)
    body_family: str = Field(min_length=1, max_length=80)
    heading_weight: int = Field(default=400, ge=100, le=900)
    body_weight: int = Field(default=400, ge=100, le=900)
    scale: TypeScale = "balanced"


class BrandKitIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # tolerate version/updated_at echoes

    name: str = Field(min_length=1, max_length=80)
    tagline: str = Field(min_length=1, max_length=160)
    audience: str = Field(min_length=1, max_length=500)
    tone: str = Field(min_length=1, max_length=500)
    positioning: str = Field(min_length=1, max_length=500)
    avoid: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )
    colors: BrandColors
    typography: BrandTypography
    logo_url: str | None = Field(default=None, max_length=500)

    @field_validator("name", "tagline", "audience", "tone", "positioning")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("logo_url")
    @classmethod
    def _blank_logo_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class BrandKitOut(BrandKitIn):
    version: int
    updated_at: datetime


# ── Company brain ────────────────────────────────────────────────────────────


class ContextItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    kind: ContextKind = "other"
    summary: str = Field(min_length=1, max_length=4000)
    source: str | None = Field(default=None, max_length=500)
    date: datetime | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=20
    )
    # Defaults closed: a record has to be deliberately released before any
    # prompt can see it.
    public_safe: bool = False

    @field_validator("title", "summary")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("source")
    @classmethod
    def _blank_source_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("tags")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))


class ContextItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    kind: str
    summary: str
    source: str | None = None
    date: datetime | None = None
    tags: list[str]
    public_safe: bool
    created_at: datetime
    updated_at: datetime


class ContextListOut(BaseModel):
    data: list[ContextItemOut]
    total: int
    public_safe: int


# ── Brain import (`churnary-brain-import/v1`) ────────────────────────────────


class BrainImportPayload(BaseModel):
    schema_version: Literal["churnary-brain-import/v1"]
    brand_kit: BrandKitIn
    context: list[ContextItemIn] = Field(min_length=1, max_length=100)


class BrainImportResult(BaseModel):
    brand_kit: BrandKitOut
    imported: list[ContextItemOut]


# ── Campaigns ────────────────────────────────────────────────────────────────


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    brief: str = Field(min_length=1, max_length=500)
    themes: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=12
    )
    platforms: list[Platform] = Field(min_length=1, max_length=2)
    start_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    interval_weeks: int = Field(default=1, ge=1, le=4)
    occurrences: int = Field(default=6, ge=2, le=52)

    @field_validator("name", "brief")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("platforms")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        if not valid_timezone(value):
            raise ValueError("must be a valid IANA timezone, e.g. America/New_York")
        return value

    @model_validator(mode="after")
    def _start_must_be_aware_and_future(self) -> CampaignIn:
        if self.start_at.tzinfo is None:
            raise ValueError(
                "start_at must include an explicit timezone offset, "
                "e.g. 2026-08-03T09:00:00-07:00"
            )
        return self


class CampaignStatusPatch(BaseModel):
    status: Literal["draft", "active", "paused", "completed"]


class SlotOut(BaseModel):
    occurrence: int
    scheduled_for: datetime
    theme: str


class CampaignOut(BaseModel):
    id: str
    name: str
    brief: str
    themes: list[str]
    platforms: list[str]
    start_at: datetime
    timezone: str
    interval_weeks: int
    occurrences: int
    status: str
    last_error: str | None = None
    slots: list[SlotOut]
    post_count: int
    created_at: datetime
    updated_at: datetime


# ── Posts / review queue ─────────────────────────────────────────────────────


class ReviewEventOut(BaseModel):
    decision: str
    reason: str
    note: str | None = None
    decided_at: datetime


class PostOut(BaseModel):
    id: str
    campaign_id: str | None = None
    campaign_occurrence: int | None = None
    platform: str
    topic: str
    post_text: str
    hashtags: list[str]
    status: str
    scheduled_for: datetime | None = None
    posted_at: datetime | None = None
    image_url: str | None = None
    alt_text: str | None = None
    source_summary: str | None = None
    source_references: list[str]
    editorial: dict
    warnings: list[str]
    generated_by: str
    published_url: str | None = None
    failure_reason: str | None = None
    review_history: list[ReviewEventOut] = Field(default_factory=list)
    created_at: datetime


class DecisionIn(BaseModel):
    decision: ReviewDecision
    reason: str = Field(max_length=32)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def _blank_note_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class ScheduleIn(BaseModel):
    scheduled_for: datetime | None = None

    @model_validator(mode="after")
    def _must_be_aware(self) -> ScheduleIn:
        if self.scheduled_for is not None and self.scheduled_for.tzinfo is None:
            raise ValueError("scheduled_for must include an explicit timezone offset")
        return self


class PublishIn(BaseModel):
    """Publishing is fail-closed: ``confirm`` must be literally true."""

    confirm: bool
    post_id: str | None = Field(default=None, max_length=300)
    mode: Literal["now", "queue"] = "now"

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Set confirm to true to publish.")
        return value


class PublishResultOut(BaseModel):
    post_id: str
    ok: bool
    status: str
    message: str
    provider_post_ids: list[str] = Field(default_factory=list)
    published_url: str | None = None


# ── Engagement inbox ─────────────────────────────────────────────────────────


class CommentIn(BaseModel):
    platform: CommentPlatform = "linkedin"
    post_url: str | None = Field(default=None, max_length=2000)
    original_post_excerpt: str | None = Field(default=None, max_length=1000)
    author: str = Field(min_length=1, max_length=120)
    comment: str = Field(min_length=1, max_length=4000)

    @field_validator("author", "comment")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("post_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        url = (value or "").strip()
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            raise ValueError("post_url must be an HTTP or HTTPS URL")
        return url


class CommentOut(BaseModel):
    id: str
    source: str
    platform: str
    post_url: str | None = None
    original_post_excerpt: str | None = None
    author: str
    comment: str
    intent: str
    sentiment: str
    priority: str
    risk: str
    recommended_action: str
    status: str
    suggested_reply: str
    approved_reply: str | None = None
    reply_variant: str
    reply_version: int
    evidence: list[str]
    created_at: datetime
    updated_at: datetime


class CommentListOut(BaseModel):
    data: list[CommentOut]
    total: int
    needs_reply: int
    high_priority: int
    demo_mode: bool


class SuggestIn(BaseModel):
    variant: ReplyVariant = "standard"


class CommentPatch(BaseModel):
    status: CommentStatus | None = None
    suggested_reply: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _needs_one_field(self) -> CommentPatch:
        if self.status is None and self.suggested_reply is None:
            raise ValueError("Provide status or suggested_reply.")
        if self.suggested_reply is not None and not self.suggested_reply.strip():
            raise ValueError("suggested_reply must not be blank.")
        return self


class BriefingOut(BaseModel):
    leads: int
    high_risk: int
    awaiting_reply: int
    approved_today: int
    top_topic: str | None
    top_topic_count: int
    top_question: str | None
    recommended_action: str
    estimated_minutes_saved: int
    generated_at: datetime
