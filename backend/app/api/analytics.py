"""Public collection endpoint for the marketing landing-page funnel.

The browser never receives the PostHog project token. It sends a small,
strictly validated first-party event here and the API forwards it through the
same failure-isolated PostHog client used by authenticated product events.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.core.posthog_client import capture_event, request_distinct_id
from app.schemas.analytics import LandingMetricIn

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/landing", status_code=status.HTTP_204_NO_CONTENT)
async def capture_landing_metric(payload: LandingMetricIn, request: Request) -> Response:
    """Queue one allow-listed, PII-free landing event."""
    properties = payload.model_dump(exclude={"event"}, exclude_none=True)
    properties.update({"surface": "landing", "metric_version": 1})
    capture_event(
        payload.event,
        distinct_id=request_distinct_id(request),
        properties=properties,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
