"""The owner-driven campaign loop: build, review, edit, approve, measure.

The LLM is stubbed throughout - this is about persistence, consent, approval
and the A/B statistics, not about copy quality.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.campaigns.experiments import MIN_PER_ARM, ArmResult, compare
from app.campaigns.generator import GeneratedCopy
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import (
    AuditLog,
    Business,
    Campaign,
    CampaignSend,
    Customer,
    GenerationLog,
    RecoveryAttribution,
    Subscription,
    Transaction,
    Visit,
)
from app.services.rag.embeddings import EmbeddingError

BUSINESS_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def stub_llm_and_senders(monkeypatch):
    """No network. Generation returns deterministic copy; sends always succeed.

    ``is_quiet_hours`` is pinned open so SMS assertions don't depend on what
    time the suite runs - the quiet-hours path has its own test.
    """

    async def _batch(contexts):
        return [
            GeneratedCopy(
                body=f"Hi {c.customer_name}, come back! ({c.incentive or 'no offer'})",
                subject=(None if c.channel == "sms" else f"We miss you, {c.customer_name}"),
                generated_by="claude",
                model="test-model",
            )
            for c in contexts
        ]

    async def _single(ctx):
        return (await _batch([ctx]))[0]

    async def _single_traced(ctx):
        from app.campaigns.generator import GenerationTrace

        return (
            await _single(ctx),
            GenerationTrace(
                system_prompt="sys", user_prompt="usr", raw_output="{}", model="test-model"
            ),
        )

    from app.services import senders

    async def _ok(*_a, **_k):
        return senders.SendResult(ok=True, provider_message_id="prov_1")

    monkeypatch.setattr("app.campaigns.manual.generate_campaigns_batch", _batch)
    monkeypatch.setattr("app.campaigns.generator.generate_campaign_traced", _single_traced)
    monkeypatch.setattr("app.api.campaigns.generate_campaign_traced", _single_traced)
    monkeypatch.setattr("app.services.automations.send_email", _ok)
    monkeypatch.setattr("app.services.automations.send_sms", _ok)
    monkeypatch.setattr("app.services.automations.is_quiet_hours", lambda *_a, **_k: False)
    # No Bedrock here. Raising EmbeddingError exercises the real degrade path:
    # retrieval returns no context and generation carries on without it.
    async def _no_embeddings(*_a, **_k):
        raise EmbeddingError("no embeddings in tests")

    monkeypatch.setattr("app.services.rag.knowledge_store.embed_query", _no_embeddings)


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


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


async def _seed(sessions, *, count: int = 3, tier: str = "growth") -> list[str]:
    """A business with `count` lapsed customers who each have visit history."""
    ids: list[str] = []
    now = datetime.now(UTC).replace(tzinfo=None)
    async with sessions() as db:
        db.add(Business(id=BUSINESS_ID, name="Hayward Coffee Co.", vertical="cafe"))
        db.add(Subscription(business_id=BUSINESS_ID, tier=tier, status="active"))
        for i in range(count):
            customer = Customer(
                business_id=BUSINESS_ID,
                source="csv",
                first_name=f"Cust{i}",
                last_name="Example",
                email=f"cust{i}@example.com",
                phone=f"+1555000{i:04d}",
            )
            db.add(customer)
            await db.flush()
            ids.append(str(customer.id))
            for week in range(8):
                db.add(
                    Visit(
                        business_id=BUSINESS_ID,
                        customer_id=customer.id,
                        source="csv",
                        occurred_at=now - timedelta(days=40 + week * 7),
                    )
                )
            db.add(
                Transaction(
                    business_id=BUSINESS_ID,
                    customer_id=customer.id,
                    source="csv",
                    amount=45,
                    occurred_at=now - timedelta(days=40),
                )
            )
        await db.commit()
    return ids


# -- Build --------------------------------------------------------------------


async def test_creating_a_campaign_queues_pending_sends_and_sends_nothing(client, sessions):
    """Approve-to-send is the default: building a campaign must not deliver."""
    ids = await _seed(sessions)
    resp = client.post(
        "/api/campaigns",
        json={
            "name": "October win-back",
            "channel": "email",
            "customer_ids": ids,
            "incentive": "20% off",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending_approval"
    assert body["stats"]["total"] == 3
    assert body["stats"]["pending"] == 3
    assert body["stats"]["sent"] == 0
    assert all(s["status"] == "pending" for s in body["sends"])
    assert all(s["subject"] for s in body["sends"])
    assert "20% off" in body["sends"][0]["body"]


async def test_every_generation_is_logged_with_model_and_prompts(client, sessions):
    """CLAUDE.md requires prompt + output + model version for every generation."""
    ids = await _seed(sessions)
    client.post(
        "/api/campaigns",
        json={"name": "Logged", "channel": "email", "customer_ids": ids},
    )
    async with sessions() as db:
        logs = (await db.execute(select(GenerationLog))).scalars().all()
    assert len(logs) == 3
    assert all(log.model == "test-model" for log in logs)
    assert all(log.purpose == "campaign_email" for log in logs)
    assert all(log.user_prompt for log in logs)
    assert all(log.campaign_send_id is not None for log in logs)


async def test_unsubscribed_customers_are_excluded_with_a_visible_reason(client, sessions):
    """An owner should see who was left out, not silently get fewer sends."""
    ids = await _seed(sessions)
    async with sessions() as db:
        customer = await db.get(Customer, uuid.UUID(ids[0]))
        customer.unsubscribed_email = True
        await db.commit()

    body = client.post(
        "/api/campaigns",
        json={"name": "Respect consent", "channel": "email", "customer_ids": ids},
    ).json()
    assert body["stats"]["total"] == 2
    assert body["skipped"][ids[0]] == "unsubscribed_email"


async def test_do_not_contact_is_honored(client, sessions):
    ids = await _seed(sessions)
    async with sessions() as db:
        customer = await db.get(Customer, uuid.UUID(ids[0]))
        customer.do_not_contact = True
        await db.commit()
    body = client.post(
        "/api/campaigns",
        json={"name": "DNC", "channel": "email", "customer_ids": ids},
    ).json()
    assert body["skipped"][ids[0]] == "do_not_contact"


async def test_a_customer_with_no_phone_cannot_be_texted(client, sessions):
    ids = await _seed(sessions)
    async with sessions() as db:
        customer = await db.get(Customer, uuid.UUID(ids[0]))
        customer.phone = None
        await db.commit()
    body = client.post(
        "/api/campaigns",
        json={"name": "SMS", "channel": "sms", "customer_ids": ids},
    ).json()
    assert body["skipped"][ids[0]] == "no_phone_on_file"


async def test_duplicate_selections_are_messaged_once(client, sessions):
    ids = await _seed(sessions, count=2)
    body = client.post(
        "/api/campaigns",
        json={"name": "Dupes", "channel": "email", "customer_ids": [ids[0], ids[0], ids[1]]},
    ).json()
    assert body["stats"]["total"] == 2


async def test_an_empty_selection_is_rejected(client, sessions):
    await _seed(sessions)
    resp = client.post(
        "/api/campaigns", json={"name": "Nobody", "channel": "email", "customer_ids": []}
    )
    assert resp.status_code == 422


async def test_another_tenants_customer_ids_are_ignored(client, sessions):
    """Tenant isolation: ids from someone else's business must not be messaged."""
    ids = await _seed(sessions)
    other_business = uuid.uuid4()
    async with sessions() as db:
        db.add(Business(id=other_business, name="Rival", vertical="salon"))
        theirs = Customer(business_id=other_business, source="csv", email="theirs@x.com")
        db.add(theirs)
        await db.commit()
        foreign_id = str(theirs.id)

    body = client.post(
        "/api/campaigns",
        json={"name": "Cross-tenant", "channel": "email", "customer_ids": [ids[0], foreign_id]},
    ).json()
    assert body["stats"]["total"] == 1
    assert body["skipped"][foreign_id] == "not_found"


