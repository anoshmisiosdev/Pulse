"""Webhook signature verification shared by inbound provider callbacks.

Resend signs webhooks the Svix way (svix-id/svix-timestamp/svix-signature
headers, HMAC-SHA256). No svix package needed — it's a short, well-documented
algorithm and adding a dependency for ~15 lines of HMAC isn't worth it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

_TOLERANCE_SECONDS = 300  # reject webhooks older than this (replay protection)


def verify_svix_signature(
    secret: str,
    payload: bytes,
    *,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    now: float | None = None,
) -> bool:
    """Verify a Svix-signed webhook (used by Resend). ``secret`` is the
    "whsec_..." value shown when the webhook endpoint was created."""
    if not (secret and svix_id and svix_timestamp and svix_signature):
        return False

    try:
        ts = int(svix_timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts) > _TOLERANCE_SECONDS:
        return False

    raw_secret = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw_secret)
    except (ValueError, TypeError):
        return False

    signed_content = f"{svix_id}.{svix_timestamp}.".encode() + payload
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()

    for candidate in svix_signature.split():
        _, _, sig = candidate.partition(",")
        if hmac.compare_digest(sig or candidate, expected):
            return True
    return False
