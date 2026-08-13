"""Outbound Discord messages for newly identified marketing visitors."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.visitor import VisitorProfile

logger = logging.getLogger("pulse.discord")
DISCORD_API_BASE = "https://discord.com/api/v10"
_REQUEST_TIMEOUT_SECONDS = 6.0


class DiscordNotConfiguredError(RuntimeError):
    """No safe Discord delivery transport is configured."""


class DiscordDeliveryError(RuntimeError):
    """Discord rejected or could not receive a message."""


@dataclass(frozen=True)
class VisitorAlert:
    visitor_id: uuid.UUID
    full_name: str | None
    job_title: str | None
    company_name: str | None
    company_domain: str | None
    primary_email: str | None
    linkedin_url: str | None
    city: str | None
    state: str | None
    identity_level: str
    intent_score: int
    last_path: str | None
    source_provider: str
    tags: tuple[str, ...]
    last_seen_at: datetime

    @classmethod
    def from_profile(cls, profile: VisitorProfile) -> VisitorAlert:
        return cls(
            visitor_id=profile.id,
            full_name=profile.full_name,
            job_title=profile.job_title,
            company_name=profile.company_name,
            company_domain=profile.company_domain,
            primary_email=profile.primary_email,
            linkedin_url=profile.linkedin_url,
            city=profile.city,
            state=profile.state,
            identity_level=profile.identity_level,
            intent_score=profile.intent_score,
            last_path=profile.last_path,
            source_provider=profile.source_provider,
            tags=tuple(profile.tags or []),
            last_seen_at=profile.last_seen_at,
        )


def _bounded(value: str | None, maximum: int = 1024) -> str:
    text = (value or "").strip()
    if len(text) <= maximum:
        return text
    return f"{text[: maximum - 1]}…"


def _safe_https_url(value: str | None) -> str | None:
    try:
        parsed = urlparse(value or "")
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return value


def _validated_webhook_url(value: str) -> str:
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise DiscordNotConfiguredError("Discord webhook URL is invalid") from exc
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or not (hostname == "discord.com" or hostname.endswith(".discord.com"))
        or not parsed.path.startswith("/api/webhooks/")
    ):
        raise DiscordNotConfiguredError(
            "Discord webhook URL must be an HTTPS discord.com /api/webhooks URL"
        )
    return value


def _dashboard_url() -> str | None:
    origin = settings.frontend_origin.rstrip("/")
    return _safe_https_url(f"{origin}/visitors")


def _alert_payload(alert: VisitorAlert, *, repeat_visitor: bool) -> dict:
    high_intent = alert.intent_score >= 60
    name = alert.full_name or alert.company_name or "Identified visitor"
    company_line = " · ".join(
        part for part in (alert.job_title, alert.company_name) if part
    )
    location = ", ".join(part for part in (alert.city, alert.state) if part)
    fields: list[dict[str, object]] = [
        {
            "name": "Intent",
            "value": f"**{alert.intent_score}/100** · "
            f"{'High intent' if high_intent else 'New match'}",
            "inline": True,
        },
        {
            "name": "Last page",
            "value": _bounded(alert.last_path or "/", 400),
            "inline": True,
        },
    ]
    if location:
        fields.append(
            {"name": "Location", "value": _bounded(location, 400), "inline": True}
        )
    if alert.company_domain:
        fields.append(
            {
                "name": "Company domain",
                "value": _bounded(alert.company_domain, 400),
                "inline": True,
            }
        )
    if alert.tags:
        fields.append(
            {
                "name": "Signals",
                "value": _bounded(" · ".join(alert.tags), 900),
                "inline": False,
            }
        )
    if settings.discord_include_email and alert.primary_email:
        fields.append(
            {
                "name": "Business email",
                "value": _bounded(alert.primary_email, 320),
                "inline": False,
            }
        )

    links: list[str] = []
    linkedin = _safe_https_url(alert.linkedin_url)
    dashboard = _dashboard_url()
    if linkedin:
        links.append(f"[LinkedIn]({linkedin})")
    if dashboard:
        links.append(f"[Open Recent Visitors]({dashboard})")
    if links:
        fields.append({"name": "Review", "value": " · ".join(links), "inline": False})

    return {
        "username": "Churnary Visitor Signals",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": _bounded(
                    f"{'High-intent' if high_intent else 'New'} RB2B match · {name}",
                    256,
                ),
                "description": _bounded(
                    company_line
                    or f"{alert.identity_level.title()}-level identity from RB2B",
                    4096,
                ),
                "color": 0x0F766E if high_intent else 0xC86442,
                "fields": fields[:25],
                "footer": {
                    "text": (
                        f"{'Repeat visit' if repeat_visitor else 'First delivery'} · "
                        "Identity matches are signals, not proof"
                    )
                },
                "timestamp": alert.last_seen_at.isoformat(),
            }
        ],
    }


async def deliver_discord_message(payload: dict) -> str:
    """Deliver a bounded message through a webhook or the configured bot channel."""
    headers = {"User-Agent": "Churnary-Visitor-Bot/1.0"}
    if settings.discord_webhook_url:
        url = _validated_webhook_url(settings.discord_webhook_url)
        transport = "channel webhook"
    elif settings.discord_bot_token and settings.discord_alert_channel_id:
        channel_id = settings.discord_alert_channel_id.strip()
        if not channel_id.isdigit():
            raise DiscordNotConfiguredError("Discord alert channel ID is invalid")
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers["Authorization"] = f"Bot {settings.discord_bot_token}"
        transport = "bot channel"
        # ``username`` is accepted by incoming webhooks, not Create Message.
        payload = {key: value for key, value in payload.items() if key != "username"}
    else:
        raise DiscordNotConfiguredError(
            "Configure DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN + "
            "DISCORD_ALERT_CHANNEL_ID"
        )

    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise DiscordDeliveryError("Discord could not be reached") from exc
    if response.status_code >= 400:
        logger.warning(
            "Discord delivery rejected (transport=%s status=%s)",
            transport,
            response.status_code,
        )
        raise DiscordDeliveryError(
            f"Discord rejected the message with status {response.status_code}"
        )
    return transport


async def send_visitor_alert(alert: VisitorAlert, repeat_visitor: bool = False) -> bool:
    """Best-effort notification; provider ingestion never depends on Discord."""
    threshold = min(100, max(0, settings.discord_alert_min_intent_score))
    if alert.intent_score < threshold or not settings.discord_alerts_configured:
        return False
    try:
        transport = await deliver_discord_message(
            _alert_payload(alert, repeat_visitor=repeat_visitor)
        )
    except (DiscordNotConfiguredError, DiscordDeliveryError):
        logger.exception(
            "Discord visitor alert failed (visitor_id=%s)", alert.visitor_id
        )
        return False
    logger.info(
        "Discord visitor alert delivered (visitor_id=%s transport=%s)",
        alert.visitor_id,
        transport,
    )
    return True


async def send_discord_test_alert() -> str:
    payload = {
        "username": "Churnary Visitor Signals",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "Discord connection is ready",
                "description": (
                    "New consented RB2B matches will appear here when they meet "
                    "the configured intent threshold."
                ),
                "color": 0x0F766E,
                "fields": [
                    {
                        "name": "Privacy",
                        "value": "Business email is hidden unless explicitly enabled.",
                        "inline": False,
                    }
                ],
                "footer": {"text": "Churnary · Test notification"},
            }
        ],
    }
    return await deliver_discord_message(payload)
