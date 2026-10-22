"""What the assistant is allowed to do, and nothing else.

Each tool is an async callable taking ``(ctx, args)`` and returning a plain
JSON-serializable dict. Three properties are enforced here rather than left to
the prompt:

1. **Tenant scoping is in SQL.** Every query filters on ``ctx.business_id``.
   The model never supplies a business id and could not use one if it tried.
2. **The allow-list is closed.** ``dispatch`` refuses any name not in
   ``TOOLS``, so a hallucinated tool is an error message rather than an
   exception or, worse, an attribute lookup on something interesting.
3. **Only one tool writes, and it cannot send.** ``draft_campaign`` queues
   pending sends for approval. There is no tool that delivers a message.

Arguments arrive from a language model, so every tool coerces and bounds its
own inputs instead of trusting them. A bad argument returns ``{"error": ...}``
for the model to read and retry, which is far more useful than a 500.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.limits import Entitlements, channel_denial
from app.core.deps import CurrentUser
from app.models import Business, Campaign, CampaignSend, Customer, RecoveryAttribution
from app.services import ingest
from app.services.activity import (
    ScoredCustomer,
    build_scored_customers,
    monthly_revenue_series,
    summarize,
)
from app.services.attribution import recovery_totals
from app.services.rag.knowledge_store import search_knowledge
from app.social import brain

logger = logging.getLogger("pulse.chat.tools")

# Caps on anything the model can ask for, so one turn can't pull the whole book
# into a prompt.
MAX_CUSTOMER_ROWS = 25
MAX_KNOWLEDGE_SNIPPETS = 6
MAX_CAMPAIGN_ROWS = 10
MAX_DRAFT_RECIPIENTS = 50


@dataclass
class ToolContext:
    """Everything a tool may read about who is asking.

    Carries the resolved ``CurrentUser`` and entitlements rather than letting
    tools re-resolve them: one source of truth per request, and no tool can
    accidentally widen its own scope.
    """

    db: AsyncSession
    user: CurrentUser
    entitlements: Entitlements

    @property
    def business_id(self) -> str:
        return self.user.business_id


def _coerce_int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _coerce_str(value: Any, *, max_len: int = 500) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def _name_of(scored: ScoredCustomer) -> str:
    first = scored.customer.first_name or ""
    last = scored.customer.last_name or ""
    return f"{first} {last}".strip() or "Unnamed customer"


async def _scored(ctx: ToolContext) -> tuple[list[ScoredCustomer], Business | None]:
    """Score this tenant's customers once per tool call that needs it."""
    biz = await ctx.db.get(Business, ingest._uuid(ctx.business_id))
    sync = await ingest.load_sync(ctx.db, ctx.business_id)
    if not sync.customers:
        return [], biz
    return build_scored_customers(sync, vertical=biz.vertical if biz else "other"), biz


# -- Read tools ---------------------------------------------------------------


async def get_portfolio_summary(ctx: ToolContext, args: dict) -> dict:
    """Headline numbers: how many at risk, how much revenue is exposed."""
    scored, _biz = await _scored(ctx)
    if not scored:
        return {
            "status": "no_data",
            "message": "No customer data has been imported yet.",
        }
    sync = await ingest.load_sync(ctx.db, ctx.business_id)
    summary = summarize(scored, monthly_revenue_series(sync))
    totals = await recovery_totals(ctx.db, ctx.business_id)
    return {
        "total_customers": summary.total_customers,
        "high_risk": summary.high_risk,
        "medium_risk": summary.med_risk,
        "low_risk": summary.low_risk,
        "revenue_at_risk": summary.revenue_at_risk,
        "average_days_since_last_visit": summary.avg_days_away,
        "customers_recovered_all_time": totals.recovered_count,
        "revenue_recovered_all_time": totals.revenue_recovered,
    }


