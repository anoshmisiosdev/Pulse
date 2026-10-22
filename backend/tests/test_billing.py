"""Billing: tier config, usage meters, the Stripe webhook, and the API.

No Stripe account is involved anywhere here. The webhook tests feed literal
event payloads straight to the handler, which is the whole reason
``app/billing/webhooks.py`` takes a dict rather than importing the SDK.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.billing.limits import automation_denial, channel_denial, evaluate
from app.billing.service import BillingError, price_id_for, tier_for_price
from app.billing.store import (
    ensure_subscription,
    entitlements,
    get_subscription,
    trial_days_left,
    usage_counts,
)
from app.billing.tiers import TIERS, get_tier, is_upgrade, tier_rank
from app.billing.webhooks import apply_subscription_event
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import Business, Customer, IntegrationConnection

BUSINESS_ID = uuid.uuid4()


# -- Tier config (pure) -------------------------------------------------------


def test_annual_price_is_two_months_free():
    for tier in TIERS.values():
        assert tier.annual_price_usd == tier.monthly_price_usd * 10


def test_tiers_match_the_published_price_list():
    assert TIERS["starter"].monthly_price_usd == 199
    assert TIERS["growth"].monthly_price_usd == 299
    assert TIERS["pro"].monthly_price_usd == 499
    assert TIERS["starter"].max_customers == 1_000
    assert TIERS["growth"].max_customers == 2_500
    assert TIERS["pro"].max_customers is None


def test_starter_is_email_only_and_has_no_automation():
    starter = TIERS["starter"]
    assert starter.allows_channel("email")
    assert not starter.allows_channel("sms")
    assert not starter.automation


def test_unknown_tier_falls_back_to_starter_rather_than_raising():
    """A tier string we don't recognize must not take down the dashboard, and
    must under-grant rather than hand out entitlements nobody paid for."""
    assert get_tier("enterprise_platinum").name == "starter"
    assert get_tier(None).name == "starter"
    assert get_tier("").name == "starter"


def test_tier_ranking_and_upgrade_detection():
    assert tier_rank("starter") < tier_rank("growth") < tier_rank("pro")
    assert is_upgrade("starter", "pro")
    assert not is_upgrade("pro", "starter")
    assert not is_upgrade("growth", "growth")


# -- Usage meters (pure) ------------------------------------------------------


def _ent(tier="starter", status="active", customers=0, integrations=0):
    return evaluate(
        tier_name=tier,
        status=status,
        customer_count=customers,
        integration_count=integrations,
    )


def test_under_ninety_percent_is_quiet():
    meter = _ent(customers=500).meters[0]
    assert meter.severity == "ok"
    assert meter.message is None


def test_ninety_percent_starts_nagging():
    meter = _ent(customers=900).meters[0]
    assert meter.severity == "approaching"
    assert "900" in meter.message


def test_going_over_the_limit_nags_but_never_blocks():
    """The product rule is 'nag at 90%, never hard-block'. Over the customer
    limit, the account stays active and every entitlement is intact."""
    ent = _ent(customers=5_000)
    meter = ent.meters[0]
    assert meter.severity == "over"
    assert ent.active
    assert channel_denial(ent, "email") is None
    assert "Nothing is turned off" in meter.message


def test_unlimited_tier_never_nags():
    ent = _ent(tier="pro", customers=10_000_000)
    assert all(m.severity == "ok" for m in ent.meters)
    assert ent.meters[0].limit is None
    assert ent.meters[0].fraction is None


def test_past_due_keeps_the_product_usable():
    """A failed card is a billing problem, not a reason to lock an owner out of
    a campaign they're mid-way through. Stripe's dunning does the chasing."""
    assert _ent(status="past_due").active


@pytest.mark.parametrize("status", ["canceled", "trial_expired", "nonsense"])
def test_inactive_statuses_are_reported_inactive(status):
    assert not _ent(status=status).active


def test_sms_is_denied_on_starter_and_allowed_on_growth():
    assert "Upgrade to Growth" in channel_denial(_ent(tier="starter"), "sms")
    assert channel_denial(_ent(tier="growth"), "sms") is None


def test_automation_is_denied_on_starter_and_mentions_manual_approval():
    denial = automation_denial(_ent(tier="starter"))
    assert "Upgrade to Growth" in denial
    assert "approve each one by hand" in denial
    assert automation_denial(_ent(tier="growth")) is None


# -- Price mapping ------------------------------------------------------------


def test_price_lookup_raises_a_clear_error_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_growth", "")
    with pytest.raises(BillingError, match="No Stripe price is configured"):
        price_id_for("growth")


def test_annual_falls_back_to_monthly_when_no_annual_price_exists(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_growth", "price_monthly")
    monkeypatch.setattr(settings, "stripe_price_growth_annual", "")
    assert price_id_for("growth", annual=True) == "price_monthly"
    monkeypatch.setattr(settings, "stripe_price_growth_annual", "price_annual")
    assert price_id_for("growth", annual=True) == "price_annual"


def test_price_ids_map_back_to_their_tier(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_pro", "price_pro_m")
    monkeypatch.setattr(settings, "stripe_price_pro_annual", "price_pro_y")
    assert tier_for_price("price_pro_m") == "pro"
    assert tier_for_price("price_pro_y") == "pro"
    assert tier_for_price("price_someone_elses") is None
    assert tier_for_price(None) is None


# -- Store / DB ---------------------------------------------------------------


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.db'}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(Business(id=BUSINESS_ID, name="Hayward Coffee Co.", vertical="cafe"))
        await db.commit()
    yield factory
    await engine.dispose()


async def test_first_read_creates_a_trialing_subscription(sessions):
    async with sessions() as db:
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await db.commit()
    assert sub.status == "trialing"
    assert sub.tier == "starter"
    assert trial_days_left(sub) == 14


async def test_ensure_subscription_is_idempotent(sessions):
    async with sessions() as db:
        first = await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await db.commit()
        second = await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await db.commit()
    assert first.id == second.id


async def test_an_expired_trial_reports_trial_expired_without_a_webhook(sessions):
    """A missed Stripe webhook must not leave someone on an unbounded free
    trial, so expiry is derived locally rather than trusted from events."""
    async with sessions() as db:
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
        sub.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
        ent = await entitlements(db, business_id=str(BUSINESS_ID))
    assert ent.status == "trial_expired"
    assert not ent.active


async def test_entitlements_work_when_the_row_is_read_in_a_fresh_session(sessions):
    """Regression: a real request reads the subscription from the database, not
    from an identity map that still holds the aware datetime we wrote.

    SQLite hands back naive datetimes for a ``DateTime(timezone=True)`` column,
    so comparing ``trial_ends_at`` against ``datetime.now(UTC)`` raised
    TypeError and 500'd GET /billing/subscription. The original tests all
    created and read the row inside one session, where ``expire_on_commit=False``
    kept the aware value alive, so they never saw it.
    """
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await db.commit()

    # A different session: nothing cached, the value comes off the driver.
    async with sessions() as db:
        ent = await entitlements(db, business_id=str(BUSINESS_ID))
        sub = await get_subscription(db, business_id=str(BUSINESS_ID))
        assert sub is not None
        assert trial_days_left(sub) == 14
    assert ent.status == "trialing"
    assert ent.active


async def test_usage_counts_only_see_this_tenant(sessions):
    other = uuid.uuid4()
    async with sessions() as db:
        db.add(Business(id=other, name="Someone Else", vertical="salon"))
        for i in range(3):
            db.add(Customer(business_id=BUSINESS_ID, source="csv", email=f"a{i}@x.com"))
        db.add(Customer(business_id=other, source="csv", email="theirs@x.com"))
        db.add(
            IntegrationConnection(
                business_id=BUSINESS_ID, source="square", status="connected"
            )
        )
        # A disconnected source doesn't consume an integration slot.
        db.add(
            IntegrationConnection(
                business_id=BUSINESS_ID, source="stripe", status="disconnected"
            )
        )
        await db.commit()
        customers, integrations = await usage_counts(db, business_id=str(BUSINESS_ID))
    assert customers == 3
    assert integrations == 1


# -- Webhooks -----------------------------------------------------------------


def _sub_event(event_type: str, **overrides) -> dict:
    obj = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "metadata": {"business_id": str(BUSINESS_ID)},
        "items": {"data": [{"price": {"id": "price_growth_m"}}]},
        "current_period_end": int(time.time()) + 86_400 * 30,
    }
    obj.update(overrides)
    return {"type": event_type, "data": {"object": obj}}


@pytest.fixture
def growth_price(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_growth", "price_growth_m")
    monkeypatch.setattr(settings, "stripe_price_pro", "price_pro_m")


async def test_checkout_completed_links_stripe_ids_only(sessions, growth_price):
    """Checkout binds ids; the plan and status come from the subscription
    events, so there's one source of truth for those fields."""
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        result = await apply_subscription_event(
            db,
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "client_reference_id": str(BUSINESS_ID),
                        "customer": "cus_123",
                        "subscription": "sub_123",
                    }
                },
            },
        )
        await db.commit()
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
    assert result["outcome"] == "linked"
    assert sub.stripe_customer_id == "cus_123"
    assert sub.stripe_subscription_id == "sub_123"
    assert sub.tier == "starter"  # untouched by checkout


