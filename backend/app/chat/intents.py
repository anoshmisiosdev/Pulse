"""Deterministic intent matching and reply templates for the assistant.

Pure functions, no I/O, no LLM - the same contract as ``scoring/engine.py`` and
``social/inbox_rules.py``, and here for the same reason: this is the floor the
assistant stands on when Claude is unreachable. If this module imported the LLM
it could not be the fallback for the LLM.

The split of responsibility is narrow on purpose. This module decides *which
tool a question is probably asking for* and *how to phrase the answer once the
numbers are in hand*. It never queries anything; the caller runs the tool.

Scope is honest rather than ambitious: it recognizes the handful of questions
owners actually ask ("who's about to leave?", "how much have we saved?") and
says plainly that it can't help with anything else while the model is down. A
keyword matcher pretending to be a general assistant would be worse than one
that knows its limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Each intent maps to one tool plus fixed arguments. Patterns are substring
# matches on a lowercased question, ordered most-specific first - "how many
# came back" must not be captured by the broader at-risk pattern.
_DRAFT_NOTE = (
    "I can't write the messages without the AI model, but open Campaigns and "
    "pick a segment — Churnary will draft them from a template and hold them "
    "for your approval."
)

_PATTERNS: tuple[tuple[str, str, dict, str | None], ...] = (
    (
        # A drafting request. The pure path can't supply customer ids, so it
        # answers with the list and says where to go — matched before the
        # at-risk pattern, which this phrasing would otherwise be caught by.
        r"draft|write|compose|send (a|an|them)|win.?back (email|message|text)",
        "get_at_risk_customers",
        {"band": "high", "limit": 10},
        _DRAFT_NOTE,
    ),
    (
        r"recover|came back|won back|win.?back result|saved|retained|roi",
        "get_recovery_stats",
        {},
        None,
    ),
    (
        r"campaign|sent|outreach|approval queue|waiting",
        "list_recent_campaigns",
        {},
        None,
    ),
    (
        r"brand voice|our services|what do we offer|notes|knowledge",
        "search_business_knowledge",
        {},
        None,
    ),
    (
        # More specific than the at-risk pattern below, which also matches
        # "at risk": asking *how much* wants the total, not a name list.
        r"revenue at risk|how much.*risk|money at risk|value at risk",
        "get_portfolio_summary",
        {},
        None,
    ),
    (
        # Includes the phrasings the chat's own suggestion chips use — a
        # fallback that can't answer the questions the product puts in front of
        # the owner is worse than no fallback.
        r"high.?risk|about to leave|leaving|at risk|churn|lapsed"
        r"|stop coming|stopped coming|not coming back|slipping"
        r"|who should i|who do i|who needs",
        "get_at_risk_customers",
        {"band": "high", "limit": 10},
        None,
    ),
    (
        r"how many customers|total customers|summary|overview|how are we doing|revenue at risk",
        "get_portfolio_summary",
        {},
        None,
    ),
)


@dataclass(frozen=True)
class Intent:
    tool: str
    args: dict
    # Appended to the rendered answer. Used when the question asks for
    # something the deterministic path can't do on its own, so the reply still
    # moves the owner forward instead of refusing.
    note: str | None = None


def match(question: str) -> Intent | None:
    """The tool this question most likely wants, or None if unrecognized."""
    text = (question or "").lower()
    if not text.strip():
        return None
    for pattern, tool, args, note in _PATTERNS:
        if re.search(pattern, text):
            return Intent(tool=tool, args=dict(args), note=note)
    return None


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _money(value: float) -> str:
    return f"${value:,.0f}"


def render(tool: str, result: dict) -> str:
    """Phrase a tool result as a reply, without a model.

    Deliberately plain. The point is to be correct and useful at 3am when
    Bedrock is throttled, not to sound like the real assistant.
    """
    if result.get("error"):
        return str(result["error"])
    if result.get("status") == "no_data":
        return (
            "There's no customer data imported yet. Connect Square or upload a CSV "
            "on the setup screen and I'll have something to work with."
        )

    if tool == "get_portfolio_summary":
        high = result.get("high_risk", 0)
        return (
            f"You have {result.get('total_customers', 0)} customers: "
            f"{high} at high risk, {result.get('medium_risk', 0)} medium, "
            f"{result.get('low_risk', 0)} low. "
            f"That puts roughly {_money(result.get('revenue_at_risk', 0))} of annual "
            f"revenue at risk. All time, you've won back "
            f"{result.get('customers_recovered_all_time', 0)} "
            f"{_plural(result.get('customers_recovered_all_time', 0), 'customer')} "
            f"worth about {_money(result.get('revenue_recovered_all_time', 0))}."
        )

    if tool == "get_at_risk_customers":
        customers = result.get("customers") or []
        if not customers:
            return "Nobody is in that risk band right now - that's good news."
        lines = [
            f"{len(customers)} of your {result.get('count', len(customers))} "
            f"highest-risk customers:"
        ]
        for c in customers:
            reasons = "; ".join(c.get("reasons") or []) or "no specific signal"
            lines.append(
                f"- {c.get('name')} (score {c.get('risk_score')}): {reasons}. "
                f"Suggested: {str(c.get('recommended_action', '')).replace('_', ' ')}."
            )
        return "\n".join(lines)

    if tool == "get_recovery_stats":
        count = result.get("customers_recovered", 0)
        window = result.get("window_days")
        when = "all time" if window == "all_time" else f"in the last {window} days"
        if not count:
            return f"No customers have been attributed as recovered {when} yet."
        return (
            f"{count} {_plural(count, 'customer')} came back {when}, worth about "
            f"{_money(result.get('revenue_recovered', 0))}."
        )

    if tool == "list_recent_campaigns":
        campaigns = result.get("campaigns") or []
        if not campaigns:
            return "You haven't run any campaigns yet."
        lines = ["Your recent campaigns:"]
        for c in campaigns:
            waiting = c.get("awaiting_approval", 0)
            tail = f", {waiting} waiting for your approval" if waiting else ""
            lines.append(
                f"- {c.get('name')} ({c.get('channel')}, {c.get('status')}): "
                f"{c.get('sent', 0)} sent{tail}."
            )
        return "\n".join(lines)

    if tool == "search_business_knowledge":
        knowledge = result.get("knowledge") or []
        brain_items = result.get("company_brain") or []
        if not knowledge and not brain_items:
            return (
                "I don't have any notes about your business yet. Add some and I'll "
                "use them when drafting campaigns."
            )
        lines = ["Here's what I have on file:"]
        for row in knowledge:
            lines.append(f"- ({row.get('kind')}) {row.get('content')}")
        for row in brain_items:
            lines.append(f"- {row.get('title')}: {row.get('summary')}")
        return "\n".join(lines)

    if tool == "draft_campaign":
        return (
            f"Drafted {result.get('drafted_for', 0)} "
            f"{_plural(result.get('drafted_for', 0), 'message')} for "
            f"'{result.get('name')}'. Nothing has been sent - they're waiting for your "
            "approval on the campaigns screen."
        )

    return "I found the information but couldn't summarize it. Try the dashboard."


UNRECOGNIZED = (
    "I'm running in a reduced mode right now and can only answer a few things: "
    "who's at risk of leaving, how your recovery numbers look, your recent "
    "campaigns, and what's in your business notes. Ask me one of those, or try "
    "again shortly."
)
