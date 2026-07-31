"""Discord application-command definitions."""

from __future__ import annotations

MANAGE_GUILD_PERMISSION = str(1 << 5)

DISCORD_COMMANDS: list[dict] = [
    {
        "name": "churnary",
        "description": "Private visitor-intelligence tools for the Churnary team",
        "type": 1,
        "default_member_permissions": MANAGE_GUILD_PERMISSION,
        "options": [
            {
                "name": "summary",
                "description": "Show visitor and RB2B performance for a time window",
                "type": 1,
                "options": [
                    {
                        "name": "days",
                        "description": "Reporting window in days",
                        "type": 4,
                        "required": False,
                        "min_value": 1,
                        "max_value": 365,
                    }
                ],
            },
            {
                "name": "recent",
                "description": "Show the highest-intent recently identified visitors",
                "type": 1,
                "options": [
                    {
                        "name": "limit",
                        "description": "Number of visitors to show",
                        "type": 4,
                        "required": False,
                        "min_value": 1,
                        "max_value": 10,
                    }
                ],
            },
            {
                "name": "status",
                "description": "Check RB2B, alerts, and bot configuration",
                "type": 1,
            },
        ],
    }
]
