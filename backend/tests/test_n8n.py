"""n8n.notify: best-effort, never raises, no-ops on an unconfigured URL."""

from __future__ import annotations

import httpx

from app.services import n8n


async def test_notify_is_a_noop_without_a_configured_url():
    assert await n8n.notify("", "recovery.attributed", {"a": 1}) is False


async def test_notify_posts_the_event_and_payload():
    captured = {}

    async def handler(request: httpx.Request):
        captured["body"] = request.content
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await n8n.notify(
            "https://n8n.example/hook",
            "recovery.attributed",
            {"customer_id": "c1"},
            http_client=client,
        )

    assert ok is True
    assert b'"event":"recovery.attributed"' in captured["body"]
    assert b'"customer_id":"c1"' in captured["body"]


async def test_notify_swallows_delivery_failures():
    async def handler(_request):
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await n8n.notify(
            "https://n8n.example/hook", "recovery.attributed", {}, http_client=client
        )

    assert ok is False
