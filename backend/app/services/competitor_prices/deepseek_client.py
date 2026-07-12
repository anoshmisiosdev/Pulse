"""DeepSeek V4 Flash client through TokenMart's OpenAI-compatible gateway.

TOKENMART_* settings are primary. Legacy DEEPSEEK_* and token-router settings
remain supported as fallbacks for existing deployments.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings

logger = logging.getLogger("pulse.competitor_prices.deepseek")

T = TypeVar("T", bound=BaseModel)
_TIMEOUT = httpx.Timeout(45.0, connect=10.0)


class DeepSeekError(Exception):
    """Base DeepSeek integration error."""


class DeepSeekConfigurationError(DeepSeekError):
    """DeepSeek cannot be called because local configuration is incomplete."""


class DeepSeekQuotaError(DeepSeekError):
    """DeepSeek or the configured gateway is rate limited."""


@dataclass
class DeepSeekJSONResult[T: BaseModel]:
    data: T
    warnings: list[str] = field(default_factory=list)
    tools_used: set[str] = field(default_factory=lambda: {"deepseek_extraction"})
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key if api_key is not None else _effective_api_key()
        self.base_url = (base_url or _effective_base_url()).rstrip("/")
        self.model = model or _effective_model()
        self.requests_made = 0
        self.duration_ms_total = 0
        self.returned_models: set[str] = set()
        self.usage_totals: dict[str, int] = {}

    async def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        max_tokens: int = 1200,
    ) -> DeepSeekJSONResult[T]:
        if not self.api_key:
            raise DeepSeekConfigurationError(
                "Set TOKENMART_API_KEY (preferred), DEEPSEEK_API_KEY, or enable "
                "DEEPSEEK_USE_TOKEN_ROUTER with TOKEN_ROUTER_API_KEY."
            )

        data = await self._chat_completion(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            use_json_mode=True,
        )
        text = extract_chat_content(data)
        try:
            parsed = parse_json_text(text, response_model)
        except ValidationError:
            repaired = await self._repair_json(text, response_model=response_model)
            parsed = parse_json_text(repaired, response_model)

        returned_model = str(data.get("model") or self.model)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        self.returned_models.add(returned_model)
        for key, value in usage.items():
            if isinstance(value, int):
                self.usage_totals[key] = self.usage_totals.get(key, 0) + value
        return DeepSeekJSONResult(data=parsed, model=returned_model, usage=usage)

    async def _repair_json(self, raw: str, *, response_model: type[T]) -> str:
        schema = json.dumps(response_model.model_json_schema(by_alias=True))
        system = "Return only valid JSON. Do not add commentary."
        prompt = (
            "Repair this content into valid json matching the schema.\n\n"
            f"Schema:\n{schema}\n\n"
            f"Content:\n{raw}"
        )
        data = await self._chat_completion(
            system=system,
            prompt=prompt,
            max_tokens=1200,
            use_json_mode=True,
        )
        return extract_chat_content(data)

    async def _chat_completion(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int,
        use_json_mode: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            return await self._post_chat_completion(payload)
        except DeepSeekError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise DeepSeekQuotaError(
                    "DeepSeek extraction quota exhausted or rate limited."
                ) from exc
            if use_json_mode and _looks_like_response_format_rejection(exc.response.text):
                logger.info(
                    "DeepSeek gateway rejected response_format; retrying without JSON mode."
                )
                return await self._chat_completion(
                    system=system,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    use_json_mode=False,
                )
            raise DeepSeekError(
                f"DeepSeek extraction request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"DeepSeek extraction request failed: {exc}") from exc

    async def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            started = time.perf_counter()
            self.requests_made += 1
            try:
                response = await client.post(
                    self._chat_url(),
                    headers=headers,
                    json=payload,
                )
            finally:
                self.duration_ms_total += round((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise DeepSeekError(f"Unexpected DeepSeek response: {data}")
        return data

    def _chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"


def extract_chat_content(data: dict[str, Any]) -> str:
    """Read OpenAI-style and common gateway-wrapped response bodies."""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                return _content_to_text(message.get("content"))
            return _content_to_text(first.get("text"))

    if "output_text" in data:
        return str(data.get("output_text") or "")
    if "content" in data:
        return _content_to_text(data.get("content"))
    if "response" in data:
        return _content_to_text(data.get("response"))

    raise DeepSeekError(f"Unexpected DeepSeek response shape: {data}")


def parse_json_text[T: BaseModel](raw: str, response_model: type[T]) -> T:
    text = _strip_fences(raw.strip())
    try:
        return response_model.model_validate_json(text)
    except ValidationError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return response_model.model_validate_json(match.group(0))


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                chunks.append(str(item.get("text") or item.get("content") or ""))
        return "".join(chunks)
    return str(content or "")


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _looks_like_response_format_rejection(text: str) -> bool:
    lowered = text.lower()
    return "response_format" in lowered or "json_object" in lowered


def _effective_api_key() -> str:
    if settings.tokenmart_api_key:
        return settings.tokenmart_api_key
    if settings.deepseek_api_key:
        return settings.deepseek_api_key
    if settings.deepseek_use_token_router:
        return settings.token_router_api_key
    return ""


def _effective_base_url() -> str:
    if settings.tokenmart_api_key:
        return settings.tokenmart_base_url
    if settings.deepseek_use_token_router and settings.token_router_base_url:
        return settings.token_router_base_url
    return settings.deepseek_base_url or "https://api.deepseek.com"


def _effective_model() -> str:
    if settings.tokenmart_api_key:
        return settings.tokenmart_model
    if settings.deepseek_use_token_router and settings.token_router_model:
        return settings.deepseek_model or settings.token_router_model
    return settings.deepseek_model
