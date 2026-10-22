"""Best-effort outbound notifications to the operator's own n8n instance.

n8n only ever receives events Pulse already decided to send — it's a place to
build extra branching (Slack/SMS, booking links, review requests) without more
Python, not a decision-maker. It never sees anyone compliance.py hasn't
already cleared, and delivery failures never block the caller.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.core.http_retry import retry_transient

logger = logging.getLogger("pulse.n8n")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEADERS = {"Content-Type": "application/json"}



async def notify(
    webhook_url: str,
    event: str,
    payload: dict,
    http_client: httpx.AsyncClient | None = None,
) -> bool:
    """POST {"event": ..., **payload} to an n8n webhook URL. Never raises.

    Serializes with default=str rather than httpx's json= — call sites build
    these payloads from ORM rows and dataclasses, and a stray UUID/datetime/
    Decimal (customer.id, sent_at, ...) would otherwise raise TypeError before
    a single byte goes out, defeating "never raises" for the one caller that
    forgot to stringify a field. Stringifying here covers every caller, once.
    """
    if not webhook_url:
        return False
    body = json.dumps(
        {"event": event, **payload}, default=str, separators=(",", ":")
    ).encode()

    @retry_transient
    async def _post() -> httpx.Response:
        if http_client is not None:
            response = await http_client.post(webhook_url, content=body, headers=_HEADERS)
        else:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(webhook_url, content=body, headers=_HEADERS)
        response.raise_for_status()
        return response

    try:
        await _post()
    except httpx.HTTPError:
        logger.warning("n8n webhook delivery failed (event=%s)", event, exc_info=True)
        return False
    return True
