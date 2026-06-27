"""The one place LLM ("AAM") calls happen — everything routes through Token Router.

Token Router is an LLM gateway. We speak whichever wire protocol it exposes
(`TOKEN_ROUTER_PROTOCOL`): OpenAI-style ``/chat/completions`` (default, the de
facto standard for routers) or Anthropic-style ``/messages``. If no router is
configured we fall back to calling Anthropic directly so local dev still works.

Callers get a single coroutine, :func:`complete_text`, and never import a vendor
SDK. ``LLMError`` signals "couldn't get a completion" so callers degrade (e.g. to
a static template) instead of crashing.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("pulse.llm")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class LLMError(Exception):
    """Raised when no completion could be obtained from the router/provider."""


def _base_url() -> str:
    return settings.token_router_base_url.rstrip("/")


async def _call_openai_compatible(system: str, user: str, max_tokens: int) -> str:
    url = f"{_base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.token_router_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.token_router_model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected Token Router (openai) response: {data}") from exc


async def _call_anthropic_compatible(system: str, user: str, max_tokens: int) -> str:
    url = f"{_base_url()}/messages"
    headers = {
        "x-api-key": settings.token_router_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.token_router_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise LLMError(f"Unexpected Token Router (anthropic) response: {data}") from exc


async def _call_anthropic_direct(system: str, user: str, max_tokens: int) -> str:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise LLMError("anthropic SDK not installed and no Token Router configured") from exc
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


async def complete_text(system: str, user: str, max_tokens: int = 700) -> str:
    """Return raw model text. Raises LLMError on any failure."""
    if settings.token_router_api_key and settings.token_router_base_url:
        try:
            if settings.token_router_protocol == "anthropic":
                return await _call_anthropic_compatible(system, user, max_tokens)
            return await _call_openai_compatible(system, user, max_tokens)
        except httpx.HTTPError as exc:
            raise LLMError(f"Token Router request failed: {exc}") from exc

    if settings.anthropic_api_key:
        logger.warning("Token Router not configured — falling back to direct Anthropic")
        return await _call_anthropic_direct(system, user, max_tokens)

    raise LLMError("No LLM configured (set TOKEN_ROUTER_API_KEY + TOKEN_ROUTER_BASE_URL)")


def active_model() -> str | None:
    """The model id that will be used, for logging/provenance."""
    if settings.token_router_api_key and settings.token_router_base_url:
        return settings.token_router_model
    if settings.anthropic_api_key:
        return settings.anthropic_model
    return None
