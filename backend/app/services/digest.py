"""The weekly owner digest: "3 customers recovered, ~$640 saved".

That sentence is in the Definition of Done and nothing produced it. It's the
email that makes the product's value legible to someone who isn't logging in —
which is most owners most weeks — so it's built the same way the rest of the
send path is: the numbers come from the database, and the *writing* is the only
part that touches an LLM.

``build_digest`` is pure given its inputs and does no I/O, so every number and
every sentence of the plain-text version is unit-testable. ``compose_digest``
adds the database reads. ``send_weekly_digests`` is the Celery entry point.

Three deliberate constraints:

* **The copy never invents a number.** Claude is asked only to write the
  friendly intro line around figures that are already computed; if it fails,
  a static template renders the identical figures. There is no path where a
  model's arithmetic reaches an owner.
* **A week with nothing to report sends nothing.** A digest that says "0
  recovered, 0 saved" every Monday trains people to delete the email, and the
  one week it matters they won't open it.
* **It is an ordinary email to the owner, not outreach.** It goes to the
  account's own address, so it isn't subject to the per-customer consent flags
  — but it still carries an unsubscribe line, because CAN-SPAM doesn't care
  that we think of it as transactional.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import active_model, complete_text, extract_json_object
from app.models import (
    Business,
    CampaignSend,
    Customer,
    RecoveryAttribution,
    User,
)
from app.services.activity import build_scored_customers
from app.services.generation_log import record_generation
from app.services.ingest import _uuid, load_sync
from app.services.senders.resend_client import send_email

logger = logging.getLogger("pulse.digest")

DEFAULT_WINDOW_DAYS = 7


@dataclass
class DigestFacts:
    """Everything the digest reports, computed before any copy is written."""

    business_name: str
    window_days: int
    recovered_count: int = 0
    revenue_recovered: float = 0.0
    messages_sent: int = 0
    awaiting_approval: int = 0
    high_risk_count: int = 0
    revenue_at_risk: float = 0.0
    # Names only, capped — enough to make it concrete without turning the
    # email into a customer list.
    recovered_names: list[str] = field(default_factory=list)
    top_risk_names: list[str] = field(default_factory=list)

    @property
    def is_worth_sending(self) -> bool:
        """Whether this week has anything an owner would want to know.

        Something recovered, something sent, something waiting on them, or
        someone newly at risk. All four zero means silence is the better
        product decision.
        """
        return bool(
            self.recovered_count
            or self.messages_sent
            or self.awaiting_approval
            or self.high_risk_count
        )


@dataclass
class Digest:
    subject: str
    body: str
    facts: DigestFacts
    generated_by: str = "fallback"  # claude | fallback
    model: str | None = None


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _join_names(names: list[str], limit: int = 3) -> str:
    shown = names[:limit]
    extra = len(names) - len(shown)
    if not shown:
        return ""
    if len(shown) == 1:
        base = shown[0]
    else:
        base = ", ".join(shown[:-1]) + f" and {shown[-1]}"
    return base + (f" and {extra} other{'s' if extra > 1 else ''}" if extra > 0 else "")


def fallback_digest(facts: DigestFacts, *, unsubscribe_url: str = "") -> tuple[str, str]:
    """The static digest. Carries exactly the same figures as the AI version."""
    if facts.recovered_count:
        subject = (
            f"{facts.recovered_count} customer"
            f"{'s' if facts.recovered_count != 1 else ''} came back this week"
        )
    elif facts.awaiting_approval:
        subject = f"{facts.awaiting_approval} win-back message(s) waiting for you"
    else:
        subject = f"Your week at {facts.business_name}"

    lines = [f"Here's your week at {facts.business_name}.", ""]

    if facts.recovered_count:
        who = _join_names(facts.recovered_names)
        lines.append(
            f"{facts.recovered_count} customer"
            f"{'s' if facts.recovered_count != 1 else ''} came back"
            f"{f' — {who}' if who else ''}, worth about "
            f"{_money(facts.revenue_recovered)}."
        )
    else:
        lines.append("No customers were attributed as recovered this week.")

    if facts.messages_sent:
        lines.append(
            f"{facts.messages_sent} win-back message"
            f"{'s' if facts.messages_sent != 1 else ''} went out."
        )
    if facts.awaiting_approval:
        lines.append(
            f"{facts.awaiting_approval} message"
            f"{'s are' if facts.awaiting_approval != 1 else ' is'} "
            "waiting for your approval."
        )
    if facts.high_risk_count:
        who = _join_names(facts.top_risk_names)
        lines.append(
            f"{facts.high_risk_count} customer"
            f"{'s are' if facts.high_risk_count != 1 else ' is'} at high risk of "
            f"not coming back{f' — {who}' if who else ''}, roughly "
            f"{_money(facts.revenue_at_risk)} of annual revenue."
        )

    lines += ["", "Open Churnary to review and approve: " + settings.billing_return_url]
    if unsubscribe_url:
        lines += ["", f"Stop these weekly emails: {unsubscribe_url}"]
    return subject, "\n".join(lines)


def _digest_prompt(facts: DigestFacts) -> tuple[str, str]:
    system = (
        f"You write a short weekly summary email for the owner of "
        f"{facts.business_name}. Warm, plain, specific — like a good manager's "
        "Monday note, not marketing copy.\n\n"
        "You are given exact figures. Use them verbatim. Never invent, round "
        "differently, estimate, or add a number that is not given. Never invent "
        "a customer name.\n\n"
        'Respond with STRICT JSON only, exactly: {"subject": "...", "body": "..."}. '
        "The body is plain text, at most 120 words, no markdown."
    )
    bullets = [
        f"- Customers recovered this week: {facts.recovered_count}",
        f"- Revenue recovered: {_money(facts.revenue_recovered)}",
        f"- Win-back messages sent: {facts.messages_sent}",
        f"- Messages awaiting the owner's approval: {facts.awaiting_approval}",
        f"- Customers now at high risk: {facts.high_risk_count}",
        f"- Annual revenue at risk: {_money(facts.revenue_at_risk)}",
    ]
    if facts.recovered_names:
        bullets.append(f"- Names of recovered customers: {', '.join(facts.recovered_names)}")
    if facts.top_risk_names:
        bullets.append(f"- Highest-risk customers: {', '.join(facts.top_risk_names)}")

    user = (
        f"Figures for the last {facts.window_days} days:\n"
        + "\n".join(bullets)
        + "\n\nWrite the email now as JSON."
    )
    return system, user


async def build_digest_copy(facts: DigestFacts) -> tuple[str, str, str, str | None]:
    """``(subject, body, generated_by, model)`` — Claude's version, or the template."""
    if not settings.llm_configured:
        subject, body = fallback_digest(facts)
        return subject, body, "fallback", None

    system, user = _digest_prompt(facts)
    model = active_model()
    try:
        raw = await complete_text(system, user, max_tokens=600)
        data = extract_json_object(raw)
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()
        if not subject or not body:
            raise ValueError("digest output missing subject or body")
        return subject, body, "claude", model
    except Exception as exc:  # LLMError, parse failure, network — all degrade
        logger.warning("digest generation failed, using template: %s", exc)
        subject, body = fallback_digest(facts)
        return subject, body, "fallback", model