async def test_a_campaign_where_nobody_is_reachable_is_marked_failed(client, sessions):
    ids = await _seed(sessions, count=1)
    async with sessions() as db:
        customer = await db.get(Customer, uuid.UUID(ids[0]))
        customer.do_not_contact = True
        await db.commit()
    body = client.post(
        "/api/campaigns",
        json={"name": "Nobody reachable", "channel": "email", "customer_ids": ids},
    ).json()
    assert body["status"] == "failed"
    assert body["stats"]["total"] == 0


# -- Review -------------------------------------------------------------------


async def test_editing_a_pending_send_marks_it_owner_edited(client, sessions):
    """The dashboard shouldn't keep crediting Claude for copy a human rewrote."""
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Edit me", "channel": "email", "customer_ids": ids}
    ).json()
    send_id = detail["sends"][0]["id"]

    resp = client.patch(
        f"/api/campaigns/sends/{send_id}",
        json={"subject": "My own subject", "body": "My own words"},
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "My own words"
    assert resp.json()["subject"] == "My own subject"
    assert resp.json()["generated_by"] == "owner_edited"


async def test_an_edit_is_recorded_in_the_audit_log(client, sessions):
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Audited", "channel": "email", "customer_ids": ids}
    ).json()
    client.patch(
        f"/api/campaigns/sends/{detail['sends'][0]['id']}", json={"body": "Rewritten"}
    )
    async with sessions() as db:
        actions = [
            row.action for row in (await db.execute(select(AuditLog))).scalars().all()
        ]
    assert "campaign_created" in actions
    assert "send_edited" in actions