async def test_subscription_created_sets_tier_and_status(sessions, growth_price):
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await apply_subscription_event(db, _sub_event("customer.subscription.created"))
        await db.commit()
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
    assert sub.tier == "growth"
    assert sub.status == "active"
    assert sub.current_period_end is not None


async def test_redelivering_the_same_event_changes_nothing(sessions, growth_price):
    """Stripe redelivers. Handlers write absolute state, so the second apply is
    a no-op rather than a double-count."""
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        event = _sub_event("customer.subscription.updated")
        await apply_subscription_event(db, event)
        await db.commit()
        first = (await ensure_subscription(db, business_id=str(BUSINESS_ID))).tier
        await apply_subscription_event(db, event)
        await db.commit()
        second = await ensure_subscription(db, business_id=str(BUSINESS_ID))
    assert first == second.tier == "growth"
    assert second.status == "active"


async def test_an_unrecognized_price_keeps_the_existing_tier(sessions, growth_price):
    """A price created in the Stripe dashboard that we have no mapping for must
    not silently downgrade a paying customer to Starter."""
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await apply_subscription_event(db, _sub_event("customer.subscription.created"))
        await db.commit()
        await apply_subscription_event(
            db,
            _sub_event(
                "customer.subscription.updated",
                items={"data": [{"price": {"id": "price_mystery"}}]},
            ),
        )
        await db.commit()
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
    assert sub.tier == "growth"


