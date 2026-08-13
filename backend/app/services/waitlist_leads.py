"""Lead assignment, email sequencing, and opt-out helpers for the waitlist.

The public endpoint commits first, then calls :func:`enqueue_email_sequence`.
Every delayed task re-loads the row and checks the sent/opt-out timestamps, so
retries and repeat form submissions cannot expand the three-message sequence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_token
from app.models.waitlist import WaitlistSignup
from app.services.senders.resend_client import send_email

logger = logging.getLogger("pulse.waitlist.leads")

EmailStage = Literal["confirmation", "useful_followup", "pilot_invitation"]
_SENT_FIELDS: dict[EmailStage, str] = {
    "confirmation": "confirmation_sent_at",
    "useful_followup": "useful_followup_sent_at",
    "pilot_invitation": "pilot_invitation_sent_at",
}
_PROVIDER_ID_FIELDS: dict[EmailStage, str] = {
    "confirmation": "confirmation_provider_message_id",
    "useful_followup": "useful_followup_provider_message_id",
    "pilot_invitation": "pilot_invitation_provider_message_id",
}
_UNSUBSCRIBE_TOKEN_VERSION = "w1"
_UNSUBSCRIBE_KEY_CONTEXT = b"churnary/waitlist-unsubscribe/v1"


class WaitlistEmailDeliveryError(RuntimeError):
    """A retryable Resend failure."""


def assign_founder(email: str, content: str | None = None) -> str:
    """Honor a founder-coded outreach link, otherwise assign deterministically.

    ``utm_content={founder}_{message_variant}`` is the outreach contract. A
    matching first/full roster name keeps that founder responsible for the lead.
    Hashing the normalized email remains the concurrency-safe fallback.
    """
    roster = settings.waitlist_founder_roster_list
    normalized_content = (content or "").strip().casefold()
    for founder in roster:
        slug = re.sub(r"[^a-z0-9]+", "_", founder.casefold()).strip("_")
        aliases = (slug, slug.split("_", 1)[0])
        if any(
            normalized_content == alias
            or normalized_content.startswith(f"{alias}_")
            or normalized_content.startswith(f"{alias}-")
            for alias in aliases
        ):
            return founder
    digest = hashlib.sha256(email.casefold().encode()).digest()
    return roster[int.from_bytes(digest[:8], "big") % len(roster)]


def _fernet_key_material() -> bytes:
    """Resolve the same 32-byte secret material used by ``core.security``.

    A configured Fernet key is already a urlsafe-base64 encoded 32-byte secret.
    Local development also supports an arbitrary passphrase, which the existing
    Fernet helper hashes; mirror that behavior so rotating ``FERNET_KEY``
    invalidates both OAuth state and unsubscribe signatures together.
    """
    configured = settings.fernet_key.strip()
    if configured:
        try:
            decoded = base64.b64decode(
                configured.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            if len(decoded) == 32:
                return decoded
        except (binascii.Error, UnicodeEncodeError, ValueError):
            pass
    return hashlib.sha256((configured or "pulse-dev-insecure-key").encode()).digest()


def _unsubscribe_signature(signup_id: uuid.UUID) -> bytes:
    payload = _UNSUBSCRIBE_KEY_CONTEXT + b":" + signup_id.bytes
    return hmac.digest(_fernet_key_material(), payload, "sha256")


def _encode_signature(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_signature(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("Invalid signature encoding")
    padded = value + "=" * (-len(value) % 4)
    decoded = base64.b64decode(
        padded.encode("ascii"),
        altchars=b"-_",
        validate=True,
    )
    # Reject alternate encodings that differ only in unused base64 padding
    # bits; one authenticated value should have one canonical URL token.
    if _encode_signature(decoded) != value:
        raise ValueError("Non-canonical signature encoding")
    return decoded


def unsubscribe_token(signup: WaitlistSignup) -> str:
    """Return a stable, authenticated token for this waitlist record.

    Fernet encryption is intentionally randomized, which made the email body
    differ when a Celery task retried with the same Resend idempotency key.
    This versioned HMAC token is deterministic without making UUIDs forgeable.
    """
    signature = _encode_signature(_unsubscribe_signature(signup.id))
    return f"{_UNSUBSCRIBE_TOKEN_VERSION}.{signup.id.hex}.{signature}"


def signup_id_from_unsubscribe_token(token: str) -> uuid.UUID:
    if token.startswith(f"{_UNSUBSCRIBE_TOKEN_VERSION}."):
        try:
            version, raw_id, raw_signature = token.split(".", 2)
            if version != _UNSUBSCRIBE_TOKEN_VERSION or not re.fullmatch(
                r"[0-9a-f]{32}", raw_id
            ):
                raise ValueError
            signup_id = uuid.UUID(hex=raw_id)
            supplied_signature = _decode_signature(raw_signature)
            if not hmac.compare_digest(
                supplied_signature,
                _unsubscribe_signature(signup_id),
            ):
                raise ValueError
            return signup_id
        except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
            raise ValueError("Invalid waitlist unsubscribe token") from exc

    # Accept links created before deterministic tokens were introduced. Fernet
    # already authenticates its ciphertext, so a tampered legacy link is still
    # rejected without weakening the new format.
    try:
        kind, raw_id = decrypt_token(token).split(":", 1)
        if kind != "waitlist":
            raise ValueError
        return uuid.UUID(raw_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid waitlist unsubscribe token") from exc


def _unsubscribe_url(signup: WaitlistSignup) -> str:
    return (
        f"{settings.api_base_url.rstrip('/')}/api/waitlist/unsubscribe"
        f"?token={unsubscribe_token(signup)}"
    )


def _email_copy(signup: WaitlistSignup, stage: EmailStage) -> tuple[str, str, str]:
    greeting = f"Hi {signup.name}," if signup.name else "Hi there,"
    unsubscribe_url = _unsubscribe_url(signup)
    footer = (
        "\n\nYou signed up for Churnary early access. "
        f"Unsubscribe: {unsubscribe_url}"
    )
    if stage == "confirmation":
        subject = "You're on the Churnary early-access list"
        body = (
            f"{greeting}\n\nThanks for joining Churnary early access. "
            "We're building a simpler way for local businesses to spot regulars "
            "who may be drifting and prepare thoughtful win-back outreach.\n\n"
            "We'll send one practical retention note, then one invitation to help "
            "shape the pilot. That's the whole sequence."
        )
    elif stage == "useful_followup":
        subject = "A five-minute retention check for this week"
        body = (
            f"{greeting}\n\nHere's a useful check you can run without any new tools:\n\n"
            "1. List regulars whose usual visit gap has passed.\n"
            "2. Prioritize people whose frequency or spend changed recently.\n"
            "3. Reach out personally with a relevant reason to return—not a blast.\n\n"
            "Churnary is designed to make that same review automatic and keep the "
            "final outreach under your approval."
        )
    else:
        subject = "Help shape the Churnary pilot?"
        body = (
            f"{greeting}\n\nWe're inviting a small group of repeat-visit businesses "
            "to pressure-test Churnary. If you'd be open to a 15-minute feedback "
            "conversation, reply to this email and tell us what kind of business "
            "you run.\n\nNo sales script—we want to learn where retention work is "
            "actually painful."
        )
    return subject, body + footer, unsubscribe_url


async def deliver_email_stage(
    db: AsyncSession,
    signup_id: uuid.UUID,
    stage: EmailStage,
) -> dict[str, str]:
    """Send one stage at most once and never after an opt-out.

    ``FOR UPDATE`` serializes duplicate Celery deliveries. Resend's idempotency
    key covers the narrower failure window between provider acceptance and our
    database commit.
    """
    sent_field = _SENT_FIELDS[stage]
    signup = (
        await db.execute(
            select(WaitlistSignup)
            .where(WaitlistSignup.id == signup_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if signup is None:
        return {"status": "missing", "stage": stage}
    if signup.email_opted_out_at is not None:
        return {"status": "opted_out", "stage": stage}
    if getattr(signup, sent_field) is not None:
        return {"status": "already_sent", "stage": stage}

    subject, body, unsubscribe_url = _email_copy(signup, stage)
    result = await send_email(
        signup.email,
        subject,
        body,
        idempotency_key=f"waitlist/{signup.id}/{stage}",
        headers={"List-Unsubscribe": f"<{unsubscribe_url}>"},
    )
    if not result.ok:
        raise WaitlistEmailDeliveryError(result.error or "resend_delivery_failed")
    setattr(signup, sent_field, datetime.now(UTC))
    setattr(signup, _PROVIDER_ID_FIELDS[stage], result.provider_message_id)
    return {"status": "sent", "stage": stage}


def enqueue_email_sequence(signup_id: uuid.UUID) -> dict[str, bool]:
    """Best-effort, post-commit Celery scheduling; never fail the HTTP signup."""
    if not settings.waitlist_email_sequence_enabled or not settings.resend_configured:
        return {stage: False for stage in _SENT_FIELDS}

    # Import lazily so API processes that do not send mail need not initialize
    # the Celery task module while importing routes.
    from app.workers.celery_app import send_waitlist_email

    delays = {
        "confirmation": 0,
        "useful_followup": max(1, settings.waitlist_followup_delay_days) * 86_400,
        "pilot_invitation": max(1, settings.waitlist_pilot_invite_delay_days) * 86_400,
    }
    scheduled: dict[str, bool] = {}
    for stage, countdown in delays.items():
        try:
            send_waitlist_email.apply_async(
                args=[str(signup_id), stage],
                countdown=countdown,
            )
            scheduled[stage] = True
        except Exception:
            scheduled[stage] = False
            logger.exception(
                "Waitlist email could not be queued (signup_id=%s stage=%s)",
                signup_id,
                stage,
            )
    return scheduled