async def test_cancelling_a_send_skips_it(client, sessions):
    ids = await _seed(sessions, count=2)
    detail = client.post(
        "/api/campaigns", json={"name": "Cancel one", "channel": "email", "customer_ids": ids}
    ).json()
    send_id = detail["sends"][0]["id"]

    assert client.post(f"/api/campaigns/sends/{send_id}/cancel").status_code == 200
    summary = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    assert summary["sent"] == 1


async def test_a_sent_message_cannot_be_edited_afterwards(client, sessions):
    """Once something is sent, the record of what was sent must stay accurate."""
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Immutable", "channel": "email", "customer_ids": ids}
    ).json()
    client.post(f"/api/campaigns/{detail['id']}/approve")

    resp = client.patch(
        f"/api/campaigns/sends/{detail['sends'][0]['id']}", json={"body": "Too late"}
    )
    assert resp.status_code == 422
    assert "can't be edited" in resp.json()["detail"]


async def test_regenerating_replaces_the_copy(client, sessions):
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Regen", "channel": "email", "customer_ids": ids}
    ).json()
    send_id = detail["sends"][0]["id"]
    resp = client.post(f"/api/campaigns/sends/{send_id}/regenerate")
    assert resp.status_code == 200
    assert resp.json()["body"]
    assert resp.json()["status"] == "pending"


async def test_sends_from_another_tenant_are_not_reachable(client, sessions):
    await _seed(sessions)
    other = uuid.uuid4()
    async with sessions() as db:
        db.add(Business(id=other, name="Rival", vertical="salon"))
        customer = Customer(business_id=other, source="csv", email="x@x.com")
        db.add(customer)
        campaign = Campaign(business_id=other, name="Theirs", channel="email")
        db.add(campaign)
        await db.flush()
        send = CampaignSend(
            business_id=other,
            campaign_id=campaign.id,
            customer_id=customer.id,
            channel="email",
            body="theirs",
            status="pending",
        )
        db.add(send)
        await db.commit()
        send_id, campaign_id = str(send.id), str(campaign.id)

    assert client.patch(f"/api/campaigns/sends/{send_id}", json={"body": "x"}).status_code == 404
    assert client.get(f"/api/campaigns/{campaign_id}").status_code == 404
    assert client.post(f"/api/campaigns/{campaign_id}/approve").status_code == 404


async def test_a_malformed_id_is_a_404_not_a_500(client, sessions):
    await _seed(sessions)
    assert client.get("/api/campaigns/not-a-uuid").status_code == 404


# -- Approve ------------------------------------------------------------------


async def test_approving_a_campaign_sends_everything_pending(client, sessions):
    ids = await _seed(sessions)
    detail = client.post(
        "/api/campaigns", json={"name": "Ship it", "channel": "email", "customer_ids": ids}
    ).json()

    summary = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    assert summary == {"sent": 3, "failed": 0, "deferred": 0, "skipped": {}}

    after = client.get(f"/api/campaigns/{detail['id']}").json()
    assert after["status"] == "sent"
    assert after["stats"]["sent"] == 3
    assert all(s["sent_at"] for s in after["sends"])


