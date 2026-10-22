"""Outbound webhooks: the SSRF guard first, then signing, delivery, retries,
and the events that fire them.

DNS is stubbed throughout (``_resolve_ips``) so every address class can be
tested deterministically, and HTTP goes through httpx.MockTransport so no test
ever makes a real request.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import (
    Campaign,
    CampaignSend,
    Customer,
    Subscription,
    Transaction,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.services import ingest
from app.services import outbound_webhooks as hooks
from app.services.attribution import detect_recoveries

BUSINESS_ID = str(uuid.uuid4())
PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch):
    """Map hostnames to addresses for the duration of a test."""
    table: dict[str, list[str]] = {"hooks.example.com": [PUBLIC_IP]}

    def _resolve(host):
        if host not in table:
            import socket

            raise socket.gaierror("not found")
        return [ipaddress.ip_address(a) for a in table[host]]

    monkeypatch.setattr(hooks, "_resolve_ips", _resolve)
    return table


# -- SSRF guard ---------------------------------------------------------------


def test_a_public_https_url_is_accepted(dns):
    assert hooks.validate_url("https://hooks.example.com/churnary") == (
        "https://hooks.example.com/churnary"
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.4.12",  # RFC1918 -- the VPC
        "172.16.0.5",
        "192.168.1.10",
        "169.254.169.254",  # AWS instance metadata: hands out credentials
        "100.64.0.1",  # carrier-grade NAT; is_private misses this, is_global doesn't
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "::1",
        "fd00::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:169.254.169.254",  # IPv4-mapped metadata address
    ],
)
def test_internal_addresses_are_refused(dns, address):
    dns["internal.example.com"] = [address]
    with pytest.raises(hooks.WebhookURLError, match="isn't reachable from the public internet"):
        hooks.validate_url("https://internal.example.com/x")


def test_a_host_that_resolves_to_any_internal_address_is_refused(dns):
    """One private answer among public ones is enough: we can't control which
    address the client ends up connecting to."""
    dns["mixed.example.com"] = [PUBLIC_IP, "10.0.0.5"]
    with pytest.raises(hooks.WebhookURLError):
        hooks.validate_url("https://mixed.example.com/")


def test_an_ip_literal_is_checked_like_any_host(dns):
    dns["169.254.169.254"] = ["169.254.169.254"]
    with pytest.raises(hooks.WebhookURLError):
        hooks.validate_url("http://169.254.169.254/latest/meta-data/")


def test_the_refusal_doesnt_say_which_internal_range_it_hit(dns):
    """No oracle for mapping the network from the outside."""
    dns["a.example.com"] = ["10.0.0.1"]
    dns["b.example.com"] = ["169.254.169.254"]
    messages = set()
    for host in ("a.example.com", "b.example.com"):
        with pytest.raises(hooks.WebhookURLError) as exc:
            hooks.validate_url(f"https://{host}/")
        messages.add(str(exc.value))
    assert len(messages) == 1


def test_an_unresolvable_host_is_refused(dns):
    with pytest.raises(hooks.WebhookURLError, match="Couldn't find the host"):
        hooks.validate_url("https://nope.invalid/")


def test_credentials_in_the_url_are_refused(dns):
    with pytest.raises(hooks.WebhookURLError, match="credentials"):
        hooks.validate_url("https://user:pass@hooks.example.com/")


@pytest.mark.parametrize("url", ["ftp://hooks.example.com/", "file:///etc/passwd", "gopher://x"])
def test_only_web_schemes_are_allowed(dns, url):
    with pytest.raises(hooks.WebhookURLError):
        hooks.validate_url(url)


def test_production_requires_https(dns, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(hooks.WebhookURLError, match="https"):
        hooks.validate_url("http://hooks.example.com/")


# -- Signing ------------------------------------------------------------------


def test_the_signature_verifies_with_the_stripe_style_scheme():
    body = b'{"type":"webhook.test"}'
    header = hooks.sign("whsec_abc", body, timestamp=1700000000)
    ts, v1 = (part.split("=", 1)[1] for part in header.split(","))
    expected = hmac.new(b"whsec_abc", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert ts == "1700000000"
    assert hmac.compare_digest(v1, expected)


def test_a_different_body_produces_a_different_signature():
    assert hooks.sign("s", b"a", timestamp=1) != hooks.sign("s", b"b", timestamp=1)


# -- Endpoint + emit ----------------------------------------------------------


async def _business(db, tier="growth", status="active"):
    await ingest.ensure_business(db, BUSINESS_ID, "Hayward Coffee Co.", "cafe")
    db.add(Subscription(business_id=uuid.UUID(BUSINESS_ID), tier=tier, status=status))
    await db.flush()


async def _endpoint(db, events=None, url="https://hooks.example.com/in"):
    created = await hooks.create_endpoint(db, business_id=BUSINESS_ID, url=url, events=events)
    await db.flush()
    return created


async def test_the_secret_is_stored_encrypted_not_in_plain_text(db, dns):
    await _business(db)
    created = await _endpoint(db)
    assert created.secret.startswith("whsec_")
    row = await db.get(WebhookEndpoint, created.endpoint.id)
    assert created.secret not in row.secret_enc


async def test_registering_an_internal_url_is_refused(db, dns):
    await _business(db)
    dns["sneaky.example.com"] = ["169.254.169.254"]
    with pytest.raises(hooks.WebhookURLError):
        await _endpoint(db, url="https://sneaky.example.com/")


async def test_emit_queues_one_delivery_per_subscribed_endpoint_with_a_shared_event_id(db, dns):
    await _business(db)
    await _endpoint(db, events=["customer.recovered"])
    await _endpoint(db, events=[])  # all events
    await _endpoint(db, events=["campaign.sent"])  # not subscribed

    queued = await hooks.emit(
        db, business_id=BUSINESS_ID, event_type="customer.recovered", data={"x": 1}
    )
    assert queued == 2
    rows = (await db.execute(select(WebhookDelivery))).scalars().all()
    assert len({r.event_id for r in rows}) == 1  # receivers dedupe on this


@pytest.mark.parametrize(("tier", "status"), [("starter", "active"), ("growth", "canceled")])
async def test_emit_is_skipped_without_an_active_automation_plan(db, dns, tier, status):
    """Same gate as unattended sending -- tier AND status, which is the bug an
    earlier commit on this branch fixed."""
    await _business(db, tier=tier, status=status)
    await _endpoint(db)
    assert await hooks.emit(db, business_id=BUSINESS_ID, event_type="campaign.sent", data={}) == 0


async def test_emit_never_raises(db, monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("app.billing.store.entitlements", _boom)
    assert await hooks.emit(db, business_id=BUSINESS_ID, event_type="campaign.sent", data={}) == 0


# -- Delivery -----------------------------------------------------------------


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _queued(db, dns, events=None):
    await _business(db)
    created = await _endpoint(db, events=events)
    await hooks.emit(db, business_id=BUSINESS_ID, event_type="campaign.sent", data={"n": 3})
    return created


async def test_a_2xx_marks_the_delivery_delivered_and_the_request_is_signed(db, dns):
    created = await _queued(db, dns)
    seen = {}

    def handler(request):
        seen["sig"] = request.headers["Churnary-Signature"]
        seen["event"] = request.headers["Churnary-Event"]
        seen["body"] = request.content
        return httpx.Response(204)

    async with _client(handler) as client:
        counts = await hooks.deliver_pending(db, client=client)

    assert counts["delivered"] == 1
    ts, v1 = (part.split("=", 1)[1] for part in seen["sig"].split(","))
    expected = hmac.new(
        created.secret.encode(), f"{ts}.".encode() + seen["body"], hashlib.sha256
    ).hexdigest()
    assert v1 == expected
    assert seen["event"] == "campaign.sent"
    assert json.loads(seen["body"])["data"] == {"n": 3}


async def test_a_failure_is_retried_with_backoff(db, dns):
    await _queued(db, dns)
    async with _client(lambda r: httpx.Response(503)) as client:
        await hooks.deliver_pending(db, client=client)
    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.last_error == "HTTP 503"
    assert hooks._aware(row.next_attempt_at) > datetime.now(UTC) + timedelta(seconds=30)


async def test_a_delivery_gives_up_after_max_attempts(db, dns):
    await _queued(db, dns)
    async with _client(lambda r: httpx.Response(500)) as client:
        later = datetime.now(UTC) + timedelta(days=2)  # past every backoff delay
        for _ in range(hooks.MAX_ATTEMPTS):
            await hooks.deliver_pending(db, client=client, now=later)
    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert row.status == "failed"
    assert row.attempts == hooks.MAX_ATTEMPTS
    assert row.next_attempt_at is None


async def test_redirects_are_not_followed(db, dns):
    """A public URL must not be able to bounce us onto an internal one."""
    await _queued(db, dns)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/"})

    async with _client(handler) as client:
        await hooks.deliver_pending(db, client=client)
    assert calls == ["https://hooks.example.com/in"]
    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert row.status == "pending"  # a 3xx is a failure, retried later
    assert row.last_error == "HTTP 302"


async def test_the_response_body_is_never_stored(db, dns):
    """Even a successful SSRF can't read anything back through the log."""
    await _queued(db, dns)
    async with _client(lambda r: httpx.Response(500, text="SECRET-INTERNAL-DATA")) as client:
        await hooks.deliver_pending(db, client=client)
    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert "SECRET" not in (row.last_error or "")