async def test_a_stale_cancel_for_a_replaced_subscription_is_ignored(sessions, growth_price):
    """Upgrading creates a new Stripe subscription and cancels the old one. The
    old one's cancel event arriving late must not cancel the live plan."""
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await apply_subscription_event(
            db, _sub_event("customer.subscription.created", id="sub_new")
        )
        await db.commit()
        result = await apply_subscription_event(
            db,
            _sub_event("customer.subscription.deleted", id="sub_old", status="canceled"),
        )
        await db.commit()
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
    assert result["outcome"] == "ignored_stale_subscription"
    assert sub.status == "active"


async def test_subscription_deleted_cancels(sessions, growth_price):
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await apply_subscription_event(db, _sub_event("customer.subscription.created"))
        await db.commit()
        await apply_subscription_event(
            db, _sub_event("customer.subscription.deleted", status="canceled")
        )
        await db.commit()
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
    assert sub.status == "canceled"


async def test_payment_failure_marks_past_due_and_payment_clears_it(sessions, growth_price):
    async with sessions() as db:
        await ensure_subscription(db, business_id=str(BUSINESS_ID))
        await apply_subscription_event(db, _sub_event("customer.subscription.created"))
        await db.commit()

        await apply_subscription_event(
            db,
            {
                "type": "invoice.payment_failed",
                "data": {"object": {"customer": "cus_123"}},
            },
        )
        await db.commit()
        assert (await ensure_subscription(db, business_id=str(BUSINESS_ID))).status == "past_due"

        await apply_subscription_event(
            db, {"type": "invoice.paid", "data": {"object": {"customer": "cus_123"}}}
        )
        await db.commit()
        assert (await ensure_subscription(db, business_id=str(BUSINESS_ID))).status == "active"


