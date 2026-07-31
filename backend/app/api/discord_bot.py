"""Signed Discord interactions endpoint for private visitor commands."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.visitor import VisitorProfile

router = APIRouter(prefix="/discord", tags=["discord"])
_MAX_BODY_BYTES = 64_000
_EPHEMERAL = 1 << 6
_ADMINISTRATOR = 1 << 3
_MANAGE_GUILD = 1 << 5


def _response(*, content: str | None = None, embeds: list[dict] | None = None) -> dict:
    data: dict[str, Any] = {
        "flags": _EPHEMERAL,
        "allowed_mentions": {"parse": []},
    }
    if content:
        data["content"] = content[:2000]
    if embeds:
        data["embeds"] = embeds[:10]
    return {"type": 4, "data": data}


def _verify_signature(body: bytes, signature: str, timestamp: str) -> None:
    if not settings.discord_public_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Discord interactions are not configured",
        )
    try:
        request_time = int(timestamp)
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(settings.discord_public_key)
        )
        public_key.verify(bytes.fromhex(signature), timestamp.encode() + body)
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Discord signature") from exc
    if abs(time.time() - request_time) > 300:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Stale Discord interaction")


def _member_is_allowed(payload: dict[str, Any]) -> bool:
    if settings.discord_guild_id and str(payload.get("guild_id") or "") != (
        settings.discord_guild_id
    ):
        return False
    member = payload.get("member") or {}
    try:
        permissions = int(member.get("permissions") or "0")
    except (TypeError, ValueError):
        permissions = 0
    if permissions & (_ADMINISTRATOR | _MANAGE_GUILD):
        return True
    member_roles = {str(role) for role in member.get("roles") or []}
    return bool(member_roles & settings.discord_allowed_role_id_set)


def _subcommand(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = payload.get("data") or {}
    options = data.get("options") or []
    if not options:
        return "summary", {}
    selected = options[0] if isinstance(options[0], dict) else {}
    values = {
        str(item.get("name")): item.get("value")
        for item in selected.get("options") or []
        if isinstance(item, dict)
    }
    return str(selected.get("name") or "summary"), values


async def _count(
    db: AsyncSession,
    cutoff: datetime,
    *criteria,
) -> int:
    value = (
        await db.execute(
            select(func.count(VisitorProfile.id)).where(
                VisitorProfile.suppressed.is_(False),
                VisitorProfile.last_seen_at >= cutoff,
                *criteria,
            )
        )
    ).scalar_one()
    return int(value)


async def _summary_embed(db: AsyncSession, values: dict[str, Any]) -> dict:
    try:
        days = min(365, max(1, int(values.get("days") or 30)))
    except (TypeError, ValueError):
        days = 30
    cutoff = datetime.now(UTC) - timedelta(days=days)
    total = await _count(db, cutoff)
    identified = await _count(db, cutoff, VisitorProfile.identity_level != "anonymous")
    provider = await _count(
        db,
        cutoff,
        VisitorProfile.source_provider == "rb2b",
    )
    high_intent = await _count(db, cutoff, VisitorProfile.intent_score >= 60)
    conversions = await _count(
        db,
        cutoff,
        VisitorProfile.waitlist_signup_id.is_not(None),
    )
    rate = round(identified / total * 100, 1) if total else 0
    return {
        "title": f"Visitor summary · {days} days",
        "color": 0x0F766E,
        "fields": [
            {"name": "Unique visitors", "value": str(total), "inline": True},
            {
                "name": "Identified",
                "value": f"{identified} · {rate}%",
                "inline": True,
            },
            {"name": "RB2B matches", "value": str(provider), "inline": True},
            {"name": "High intent", "value": str(high_intent), "inline": True},
            {"name": "Waitlist conversions", "value": str(conversions), "inline": True},
        ],
        "footer": {"text": "Private Churnary platform analytics"},
    }


async def _recent_embed(db: AsyncSession, values: dict[str, Any]) -> dict:
    try:
        limit = min(10, max(1, int(values.get("limit") or 5)))
    except (TypeError, ValueError):
        limit = 5
    profiles = list(
        (
            await db.execute(
                select(VisitorProfile)
                .where(
                    VisitorProfile.suppressed.is_(False),
                    VisitorProfile.identity_level != "anonymous",
                )
                .order_by(
                    VisitorProfile.intent_score.desc(),
                    VisitorProfile.last_seen_at.desc(),
                )
                .limit(limit)
            )
        ).scalars()
    )
    if not profiles:
        return {
            "title": "Recent identified visitors",
            "description": "No identified visitors have arrived yet.",
            "color": 0xC86442,
        }

    fields: list[dict[str, object]] = []
    for profile in profiles:
        name = profile.full_name or profile.company_name or "Identified visitor"
        detail = " · ".join(
            part for part in (profile.job_title, profile.company_name) if part
        )
        lines = [
            detail or profile.identity_level.title(),
            f"Intent **{profile.intent_score}/100** · `{profile.last_path or '/'}`",
            f"Seen <t:{int(profile.last_seen_at.timestamp())}:R>",
        ]
        if profile.linkedin_url and profile.linkedin_url.startswith("https://"):
            lines.append(f"[LinkedIn]({profile.linkedin_url})")
        if settings.discord_include_email and profile.primary_email:
            lines.append(profile.primary_email)
        fields.append(
            {
                "name": name[:256],
                "value": "\n".join(lines)[:1024],
                "inline": False,
            }
        )
    return {
        "title": "Highest-intent recent visitors",
        "color": 0x0F766E,
        "fields": fields,
        "footer": {"text": "Identity matches are signals, not proof"},
    }


def _status_embed() -> dict:
    def state(ready: bool) -> str:
        return "Ready" if ready else "Needs configuration"

    return {
        "title": "RB2B + Discord status",
        "color": 0x0F766E if settings.discord_alerts_configured else 0xC86442,
        "fields": [
            {
                "name": "RB2B webhook",
                "value": state(bool(settings.rb2b_webhook_secret)),
                "inline": True,
            },
            {
                "name": "Discord alerts",
                "value": state(settings.discord_alerts_configured),
                "inline": True,
            },
            {
                "name": "Discord commands",
                "value": state(settings.discord_commands_configured),
                "inline": True,
            },
            {
                "name": "Alert threshold",
                "value": f"{min(100, max(0, settings.discord_alert_min_intent_score))}/100",
                "inline": True,
            },
            {
                "name": "Business email in Discord",
                "value": "Included" if settings.discord_include_email else "Hidden",
                "inline": True,
            },
        ],
        "footer": {"text": "Use /churnary recent or /churnary summary"},
    }


@router.post("/interactions")
async def discord_interactions(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    try:
        content_length = int(request.headers.get("content-length", "0") or "0")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Content-Length") from exc
    if content_length > _MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Payload too large")
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Payload too large")
    _verify_signature(body, signature, timestamp)
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "JSON object required")
    if settings.discord_application_id and str(payload.get("application_id") or "") != (
        settings.discord_application_id
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong Discord application")

    interaction_type = payload.get("type")
    if interaction_type == 1:
        return {"type": 1}
    if interaction_type != 2:
        return _response(content="This Discord interaction is not supported.")
    if not _member_is_allowed(payload):
        return _response(content="You do not have access to visitor intelligence.")
    if str((payload.get("data") or {}).get("name") or "") != "churnary":
        return _response(content="Unknown command.")

    command, values = _subcommand(payload)
    if command == "recent":
        embed = await _recent_embed(db, values)
    elif command == "status":
        embed = _status_embed()
    else:
        embed = await _summary_embed(db, values)
    return _response(embeds=[embed])
