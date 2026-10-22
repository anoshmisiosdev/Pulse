"""Retention analytics, score drill-downs, segments, CSV export, and the digest.

Read-only except for ``POST /insights/digest/send``, which exists so an owner
(or an operator verifying a Resend domain) can trigger the weekly email without
waiting for the beat schedule.
"""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.guard import EntitlementsDep, require_multi_location
from app.billing.limits import Entitlements
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.posthog_client import capture_event
from app.models import Business
from app.schemas.insights import (
    CohortOut,
    CohortsOut,
    DigestPreviewOut,
    DigestSendOut,
    LocationsOut,
    LocationSummaryOut,
    ScoreExplanationOut,
    ScoreFactorOut,
    SegmentDefinitionOut,
    SegmentPreviewOut,
    SegmentsOut,
)
from app.services import insights
from app.services.activity import build_scored_customers
from app.services.digest import compose_digest, owner_emails, send_digest_for_business
from app.services.ingest import _uuid, load_sync

logger = logging.getLogger("pulse.api.insights")
router = APIRouter(prefix="/insights", tags=["insights"])


async def _scored(db: AsyncSession, user: CurrentUser):
    biz = await db.get(Business, _uuid(user.business_id))
    sync = await load_sync(db, user.business_id)
    if not sync.customers:
        return [], biz
    return build_scored_customers(sync, vertical=(biz.vertical if biz else "other")), biz


# -- Cohort retention ---------------------------------------------------------


@router.get("/cohorts", response_model=CohortsOut)
async def cohorts(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    months: int = Query(default=12, ge=1, le=insights.MAX_COHORT_MONTHS),
) -> CohortsOut:
    """Retention by acquisition month.

    Each cohort reports its own size and whether that size is large enough to
    read anything into, because a retention curve drawn from four customers per
    cohort looks authoritative and means nothing.
    """
    rows = await insights.load_cohorts(db, business_id=user.business_id, max_months=months)
    max_offset = max(
        (offset for cohort in rows for offset in cohort.active_by_offset), default=0
    )
    return CohortsOut(
        max_offset=max_offset,
        min_meaningful_size=insights.MIN_MEANINGFUL_COHORT,
        cohorts=[
            CohortOut(
                cohort_month=cohort.cohort_month,
                size=cohort.size,
                meaningful=cohort.meaningful,
                retention=[cohort.retention_at(i) for i in range(max_offset + 1)],
                active=[cohort.active_by_offset.get(i, 0) for i in range(max_offset + 1)],
            )
            for cohort in rows
        ],
    )


# -- Score explainability -----------------------------------------------------


