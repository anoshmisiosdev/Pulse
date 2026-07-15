"""SMS delivery via Twilio.

Degrades like every other external call in this codebase: when Twilio isn't
configured, or the send fails, this logs and returns a failure result rather
than raising — the caller (the automation dispatcher, or the manual-approve
API) decides what "not sent" means for a CampaignSend row instead of the
whole dispatch run crashing over one bad number.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.senders import SendResult

logger = logging.getLogger("pulse.senders.twilio")


def _send_sync(to: str, body: str) -> SendResult:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    try:
        message = client.messages.create(to=to, from_=settings.twilio_from_number, body=body)
    except TwilioRestException as exc:
        return SendResult(ok=False, error=str(exc))
    if message.error_code:
        return SendResult(
            ok=False, error=f"{message.status} ({message.error_code}): {message.error_message}"
        )
    return SendResult(ok=True, provider_message_id=message.sid)


async def send_sms(to: str, body: str) -> SendResult:
    if not settings.twilio_configured:
        logger.warning("Twilio not configured — SMS to %s not sent", to)
        return SendResult(ok=False, error="twilio_not_configured")
    try:
        return await asyncio.to_thread(_send_sync, to, body)
    except Exception as exc:  # network / SDK errors outside TwilioRestException
        logger.warning("SMS send failed: %s", exc)
        return SendResult(ok=False, error=str(exc))