async def test_an_invoice_paid_against_a_canceled_plan_does_not_reactivate(sessions):
    """A final proration invoice settles after cancellation. Paying it must not
    silently hand the account back."""
    async with sessions() as db:
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
        sub.stripe_customer_id = "cus_123"
        sub.status = "canceled"
        await db.commit()
        await apply_subscription_event(
            db, {"type": "invoice.paid", "data": {"object": {"customer": "cus_123"}}}
        )
        await db.commit()
        assert (await ensure_subscription(db, business_id=str(BUSINESS_ID))).status == "canceled"


async def test_events_for_an_unknown_tenant_are_ignored_not_crashed(sessions):
    async with sessions() as db:
        result = await apply_subscription_event(
            db,
            _sub_event(
                "customer.subscription.updated",
                customer="cus_nobody",
                metadata={},
            ),
        )
    assert result["outcome"] == "ignored_unknown_tenant"


async def test_a_malformed_business_id_is_ignored(sessions):
    async with sessions() as db:
        result = await apply_subscription_event(
            db,
            {
                "type": "checkout.session.completed",
                "data": {"object": {"client_reference_id": "not-a-uuid"}},
            },
        )
    assert result["outcome"] == "ignored_no_business_id"


async def test_unhandled_event_types_are_acknowledged(sessions):
    """Stripe retries 4xx. Acknowledging events we'll never handle keeps the
    blast radius of a new Stripe event type at zero."""
    async with sessions() as db:
        result = await apply_subscription_event(
            db, {"type": "radar.early_fraud_warning.created", "data": {"object": {}}}
        )
    assert result == {"status": "ignored", "type": "radar.early_fraud_warning.created"}


async def test_a_payload_without_an_object_is_ignored(sessions):
    async with sessions() as db:
        result = await apply_subscription_event(
            db, {"type": "customer.subscription.updated", "data": {"object": "nope"}}
        )
    assert result["reason"] == "unexpected_payload"


# -- API ----------------------------------------------------------------------


@pytest.fixture
async def client(sessions):
    async def _db():
        async with sessions() as session:
            yield session
            await session.commit()

    def _user() -> CurrentUser:
        return CurrentUser(
            user_id="u1",
            email="owner@hayward.coffee",
            business_id=str(BUSINESS_ID),
            business_name="Hayward Coffee Co.",
        )

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    fastapi_app.dependency_overrides.clear()


def test_plans_endpoint_returns_the_published_price_list(client):
    body = client.get("/api/billing/plans").json()
    assert [t["name"] for t in body["tiers"]] == ["starter", "growth", "pro"]
    assert body["trial_days"] == 14
    assert body["current_tier"] == "starter"
    growth = next(t for t in body["tiers"] if t["name"] == "growth")
    assert growth["monthly_price_usd"] == 299
    assert growth["annual_price_usd"] == 2990
    assert growth["channels"] == ["email", "sms"]


def test_subscription_endpoint_reports_the_trial(client):
    body = client.get("/api/billing/subscription").json()
    assert body["tier"] == "starter"
    assert body["status"] == "trialing"
    assert body["active"] is True
    assert body["trial_days_left"] == 14
    assert body["has_payment_method"] is False
    assert {m["key"] for m in body["meters"]} == {"customers", "integrations"}