async def get_at_risk_customers(ctx: ToolContext, args: dict) -> dict:
    """The work queue: who is most likely to leave, and why in plain English."""
    band = _coerce_str(args.get("band"), max_len=8).lower()
    limit = _coerce_int(args.get("limit"), 10, low=1, high=MAX_CUSTOMER_ROWS)
    scored, _biz = await _scored(ctx)
    if not scored:
        return {"status": "no_data", "customers": []}

    if band in ("high", "med", "medium", "low"):
        wanted = "med" if band == "medium" else band
        scored = [s for s in scored if s.result.band == wanted]
    scored.sort(key=lambda s: s.result.score, reverse=True)

    return {
        "count": len(scored),
        "showing": min(limit, len(scored)),
        "customers": [
            {
                # The row id, so draft_campaign can be called with it directly.
                "customer_id": s.customer.external_id,
                "name": _name_of(s),
                "risk_score": s.result.score,
                "risk_band": s.result.band,
                "reasons": s.result.reasons,
                "days_since_last_visit": s.days_since_last_visit,
                "estimated_annual_value": s.estimated_annual_value,
                "recommended_action": s.recommended_action,
                "action_reason": s.action_reason,
                "has_email": bool(s.customer.email),
                "has_phone": bool(s.customer.phone),
            }
            for s in scored[:limit]
        ],
    }


