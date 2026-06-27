"""Backend-brokered Convex auth client.

Convex is the system of record for users + businesses. We call a Convex HTTP
action (authored in ``convex/http.ts``) with the shared ``CONVEX_API_KEY`` to
verify credentials; the browser never sees the Convex key or talks to Convex
directly. HTTP actions are served from the ``.convex.site`` domain, so we derive
that from ``CONVEX_URL`` (the ``.convex.cloud`` deployment URL).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


class ConvexAuthError(Exception):
    """Invalid credentials or Convex rejected the request."""


class ConvexUnavailable(Exception):
    """Convex is not configured or unreachable."""


@dataclass
class ConvexUser:
    user_id: str
    business_id: str
    business_name: str
    email: str
    role: str = "owner"


def _site_base() -> str:
    """HTTP-action base URL (.convex.site) derived from the deployment URL."""
    url = settings.convex_url.rstrip("/")
    return url.replace(".convex.cloud", ".convex.site")


def is_configured() -> bool:
    return bool(settings.convex_url and settings.convex_api_key)


async def verify_login(email: str, password: str) -> ConvexUser:
    """Verify credentials against Convex. Raises on bad creds / unavailable."""
    if not is_configured():
        raise ConvexUnavailable("Convex auth is not configured (set CONVEX_URL + CONVEX_API_KEY)")

    url = f"{_site_base()}/auth/login"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                json={"email": email.strip().lower(), "password": password},
                headers={"x-pulse-key": settings.convex_api_key},
            )
    except httpx.HTTPError as exc:
        raise ConvexUnavailable(f"Could not reach Convex: {exc}") from exc

    if resp.status_code == 401:
        raise ConvexAuthError("Invalid email or password")
    if resp.status_code >= 400:
        raise ConvexUnavailable(f"Convex error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    return ConvexUser(
        user_id=str(data["userId"]),
        business_id=str(data["businessId"]),
        business_name=data.get("businessName", "My Business"),
        email=data.get("email", email),
        role=data.get("role", "owner"),
    )


async def register(email: str, password: str, business_name: str) -> ConvexUser:
    """Create a tenant + owner in Convex (operator bootstrap, guarded by the API key)."""
    if not is_configured():
        raise ConvexUnavailable("Convex auth is not configured")
    url = f"{_site_base()}/auth/register"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                json={
                    "email": email.strip().lower(),
                    "password": password,
                    "businessName": business_name,
                },
                headers={"x-pulse-key": settings.convex_api_key},
            )
    except httpx.HTTPError as exc:
        raise ConvexUnavailable(f"Could not reach Convex: {exc}") from exc

    if resp.status_code == 409:
        raise ConvexAuthError("An account with that email already exists")
    if resp.status_code >= 400:
        raise ConvexUnavailable(f"Convex error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    return ConvexUser(
        user_id=str(data["userId"]),
        business_id=str(data["businessId"]),
        business_name=data.get("businessName", business_name),
        email=data.get("email", email),
        role=data.get("role", "owner"),
    )
