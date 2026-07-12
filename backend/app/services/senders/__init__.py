"""Outbound message delivery (Twilio SMS, Resend email). Shared result shape so
the automation dispatcher can treat both channels identically."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
