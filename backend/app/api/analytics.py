"""Public collection endpoint for the marketing landing-page funnel.

The browser never receives the PostHog project token. It sends a small,
strictly validated first-party event here and the API forwards it through the
same failure-isolated PostHog client used by authenticated product events.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.posthog_client import capture_event, request_distinct_id
from app.schemas.analytics import LandingMetricIn
from app.visitor_intelligence.service import record_browser_event, request_session_id

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("pulse.analytics")


@router.post("/landing", status_code=status.HTTP_204_NO_CONTENT)
async def capture_landing_metric(
    payload: LandingMetricIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Queue one allow-listed, PII-free landing event."""
    properties = payload.model_dump(exclude={"event"}, exclude_none=True)
    properties.update({"surface": "landing", "metric_version": 1})
    distinct_id = request_distinct_id(request)
    try:
        await record_browser_event(
            db,
            anonymous_id=distinct_id,
            session_id=request_session_id(request),
            event_name=payload.event,
            properties=properties,
        )
    except Exception:
        await db.rollback()
        logger.exception("First-party visitor event persistence failed")
    if distinct_id:
        capture_event(
            payload.event,
            distinct_id=distinct_id,
            properties=properties,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
