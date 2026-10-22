"""Outbound webhooks: signed POSTs to URLs an owner registers.

**The security problem this module exists to manage is server-side request
forgery.** The URL is chosen by a tenant and fetched by our server, which runs
inside AWS. Unchecked, a tenant could register ``http://169.254.169.254/...``
(the instance metadata service, which hands out credentials), an RDS endpoint,
or anything else reachable from inside the VPC, and read the response back
through the delivery log. So:

* the hostname is resolved and **every** returned address must be public
  (``is_global``), which rules out loopback, RFC1918, link-local (including the
  metadata address), CGNAT, multicast and reserved ranges, and IPv4-mapped IPv6
  forms of all of those;
* the check runs **at registration and again at every delivery**, so a record
  that was public when saved and later re-pointed inside the VPC is caught;
* redirects are **not followed**, so a public URL can't bounce us inward;
* only the status code is stored, **never the response body**, so even a
  successful request can't be used to read anything back.

What remains is the DNS-rebinding window between our resolution and httpx's
own connect, a few milliseconds per delivery. Closing it fully would mean
pinning the connection to the vetted IP, which breaks TLS hostname
verification; it's noted rather than pretended away.

Delivery uses the outbox in ``models/webhooks.py``: emitting only inserts rows,
and ``deliver_pending`` (driven by Celery) does the network work with backoff.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_token, encrypt_token
from app.models import WebhookDelivery, WebhookEndpoint
from app.models.webhooks import WEBHOOK_EVENTS

logger = logging.getLogger("pulse.webhooks.outbound")

SIGNATURE_HEADER = "Churnary-Signature"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# Delay before attempt N+1, by attempts made so far. Six attempts over ~8 hours.
_BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)
MAX_ATTEMPTS = len(_BACKOFF_SECONDS) + 1
# Stop hammering an endpoint that's plainly gone; the owner re-enables it.
DISABLE_AFTER_CONSECUTIVE_FAILURES = 25
_MAX_ERROR_CHARS = 500


class WebhookURLError(ValueError):
    """The URL can't be used as a webhook target. Message is owner-facing."""


# -- SSRF guard ---------------------------------------------------------------


def _resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address ``host`` resolves to. Module-level so tests can stub DNS."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos]


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # ::ffff:127.0.0.1 must be judged as 127.0.0.1, not as an IPv6 address.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def validate_url(url: str) -> str:
    """Return the normalised URL, or raise WebhookURLError.

    Called at registration and again before every delivery.
    """
    url = (url or "").strip()
    if len(url) > 2048:
        raise WebhookURLError("That URL is too long.")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise WebhookURLError("That isn't a valid URL.") from exc

    allowed = {"https"} if settings.is_production else {"https", "http"}
    if parts.scheme not in allowed:
        raise WebhookURLError(
            "Webhook URLs must use https." if settings.is_production
            else "Webhook URLs must start with https:// (or http:// in development)."
        )
    if parts.username or parts.password:
        raise WebhookURLError("Put credentials in a header on your side, not in the URL.")
    host = parts.hostname
    if not host:
        raise WebhookURLError("That URL has no host.")
    try:
        port = parts.port  # raises on a malformed port
    except ValueError as exc:
        raise WebhookURLError("That URL's port isn't valid.") from exc
    del port

    try:
        addresses = _resolve_ips(host)
    except (socket.gaierror, UnicodeError, ValueError) as exc:
        raise WebhookURLError(f"Couldn't find the host {host!r}.") from exc
    if not addresses:
        raise WebhookURLError(f"Couldn't find the host {host!r}.")
    if not all(_is_public(ip) for ip in addresses):
        # One message whatever the address was: don't tell a prober which
        # internal ranges exist.
        raise WebhookURLError(
            "That address isn't reachable from the public internet, so it can't "
            "receive webhooks."
        )
    return url


# -- Signing ------------------------------------------------------------------


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """``t=<unix>,v1=<hex hmac-sha256 of "<t>.<body>">`` -- Stripe's scheme, so a
    receiver can verify with code they've likely already written."""
    ts = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


# -- Endpoints ----------------------------------------------------------------


@dataclass
class CreatedEndpoint:
    endpoint: WebhookEndpoint
    secret: str  # shown once


def _clean_events(events: list[str] | None) -> list[str]:
    chosen = sorted({e for e in (events or []) if e in WEBHOOK_EVENTS and e != "webhook.test"})
    return chosen


async def create_endpoint(
    db: AsyncSession,
    *,
    business_id: str,
    url: str,
    events: list[str] | None = None,
    description: str | None = None,
) -> CreatedEndpoint:
    url = validate_url(url)
    unknown = [e for e in (events or []) if e not in WEBHOOK_EVENTS]
    if unknown:
        raise WebhookURLError(f"Unknown event(s): {', '.join(unknown)}.")
    secret = new_secret()
    endpoint = WebhookEndpoint(
        business_id=uuid.UUID(business_id),
        url=url,
        description=(description or "").strip()[:255] or None,
        secret_enc=encrypt_token(secret),
        events=_clean_events(events),
        enabled=True,
    )
    db.add(endpoint)
    await db.flush()
    return CreatedEndpoint(endpoint=endpoint, secret=secret)