async def test_dns_that_changes_to_internal_after_registration_is_caught(db, dns):
    """The guard runs again at send time, not just when the URL was saved."""
    await _queued(db, dns)
    dns["hooks.example.com"] = ["10.0.0.9"]
    calls = []
    async with _client(lambda r: calls.append(r) or httpx.Response(200)) as client:
        await hooks.deliver_pending(db, client=client)
    assert calls == []  # no request was made
    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert "public internet" in row.last_error


async def test_an_endpoint_that_keeps_failing_is_switched_off(db, dns):
    created = await _queued(db, dns)
    endpoint = await db.get(WebhookEndpoint, created.endpoint.id)
    endpoint.consecutive_failures = hooks.DISABLE_AFTER_CONSECUTIVE_FAILURES - 1
    await db.flush()
    async with _client(lambda r: httpx.Response(500)) as client:
        await hooks.deliver_pending(db, client=client)
    assert endpoint.enabled is False


async def test_a_success_resets_the_failure_count(db, dns):
    created = await _queued(db, dns)
    endpoint = await db.get(WebhookEndpoint, created.endpoint.id)
    endpoint.consecutive_failures = 7
    await db.flush()
    async with _client(lambda r: httpx.Response(200)) as client:
        await hooks.deliver_pending(db, client=client)
    assert endpoint.consecutive_failures == 0
    assert endpoint.last_success_at is not None