async def collect_facts(
    db: AsyncSession, *, business_id: str, window_days: int = DEFAULT_WINDOW_DAYS
) -> DigestFacts:
    """Read the week's numbers. No LLM, no sending."""
    bid = _uuid(business_id)
    since = datetime.now(UTC) - timedelta(days=window_days)
    business = await db.get(Business, bid)
    facts = DigestFacts(
        business_name=(business.name if business else "your business"),
        window_days=window_days,
    )

    recovery_rows = (
        await db.execute(
            select(RecoveryAttribution.customer_id, RecoveryAttribution.estimated_value).where(
                RecoveryAttribution.business_id == bid,
                RecoveryAttribution.recovered_at >= since,
            )
        )
    ).all()
    facts.recovered_count = len(recovery_rows)
    facts.revenue_recovered = round(sum(float(v or 0) for _cid, v in recovery_rows), 2)

    if recovery_rows:
        names = (
            await db.execute(
                select(Customer.first_name, Customer.last_name).where(
                    Customer.business_id == bid,
                    Customer.id.in_([cid for cid, _v in recovery_rows]),
                )
            )
        ).all()
        facts.recovered_names = [
            f"{first or ''} {last or ''}".strip() for first, last in names
        ][:5]
        facts.recovered_names = [n for n in facts.recovered_names if n]

    facts.messages_sent = (
        await db.scalar(
            select(func.count())
            .select_from(CampaignSend)
            .where(
                CampaignSend.business_id == bid,
                CampaignSend.status.in_(("sent", "delivered")),
                CampaignSend.sent_at >= since,
            )
        )
    ) or 0
    facts.awaiting_approval = (
        await db.scalar(
            select(func.count())
            .select_from(CampaignSend)
            .where(CampaignSend.business_id == bid, CampaignSend.status == "pending")
        )
    ) or 0

    sync = await load_sync(db, business_id)
    if sync.customers:
        scored = build_scored_customers(
            sync, vertical=(business.vertical if business else "other")
        )
        high = sorted(
            (s for s in scored if s.result.band == "high"),
            key=lambda s: s.estimated_annual_value,
            reverse=True,
        )
        facts.high_risk_count = len(high)
        facts.revenue_at_risk = round(sum(s.estimated_annual_value for s in high), 2)
        facts.top_risk_names = [
            n
            for n in (
                f"{s.customer.first_name or ''} {s.customer.last_name or ''}".strip()
                for s in high[:3]
            )
            if n
        ]

    return facts