@router.get("/customers/{customer_id}/score", response_model=ScoreExplanationOut)
async def explain_customer_score(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> ScoreExplanationOut:
    """Why this customer's score is what it is, factor by factor."""
    scored, biz = await _scored(db, user)
    match = next((s for s in scored if s.customer.external_id == customer_id), None)
    if match is None:
        raise HTTPException(404, "Not found")

    factors = insights.explain_score(match, vertical=(biz.vertical if biz else "other"))
    return ScoreExplanationOut(
        customer_id=customer_id,
        name=(
            f"{match.customer.first_name or ''} {match.customer.last_name or ''}".strip()
            or "Unnamed customer"
        ),
        score=match.result.score,
        band=match.result.band,
        reasons=match.result.reasons,
        recommended_action=match.recommended_action,
        action_reason=match.action_reason,
        confidence=match.confidence,
        factors=[
            ScoreFactorOut(
                key=f.key,
                label=f.label,
                points=f.points,
                share=f.share,
                risk=f.risk,
                detail=f.detail,
            )
            for f in factors
        ],
    )


# -- Segments -----------------------------------------------------------------


@router.get("/segments", response_model=SegmentsOut)
async def list_segments(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> SegmentsOut:
    """Every segment with its current size, so the picker shows real counts."""
    scored, _biz = await _scored(db, user)
    reachable = await insights.contactable_ids(
        db, business_id=user.business_id, channel="email"
    )
    return SegmentsOut(
        segments=[
            SegmentDefinitionOut(
                key=rule.key,
                label=rule.label,
                description=rule.description,
                size=len(insights.apply_segment(rule.key, scored, contactable=reachable)),
            )
            for rule in insights.SEGMENTS
        ]
    )


@router.get("/segments/{segment_key}", response_model=SegmentPreviewOut)
async def preview_segment(
    segment_key: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
    limit: int = Query(default=100, ge=1, le=500),
    channel: str = Query(default="email", pattern="^(email|sms)$"),
    location: str = Query(default="", max_length=120),
) -> SegmentPreviewOut:
    """The customers in one segment, ready to feed into a campaign.

    ``location`` narrows it to one location's customers (Pro), so an owner can
    run a win-back for the store that's actually losing people.
    """
    if segment_key not in insights.SEGMENT_KEYS:
        raise HTTPException(
            404, f"Unknown segment. Available: {', '.join(insights.SEGMENT_KEYS)}"
        )
    scored, _biz = await _scored(db, user)
    if location:
        require_multi_location(ent)
        home = await insights.home_locations(db, business_id=user.business_id)
        scored = insights.filter_by_location(scored, home, location)
    reachable = await insights.contactable_ids(
        db, business_id=user.business_id, channel=channel
    )
    members = insights.apply_segment(segment_key, scored, contactable=reachable)
    members.sort(key=lambda s: s.result.score, reverse=True)

    return SegmentPreviewOut(
        key=segment_key,
        total=len(members),
        # Ids a campaign can be built from directly.
        customer_ids=[s.customer.external_id for s in members[:limit] if s.customer.external_id],
        reachable_on_channel=sum(
            1 for s in members if (s.customer.external_id or "") in reachable
        ),
        channel=channel,
    )


@router.get("/export.csv")
async def export_customers_csv(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    segment: str = Query(default="", description="Optional segment key to filter by"),
) -> Response:
    """The at-risk list as a CSV, because owners live in spreadsheets."""
    if segment and segment not in insights.SEGMENT_KEYS:
        raise HTTPException(
            404, f"Unknown segment. Available: {', '.join(insights.SEGMENT_KEYS)}"
        )
    scored, _biz = await _scored(db, user)
    if segment:
        reachable = await insights.contactable_ids(
            db, business_id=user.business_id, channel="email"
        )
        scored = insights.apply_segment(segment, scored, contactable=reachable)
    scored.sort(key=lambda s: s.result.score, reverse=True)

    buffer = io.StringIO()
    # QUOTE_ALL so a reason containing a comma can't shift columns, and
    # \r\n because that's what Excel expects from a CSV.
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerows(insights.to_csv_rows(scored))

    capture_event(
        "customers_exported_csv",
        distinct_id=user.user_id,
        properties={"segment": segment or "all", "rows": len(scored)},
    )
    filename = f"churnary-{segment or 'customers'}-{insights.utc_today()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -- Multi-location -----------------------------------------------------------


@router.get("/locations", response_model=LocationsOut)
async def locations(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    ent: Entitlements = EntitlementsDep,
) -> LocationsOut:
    """Risk and revenue for each location, worst first (Pro)."""
    require_multi_location(ent)
    scored, _biz = await _scored(db, user)
    home = await insights.home_locations(db, business_id=user.business_id)
    rows = insights.location_breakdown(scored, home)
    return LocationsOut(
        has_location_data=bool(home),
        locations=[
            LocationSummaryOut(
                location=r.location,
                customers=r.customers,
                high_risk=r.high_risk,
                med_risk=r.med_risk,
                low_risk=r.low_risk,
                high_risk_share=r.high_risk_share,
                revenue_at_risk=r.revenue_at_risk,
                annual_value=r.annual_value,
            )
            for r in rows
        ],
    )


# -- Weekly digest ------------------------------------------------------------


@router.get("/digest", response_model=DigestPreviewOut)
async def preview_digest(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    days: int = Query(default=7, ge=1, le=90),
) -> DigestPreviewOut:
    """What this week's digest would say. Sends nothing."""
    digest = await compose_digest(db, business_id=user.business_id, window_days=days)
    await db.commit()
    recipients = await owner_emails(db, business_id=user.business_id)
    facts = digest.facts
    return DigestPreviewOut(
        subject=digest.subject,
        body=digest.body,
        generated_by=digest.generated_by,
        model=digest.model,
        window_days=facts.window_days,
        would_send=facts.is_worth_sending,
        recipients=recipients,
        recovered_count=facts.recovered_count,
        revenue_recovered=facts.revenue_recovered,
        messages_sent=facts.messages_sent,
        awaiting_approval=facts.awaiting_approval,
        high_risk_count=facts.high_risk_count,
        revenue_at_risk=facts.revenue_at_risk,
    )


@router.post("/digest/send", response_model=DigestSendOut)
async def send_digest_now(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
    days: int = Query(default=7, ge=1, le=90),
) -> DigestSendOut:
    """Send the digest to this account's owners now.

    Goes to the account's own addresses, never to customers, so it isn't
    outreach and doesn't touch the per-customer consent flags.
    """
    outcome = await send_digest_for_business(
        db, business_id=user.business_id, window_days=days
    )
    await db.commit()
    messages = {
        "sent": "Digest sent.",
        "nothing_to_report": (
            "Nothing to report for this period, so no email was sent. "
            "An empty weekly summary trains people to ignore the real ones."
        ),
        "no_recipient": (
            "No owner email address is on file for this business, so there was "
            "nowhere to send it."
        ),
        "failed": "The email provider rejected the send. Check the Resend configuration.",
    }
    capture_event(
        "digest_sent_manually", distinct_id=user.user_id, properties={"outcome": outcome}
    )
    return DigestSendOut(
        outcome=outcome, message=messages.get(outcome, outcome), sent=outcome == "sent"
    )