def test_checkout_without_stripe_configured_is_a_503_not_a_500(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    resp = client.post("/api/billing/checkout", json={"tier": "growth"})
    assert resp.status_code == 503
    assert "configured" in resp.json()["detail"].lower()


def test_portal_before_any_checkout_explains_itself(client):
    resp = client.post("/api/billing/portal")
    assert resp.status_code == 503
    assert "pick a plan" in resp.json()["detail"]


def test_an_unknown_tier_is_rejected_by_validation(client):
    assert client.post("/api/billing/checkout", json={"tier": "enterprise"}).status_code == 422


def test_webhook_rejects_an_unsigned_delivery(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    resp = client.post("/api/billing/webhook", content=b'{"type":"invoice.paid"}')
    assert resp.status_code == 401


def test_webhook_is_unavailable_when_no_secret_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    resp = client.post("/api/billing/webhook", content=b"{}")
    assert resp.status_code == 503


def test_webhook_accepts_a_correctly_signed_delivery(client, monkeypatch):
    import hashlib
    import hmac

    secret = "whsec_test"
    monkeypatch.setattr(settings, "stripe_webhook_secret", secret)
    body = b'{"type":"radar.early_fraud_warning.created","data":{"object":{}}}'
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/billing/webhook",
        content=body,
        headers={"stripe-signature": f"t={ts},v1={sig}"},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"


# -- Enforcement at the gates -------------------------------------------------


async def _set_tier(sessions, tier: str) -> None:
    async with sessions() as db:
        sub = await ensure_subscription(db, business_id=str(BUSINESS_ID))
        sub.tier = tier
        sub.status = "active"
        await db.commit()


async def test_starter_cannot_create_an_sms_rule(client, sessions):
    await _set_tier(sessions, "starter")
    resp = client.post(
        "/api/automations/rules",
        json={"name": "Text the lapsed", "channel": "sms", "trigger_band": "high"},
    )
    assert resp.status_code == 402
    assert "Upgrade to Growth" in resp.json()["detail"]


async def test_starter_cannot_create_an_auto_mode_rule(client, sessions):
    await _set_tier(sessions, "starter")
    resp = client.post(
        "/api/automations/rules",
        json={"name": "Hands off", "channel": "email", "mode": "auto"},
    )
    assert resp.status_code == 402
    assert "Automation rules aren't included" in resp.json()["detail"]


async def test_starter_can_still_create_an_approve_mode_email_rule(client, sessions):
    """Approve-to-send is the default mode product-wide and is included on
    every plan - only hands-off 'auto' is gated."""
    await _set_tier(sessions, "starter")
    resp = client.post(
        "/api/automations/rules",
        json={"name": "Email the lapsed", "channel": "email", "mode": "approve"},
    )
    assert resp.status_code == 201


async def test_growth_can_create_an_sms_auto_rule(client, sessions):
    await _set_tier(sessions, "growth")
    resp = client.post(
        "/api/automations/rules",
        json={"name": "Text the lapsed", "channel": "sms", "mode": "auto"},
    )
    assert resp.status_code == 201


async def test_patching_an_email_rule_to_sms_is_gated(client, sessions):
    """The create-time gate alone would be bypassable by creating an email rule
    and patching the channel."""
    await _set_tier(sessions, "growth")
    rule_id = client.post(
        "/api/automations/rules",
        json={"name": "Email", "channel": "email", "mode": "approve"},
    ).json()["id"]
    await _set_tier(sessions, "starter")
    resp = client.patch(f"/api/automations/rules/{rule_id}", json={"channel": "sms"})
    assert resp.status_code == 402


async def test_starter_cannot_trigger_a_dispatch_run(client, sessions):
    await _set_tier(sessions, "starter")
    assert client.post("/api/automations/dispatch").status_code == 402


async def test_starter_cannot_generate_sms_copy(client, sessions):
    """Refused before an LLM call is spent on copy the plan can't send."""
    await _set_tier(sessions, "starter")
    resp = client.post(
        "/api/campaigns/generate",
        json={
            "business_name": "Hayward Coffee Co.",
            "business_type": "cafe",
            "customer_name": "Dana",
            "channel": "sms",
            "risk_reasons": ["No visits in 21 days"],
        },
    )
    assert resp.status_code == 402


async def test_going_over_the_customer_limit_does_not_block_anything(client, sessions):
    """The one test that pins the 'never hard-block' rule end to end."""
    await _set_tier(sessions, "starter")
    async with sessions() as db:
        for i in range(1_100):
            db.add(Customer(business_id=BUSINESS_ID, source="csv", email=f"c{i}@x.com"))
        await db.commit()

    body = client.get("/api/billing/subscription").json()
    customers = next(m for m in body["meters"] if m["key"] == "customers")
    assert customers["severity"] == "over"
    assert body["active"] is True
    # Still able to do the core job.
    assert client.get("/api/portfolio").status_code == 200
    assert (
        client.post(
            "/api/automations/rules",
            json={"name": "Email", "channel": "email", "mode": "approve"},
        ).status_code
        == 201
    )