async def test_consent_revoked_after_generation_blocks_the_send(client, sessions):
    """An owner can approve days after the copy was written. Someone who replied
    STOP in between must not be messaged."""
    ids = await _seed(sessions, count=2)
    detail = client.post(
        "/api/campaigns", json={"name": "Late approve", "channel": "sms", "customer_ids": ids}
    ).json()
    async with sessions() as db:
        customer = await db.get(Customer, uuid.UUID(ids[0]))
        customer.unsubscribed_sms = True
        await db.commit()

    summary = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    assert summary["sent"] == 1
    assert summary["skipped"] == {"unsubscribed_sms": 1}


async def test_quiet_hours_defer_an_sms_campaign_without_failing_it(client, sessions, monkeypatch):
    """TCPA: held, not failed - the campaign stays 'sending' so a later tick
    picks it up rather than the owner thinking it went out."""
    monkeypatch.setattr("app.services.automations.is_quiet_hours", lambda *_a, **_k: True)
    ids = await _seed(sessions, count=2)
    detail = client.post(
        "/api/campaigns", json={"name": "2am", "channel": "sms", "customer_ids": ids}
    ).json()

    summary = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    assert summary["deferred"] == 2
    assert summary["sent"] == 0
    assert client.get(f"/api/campaigns/{detail['id']}").json()["status"] == "sending"


async def test_approving_twice_does_not_resend(client, sessions):
    ids = await _seed(sessions, count=2)
    detail = client.post(
        "/api/campaigns", json={"name": "Idempotent", "channel": "email", "customer_ids": ids}
    ).json()
    first = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    second = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    assert first["sent"] == 2
    assert second["sent"] == 0


async def test_a_send_with_no_copy_is_held_rather_than_sent_blank(client, sessions):
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Blank", "channel": "email", "customer_ids": ids}
    ).json()
    async with sessions() as db:
        send = await db.get(CampaignSend, uuid.UUID(detail["sends"][0]["id"]))
        send.body = "   "
        await db.commit()

    summary = client.post(f"/api/campaigns/{detail['id']}/approve").json()
    assert summary["sent"] == 0
    assert summary["skipped"] == {"no_copy": 1}


async def test_the_campaign_list_reports_stats(client, sessions):
    ids = await _seed(sessions, count=2)
    detail = client.post(
        "/api/campaigns", json={"name": "Listed", "channel": "email", "customer_ids": ids}
    ).json()
    client.post(f"/api/campaigns/{detail['id']}/approve")

    rows = client.get("/api/campaigns").json()
    assert len(rows) == 1
    assert rows[0]["stats"]["sent"] == 2
    assert rows[0]["stats"]["recovered"] == 0


# -- A/B statistics (pure) ----------------------------------------------------


def _arm(variant, sent, recovered, revenue=0.0):
    return ArmResult(variant=variant, sent=sent, recovered=recovered, revenue_recovered=revenue)


def test_an_underpowered_test_refuses_to_pick_a_winner():
    """The honesty constraint: 3 recoveries vs 1 on tiny arms is noise, and
    telling an owner 'B wins' would make them rewrite copy on nothing."""
    result = compare(_arm("A", 10, 1), _arm("B", 10, 3))
    assert not result.confident
    assert result.winner is None
    assert "Too early to tell" in result.verdict


def test_the_shortfall_message_counts_the_smaller_arm():
    result = compare(_arm("A", 19, 2), _arm("B", 40, 9))
    assert f"{MIN_PER_ARM - 19} more" in result.verdict


def test_a_close_result_on_adequate_samples_reports_no_clear_winner():
    result = compare(_arm("A", 100, 10), _arm("B", 100, 12))
    assert not result.confident
    assert result.winner is None
    assert "No clear winner" in result.verdict


def test_a_large_difference_on_adequate_samples_names_the_winner():
    result = compare(_arm("A", 200, 10), _arm("B", 200, 50))
    assert result.confident
    assert result.winner == "B"
    assert result.lift_pp == 20.0
    assert "Version B won" in result.verdict


def test_variant_a_can_win_too():
    result = compare(_arm("A", 200, 50), _arm("B", 200, 10))
    assert result.winner == "A"
    assert result.lift_pp == -20.0


