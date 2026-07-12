"""AI win-back copy generation.

Strict-JSON request, defensive parse, retry once, then fall back to a static
template. ``parse_model_json`` is pure and unit-tested; ``generate_campaign`` does
the I/O and degrades gracefully so a missing key or a flaky model never blocks a send.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.campaigns.templates import fallback_email, fallback_sms
from app.core.config import settings
from app.core.llm import active_model, complete_text

logger = logging.getLogger("pulse.campaigns")

SMS_MAX_CHARS = 320
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass
class CampaignContext:
    business_name: str
    business_type: str
    customer_name: str
    channel: str  # "email" | "sms"
    tone: str = "warm, concise, local small-business"
    incentive: str | None = None
    risk_reasons: list[str] = field(default_factory=list)
    history_summary: str = ""
    unsubscribe_url: str = "https://app.pulse/u/unsub"
    # Retrieved via app.services.rag.knowledge_store.search_knowledge — the
    # business's own services/brand-voice/past-campaign notes, most relevant
    # to this send first. Empty when retrieval is unavailable; generation
    # still works, just without that grounding (same degrade-gracefully
    # philosophy as the LLM call itself).
    knowledge_snippets: list[str] = field(default_factory=list)


@dataclass
class GeneratedCopy:
    body: str
    subject: str | None = None
    generated_by: str = "claude"  # "claude" | "fallback"
    model: str | None = None


def parse_model_json(raw: str, channel: str) -> GeneratedCopy:
    """Parse a model response into copy. Strips markdown fences; raises ValueError
    if the payload is unusable so the caller can retry or fall back."""
    text = raw.strip()
    # Strip a leading/trailing code fence if present.
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    # Salvage the outermost JSON object if the model added prose around it.
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found in model output")
        text = text[start : end + 1]

    data = json.loads(text)  # raises ValueError on malformed JSON
    if not isinstance(data, dict):
        raise ValueError("model output was not a JSON object")

    body = (data.get("body") or "").strip()
    if not body:
        raise ValueError("model output missing 'body'")

    if channel == "sms":
        return GeneratedCopy(body=body[:SMS_MAX_CHARS], subject=None)

    subject = (data.get("subject") or "").strip()
    if not subject:
        raise ValueError("email output missing 'subject'")
    return GeneratedCopy(body=body, subject=subject)


def _build_prompt(ctx: CampaignContext) -> tuple[str, str]:
    reasons = "; ".join(ctx.risk_reasons) or "no specific signal"
    incentive = ctx.incentive or "no specific offer"
    if ctx.channel == "sms":
        shape = '{"body": "..."}'
        rules = (
            f"- SMS only, {SMS_MAX_CHARS} characters max.\n"
            "- End with an opt-out cue (e.g. 'Reply STOP to opt out').\n"
        )
    else:
        shape = '{"subject": "...", "body": "..."}'
        rules = "- Email must end with a clear unsubscribe line.\n"

    system = (
        f"You write win-back messages for {ctx.business_name}, a {ctx.business_type}. "
        f"Tone: {ctx.tone}. Never fabricate facts, discounts, or claims not provided. "
        f"Respond with STRICT JSON only, exactly this shape: {shape}. No markdown, no prose."
    )
    knowledge_block = ""
    if ctx.knowledge_snippets:
        bullets = "\n".join(f"- {s}" for s in ctx.knowledge_snippets)
        knowledge_block = (
            f"About this business (use if relevant, don't force it in):\n{bullets}\n\n"
        )
    user = (
        f"Customer: {ctx.customer_name}\n"
        f"Why they're at risk: {reasons}\n"
        f"History: {ctx.history_summary or 'n/a'}\n"
        f"Incentive to offer: {incentive}\n"
        f"Channel: {ctx.channel}\n\n"
        f"{knowledge_block}"
        f"Constraints:\n{rules}\n"
        f"Write the message now as JSON."
    )
    return system, user


def _fallback(ctx: CampaignContext) -> GeneratedCopy:
    if ctx.channel == "sms":
        body = fallback_sms(
            business_name=ctx.business_name,
            customer_name=ctx.customer_name,
            incentive=ctx.incentive,
        )
        return GeneratedCopy(body=body, subject=None, generated_by="fallback")
    subject, body = fallback_email(
        business_name=ctx.business_name,
        customer_name=ctx.customer_name,
        incentive=ctx.incentive,
        unsubscribe_url=ctx.unsubscribe_url,
    )
    return GeneratedCopy(body=body, subject=subject, generated_by="fallback")


async def generate_campaign(ctx: CampaignContext) -> GeneratedCopy:
    """Generate copy via Token Router, degrading to a static template on any failure."""
    if not settings.llm_configured:
        return _fallback(ctx)

    system, user = _build_prompt(ctx)
    model = active_model()

    for attempt in (1, 2):  # generate, then one retry on parse failure
        try:
            raw = await complete_text(system, user, max_tokens=700)
            copy = parse_model_json(raw, ctx.channel)
            copy.model = model
            logger.info("campaign generated", extra={"channel": ctx.channel, "attempt": attempt})
            return copy
        except Exception as exc:  # network, parse, or API error — never blocks the send
            logger.warning("generation attempt %s failed: %s", attempt, exc)

    return _fallback(ctx)
