"""Landing-page analytics contract and PII guardrails."""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from app.api import analytics as analytics_api
from app.core.posthog_client import POSTHOG_DISTINCT_ID_HEADER
from app.main import app


def test_landing_metric_is_forwarded_with_identity_and_version(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(event: str, **kwargs: Any) -> None:
        calls.append((event, kwargs))

    monkeypatch.setattr(analytics_api, "capture_event", fake_capture)
    response = TestClient(app).post(
        "/api/analytics/landing",
        headers={
            POSTHOG_DISTINCT_ID_HEADER: "landing-browser-123",
            "x-forwarded-for": "198.51.100.201",
        },
        json={
            "event": "landing_cta_clicked",
            "cta": "join_waitlist",
            "location": "pricing",
            "destination": "waitlist",
            "plan": "growth",
        },
    )

    assert response.status_code == 204
    assert calls == [
        (
            "landing_cta_clicked",
            {
                "distinct_id": "landing-browser-123",
                "properties": {
                    "cta": "join_waitlist",
                    "location": "pricing",
                    "destination": "waitlist",
                    "plan": "growth",
                    "surface": "landing",
                    "metric_version": 1,
                },
            },
        )
    ]


def test_landing_metric_rejects_unknown_events_and_properties(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        analytics_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )
    client = TestClient(app)
    headers = {"x-forwarded-for": "198.51.100.202"}

    unknown = client.post(
        "/api/analytics/landing",
        headers=headers,
        json={"event": "arbitrary_event", "email": "visitor@example.com"},
    )
    pii = client.post(
        "/api/analytics/landing",
        headers=headers,
        json={
            "event": "landing_waitlist_started",
            "email": "visitor@example.com",
        },
    )

    assert unknown.status_code == 422
    assert pii.status_code == 422
    assert calls == []


def test_landing_view_accepts_bounded_attribution(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        analytics_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = TestClient(app).post(
        "/api/analytics/landing",
        headers={
            POSTHOG_DISTINCT_ID_HEADER: "landing-browser-789",
            "x-forwarded-for": "198.51.100.203",
        },
        json={
            "event": "landing_viewed",
            "path": "/landing",
            "referrer_host": "search.example",
            "utm_source": "newsletter",
            "utm_medium": "email",
            "utm_campaign": "summer-launch",
        },
    )

    assert response.status_code == 204
    assert calls[0][1]["properties"]["referrer_host"] == "search.example"
    assert calls[0][1]["properties"]["utm_campaign"] == "summer-launch"


def test_landing_metric_without_consent_header_is_not_forwarded(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        analytics_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = TestClient(app).post(
        "/api/analytics/landing",
        headers={"x-forwarded-for": "198.51.100.204"},
        json={"event": "landing_waitlist_started"},
    )

    assert response.status_code == 204
    assert calls == []