def test_zero_recoveries_on_both_arms_is_not_a_winner():
    """A pooled rate of 0 makes the z-statistic undefined, which must read as
    'no signal' rather than crashing or declaring a tie a victory."""
    result = compare(_arm("A", 100, 0), _arm("B", 100, 0))
    assert not result.confident
    assert result.winner is None


def test_an_empty_arm_does_not_divide_by_zero():
    result = compare(_arm("A", 0, 0), _arm("B", 50, 5))
    assert not result.confident
    assert result.a.recovery_rate == 0.0


# -- A/B end to end -----------------------------------------------------------


async def test_an_ab_campaign_splits_evenly_and_alternates(client, sessions):
    ids = await _seed(sessions, count=5)
    detail = client.post(
        "/api/campaigns",
        json={
            "name": "Offer test",
            "channel": "email",
            "customer_ids": ids,
            "incentive": "10% off",
            "ab_test": True,
            "variant_b_incentive": "Free drink",
        },
    ).json()

    variants = [s["variant"] for s in detail["sends"]]
    assert variants == ["A", "B", "A", "B", "A"]
    bodies = {s["variant"]: s["body"] for s in detail["sends"]}
    assert "10% off" in bodies["A"]
    assert "Free drink" in bodies["B"]


async def test_ab_results_count_recoveries_per_variant(client, sessions):
    ids = await _seed(sessions, count=4)
    detail = client.post(
        "/api/campaigns",
        json={"name": "Measured", "channel": "email", "customer_ids": ids, "ab_test": True},
    ).json()
    client.post(f"/api/campaigns/{detail['id']}/approve")

    # Attribute one recovery to a B recipient.
    b_send = next(s for s in detail["sends"] if s["variant"] == "B")
    async with sessions() as db:
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(b_send["customer_id"]),
                campaign_send_id=uuid.UUID(b_send["id"]),
                estimated_value=320,
                recovered_at=datetime.now(UTC),
            )
        )
        await db.commit()

    result = client.get(f"/api/campaigns/{detail['id']}/experiment").json()
    assert result["a"]["sent"] == 2
    assert result["b"]["sent"] == 2
    assert result["b"]["recovered"] == 1
    assert result["b"]["revenue_recovered"] == 320.0
    # Two per arm is nowhere near enough to call.
    assert result["confident"] is False
    assert result["winner"] is None


async def test_asking_for_experiment_results_on_a_normal_campaign_is_rejected(client, sessions):
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Not a test", "channel": "email", "customer_ids": ids}
    ).json()
    resp = client.get(f"/api/campaigns/{detail['id']}/experiment")
    assert resp.status_code == 422


# -- Transparency endpoints ---------------------------------------------------


async def test_the_generation_log_endpoint_returns_prompts_and_models(client, sessions):
    ids = await _seed(sessions, count=1)
    client.post(
        "/api/campaigns", json={"name": "Traceable", "channel": "email", "customer_ids": ids}
    )
    rows = client.get("/api/campaigns/logs/generations").json()
    assert rows
    assert rows[0]["model"] == "test-model"
    assert rows[0]["purpose"] == "campaign_email"
    assert rows[0]["user_prompt"]


async def test_the_audit_log_endpoint_can_filter_by_action(client, sessions):
    ids = await _seed(sessions, count=1)
    detail = client.post(
        "/api/campaigns", json={"name": "Audit", "channel": "email", "customer_ids": ids}
    ).json()
    client.post(f"/api/campaigns/{detail['id']}/approve")

    launched = client.get("/api/campaigns/logs/audit?action=campaign_launched").json()
    assert len(launched) == 1
    assert "Approved campaign" in launched[0]["summary"]
    assert launched[0]["actor_email"] == "owner@hayward.coffee"


async def test_logs_are_scoped_to_the_tenant(client, sessions):
    await _seed(sessions, count=1)
    other = uuid.uuid4()
    async with sessions() as db:
        db.add(
            GenerationLog(
                business_id=other,
                purpose="campaign_email",
                system_prompt="theirs",
                user_prompt="theirs",
            )
        )
        db.add(AuditLog(business_id=other, action="send_approved", summary="theirs"))
        await db.commit()

    assert client.get("/api/campaigns/logs/generations").json() == []
    assert client.get("/api/campaigns/logs/audit").json() == []
