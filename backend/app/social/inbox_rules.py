"""Engagement-inbox rules: classification, reply drafting, and the daily briefing.

Pure functions, no side effects, no I/O — same contract as ``app/scoring/engine.py``.
Inputs are plain dataclasses; outputs are plain dataclasses and strings.

Ported from Splay's ``apps/api/src/engagement.ts``. The logic there is entirely
deterministic (regex + templates, no LLM), which is exactly what Pulse wants as
the never-fails floor: ``app/social/inbox.py`` may ask Claude for a nicer draft,
but it always has this to fall back to.

Two regex conventions live side by side on purpose, inherited from the original:
the *classifier* patterns match bare substrings (so "promot" catches "promoting")
while the *topic* patterns are word-bounded. Normalising either one changes which
comments land in which bucket, so they are kept as-is.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

# ── Enums (the complete legal value sets) ────────────────────────────────────

PLATFORMS = ("linkedin", "x", "other")
SOURCES = ("demo", "manual")
INTENTS = ("product_question", "sales_lead", "complaint", "praise", "feedback", "spam")
SENTIMENTS = ("positive", "neutral", "negative")
PRIORITIES = ("high", "medium", "low")
RISKS = ("high", "medium", "low")
STATUSES = ("needs_reply", "drafted", "approved", "resolved")
REPLY_VARIANTS = ("standard", "shorter", "warmer")


# ── Classification ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
    intent: str
    sentiment: str
    priority: str
    risk: str
    recommended_action: str


_SPAM = re.compile(r"(crypto|backlinks?|promot(?:e|ion)|follow me|guaranteed followers)", re.I)
_COMPLAINT = re.compile(
    r"(security|breach|lawsuit|legal|scam|fraud|stole|refund|angry|furious)", re.I
)
_SALES_LEAD = re.compile(r"(demo|pricing|price|cost|buy|sign up|talk to sales|book a call)", re.I)
_PRODUCT_QUESTION = re.compile(r"[?]|(does|do you|how|what|when|where|integrat|support)", re.I)
_PRAISE = re.compile(
    r"(congrats|congratulations|love this|great work|awesome|amazing|well done)", re.I
)
# Straight apostrophe only — a curly "didn’t" deliberately does not match here.
_NEGATIVE = re.compile(r"(?:didn'?t|not|but|however|issue|problem)", re.I)


def classify(comment: str) -> Classification:
    """Bucket a comment from its text alone. First rule that matches wins."""
    text = comment.lower()

    if _SPAM.search(text):
        return Classification(
            "spam", "neutral", "low", "low", "Resolve without replying"
        )
    if _COMPLAINT.search(text):
        return Classification(
            "complaint", "negative", "high", "high",
            "Escalate for human review before replying",
        )
    if _SALES_LEAD.search(text):
        return Classification(
            "sales_lead", "positive", "high", "low",
            "Reply promptly and offer a clear next step",
        )
    if _PRODUCT_QUESTION.search(text):
        return Classification(
            "product_question", "neutral", "high", "medium",
            "Answer only from approved company knowledge",
        )
    if _PRAISE.search(text):
        return Classification("praise", "positive", "low", "low", "Acknowledge warmly")

    return Classification(
        "feedback",
        "negative" if _NEGATIVE.search(text) else "neutral",
        "medium",
        "medium",
        "Acknowledge the feedback and keep the conversation open",
    )


# ── Reply drafting ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContextItem:
    """One public-safe company-brain record, as far as drafting is concerned."""

    title: str
    summary: str


@dataclass(frozen=True)
class BrandVoice:
    name: str
    positioning: str
    # Only the LLM path reads this; the templates are written in a fixed voice.
    tone: str = "clear and friendly"


@dataclass(frozen=True)
class Suggestion:
    reply: str
    evidence: list[str] = field(default_factory=list)


HIGH_RISK_REPLY = (
    "Thanks for flagging this, {first}. We want to make sure the right person "
    "reviews it rather than guessing in public. Please send us the details "
    "through the appropriate support channel so our team can investigate."
)

_WORD = re.compile(r"[a-z0-9]{4,}")
_FIRST_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_MAX_FACT_CHARS = 180


def _words(value: str) -> list[str]:
    return _WORD.findall(value.lower())


def rank_context(comment: str, items: list[ContextItem]) -> list[ContextItem]:
    """Rank company-brain items by raw term overlap with the comment.

    Query terms are deduplicated but document terms are not, so a word repeated
    in a summary scores once per occurrence. Ties keep the incoming order, which
    callers supply newest-first.
    """
    query = set(_words(comment))
    scored = [
        (sum(1 for word in _words(f"{item.title} {item.summary}") if word in query), item)
        for item in items
    ]
    hits = [pair for pair in scored if pair[0] > 0]
    return [item for _, item in sorted(hits, key=lambda pair: -pair[0])]


def _first_name(author: str) -> str:
    return next(iter(author.strip().split()), "") or "there"


def build_suggestion(
    *,
    author: str,
    comment: str,
    intent: str,
    risk: str,
    brand: BrandVoice,
    context: list[ContextItem],
    variant: str = "standard",
) -> Suggestion:
    """Draft a reply from the brand voice plus the top public-safe context items.

    ``context`` must already be filtered to public-safe records — this function
    has no way to tell, and anything passed in can reach the drafted text.
    """
    name = brand.name or "our team"
    first = _first_name(author)

    relevant = rank_context(comment, context)[:2]
    evidence = [item.title for item in relevant]
    positioning = brand.positioning.strip()
    if positioning:
        evidence.append("Brand positioning")

    # High risk never gets a substantive answer, and never honours a variant —
    # a complaint about fraud or legal action goes to a human, verbatim.
    if risk == "high":
        return Suggestion(HIGH_RISK_REPLY.format(first=first), evidence)

    fact = ""
    if relevant:
        candidate = _FIRST_SENTENCE.split(relevant[0].summary)[0].strip()
        if len(candidate) <= _MAX_FACT_CHARS:
            fact = candidate

    if intent == "sales_lead":
        reply = (
            f"Thanks for asking, {first}. {fact} Happy to walk you through how "
            f"{name} could fit your workflow."
            if fact
            else f"Thanks for asking, {first}. Happy to walk you through how "
            f"{name} works and whether it fits your workflow."
        )
    elif intent == "product_question":
        reply = (
            f"Great question, {first}. {fact}"
            if fact
            else f"Great question, {first}. We do not want to guess at the details, "
            "so let us confirm this with the team and follow up with an accurate answer."
        )
    elif intent == "praise":
        reply = (
            f"Thank you, {first} — that means a lot to the {name} team. "
            "We’re excited to keep building in the open."
        )
    elif intent == "spam":
        reply = ""
    else:
        closing = positioning or f"We’re continuing to improve {name} around feedback like this."
        reply = (
            f"Thanks for sharing this, {first}. {closing} "
            "We appreciate the thoughtful perspective."
        )

    if variant == "shorter":
        # Replaces the draft outright rather than trimming it. Inherited quirk:
        # this arm is not guarded on spam, so asking for a "shorter" spam reply
        # produces the generic line instead of the deliberate empty string. The
        # UI never offers it; the API still allows it.
        if intent == "praise":
            reply = f"Thank you, {first} — we really appreciate it."
        elif intent == "product_question" and fact:
            reply = f"Great question, {first}. {fact}"
        else:
            reply = (
                f"Thanks, {first}. We appreciate the question and will follow up "
                "with an accurate answer."
            )
    elif variant == "warmer" and reply:
        reply = f"{reply} Thanks for taking the time to reach out."

    return Suggestion(reply, list(dict.fromkeys(evidence)))


# ── Daily briefing ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BriefingItem:
    """The subset of an inbox row the briefing math reads."""

    intent: str
    risk: str
    status: str
    comment: str
    original_post_excerpt: str | None
    reply_version: int
    suggested_reply: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Briefing:
    leads: int
    high_risk: int
    awaiting_reply: int
    approved_today: int
    top_topic: str | None
    top_topic_count: int
    top_question: str | None
    recommended_action: str
    estimated_minutes_saved: int


TOPIC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Integrations", re.compile(
        r"\b(integrat(?:e|es|ed|ion|ions)|stripe|hubspot|salesforce|slack|api|connect)\b", re.I)),
    ("Pricing", re.compile(r"\b(pric(?:e|ing)|cost|plan|subscription|afford|trial)\b", re.I)),
    ("Security", re.compile(r"\b(security|secure|privacy|compliance|soc ?2|gdpr|data)\b", re.I)),
    ("Analytics", re.compile(
        r"\b(analytics|metric|report|dashboard|performance|roi)\b", re.I)),
    ("Content generation", re.compile(
        r"\b(content|generate|draft|creative|image|copywriting)\b", re.I)),
    ("Scheduling", re.compile(r"\b(schedule|calendar|publish|posting|buffer|queue)\b", re.I)),
    ("Team collaboration", re.compile(
        r"\b(team|approval|approve|collaborat|role|permission|workspace)\b", re.I)),
    ("Support", re.compile(r"\b(support|help|issue|problem|refund|broken|error)\b", re.I)),
)


def _count_label(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def summarize(items: list[BriefingItem], *, today: date) -> Briefing:
    """Roll the inbox into the "Today's opportunities" card.

    ``today`` is a UTC calendar day — the original compares ISO-8601 date
    prefixes, so a business in UTC-8 sees the counter roll over mid-afternoon.
    Kept as-is so the number matches what the rest of the system reports.
    """
    active = [i for i in items if i.status != "resolved"]

    leads = sum(1 for i in active if i.intent == "sales_lead")
    high_risk = sum(1 for i in active if i.risk == "high")
    awaiting_reply = sum(
        1 for i in active if i.intent != "spam" and i.status in ("needs_reply", "drafted")
    )
    approved_today = sum(
        1 for i in items if i.status == "approved" and i.updated_at.date() == today
    )

    counts: Counter[str] = Counter()
    for item in (i for i in active if i.intent != "spam"):
        haystack = f"{item.comment} {item.original_post_excerpt or ''}"
        for label, pattern in TOPIC_RULES:
            if pattern.search(haystack):
                counts[label] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_topic, top_topic_count = ranked[0] if ranked else (None, 0)

    top_question = next(
        (i.comment for i in active if i.intent == "product_question"), None
    )

    if high_risk:
        action = f"Review {_count_label(high_risk, 'high-risk conversation')} before responding."
    elif leads:
        action = f"Approve replies for {_count_label(leads, 'prospective customer')}."
    elif top_topic and top_topic_count > 1:
        action = f"{top_topic} is coming up repeatedly. Consider creating an explainer post."
    elif awaiting_reply:
        action = f"Review and approve {_count_label(awaiting_reply, 'drafted reply')}."
    else:
        action = "Your priority inbox is clear. Review new audience feedback."

    minutes = 0
    for item in items:
        if item.created_at.date() != today and item.updated_at.date() != today:
            continue
        minutes += 1  # classification
        if item.reply_version > 0 and item.suggested_reply:
            minutes += 2  # drafting
        if item.status == "approved":
            minutes += 1  # approval
        if item.intent == "spam" and item.status == "resolved":
            minutes += 1  # spam triage

    return Briefing(
        leads=leads,
        high_risk=high_risk,
        awaiting_reply=awaiting_reply,
        approved_today=approved_today,
        top_topic=top_topic,
        top_topic_count=top_topic_count,
        top_question=top_question,
        recommended_action=action,
        estimated_minutes_saved=minutes,
    )
