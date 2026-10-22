"""Per-business data export and deletion.

CLAUDE.md requires a per-business data-deletion endpoint. The existing
``ingest.wipe_business_data`` only ever covered the retention-ingest tables
(customers, visits, transactions, scores, sync runs) — it predates campaigns,
social, the assistant and the logs, so calling it for a deletion request would
have left a tenant's generated copy, chat transcripts and campaign history
behind. That is exactly the failure mode a deletion endpoint exists to prevent,
so this module enumerates every tenant-scoped table instead.

Two deliberate choices:

**Deletion order is explicit, and children go before parents.** Several child
tables declare ``ON DELETE CASCADE``, which Postgres enforces and SQLite does
not unless ``PRAGMA foreign_keys`` is on. Depending on the cascade would mean a
deletion that is complete on one of our two dialects and leaves orphans on the
other, which is not a thing to discover from a regulator's letter.

**One audit row survives.** A deletion request erases personal data; it does
not erase the fact that the request was honoured. The ``data_deleted`` audit
row is written after the purge so it isn't deleted by it, and it carries counts
rather than any of the deleted content.

The export is a plain JSON structure rather than a file format, so the API can
hand it over as a download and a test can assert on its contents.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models import (
    AuditLog,
    AutomationRule,
    BrandKitVersion,
    Business,
    BusinessKnowledge,
    Campaign,
    CampaignSend,
    ChatConversation,
    ChatMessage,
    CompanyContextItem,
    CompetitorPriceResearchRun,
    CompetitorPriceWatch,
    Customer,
    CustomerIdentity,
    EngagementEvent,
    GenerationLog,
    IntegrationConnection,
    PostReviewEvent,
    ProviderWebhookEvent,
    RecoveryAttribution,
    RiskScore,
    SocialCampaign,
    SocialComment,
    SocialPost,
    SyncRun,
    TeamInvite,
    Transaction,
    User,
    Visit,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.services.generation_log import record_audit

logger = logging.getLogger("pulse.privacy")


# Every tenant-scoped table, children before parents. Grouped so a caller can
# delete the retention data without destroying the business's social presence
# and brand kit, which is the common support request ("re-import my customers,
# start the scores over") and is not a privacy deletion at all.
#
# Ordering within each tuple matters; the groups themselves are independent.
RETENTION_TABLES: tuple[Any, ...] = (
    # Webhook deliveries hold customer names and contact details in their
    # payloads, so they're customer data, not configuration.
    WebhookDelivery,
    # Children of campaign_sends / customers first.
    RecoveryAttribution,
    EngagementEvent,
    CampaignSend,
    Campaign,
    AutomationRule,
    RiskScore,
    Visit,
    Transaction,
    CustomerIdentity,
    Customer,
    ProviderWebhookEvent,
    SyncRun,
)

SOCIAL_TABLES: tuple[Any, ...] = (
    PostReviewEvent,
    SocialComment,
    SocialPost,
    SocialCampaign,
    CompanyContextItem,
    BrandKitVersion,
)

ASSISTANT_TABLES: tuple[Any, ...] = (
    ChatMessage,
    ChatConversation,
)

KNOWLEDGE_TABLES: tuple[Any, ...] = (BusinessKnowledge,)

LOG_TABLES: tuple[Any, ...] = (GenerationLog,)

PRICING_TABLES: tuple[Any, ...] = (
    CompetitorPriceResearchRun,
    CompetitorPriceWatch,
)

CONNECTION_TABLES: tuple[Any, ...] = (
    IntegrationConnection,
    # After WebhookDelivery (in RETENTION_TABLES), which references it.
    WebhookEndpoint,
    # Pending invites name people who never joined.
    TeamInvite,
)

# What "everything" means. Subscription is excluded on purpose: it is the
# billing relationship, not customer data, and dropping it would leave a
# paying tenant with no plan while Stripe keeps charging. Users is excluded for
# the same reason — deleting the login that asked for the deletion would make
# the confirmation screen unreachable.
ALL_TABLES: tuple[Any, ...] = (
    *RETENTION_TABLES,
    *SOCIAL_TABLES,
    *ASSISTANT_TABLES,
    *KNOWLEDGE_TABLES,
    *LOG_TABLES,
    *PRICING_TABLES,
    *CONNECTION_TABLES,
)

SCOPES = ("retention", "social", "assistant", "knowledge", "all")

_SCOPE_TABLES: dict[str, tuple[Any, ...]] = {
    "retention": RETENTION_TABLES,
    "social": SOCIAL_TABLES,
    "assistant": ASSISTANT_TABLES,
    "knowledge": KNOWLEDGE_TABLES,
    "all": ALL_TABLES,
}


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


@dataclass
class DeletionReport:
    scope: str
    deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


async def delete_business_data(
    db: AsyncSession,
    *,
    business_id: str,
    scope: str = "all",
    actor: CurrentUser | None = None,
) -> DeletionReport:
    """Erase this tenant's data. Does not commit — the caller owns the transaction.

    ``scope`` is one of ``SCOPES``. ``all`` is the privacy-request path and
    clears everything except the billing subscription and the login accounts
    (see ``ALL_TABLES``).
    """
    if scope not in _SCOPE_TABLES:
        raise ValueError(f"scope must be one of {SCOPES}")

    bid = _uuid(business_id)
    report = DeletionReport(scope=scope)

    tables = list(_SCOPE_TABLES[scope])
    if scope == "all":
        # Prior audit summaries can name a customer, so a full privacy deletion
        # clears them too. The single `data_deleted` row written below lands
        # after this and is what survives as proof the request was honoured.
        tables.append(AuditLog)

    for model in tables:
        table = model.__tablename__
        # Counted before deleting: the report is what the owner is shown as
        # confirmation, and "0 rows" vs "no such table" are different answers.
        count = (
            await db.scalar(
                select(func.count()).select_from(model).where(model.business_id == bid)
            )
        ) or 0
        if count:
            await db.execute(delete(model).where(model.business_id == bid))
            report.deleted[table] = count

    await db.flush()

    # Written after the purge so it survives it. Carries counts, never content.
    await record_audit(
        db,
        business_id=bid,
        action="data_deleted",
        actor=actor,
        subject_type="business",
        subject_id=str(bid),
        summary=(
            f"Deleted {report.total} row(s) in scope '{scope}': "
            + (
                ", ".join(f"{table}={n}" for table, n in sorted(report.deleted.items()))
                or "nothing to delete"
            )
        ),
    )
    logger.info("data deletion for %s scope=%s rows=%s", bid, scope, report.total)
    return report


async def delete_customer(
    db: AsyncSession,
    *,
    business_id: str,
    customer_id: str,
    actor: CurrentUser | None = None,
) -> bool:
    """Erase one customer and everything attached to them.

    The individual right-to-be-forgotten case. Returns False when the customer
    isn't this tenant's, so the caller can 404 rather than reporting a deletion
    that didn't happen.
    """
    bid = _uuid(business_id)
    try:
        cid = _uuid(customer_id)
    except (ValueError, AttributeError):
        return False

    customer = await db.get(Customer, cid)
    if customer is None or customer.business_id != bid:
        return False

    # Children of this customer's sends before the sends themselves.
    send_ids = list(
        (
            await db.execute(
                select(CampaignSend.id).where(
                    CampaignSend.business_id == bid, CampaignSend.customer_id == cid
                )
            )
        )
        .scalars()
        .all()
    )
    if send_ids:
        await db.execute(
            delete(EngagementEvent).where(EngagementEvent.campaign_send_id.in_(send_ids))
        )
        await db.execute(
            delete(RecoveryAttribution).where(
                RecoveryAttribution.campaign_send_id.in_(send_ids)
            )
        )

    for model in (
        RecoveryAttribution,
        EngagementEvent,
        CampaignSend,
        RiskScore,
        Visit,
        Transaction,
        CustomerIdentity,
    ):
        await db.execute(
            delete(model).where(model.business_id == bid, model.customer_id == cid)
        )

    # Generation logs reference the customer loosely (no FK) and hold their name
    # inside the prompt text, so they have to go too — a deletion that leaves
    # the customer's name in a stored prompt hasn't deleted them.
    await db.execute(
        delete(GenerationLog).where(
            GenerationLog.business_id == bid, GenerationLog.customer_id == cid
        )
    )

    await db.delete(customer)
    await db.flush()
    await record_audit(
        db,
        business_id=bid,
        action="data_deleted",
        actor=actor,
        subject_type="customer",
        subject_id=str(cid),
        # The name is deliberately not recorded: writing it into a row that
        # survives the purge would defeat the erasure it is documenting.
        summary="Deleted a customer and all of their associated history",
    )
    return True


def _iso(value) -> str | None:
    return value.isoformat() if value else None


async def export_business_data(db: AsyncSession, *, business_id: str) -> dict:
    """Everything we hold for this tenant, as JSON.

    Includes the generated copy and the assistant transcripts, not just the
    imported rows: "a copy of my data" means what the product produced about
    their customers as much as what it ingested.
    """
    bid = _uuid(business_id)
    business = await db.get(Business, bid)

    async def rows(model, order=None):
        stmt = select(model).where(model.business_id == bid)
        if order is not None:
            stmt = stmt.order_by(order)
        return list((await db.execute(stmt)).scalars().all())

    customers = await rows(Customer, Customer.created_at)
    visits = await rows(Visit, Visit.occurred_at)
    transactions = await rows(Transaction, Transaction.occurred_at)
    campaigns = await rows(Campaign, Campaign.created_at)
    sends = await rows(CampaignSend, CampaignSend.created_at)
    engagement = await rows(EngagementEvent, EngagementEvent.occurred_at)
    recoveries = await rows(RecoveryAttribution, RecoveryAttribution.recovered_at)
    rules = await rows(AutomationRule, AutomationRule.created_at)
    knowledge = await rows(BusinessKnowledge, BusinessKnowledge.created_at)
    conversations = await rows(ChatConversation, ChatConversation.created_at)
    messages = await rows(ChatMessage, ChatMessage.created_at)
    audit = await rows(AuditLog, AuditLog.created_at)
    members = await rows(User, User.created_at)
    invites = await rows(TeamInvite, TeamInvite.created_at)
    endpoints = await rows(WebhookEndpoint, WebhookEndpoint.created_at)

    return {
        "exported_at": _iso(datetime.now(UTC)),
        "business": {
            "id": str(bid),
            "name": business.name if business else None,
            "vertical": business.vertical if business else None,
            "timezone": business.timezone if business else None,
        },
        "customers": [
            {
                "id": str(c.id),
                "first_name": c.first_name,
                "last_name": c.last_name,
                "email": c.email,
                "phone": c.phone,
                "source": c.source,
                "do_not_contact": c.do_not_contact,
                "unsubscribed_email": c.unsubscribed_email,
                "unsubscribed_sms": c.unsubscribed_sms,
                "created_at": _iso(c.created_at),
            }
            for c in customers
        ],
        "visits": [
            {
                "customer_id": str(v.customer_id),
                "source": v.source,
                "occurred_at": _iso(v.occurred_at),
            }
            for v in visits
        ],
        "transactions": [
            {
                "customer_id": str(t.customer_id) if t.customer_id else None,
                "source": t.source,
                "amount": float(t.amount or 0),
                "currency": t.currency,
                "status": t.status,
                "occurred_at": _iso(t.occurred_at),
            }
            for t in transactions
        ],
        "campaigns": [
            {
                "id": str(c.id),
                "name": c.name,
                "channel": c.channel,
                "status": c.status,
                "incentive": c.incentive,
                "ab_test": c.ab_test,
                "created_at": _iso(c.created_at),
            }
            for c in campaigns
        ],
        "campaign_sends": [
            {
                "id": str(s.id),
                "campaign_id": str(s.campaign_id),
                "customer_id": str(s.customer_id),
                "channel": s.channel,
                "subject": s.subject,
                "body": s.body,
                "status": s.status,
                "variant": s.variant,
                "generated_by": s.generated_by,
                "generation_model": s.generation_model,
                "sent_at": _iso(s.sent_at),
            }
            for s in sends
        ],
        "engagement_events": [
            {
                "customer_id": str(e.customer_id) if e.customer_id else None,
                "kind": e.kind,
                "occurred_at": _iso(e.occurred_at),
            }
            for e in engagement
        ],
        "recoveries": [
            {
                "customer_id": str(r.customer_id),
                "estimated_value": float(r.estimated_value or 0),
                "recovered_at": _iso(r.recovered_at),
            }
            for r in recoveries
        ],
        "automation_rules": [
            {
                "name": r.name,
                "trigger_band": r.trigger_band,
                "channel": r.channel,
                "mode": r.mode,
                "enabled": r.enabled,
                "cooldown_days": r.cooldown_days,
            }
            for r in rules
        ],
        "business_knowledge": [
            {"kind": k.kind, "content": k.content, "created_at": _iso(k.created_at)}
            for k in knowledge
        ],
        "assistant_conversations": [
            {
                "id": str(c.id),
                "title": c.title,
                "created_at": _iso(c.created_at),
                "messages": [
                    {
                        "role": m.role,
                        "content": m.content,
                        "generated_by": m.generated_by,
                        "created_at": _iso(m.created_at),
                    }
                    for m in messages
                    if m.conversation_id == c.id
                ],
            }
            for c in conversations
        ],
        "team_members": [
            {"email": m.email, "role": m.role, "joined_at": _iso(m.created_at)}
            for m in members
        ],
        "team_invites": [
            {
                "email": i.email,
                "role": i.role,
                "created_at": _iso(i.created_at),
                "accepted_at": _iso(i.accepted_at),
                "revoked_at": _iso(i.revoked_at),
            }
            for i in invites
        ],
        # Where customer data is being sent. The signing secret is not included.
        "webhook_endpoints": [
            {"url": e.url, "events": list(e.events or []), "enabled": e.enabled}
            for e in endpoints
        ],
        "audit_log": [
            {
                "action": a.action,
                "actor_email": a.actor_email,
                "summary": a.summary,
                "created_at": _iso(a.created_at),
            }
            for a in audit
        ],
    }
