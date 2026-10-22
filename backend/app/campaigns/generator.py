"""AI win-back copy generation.

Strict-JSON request, defensive parse, retry once, then fall back to a static
template. ``parse_model_json`` is pure and unit-tested; ``generate_campaign`` does
the I/O and degrades gracefully so a missing key or a flaky model never blocks a send.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.campaigns.templates import fallback_email, fallback_sms
from app.core.config import settings
from app.core.llm import active_model, complete_text, extract_json_object

logger = logging.getLogger("pulse.campaigns")

SMS_MAX_CHARS = 320


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


@dataclass
class GenerationTrace:
    """Everything the audit log needs about one generation attempt sequence.

    CLAUDE.md requires logging prompt + output + model version for every
    generation, and the prompt is built inside this module — so rather than
    rebuilding it at the call site (which would risk logging a prompt that
    isn't the one that was sent), generation hands the trace back.
    """

    system_prompt: str
    user_prompt: str
    raw_output: str | None = None
    model: str | None = None
    attempts: int = 1
    latency_ms: int | None = None
    error: str | None = None


def parse_model_json(raw: str, channel: str) -> GeneratedCopy:
    """Parse a model response into copy. Strips markdown fences; raises ValueError
    if the payload is unusable so the caller can retry or fall back."""
    data = extract_json_object(raw)

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


async def generate_campaign_traced(
    ctx: CampaignContext,
) -> tuple[GeneratedCopy, GenerationTrace]:
    """``generate_campaign``, plus the prompts/outcome for the audit log."""
    if not settings.llm_configured:
        return _fallback(ctx), GenerationTrace(
            system_prompt="",
            user_prompt="",
            attempts=0,
            error="llm_not_configured",
        )

    system, user = _build_prompt(ctx)
    model = active_model()
    trace = GenerationTrace(system_prompt=system, user_prompt=user, model=model)
    started = time.monotonic()

    for attempt in (1, 2):  # generate, then one retry on parse failure
        trace.attempts = attempt
        try:
            raw = await complete_text(system, user, max_tokens=700)
            trace.raw_output = raw
            copy = parse_model_json(raw, ctx.channel)
            copy.model = model
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            logger.info("campaign generated", extra={"channel": ctx.channel, "attempt": attempt})
            return copy, trace
        except Exception as exc:  # network, parse, or API error — never blocks the send
            logger.warning("generation attempt %s failed: %s", attempt, exc)
            trace.error = f"{type(exc).__name__}: {exc}"

    trace.latency_ms = int((time.monotonic() - started) * 1000)
    return _fallback(ctx), trace


async def generate_campaign(ctx: CampaignContext) -> GeneratedCopy:
    """Generate copy via Token Router, degrading to a static template on any failure."""
    copy, _trace = await generate_campaign_traced(ctx)
    return copy


# Caps prompt/response size for one call: 6 customers' worth of context stays
# comfortably inside max_tokens without risking a truncated JSON array. A
# larger eligible list is chunked into multiple calls of this size.
MAX_BATCH_SIZE = 6


def _build_batch_prompt(contexts: list[CampaignContext]) -> tuple[str, str]:
    """Callers must batch same-business, same-channel contexts only (true of
    every current caller — one automation rule's eligible customers) — the
    shared system prompt below is built from contexts[0] alone."""
    first = contexts[0]
    if first.channel == "sms":
        item_shape = '{"id": 0, "body": "..."}'
        rules = (
            f"- SMS only, {SMS_MAX_CHARS} characters max per message.\n"
            "- Each message ends with an opt-out cue (e.g. 'Reply STOP to opt out').\n"
        )
    else:
        item_shape = '{"id": 0, "subject": "...", "body": "..."}'
        rules = "- Each email ends with a clear unsubscribe line.\n"

    system = (
        f"You write win-back messages for {first.business_name}, a {first.business_type}. "
        f"Tone: {first.tone}. Never fabricate facts, discounts, or claims not provided. "
        "You'll get several customers in one request — write one message per customer, "
        "each personal to that customer, not a form letter reused verbatim. "
        f'Respond with STRICT JSON only, exactly this shape: {{"items": [{item_shape}, ...]}}, '
        'one item per customer in the same order given, each tagged with its "id". '
        "No markdown, no prose."
    )

    blocks = []
    for i, ctx in enumerate(contexts):
        reasons = "; ".join(ctx.risk_reasons) or "no specific signal"
        incentive = ctx.incentive or "no specific offer"
        knowledge_block = ""
        if ctx.knowledge_snippets:
            bullets = "\n".join(f"    - {s}" for s in ctx.knowledge_snippets)
            knowledge_block = f"\n  About this business:\n{bullets}"
        blocks.append(
            f"id {i}:\n"
            f"  Customer: {ctx.customer_name}\n"
            f"  Why they're at risk: {reasons}\n"
            f"  History: {ctx.history_summary or 'n/a'}\n"
            f"  Incentive to offer: {incentive}"
            f"{knowledge_block}"
        )
    user = "\n\n".join(blocks) + f"\n\nConstraints:\n{rules}\nWrite all messages now as JSON."
    return system, user


def _parse_batch_json(raw: str, channel: str, n: int) -> list[GeneratedCopy | None]:
    """Best-effort parse of a batch response: one slot per expected item, None
    where an item was missing or malformed. A partial batch isn't discarded —
    the caller fills in only the missing slots with individual calls."""
    data = extract_json_object(raw)
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("batch output missing 'items' array")

    out: list[GeneratedCopy | None] = [None] * n
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("id")
        if not isinstance(idx, int) or not (0 <= idx < n):
            continue
        body = (item.get("body") or "").strip()
        if not body:
            continue
        if channel == "sms":
            out[idx] = GeneratedCopy(body=body[:SMS_MAX_CHARS], subject=None)
            continue
        subject = (item.get("subject") or "").strip()
        if not subject:
            continue
        out[idx] = GeneratedCopy(body=body, subject=subject)
    return out


async def _generate_batch_chunk(contexts: list[CampaignContext]) -> list[GeneratedCopy | None]:
    if not settings.llm_configured:
        return [None] * len(contexts)

    system, user = _build_batch_prompt(contexts)
    model = active_model()
    channel = contexts[0].channel

    for attempt in (1, 2):  # generate, then one retry on parse failure — same shape as above
        try:
            raw = await complete_text(system, user, max_tokens=700 * len(contexts))
            results = _parse_batch_json(raw, channel, len(contexts))
            for r in results:
                if r is not None:
                    r.model = model
            logger.info(
                "batch campaign generated",
                extra={"channel": channel, "count": len(contexts), "attempt": attempt},
            )
            return results
        except Exception as exc:  # network, parse, or API error — caller falls back per item
            logger.warning("batch generation attempt %s failed: %s", attempt, exc)

    return [None] * len(contexts)


async def generate_campaigns_batch(contexts: list[CampaignContext]) -> list[GeneratedCopy]:
    """Generate copy for several customers in as few LLM calls as possible —
    one shared system prompt instead of one per customer, cutting the
    repeated-context token cost roughly N-fold for a same-business,
    same-channel batch (e.g. one automation rule's eligible customers).

    Never worse than calling generate_campaign per customer: a chunk that
    doesn't parse cleanly falls back to generating those customers
    individually, so a bad batch response can't corrupt or drop a send that
    would've worked on its own. Order of the input list is preserved."""
    if not contexts:
        return []
    if len(contexts) == 1:
        return [await generate_campaign(contexts[0])]

    results: list[GeneratedCopy | None] = [None] * len(contexts)
    for start in range(0, len(contexts), MAX_BATCH_SIZE):
        chunk = contexts[start : start + MAX_BATCH_SIZE]
        results[start : start + len(chunk)] = await _generate_batch_chunk(chunk)

    for i, r in enumerate(results):
        if r is None:
            results[i] = await generate_campaign(contexts[i])
    return results  # type: ignore[return-value]  # every slot filled by the loop above
