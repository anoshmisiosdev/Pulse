"""The assistant's turn loop: choose tools, read results, answer.

``core/llm.py`` exposes one primitive - ``complete_text(system, user)`` - and
fans out across Bedrock, Token Router and direct Anthropic. Tool use is
therefore implemented as a JSON protocol over that primitive rather than with a
provider's native tool-calling API: a native implementation would work on one
of the three paths and silently lose tool use on the other two, which are
exactly the paths that run when the primary is down. The protocol is the same
strict-JSON-with-defensive-parse discipline ``campaigns/generator.py`` uses.

Each step the model returns either::

    {"tool": "get_at_risk_customers", "args": {...}}
    {"reply": "..."}

Tool results are appended to the prompt and the loop runs again, up to
``MAX_STEPS``. Hitting the cap answers from whatever was gathered instead of
looping forever.

Degradation is layered, so the assistant is never simply broken:

1. the model answers, using tools;
2. the model is unreachable or keeps emitting unparseable output, so
   ``intents.py`` matches the question to one tool and templates the answer;
3. even that doesn't recognize the question, so it says what it can do.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from app.chat import intents
from app.chat.tools import TOOLS, ToolContext, dispatch, tool_catalog
from app.core.config import settings
from app.core.llm import active_model, complete_text, extract_json_object

logger = logging.getLogger("pulse.chat.agent")

# Tool calls per user turn. Four is enough for the realistic chains ("find
# Maria" -> "get her detail" -> "draft a campaign" -> answer) while bounding
# both latency and spend on a single question.
MAX_STEPS = 4

# Characters of a tool result fed back into the prompt. A 25-customer list is
# comfortably inside this; the cap exists so one tool can't crowd out the rest
# of the conversation.
MAX_RESULT_CHARS = 6_000

# How much prior conversation to carry. Enough for "what about the second one?"
# to resolve, short enough to keep the prompt cheap on a long thread.
MAX_HISTORY_TURNS = 8


@dataclass
class ToolInvocation:
    """One tool run, surfaced to the UI as the citation for the answer."""

    tool: str
    args: dict
    summary: str

    def as_dict(self) -> dict:
        return {"tool": self.tool, "args": self.args, "summary": self.summary}


@dataclass
class AgentReply:
    text: str
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    generated_by: str = "claude"  # claude | fallback
    model: str | None = None
    steps: int = 0
    latency_ms: int | None = None
    # Set when the loop fell back, for the generation log.
    error: str | None = None

    @property
    def drafted_campaign_id(self) -> str | None:
        """The campaign this turn queued, if any - the UI deep-links to it."""
        for call in self.tool_calls:
            if call.tool == "draft_campaign":
                campaign_id = call.args.get("_result_campaign_id")
                if campaign_id:
                    return str(campaign_id)
        return None


def _system_prompt(business_name: str, vertical: str) -> str:
    return (
        f"You are Churnary's assistant for {business_name}, a {vertical}. You help "
        "the owner understand which customers are about to stop coming back, and "
        "draft win-back messages.\n\n"
        "You answer ONLY from data returned by tools. Never invent a customer, a "
        "number, a date or a reason. If a tool returns nothing useful, say so "
        "plainly.\n\n"
        "Available tools:\n"
        f"{tool_catalog()}\n\n"
        "Respond with STRICT JSON only, no markdown and no prose outside it. Exactly "
        "one of these two shapes per response:\n"
        '  {"tool": "<tool name>", "args": {...}}   to look something up\n'
        '  {"reply": "<your answer to the owner>"}  to answer\n\n'
        "Guidance:\n"
        "- Look things up before answering anything factual.\n"
        "- draft_campaign needs real customer_ids from get_at_risk_customers or "
        "find_customer. Never guess an id.\n"
        "- draft_campaign does not send. Always tell the owner the messages are "
        "waiting for their approval.\n"
        "- Write like you're talking to a busy small-business owner: short, "
        "concrete, no jargon, no bullet-point walls. Give numbers and names.\n"
        "- When you name a risk, give the plain-English reason behind it."
    )


def _render_history(history: list[tuple[str, str]]) -> str:
    if not history:
        return ""
    lines = []
    for role, content in history[-MAX_HISTORY_TURNS:]:
        speaker = "Owner" if role == "user" else "You"
        lines.append(f"{speaker}: {content}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


def _clip(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + " …(truncated)"


def _summarize_result(tool: str, result: dict) -> str:
    """A one-line, owner-readable note about what a tool did, for the UI."""
    if result.get("error"):
        return f"{tool}: {result['error']}"
    if tool == "get_at_risk_customers":
        return f"Read {len(result.get('customers') or [])} at-risk customers from your data"
    if tool == "get_portfolio_summary":
        return f"Read your portfolio ({result.get('total_customers', 0)} customers)"
    if tool == "find_customer":
        return f"Searched your customers ({len(result.get('matches') or [])} matches)"
    if tool == "get_customer_detail":
        return f"Read {result.get('name', 'a customer')}'s history"
    if tool == "get_recovery_stats":
        return f"Read recovery stats ({result.get('customers_recovered', 0)} recovered)"
    if tool == "list_recent_campaigns":
        return f"Read {len(result.get('campaigns') or [])} recent campaigns"
    if tool == "search_business_knowledge":
        found = len(result.get("knowledge") or []) + len(result.get("company_brain") or [])
        return f"Searched your business notes ({found} found)"
    if tool == "draft_campaign":
        return (
            f"Drafted {result.get('drafted_for', 0)} message(s) into your approval queue"
        )
    return f"Ran {tool}"


async def _fallback(ctx: ToolContext, question: str, reason: str) -> AgentReply:
    """Answer without the model: match an intent, run its tool, template it."""
    intent = intents.match(question)
    if intent is None:
        return AgentReply(
            text=intents.UNRECOGNIZED, generated_by="fallback", error=reason
        )
    if intent.tool == "search_business_knowledge":
        intent.args.setdefault("query", question)
    result = await dispatch(ctx, intent.tool, intent.args)
    text = intents.render(intent.tool, result)
    if intent.note:
        # The question asked for something the pure path can't do, so the answer
        # carries a pointer rather than refusing.
        text = f"{text}\n\n{intent.note}"
    return AgentReply(
        text=text,
        tool_calls=[
            ToolInvocation(
                tool=intent.tool,
                args=intent.args,
                summary=_summarize_result(intent.tool, result),
            )
        ],
        generated_by="fallback",
        error=reason,
    )


async def answer(
    ctx: ToolContext,
    *,
    question: str,
    history: list[tuple[str, str]] | None = None,
    business_name: str = "your business",
    vertical: str = "local business",
) -> AgentReply:
    """One assistant turn. Never raises - always returns something to show."""
    question = (question or "").strip()
    if not question:
        return AgentReply(
            text="Ask me anything about your customers - who's at risk, what to send them, "
            "or how your win-backs are doing.",
            generated_by="fallback",
        )

    if not settings.llm_configured:
        return await _fallback(ctx, question, "llm_not_configured")

    system = _system_prompt(business_name, vertical)
    base = _render_history(history or []) + f"Owner's question: {question}\n\n"
    transcript: list[str] = []
    invocations: list[ToolInvocation] = []
    model = active_model()
    started = time.monotonic()
    last_error: str | None = None

    for step in range(1, MAX_STEPS + 1):
        prompt = base
        if transcript:
            prompt += "Tool results so far:\n" + "\n".join(transcript) + "\n\n"
        prompt += (
            "Answer the owner now with {\"reply\": ...}, or look something up with "
            '{"tool": ..., "args": ...}.'
            if step == MAX_STEPS
            else "Respond with your next JSON step."
        )

        try:
            raw = await complete_text(system, prompt, max_tokens=1200)
            parsed = extract_json_object(raw)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("chat step %s failed: %s", step, last_error)
            break

        reply = parsed.get("reply")
        if isinstance(reply, str) and reply.strip():
            return AgentReply(
                text=reply.strip(),
                tool_calls=invocations,
                generated_by="claude",
                model=model,
                steps=step,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        tool_name = parsed.get("tool")
        if not isinstance(tool_name, str) or tool_name not in TOOLS:
            # An unparseable or hallucinated step: tell the model, don't fail.
            available = ", ".join(sorted(TOOLS))
            transcript.append(
                f"[error] '{tool_name}' is not a tool. Use one of: {available}. "
                'Or answer with {"reply": "..."}.'
            )
            last_error = f"invalid_tool:{tool_name}"
            continue

        args = parsed.get("args")
        args = args if isinstance(args, dict) else {}
        result = await dispatch(ctx, tool_name, args)

        recorded_args = dict(args)
        if tool_name == "draft_campaign" and result.get("campaign_id"):
            # Stashed so the API can deep-link the owner to the draft.
            recorded_args["_result_campaign_id"] = result["campaign_id"]
        invocations.append(
            ToolInvocation(
                tool=tool_name,
                args=recorded_args,
                summary=_summarize_result(tool_name, result),
            )
        )
        transcript.append(f"{tool_name}({json.dumps(args)}) -> {_clip(json.dumps(result))}")

    # Out of steps, or the model stopped being usable. If tools did run, answer
    # from them deterministically rather than throwing the work away.
    if invocations:
        last = invocations[-1]
        result_line = transcript[-1] if transcript else ""
        try:
            payload = json.loads(result_line.split(" -> ", 1)[1])
        except (IndexError, ValueError):
            payload = {}
        return AgentReply(
            text=intents.render(last.tool, payload),
            tool_calls=invocations,
            generated_by="fallback",
            model=model,
            steps=MAX_STEPS,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=last_error or "max_steps_reached",
        )

    fallback = await _fallback(ctx, question, last_error or "no_usable_model_output")
    fallback.model = model
    fallback.latency_ms = int((time.monotonic() - started) * 1000)
    return fallback
