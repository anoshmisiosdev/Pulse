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


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    now: int | None = None,
    tolerance_seconds: int = _TOLERANCE_SECONDS,
) -> bool:
    """Verify Stripe's ``t=…,v1=…`` signature against the unmodified body."""
    if not payload or not signature_header or not secret:
        return False
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        key, sep, value = item.strip().partition("=")
        if sep:
            parts.setdefault(key, []).append(value)
    try:
        timestamp = int((parts.get("t") or [""])[0])
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False
    signed = str(timestamp).encode() + b"." + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, value) for value in parts.get("v1", []))


def verify_square_signature(
    payload: bytes,
    signature_header: str,
    signature_key: str,
    notification_url: str,
) -> bool:
    """Verify Square's HMAC-SHA256 signature in constant time."""
    if not payload or not signature_header or not signature_key or not notification_url:
        return False
    signed = notification_url.encode() + payload
    expected = base64.b64encode(
        hmac.new(signature_key.encode(), signed, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)
