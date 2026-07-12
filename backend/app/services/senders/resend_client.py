"""Email delivery via Resend. Plain text only for now — the campaign generator
(app/campaigns/generator.py) produces plain-text bodies, not HTML."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.senders import SendResult

logger = logging.getLogger("pulse.senders.resend")


def _send_sync(to: str, subject: str, text: str) -> SendResult:
    import resend

    resend.api_key = settings.resend_api_key
    try:
        response = resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": to,
                "subject": subject,
                "text": text,
            }
        )
    except Exception as exc:  # resend raises its own exception hierarchy
        return SendResult(ok=False, error=str(exc))
    return SendResult(ok=True, provider_message_id=response.get("id"))


async def send_email(to: str, subject: str, text: str) -> SendResult:
    if not settings.resend_configured:
        logger.warning("Resend not configured — email to %s not sent", to)
        return SendResult(ok=False, error="resend_not_configured")
    try:
        return await asyncio.to_thread(_send_sync, to, subject, text)
    except Exception as exc:
        logger.warning("Email send failed: %s", exc)
        return SendResult(ok=False, error=str(exc))
