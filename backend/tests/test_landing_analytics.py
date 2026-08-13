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
            "path": "/coffee-shop-customer-retention",
            "referrer_host": "search.example",
            "utm_source": "newsletter",
            "utm_medium": "email",
            "utm_campaign": "summer-launch",
            "utm_content": "aditya_observation_a",
            "landing_variant": "coffee_shop",
        },
    )

    assert response.status_code == 204
    assert calls[0][1]["properties"]["referrer_host"] == "search.example"
    assert calls[0][1]["properties"]["utm_campaign"] == "summer-launch"
    assert calls[0][1]["properties"]["utm_content"] == "aditya_observation_a"
    assert calls[0][1]["properties"]["landing_variant"] == "coffee_shop"


def test_funnel_steps_accept_content_and_landing_variant(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        analytics_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = TestClient(app).post(
        "/api/analytics/landing",
        headers={
            POSTHOG_DISTINCT_ID_HEADER: "landing-browser-variant",
            "x-forwarded-for": "198.51.100.205",
        },
        json={
            "event": "landing_waitlist_started",
            "utm_content": "pranjal_demo_b",
            "landing_variant": "gym",
        },
    )

    assert response.status_code == 204
    assert calls[0][1]["properties"]["utm_content"] == "pranjal_demo_b"
    assert calls[0][1]["properties"]["landing_variant"] == "gym"


def test_cta_accepts_post_calculator_location(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        analytics_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = TestClient(app).post(
        "/api/analytics/landing",
        headers={
            POSTHOG_DISTINCT_ID_HEADER: "landing-browser-calculator",
            "x-forwarded-for": "198.51.100.206",
        },
        json={
            "event": "landing_cta_clicked",
            "cta": "join_waitlist",
            "location": "calculator",
            "destination": "waitlist",
            "landing_variant": "calculator",
        },
    )

    assert response.status_code == 204
    assert calls[0][1]["properties"]["location"] == "calculator"


def test_calculator_accepts_every_public_control(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        analytics_api,
        "capture_event",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    response = TestClient(app).post(
        "/api/analytics/landing",
        headers={
            POSTHOG_DISTINCT_ID_HEADER: "landing-browser-calculator-value",
            "x-forwarded-for": "198.51.100.207",
        },
        json={
            "event": "landing_demo_interacted",
            "control": "monthly_value",
            "vertical": "cafe",
            "risk_band": "watch",
            "landing_variant": "calculator_v1",
        },
    )

    assert response.status_code == 204
    assert calls[0][1]["properties"]["control"] == "monthly_value"


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