async def test_deliveries_for_a_deleted_or_disabled_endpoint_fail_without_a_request(db, dns):
    created = await _queued(db, dns)
    endpoint = await db.get(WebhookEndpoint, created.endpoint.id)
    endpoint.enabled = False
    await db.flush()
    calls = []
    async with _client(lambda r: calls.append(r) or httpx.Response(200)) as client:
        await hooks.deliver_pending(db, client=client)
    assert calls == []
    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert row.status == "failed"


# -- The event that matters most ----------------------------------------------


async def test_a_recovery_emits_customer_recovered(db, dns):
    await _business(db)
    await _endpoint(db, events=["customer.recovered"])
    bid = uuid.UUID(BUSINESS_ID)
    customer = Customer(
        business_id=bid, source="csv", first_name="Dana", last_name="Reyes",
        email="dana@example.com",
    )
    db.add(customer)
    await db.flush()
    campaign = Campaign(business_id=bid, name="Win back", channel="email", status="sent")
    db.add(campaign)
    await db.flush()
    db.add(
        CampaignSend(
            business_id=bid, campaign_id=campaign.id, customer_id=customer.id,
            channel="email", body="Come back", status="sent",
            sent_at=datetime.now() - timedelta(days=10),
        )
    )
    db.add(
        Transaction(
            business_id=bid, customer_id=customer.id, source="csv", amount=64,
            occurred_at=datetime.now() - timedelta(days=3),
        )
    )
    await db.flush()

    summary = await detect_recoveries(db, BUSINESS_ID)
    assert summary.recoveries_found == 1

    row = (await db.execute(select(WebhookDelivery))).scalars().one()
    assert row.event_type == "customer.recovered"
    data = row.payload["data"]
    assert data["customer"]["email"] == "dana@example.com"
    assert data["estimated_value"] == 64.0