def subscribed(endpoint: WebhookEndpoint, event_type: str) -> bool:
    if event_type == "webhook.test":
        return True
    return not endpoint.events or event_type in endpoint.events


# -- Emitting -----------------------------------------------------------------


async def emit(
    db: AsyncSession,
    *,
    business_id: str | uuid.UUID,
    event_type: str,
    data: dict,
    only_endpoint_id: uuid.UUID | None = None,
) -> int:
    """Queue ``event_type`` for every subscribed endpoint. Returns rows queued.

    Never raises: a webhook must never be the reason a recovery or a campaign
    approval fails to record. Flushes into the caller's transaction, so the
    event and the thing it describes commit together.

    Skipped entirely when the plan doesn't include automation or isn't active
    -- the same gate as automated sending. (Checking status here matters; an
    earlier bug on this branch gated features on tier alone and let cancelled
    plans keep their paid features.)
    """
    try:
        from app.billing.store import entitlements

        bid = business_id if isinstance(business_id, uuid.UUID) else uuid.UUID(str(business_id))
        if event_type != "webhook.test":
            ent = await entitlements(db, business_id=str(bid))
            if not (ent.active and ent.automation):
                return 0

        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.business_id == bid, WebhookEndpoint.enabled.is_(True)
        )
        if only_endpoint_id is not None:
            stmt = stmt.where(WebhookEndpoint.id == only_endpoint_id)
        endpoints = [e for e in (await db.execute(stmt)).scalars() if subscribed(e, event_type)]
        if not endpoints:
            return 0

        event_id = f"evt_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        payload = {
            "id": event_id,
            "type": event_type,
            "created": now.isoformat(),
            "data": data,
        }
        for endpoint in endpoints:
            db.add(
                WebhookDelivery(
                    business_id=bid,
                    endpoint_id=endpoint.id,
                    event_type=event_type,
                    event_id=event_id,
                    payload=payload,
                    status="pending",
                    attempts=0,
                    next_attempt_at=now,
                )
            )
        await db.flush()
        return len(endpoints)
    except Exception as exc:  # see docstring: never break the caller
        logger.warning("could not queue webhook %s: %s", event_type, exc)
        return 0


# -- Delivering ---------------------------------------------------------------


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def deliver_one(
    db: AsyncSession, delivery: WebhookDelivery, *, client: httpx.AsyncClient
) -> str:
    """Attempt one delivery. Returns its new status. Never raises."""
    endpoint = await db.get(WebhookEndpoint, delivery.endpoint_id)
    now = datetime.now(UTC)
    if endpoint is None or not endpoint.enabled:
        delivery.status = "failed"
        delivery.last_error = "endpoint disabled or deleted"
        delivery.next_attempt_at = None
        return delivery.status

    delivery.attempts += 1
    error: str | None = None
    status_code: int | None = None
    try:
        # Re-checked at send time: DNS may have changed since registration.
        url = validate_url(endpoint.url)
        body = json.dumps(delivery.payload, separators=(",", ":"), default=str).encode()
        resp = await client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Churnary-Webhooks/1",
                SIGNATURE_HEADER: sign(decrypt_token(endpoint.secret_enc), body),
                "Churnary-Event": delivery.event_type,
                "Churnary-Event-Id": delivery.event_id,
                "Churnary-Delivery": str(delivery.id),
            },
            follow_redirects=False,
            timeout=_TIMEOUT,
        )
        status_code = resp.status_code
        if not 200 <= resp.status_code < 300:
            # Deliberately not resp.text: never store or surface what the
            # target returned (see the module docstring on SSRF).
            error = f"HTTP {resp.status_code}"
    except WebhookURLError as exc:
        error = str(exc)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}"
    except Exception as exc:  # decrypt failure etc. — record, don't crash the tick
        error = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]

    delivery.response_status = status_code
    if error is None:
        delivery.status = "delivered"
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        delivery.last_error = None
        endpoint.last_success_at = now
        endpoint.consecutive_failures = 0
        return delivery.status

    delivery.last_error = error[:_MAX_ERROR_CHARS]
    endpoint.last_failure_at = now
    endpoint.consecutive_failures = (endpoint.consecutive_failures or 0) + 1
    if endpoint.consecutive_failures >= DISABLE_AFTER_CONSECUTIVE_FAILURES:
        endpoint.enabled = False
        logger.warning(
            "disabled webhook endpoint %s after %s consecutive failures",
            endpoint.id,
            endpoint.consecutive_failures,
        )
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        delivery.status = "pending"
        delivery.next_attempt_at = now + timedelta(
            seconds=_BACKOFF_SECONDS[delivery.attempts - 1]
        )
    return delivery.status


async def deliver_pending(
    db: AsyncSession,
    *,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
    limit: int = 200,
    business_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Deliver everything that's due. Caller commits."""
    now = now or datetime.now(UTC)
    stmt = (
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(limit)
    )
    if business_id is not None:
        stmt = stmt.where(WebhookDelivery.business_id == business_id)
    due = list((await db.execute(stmt)).scalars().all())

    counts = {"delivered": 0, "pending": 0, "failed": 0}
    if not due:
        return counts
    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        for delivery in due:
            outcome = await deliver_one(db, delivery, client=client)
            counts[outcome] = counts.get(outcome, 0) + 1
            await db.flush()
    finally:
        if owns_client:
            await client.aclose()
    return counts
