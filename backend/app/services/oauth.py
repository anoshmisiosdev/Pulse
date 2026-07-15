"""OAuth handshakes for "Connect with Stripe / Square".

The backend brokers the whole flow: it builds the authorize URL (with a signed,
short-lived ``state`` carrying the tenant), receives the provider's callback,
exchanges the code for an access token, and hands that token to the existing
adapters — which don't know or care whether a key was pasted or OAuth-issued.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.http_retry import retry_transient
from app.integrations.base import IntegrationError

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_SQUARE_HOSTS = {
    "production": "https://connect.squareup.com",
    "sandbox": "https://connect.squareupsandbox.com",
}
# Read-only scopes: enough to pull customers + payments, nothing more.
_SQUARE_SCOPES = "CUSTOMERS_READ PAYMENTS_READ MERCHANT_PROFILE_READ"


def availability() -> dict[str, bool]:
    """Which providers have OAuth app credentials configured."""
    return {
        "stripe": bool(settings.stripe_connect_client_id and settings.stripe_secret_key),
        "square": bool(settings.square_app_id and settings.square_app_secret),
    }


def redirect_uri(provider: str) -> str:
    """The callback URL registered in the provider's dashboard (must match exactly)."""
    return f"{settings.api_base_url.rstrip('/')}/api/integrations/oauth/{provider}/callback"


def authorize_url(provider: str, state: str) -> str:
    if provider == "stripe":
        params = urlencode(
            {
                "response_type": "code",
                "client_id": settings.stripe_connect_client_id,
                "scope": "read_only",
                "state": state,
                "redirect_uri": redirect_uri("stripe"),
            }
        )
        return f"https://connect.stripe.com/oauth/authorize?{params}"
    if provider == "square":
        host = _SQUARE_HOSTS[settings.square_environment]
        params = urlencode(
            {
                "client_id": settings.square_app_id,
                "scope": _SQUARE_SCOPES,
                "session": "false",
                "state": state,
                "redirect_uri": redirect_uri("square"),
            }
        )
        return f"{host}/oauth2/authorize?{params}"
    raise IntegrationError(f"OAuth not supported for {provider!r}")


@retry_transient
async def _post(url: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, **kwargs)
    if resp.status_code >= 500:
        resp.raise_for_status()  # transient — retried by the decorator
    return resp


async def exchange_code(provider: str, code: str) -> dict:
    """Swap an authorization code for tokens. Returns at least {"access_token": ...}."""
    try:
        if provider == "stripe":
            resp = await _post(
                "https://connect.stripe.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_secret": settings.stripe_secret_key,
                },
            )
            data = resp.json()
            if resp.status_code >= 400 or "error" in data:
                raise IntegrationError(
                    f"Stripe OAuth failed: {data.get('error_description') or resp.text[:200]}"
                )
            token = data.get("access_token")
            if not token:
                raise IntegrationError(
                    "Stripe connected, but no data token was returned — "
                    "paste a restricted API key instead"
                )
            return {"access_token": token, "account_id": data.get("stripe_user_id")}

        if provider == "square":
            host = _SQUARE_HOSTS[settings.square_environment]
            resp = await _post(
                f"{host}/oauth2/token",
                json={
                    "client_id": settings.square_app_id,
                    "client_secret": settings.square_app_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri("square"),
                },
            )
            data = resp.json()
            if resp.status_code >= 400 or not data.get("access_token"):
                detail = (data.get("errors") or [{}])[0].get("detail", resp.text[:200])
                raise IntegrationError(f"Square OAuth failed: {detail}")
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "account_id": data.get("merchant_id"),
            }
    except httpx.HTTPError as exc:
        raise IntegrationError(f"Could not reach {provider}: {exc}") from exc

    raise IntegrationError(f"OAuth not supported for {provider!r}")
