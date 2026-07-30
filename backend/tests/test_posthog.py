"""PostHog SDK compatibility, identity, and failure-isolation tests."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from app.api import auth as auth_api
from app.api import integrations as integrations_api
from app.core import posthog_client
from app.core.config import settings
from app.main import app


class RecordingClient:
    def __init__(self) -> None:
        self.captures: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.aliases: list[dict[str, Any]] = []
        self.sets: list[dict[str, Any]] = []
        self.shutdown_calls = 0

    def capture(self, *args: Any, **kwargs: Any) -> str:
        self.captures.append((args, kwargs))
        return "event-uuid"

    def alias(self, **kwargs: Any) -> None:
        self.aliases.append(kwargs)

    def set(self, **kwargs: Any) -> None:
        self.sets.append(kwargs)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.fixture
def recording_client(monkeypatch) -> RecordingClient:
    client = RecordingClient()
    monkeypatch.setattr(posthog_client, "_client", client)
    return client


def _request(distinct_id: str | None) -> Request:
    headers = []
    if distinct_id is not None:
        headers.append(
            (
                posthog_client.POSTHOG_DISTINCT_ID_HEADER.lower().encode(),
                distinct_id.encode(),
            )
        )
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_init_uses_posthog_7_constructor_and_registers_shutdown(monkeypatch):
    created: list[tuple[str, dict[str, Any]]] = []
    registered: list[Any] = []

    class FakePosthog(RecordingClient):
        def __init__(self, project_api_key: str, **kwargs: Any) -> None:
            super().__init__()
            created.append((project_api_key, kwargs))

    monkeypatch.setattr(posthog_client, "Posthog", FakePosthog)
    monkeypatch.setattr(posthog_client.atexit, "register", registered.append)
    monkeypatch.setattr(posthog_client, "_client", None)
    monkeypatch.setattr(posthog_client, "_atexit_registered", False)

    client = posthog_client.init_posthog(
        "phc_test",
        host="https://us.i.posthog.com",
        debug=True,
    )

    assert isinstance(client, FakePosthog)
    assert created == [
        (
            "phc_test",
            {
                "host": "https://us.i.posthog.com",
                "debug": True,
                "enable_exception_autocapture": True,
            },
        )
    ]
    assert registered == [posthog_client.shutdown_posthog]


def test_init_failure_disables_analytics_without_raising(monkeypatch):
    class BrokenPosthog:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("SDK unavailable")

    monkeypatch.setattr(posthog_client, "Posthog", BrokenPosthog)
    monkeypatch.setattr(posthog_client, "_client", None)

    assert posthog_client.init_posthog("phc_test", host="https://example.test") is None
    assert posthog_client.get_client() is None


def test_capture_uses_event_first_and_keyword_distinct_id(recording_client):
    result = posthog_client.capture_event(
        "demo_viewed",
        distinct_id="anon-123",
        properties={"customer_count": 3},
    )

    assert result == "event-uuid"
    assert recording_client.captures == [
        (
            ("demo_viewed",),
            {
                "distinct_id": "anon-123",
                "properties": {"customer_count": 3},
            },
        )
    ]


def test_capture_without_browser_id_stays_personless(recording_client):
    posthog_client.capture_event("demo_viewed", properties={"customer_count": 1})

    _, kwargs = recording_client.captures[0]
    assert "distinct_id" not in kwargs


def test_identify_aliases_anonymous_activity_and_sets_person(recording_client):
    posthog_client.identify_user(
        "user-123",
        anonymous_id="anon-123",
        properties={"business_id": "biz-9", "role": "owner"},
    )

    assert recording_client.aliases == [
        {"previous_id": "anon-123", "distinct_id": "user-123"}
    ]
    assert recording_client.sets == [
        {
            "distinct_id": "user-123",
            "properties": {"business_id": "biz-9", "role": "owner"},
        }
    ]


def test_identify_does_not_alias_a_user_to_itself(recording_client):
    posthog_client.identify_user(
        "user-123",
        anonymous_id="user-123",
        properties={"role": "owner"},
    )

    assert recording_client.aliases == []
    assert len(recording_client.sets) == 1


def test_sdk_errors_never_escape_customer_request(monkeypatch):
    class BrokenClient(RecordingClient):
        def capture(self, *_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("capture failed")

        def alias(self, **_kwargs: Any) -> None:
            raise RuntimeError("alias failed")

        def shutdown(self) -> None:
            raise RuntimeError("shutdown failed")

    client = BrokenClient()
    monkeypatch.setattr(posthog_client, "_client", client)

    assert posthog_client.capture_event("safe_event") is None
    posthog_client.identify_user(
        "user-123",
        anonymous_id="anon-123",
        properties={"role": "owner"},
    )
    posthog_client.shutdown_posthog()
    assert posthog_client.get_client() is None


@pytest.mark.parametrize("value", [None, "", "contains whitespace", "x" * 201])
def test_request_distinct_id_rejects_invalid_values(value):
    assert posthog_client.request_distinct_id(_request(value)) is None


def test_request_distinct_id_accepts_browser_uuid():
    value = "5fcbaaf0-1d36-43c7-a3bc-8a3b58dc23d8"
    assert posthog_client.request_distinct_id(_request(value)) == value


def test_auth_me_links_browser_and_authenticated_ids(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_identify(distinct_id: str, **kwargs: Any) -> None:
        calls.append((distinct_id, kwargs))

    monkeypatch.setattr(auth_api, "identify_user", fake_identify)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")

    response = TestClient(app).get(
        "/api/auth/me",
        headers={posthog_client.POSTHOG_DISTINCT_ID_HEADER: "anon-browser"},
    )

    assert response.status_code == 200
    assert calls == [
        (
            "demo-user",
            {
                "anonymous_id": "anon-browser",
                "properties": {
                    "business_id": "00000000-0000-0000-0000-000000000001",
                    "business_name": "Hayward Coffee Co.",
                    "role": "owner",
                },
            },
        )
    ]


def test_demo_captures_browser_distinct_id(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(event: str, **kwargs: Any) -> None:
        calls.append((event, kwargs))

    monkeypatch.setattr(integrations_api, "capture_event", fake_capture)
    response = TestClient(app).post(
        "/api/integrations/demo?count=3",
        headers={posthog_client.POSTHOG_DISTINCT_ID_HEADER: "anon-browser"},
    )

    assert response.status_code == 200
    assert calls[0][0] == "demo_viewed"
    assert calls[0][1]["distinct_id"] == "anon-browser"
    assert calls[0][1]["properties"]["customer_count"] == 3


def test_cors_allows_posthog_distinct_id_header():
    response = TestClient(app).options(
        "/api/integrations/demo",
        headers={
            "Origin": settings.frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": posthog_client.POSTHOG_DISTINCT_ID_HEADER,
        },
    )

    assert response.status_code == 200
    assert (
        posthog_client.POSTHOG_DISTINCT_ID_HEADER.lower()
        in response.headers["access-control-allow-headers"].lower()
    )