async def find_customer(ctx: ToolContext, args: dict) -> dict:
    """Look a customer up by name, email or phone.

    Needed because an owner types "draft something for Maria", not a UUID.
    Matching is done in SQL, scoped to the tenant, so a name that happens to
    exist in another business is simply not found.
    """
    query = _coerce_str(args.get("query"), max_len=120)
    if not query:
        return {"error": "Provide a name, email or phone to search for."}

    pattern = f"%{query.lower()}%"
    rows = (
        (
            await ctx.db.execute(
                select(Customer)
                .where(
                    Customer.business_id == ingest._uuid(ctx.business_id),
                    or_(
                        func.lower(Customer.first_name).like(pattern),
                        func.lower(Customer.last_name).like(pattern),
                        func.lower(Customer.email).like(pattern),
                        Customer.phone.like(pattern),
                    ),
                )
                .limit(MAX_CUSTOMER_ROWS)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"matches": [], "message": f"Nobody matching '{query}'."}
    return {
        "matches": [
            {
                "customer_id": str(row.id),
                "name": f"{row.first_name or ''} {row.last_name or ''}".strip()
                or "Unnamed customer",
                "email": row.email,
                "phone": row.phone,
                "do_not_contact": row.do_not_contact,
                "unsubscribed_email": row.unsubscribed_email,
                "unsubscribed_sms": row.unsubscribed_sms,
            }
            for row in rows
        ]
    }


async def get_customer_detail(ctx: ToolContext, args: dict) -> dict:
    """One customer's score, reasons and recent outreach history."""
    raw_id = _coerce_str(args.get("customer_id"), max_len=64)
    try:
        customer_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        return {"error": "customer_id must be an id from find_customer or get_at_risk_customers."}

    customer = await ctx.db.get(Customer, customer_id)
    if customer is None or str(customer.business_id) != str(
        ingest._uuid(ctx.business_id)
    ):
        return {"error": "No such customer."}

    scored, _biz = await _scored(ctx)
    match = next((s for s in scored if s.customer.external_id == str(customer_id)), None)

    sends = (
        (
            await ctx.db.execute(
                select(CampaignSend)
                .where(
                    CampaignSend.business_id == ingest._uuid(ctx.business_id),
                    CampaignSend.customer_id == customer_id,
                )
                .order_by(CampaignSend.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    return {
        "customer_id": str(customer.id),
        "name": f"{customer.first_name or ''} {customer.last_name or ''}".strip()
        or "Unnamed customer",
        "email": customer.email,
        "phone": customer.phone,
        "can_be_emailed": bool(customer.email)
        and not customer.unsubscribed_email
        and not customer.do_not_contact,
        "can_be_texted": bool(customer.phone)
        and not customer.unsubscribed_sms
        and not customer.do_not_contact,
        "risk_score": match.result.score if match else None,
        "risk_band": match.result.band if match else None,
        "reasons": match.result.reasons if match else [],
        "visit_count": match.visit_count if match else 0,
        "total_spend": match.total_spend if match else 0.0,
        "days_since_last_visit": match.days_since_last_visit if match else None,
        "recent_outreach": [
            {
                "status": s.status,
                "channel": s.channel,
                "sent_at": s.sent_at.isoformat() if s.sent_at else None,
                "subject": s.subject,
            }
            for s in sends
        ],
    }


async def get_recovery_stats(ctx: ToolContext, args: dict) -> dict:
    """How much the product has actually won back, optionally over a window."""
    days = _coerce_int(args.get("days"), 0, low=0, high=3650)
    bid = ingest._uuid(ctx.business_id)

    stmt = select(
        func.count(RecoveryAttribution.id),
        func.coalesce(func.sum(RecoveryAttribution.estimated_value), 0),
    ).where(RecoveryAttribution.business_id == bid)
    if days:
        stmt = stmt.where(
            RecoveryAttribution.recovered_at >= datetime.now(UTC) - timedelta(days=days)
        )
    count, value = (await ctx.db.execute(stmt)).one()

    return {
        "window_days": days or "all_time",
        "customers_recovered": int(count or 0),
        "revenue_recovered": round(float(value or 0), 2),
    }


async def list_recent_campaigns(ctx: ToolContext, args: dict) -> dict:
    """Recent campaigns and how they did."""
    limit = _coerce_int(args.get("limit"), 5, low=1, high=MAX_CAMPAIGN_ROWS)
    bid = ingest._uuid(ctx.business_id)
    campaigns = (
        (
            await ctx.db.execute(
                select(Campaign)
                .where(Campaign.business_id == bid)
                .order_by(Campaign.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not campaigns:
        return {"campaigns": [], "message": "No campaigns yet."}

    counts = dict.fromkeys((c.id for c in campaigns), 0)
    pending = dict.fromkeys((c.id for c in campaigns), 0)
    rows = (
        await ctx.db.execute(
            select(CampaignSend.campaign_id, CampaignSend.status, func.count())
            .where(CampaignSend.campaign_id.in_(list(counts)))
            .group_by(CampaignSend.campaign_id, CampaignSend.status)
        )
    ).all()
    for cid, status, count in rows:
        if status in ("sent", "delivered"):
            counts[cid] = counts.get(cid, 0) + count
        elif status == "pending":
            pending[cid] = pending.get(cid, 0) + count

    return {
        "campaigns": [
            {
                "campaign_id": str(c.id),
                "name": c.name,
                "channel": c.channel,
                "status": c.status,
                "sent": counts.get(c.id, 0),
                "awaiting_approval": pending.get(c.id, 0),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in campaigns
        ]
    }


async def search_business_knowledge(ctx: ToolContext, args: dict) -> dict:
    """The owner's own notes: services, brand voice, past campaigns, brain facts.

    Brain records come from ``brain.list_public()`` only. Private records are
    not returned to the assistant at all, so there is no path by which one
    reaches a drafted message.
    """
    query = _coerce_str(args.get("query"), max_len=300)
    if not query:
        return {"error": "Provide something to search for."}

    snippets = await search_knowledge(
        ctx.db, business_id=ctx.business_id, query=query, top_k=MAX_KNOWLEDGE_SNIPPETS
    )
    public_brain = await brain.list_public(ctx.db, business_id=ctx.business_id)
    matched_brain = brain.search(public_brain, query)[:MAX_KNOWLEDGE_SNIPPETS]

    return {
        "knowledge": [{"kind": row.kind, "content": row.content} for row in snippets],
        "company_brain": [
            {"title": row.title, "kind": row.kind, "summary": row.summary}
            for row in matched_brain
        ],
    }


# -- The one write tool -------------------------------------------------------


async def draft_campaign(ctx: ToolContext, args: dict) -> dict:
    """Queue a win-back campaign for the owner's approval. Sends nothing.

    Deliberately the only mutation the assistant can perform, and deliberately
    incapable of delivery: it produces ``pending`` rows in the same queue the
    dashboard's review screen reads, so nothing reaches a customer without a
    human pressing approve.
    """
    from app.campaigns import manual

    raw_ids = args.get("customer_ids")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list) or not raw_ids:
        return {
            "error": "customer_ids must be a non-empty list of ids from "
            "get_at_risk_customers or find_customer."
        }
    customer_ids = [_coerce_str(v, max_len=64) for v in raw_ids[:MAX_DRAFT_RECIPIENTS]]

    channel = _coerce_str(args.get("channel"), max_len=8).lower() or "email"
    if channel not in ("email", "sms"):
        return {"error": "channel must be 'email' or 'sms'."}
    denial = channel_denial(ctx.entitlements, channel)
    if denial:
        # Returned as data, not raised: the model should tell the owner why and
        # offer email instead, rather than the turn failing.
        return {"error": denial, "upgrade_required": True}

    name = _coerce_str(args.get("name"), max_len=120) or "Win-back from chat"
    incentive = _coerce_str(args.get("incentive"), max_len=255) or None

    try:
        result = await manual.build_campaign(
            ctx.db,
            user=ctx.user,
            name=name,
            channel=channel,
            customer_ids=customer_ids,
            incentive=incentive,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    return {
        "campaign_id": str(result.campaign.id),
        "name": result.campaign.name,
        "channel": channel,
        "status": result.campaign.status,
        "drafted_for": len(result.sends),
        "skipped": result.skipped,
        "awaiting_approval": True,
        "note": (
            "Drafted and waiting for approval. Nothing has been sent - "
            "the owner reviews and approves these on the campaign screen."
        ),
        "preview": [
            {"to": s.customer_id and str(s.customer_id), "subject": s.subject, "body": s.body}
            for s in result.sends[:3]
        ],
    }


# -- Registry -----------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: str
    handler: Any
    writes: bool = False


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="get_portfolio_summary",
            description=(
                "Headline retention numbers: how many customers are at high/medium/low "
                "risk, revenue at risk, and how much has been recovered all time."
            ),
            arguments="none",
            handler=get_portfolio_summary,
        ),
        ToolSpec(
            name="get_at_risk_customers",
            description=(
                "List customers most likely to leave, with the plain-English reasons "
                "and the recommended next action for each."
            ),
            arguments='{"band": "high|med|low (optional)", "limit": "1-25 (optional)"}',
            handler=get_at_risk_customers,
        ),
        ToolSpec(
            name="find_customer",
            description="Find a customer by name, email or phone.",
            arguments='{"query": "Maria"}',
            handler=find_customer,
        ),
        ToolSpec(
            name="get_customer_detail",
            description=(
                "One customer's risk score, reasons, spend, visit history and recent "
                "outreach. Also says whether they can be emailed or texted."
            ),
            arguments='{"customer_id": "<id from find_customer>"}',
            handler=get_customer_detail,
        ),
        ToolSpec(
            name="get_recovery_stats",
            description="How many customers came back and how much revenue that was.",
            arguments='{"days": "optional window, e.g. 30"}',
            handler=get_recovery_stats,
        ),
        ToolSpec(
            name="list_recent_campaigns",
            description="Recent campaigns, their status, and how many were sent.",
            arguments='{"limit": "1-10 (optional)"}',
            handler=list_recent_campaigns,
        ),
        ToolSpec(
            name="search_business_knowledge",
            description=(
                "Search the owner's own notes: services, brand voice, past campaigns "
                "that worked, and public company-brain facts."
            ),
            arguments='{"query": "brand voice"}',
            handler=search_business_knowledge,
        ),
        ToolSpec(
            name="draft_campaign",
            description=(
                "Draft win-back messages for specific customers and put them in the "
                "approval queue. Does NOT send - the owner must approve first."
            ),
            arguments=(
                '{"customer_ids": ["<id>", ...], "channel": "email|sms", '
                '"incentive": "20% off (optional)", "name": "optional label"}'
            ),
            handler=draft_campaign,
            writes=True,
        ),
    )
}


async def dispatch(ctx: ToolContext, name: str, args: dict | None) -> dict:
    """Run one tool by name. A name outside the allow-list is an error, not a crash."""
    spec = TOOLS.get(name)
    if spec is None:
        return {
            "error": f"'{name}' isn't a tool. Available: {', '.join(sorted(TOOLS))}.",
        }
    try:
        return await spec.handler(ctx, args or {})
    except Exception as exc:  # a tool failing must not kill the conversation
        logger.warning("chat tool %s failed: %s", name, exc, exc_info=True)
        return {"error": f"That lookup failed ({type(exc).__name__}). Try a different question."}


def tool_catalog() -> str:
    """The tool list as it appears in the system prompt."""
    return "\n".join(
        f"- {spec.name}: {spec.description} Arguments: {spec.arguments}"
        for spec in TOOLS.values()
    )
