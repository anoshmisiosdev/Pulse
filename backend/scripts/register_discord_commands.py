"""Register Churnary's Discord commands in one guild (or globally).

Run from ``backend/`` after configuring the Discord values in the environment:

    uv run python scripts/register_discord_commands.py
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.discord_bot.commands import DISCORD_COMMANDS

DISCORD_API_BASE = "https://discord.com/api/v10"
BOT_PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 14)  # view, send, embed


def _require(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


async def main() -> None:
    application_id = _require(settings.discord_application_id, "DISCORD_APPLICATION_ID")
    bot_token = _require(settings.discord_bot_token, "DISCORD_BOT_TOKEN")
    guild_id = _require(settings.discord_guild_id, "DISCORD_GUILD_ID")
    endpoint = (
        f"{DISCORD_API_BASE}/applications/{application_id}/guilds/{guild_id}/commands"
    )
    scope_label = f"guild {guild_id}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        for command in DISCORD_COMMANDS:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bot {bot_token}",
                    "User-Agent": "Churnary-Visitor-Bot/1.0",
                },
                json=command,
            )
            if response.status_code >= 400:
                raise SystemExit(
                    f"Discord rejected /{command['name']} "
                    f"({response.status_code}): {response.text[:500]}"
                )
            command_id = response.json().get("id", "unknown")
            print(f"Registered /{command['name']} in {scope_label} (id={command_id})")

    install_params = {
        "client_id": application_id,
        "scope": "bot applications.commands",
        "permissions": str(BOT_PERMISSIONS),
    }
    install_params["guild_id"] = guild_id
    install_params["disable_guild_select"] = "true"
    print(f"Install URL: https://discord.com/oauth2/authorize?{urlencode(install_params)}")
    print(
        "Interactions endpoint: "
        f"{settings.api_base_url.rstrip('/')}/api/discord/interactions"
    )


if __name__ == "__main__":
    asyncio.run(main())
