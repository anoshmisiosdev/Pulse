"""Retry preset for outbound HTTP calls.

3 attempts, exponential backoff, transient failures only (network errors and
5xx). 4xx are never retried — they're the caller's bug or the user's input.

Usage: decorate a small inner coroutine that makes exactly one request and
raises ``HTTPStatusError`` on 5xx (``resp.raise_for_status()``).
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):  # connect/read timeout, DNS, reset
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


retry_transient = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
