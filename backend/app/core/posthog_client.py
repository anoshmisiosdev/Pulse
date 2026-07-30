"""Failure-isolated PostHog analytics helpers.

Analytics must never prevent the API from starting or turn a successful
customer action into a 500. Routes use the helpers in this module rather than
calling the SDK directly so SDK upgrades and delivery failures stay contained.
"""

from __future__ import annotations

import atexit
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from posthog import Posthog

logger = logging.getLogger("pulse.posthog")

POSTHOG_DISTINCT_ID_HEADER = "X-PostHog-Distinct-Id"
_MAX_DISTINCT_ID_LENGTH = 200

_client: Posthog | None = None
_atexit_registered = False


def init_posthog(project_api_key: str, host: str, debug: bool = False) -> Posthog | None:
    """Initialize the process-wide client, returning ``None`` on failure."""
    global _atexit_registered, _client

    try:
        client = Posthog(
            project_api_key,
            host=host,
            debug=debug,
            enable_exception_autocapture=True,
        )
    except Exception:
        logger.exception("PostHog initialization failed; analytics disabled")
        _client = None
        return None

    _client = client
    if not _atexit_registered:
        atexit.register(shutdown_posthog)
        _atexit_registered = True
    logger.info("PostHog initialized (host=%s)", host)
    return client


def get_client() -> Posthog | None:
    return _client


def request_distinct_id(request: Request) -> str | None:
    """Return a bounded, printable anonymous ID supplied by the browser."""
    value = request.headers.get(POSTHOG_DISTINCT_ID_HEADER, "").strip()
    if not value or len(value) > _MAX_DISTINCT_ID_LENGTH:
        return None
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        return None
    return value


def capture_event(
    event: str,
    *,
    distinct_id: str | None = None,
    properties: Mapping[str, Any] | None = None,
) -> str | None:
    """Capture one event using the PostHog 7.x keyword-only identity API."""
    client = _client
    if client is None:
        return None

    kwargs: dict[str, Any] = {"properties": dict(properties or {})}
    if distinct_id:
        kwargs["distinct_id"] = distinct_id
    try:
        return client.capture(event, **kwargs)
    except Exception:
        logger.exception("PostHog capture failed (event=%s)", event)
        return None


def identify_user(
    distinct_id: str,
    *,
    properties: Mapping[str, Any],
    anonymous_id: str | None = None,
) -> None:
    """Link pre-login activity to a user and update their person properties."""
    client = _client
    if client is None:
        return

    if anonymous_id and anonymous_id != distinct_id:
        try:
            client.alias(previous_id=anonymous_id, distinct_id=distinct_id)
        except Exception:
            logger.exception("PostHog alias failed")
    try:
        client.set(distinct_id=distinct_id, properties=dict(properties))
    except Exception:
        logger.exception("PostHog person update failed")


def shutdown_posthog() -> None:
    """Flush queued events and stop SDK worker threads exactly once."""
    global _client

    client, _client = _client, None
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:
        logger.exception("PostHog shutdown failed")