async def compose_digest(
    db: AsyncSession, *, business_id: str, window_days: int = DEFAULT_WINDOW_DAYS
) -> Digest:
    """Collect the numbers and write the copy. Sends nothing."""
    facts = await collect_facts(db, business_id=business_id, window_days=window_days)
    subject, body, generated_by, model = await build_digest_copy(facts)
    await record_generation(
        db,
        business_id=business_id,
        purpose="digest_summary",
        system_prompt="[weekly digest]",
        user_prompt=f"recovered={facts.recovered_count} at_risk={facts.high_risk_count}",
        raw_output=f"{subject}\n\n{body}",
        model=model,
        generated_by=generated_by,
    )
    return Digest(
        subject=subject, body=body, facts=facts, generated_by=generated_by, model=model
    )


async def owner_emails(db: AsyncSession, *, business_id: str) -> list[str]:
    """Addresses the digest goes to: the account's own owners, not customers."""
    rows = (
        (
            await db.execute(
                select(User.email).where(
                    User.business_id == _uuid(business_id), User.role == "owner"
                )
            )
        )
        .scalars()
        .all()
    )
    return [e for e in rows if e]


@dataclass
class DigestRunSummary:
    businesses_considered: int = 0
    sent: int = 0
    skipped_nothing_to_report: int = 0
    skipped_no_recipient: int = 0
    failed: int = 0


async def send_digest_for_business(
    db: AsyncSession, *, business_id: str, window_days: int = DEFAULT_WINDOW_DAYS
) -> str:
    """Compose and email one business's digest. Returns a short outcome string."""
    digest = await compose_digest(db, business_id=business_id, window_days=window_days)
    if not digest.facts.is_worth_sending:
        return "nothing_to_report"

    recipients = await owner_emails(db, business_id=business_id)
    if not recipients:
        return "no_recipient"

    failures = 0
    for address in recipients:
        result = await send_email(address, digest.subject, digest.body)
        if not result.ok:
            failures += 1
            logger.warning("digest to %s failed: %s", address, result.error)
    return "sent" if failures < len(recipients) else "failed"
