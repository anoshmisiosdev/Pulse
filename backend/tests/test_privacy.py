"""Data export and deletion — the CLAUDE.md compliance endpoint.

The assertion that matters most is the completeness one: a deletion request
that leaves a tenant's generated copy or chat transcripts behind hasn't deleted
anything that matters. ``test_a_full_deletion_leaves_no_tenant_rows_behind``
walks the metadata rather than a hand-written list, so a table added later
fails this test instead of silently escaping deletion.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import (
    AuditLog,
    AutomationRule,
    BrandKitVersion,
    Business,
    BusinessKnowledge,
    Campaign,
    CampaignSend,
    ChatConversation,
    ChatMessage,
    CompanyContextItem,
    Customer,
    CustomerIdentity,
    EngagementEvent,
    GenerationLog,
    IntegrationConnection,
    RecoveryAttribution,
    RiskScore,
    Subscription,
    SyncRun,
    Transaction,
    User,
    Visit,
)
from app.services import privacy

BUSINESS_ID = uuid.uuid4()
OTHER_BUSINESS_ID = uuid.uuid4()


def _user(business_id: uuid.UUID = BUSINESS_ID) -> CurrentUser:
    return CurrentUser(
        user_id="u1",
        email="owner@hayward.coffee",
        business_id=str(business_id),
        business_name="Hayward Coffee Co.",
    )


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p.db'}", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_everything(sessions, business_id: uuid.UUID = BUSINESS_ID) -> dict:
    """One row in every tenant-scoped table, for both the export and the purge."""
    now = datetime.now(UTC)
    naive = now.replace(tzinfo=None)
    async with sessions() as db:
        db.add(Business(id=business_id, name="Hayward Coffee Co.", vertical="cafe"))
        db.add(
            User(
                business_id=business_id,
                email="owner@hayward.coffee",
                role="owner",
                supabase_user_id="u1",
            )
        )
        db.add(Subscription(business_id=business_id, tier="growth", status="active"))
        db.add(
            IntegrationConnection(business_id=business_id, source="csv", status="connected")
        )
        db.add(SyncRun(business_id=business_id, source="csv", status="success"))

        customer = Customer(
            business_id=business_id,
            source="csv",
            first_name="Maria",
            last_name="Lopez",
            email="maria@example.com",
            phone="+15551112222",
        )
        db.add(customer)
        await db.flush()
        db.add(
            CustomerIdentity(
                business_id=business_id,
                customer_id=customer.id,
                source="csv",
                external_id="ext-1",
            )
        )
        db.add(
            Visit(
                business_id=business_id,
                customer_id=customer.id,
                source="csv",
                occurred_at=naive - timedelta(days=40),
            )
        )
        db.add(
            Transaction(
                business_id=business_id,
                customer_id=customer.id,
                source="csv",
                amount=85,
                occurred_at=naive - timedelta(days=40),
            )
        )
        db.add(
            RiskScore(
                business_id=business_id,
                customer_id=customer.id,
                score=82,
                band="high",
                reasons=["No visits in 40 days"],
            )
        )

        campaign = Campaign(
            business_id=business_id, name="October win-back", channel="email", status="sent"
        )
        db.add(campaign)
        await db.flush()
        send = CampaignSend(
            business_id=business_id,
            campaign_id=campaign.id,
            customer_id=customer.id,
            channel="email",
            subject="We miss you",
            body="Come back, Maria!",
            status="sent",
            sent_at=now,
        )
        db.add(send)
        await db.flush()
        db.add(
            EngagementEvent(
                business_id=business_id,
                customer_id=customer.id,
                campaign_send_id=send.id,
                kind="email_open",
                occurred_at=now,
            )
        )
        db.add(
            RecoveryAttribution(
                business_id=business_id,
                customer_id=customer.id,
                campaign_send_id=send.id,
                estimated_value=640,
                recovered_at=now,
            )
        )
        db.add(
            AutomationRule(business_id=business_id, name="Nightly high-risk", channel="email")
        )
        db.add(
            BusinessKnowledge(
                business_id=business_id,
                kind="brand_voice",
                content="Warm and local",
                embedding=[0.0] * 8,
            )
        )
        db.add(
            GenerationLog(
                business_id=business_id,
                purpose="campaign_email",
                system_prompt="sys",
                user_prompt="Customer: Maria Lopez",
                raw_output="Come back, Maria!",
                customer_id=customer.id,
                campaign_send_id=send.id,
            )
        )
        db.add(
            AuditLog(
                business_id=business_id,
                action="send_approved",
                actor_email="owner@hayward.coffee",
                summary="Approved a send for Maria Lopez",
            )
        )

        conversation = ChatConversation(business_id=business_id, title="Who is at risk?")
        db.add(conversation)
        await db.flush()
        db.add(
            ChatMessage(
                business_id=business_id,
                conversation_id=conversation.id,
                role="user",
                content="Who is at risk?",
            )
        )
        db.add(
            BrandKitVersion(
                business_id=business_id,
                version=1,
                name="Hayward Coffee Co.",
                tagline="Your morning, sorted",
                audience="locals",
                tone="warm",
                positioning="The friendly corner cafe",
                avoid=[],
                color_primary="#b4532a",
                color_secondary="#2a3b4c",
                color_accent="#f0c060",
                color_background="#fffdf8",
                color_text="#1a1a1a",
                heading_family="Inter",
                body_family="Inter",
            )
        )
        db.add(
            CompanyContextItem(
                business_id=business_id,
                title="Second location",
                kind="note",
                summary="Opening in spring",
                public_safe=False,
            )
        )
        await db.commit()
        return {"customer_id": str(customer.id), "send_id": str(send.id)}


@pytest.fixture
async def client(sessions):
    async def _db():
        async with sessions() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: _user()
    yield TestClient(app)
    fastapi_app.dependency_overrides.clear()


# -- Coverage ------------------------------------------------------------------


def test_every_tenant_scoped_table_is_either_deleted_or_deliberately_kept():
    """Walks the metadata, so a table added later fails here rather than
    silently escaping a deletion request."""
    scoped = {
        name for name, table in Base.metadata.tables.items() if "business_id" in table.c
    }
    covered = {model.__tablename__ for model in privacy.ALL_TABLES}
    # audit_logs is purged inside delete_business_data for scope="all"; the
    # other two are kept on purpose (see privacy.ALL_TABLES).
    deliberately_kept = {"audit_logs", "subscriptions", "users"}
    assert scoped - covered == deliberately_kept


async def test_a_full_deletion_leaves_no_tenant_rows_behind(sessions):
    await _seed_everything(sessions)
    async with sessions() as db:
        report = await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="all", actor=_user()
        )
        await db.commit()

    assert report.total > 0
    async with sessions() as db:
        for model in privacy.ALL_TABLES:
            remaining = await db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.business_id == BUSINESS_ID)
            )
            assert remaining == 0, f"{model.__tablename__} still has rows"


async def test_a_full_deletion_clears_prior_audit_rows_that_could_name_a_customer(
    sessions,
):
    await _seed_everything(sessions)
    async with sessions() as db:
        await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="all", actor=_user()
        )
        await db.commit()

    async with sessions() as db:
        rows = (await db.execute(select(AuditLog))).scalars().all()
    # Exactly one row survives: the record that the deletion happened.
    assert len(rows) == 1
    assert rows[0].action == "data_deleted"
    assert "Maria Lopez" not in rows[0].summary


async def test_the_deletion_itself_is_recorded_with_counts_not_content(sessions):
    await _seed_everything(sessions)
    async with sessions() as db:
        await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="all", actor=_user()
        )
        await db.commit()
    async with sessions() as db:
        row = (await db.execute(select(AuditLog))).scalars().one()
    assert "customers=1" in row.summary
    assert row.actor_email == "owner@hayward.coffee"
    assert "Come back, Maria" not in row.summary


async def test_billing_and_logins_survive_a_deletion(sessions):
    """Dropping the subscription would leave a paying tenant with no plan while
    Stripe keeps charging; dropping the login would make the confirmation
    screen unreachable."""
    await _seed_everything(sessions)
    async with sessions() as db:
        await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="all", actor=_user()
        )
        await db.commit()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Subscription)) == 1
        assert await db.scalar(select(func.count()).select_from(User)) == 1


async def test_deletion_never_touches_another_tenant(sessions):
    await _seed_everything(sessions)
    await _seed_everything(sessions, business_id=OTHER_BUSINESS_ID)
    async with sessions() as db:
        await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="all", actor=_user()
        )
        await db.commit()
    async with sessions() as db:
        theirs = await db.scalar(
            select(func.count())
            .select_from(Customer)
            .where(Customer.business_id == OTHER_BUSINESS_ID)
        )
    assert theirs == 1


async def test_the_retention_scope_spares_the_brand_kit_and_assistant(sessions):
    """"Re-import my customers and start the scores over" is a support request,
    not a privacy deletion, and shouldn't destroy a brand kit."""
    await _seed_everything(sessions)
    async with sessions() as db:
        await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="retention", actor=_user()
        )
        await db.commit()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customer)) == 0
        assert await db.scalar(select(func.count()).select_from(BrandKitVersion)) == 1
        assert await db.scalar(select(func.count()).select_from(ChatConversation)) == 1
        assert await db.scalar(select(func.count()).select_from(BusinessKnowledge)) == 1


async def test_an_unknown_scope_is_refused(sessions):
    await _seed_everything(sessions)
    async with sessions() as db:
        with pytest.raises(ValueError, match="scope must be one of"):
            await privacy.delete_business_data(
                db, business_id=str(BUSINESS_ID), scope="everything"
            )


async def test_deleting_from_an_empty_tenant_reports_nothing_rather_than_failing(sessions):
    async with sessions() as db:
        db.add(Business(id=BUSINESS_ID, name="Fresh", vertical="cafe"))
        await db.commit()
    async with sessions() as db:
        report = await privacy.delete_business_data(
            db, business_id=str(BUSINESS_ID), scope="all", actor=_user()
        )
        await db.commit()
    assert report.total == 0
    assert "nothing to delete" in report.deleted.__str__() or report.deleted == {}


# -- Single customer erasure ---------------------------------------------------


async def test_deleting_one_customer_removes_all_their_history(sessions):
    ids = await _seed_everything(sessions)
    async with sessions() as db:
        assert await privacy.delete_customer(
            db, business_id=str(BUSINESS_ID), customer_id=ids["customer_id"], actor=_user()
        )
        await db.commit()

    async with sessions() as db:
        for model in (
            Visit,
            Transaction,
            RiskScore,
            CustomerIdentity,
            CampaignSend,
            EngagementEvent,
            RecoveryAttribution,
        ):
            assert (
                await db.scalar(select(func.count()).select_from(model))
            ) == 0, model.__tablename__
        assert await db.scalar(select(func.count()).select_from(Customer)) == 0
        # The campaign itself survives — it's business history, not personal data.
        assert await db.scalar(select(func.count()).select_from(Campaign)) == 1


async def test_deleting_a_customer_also_removes_prompts_containing_their_name(sessions):
    """A deletion that leaves the customer's name inside a stored prompt hasn't
    deleted them."""
    ids = await _seed_everything(sessions)
    async with sessions() as db:
        await privacy.delete_customer(
            db, business_id=str(BUSINESS_ID), customer_id=ids["customer_id"], actor=_user()
        )
        await db.commit()
    async with sessions() as db:
        logs = (await db.execute(select(GenerationLog))).scalars().all()
    assert logs == []


async def test_the_customer_erasure_audit_row_does_not_record_the_name(sessions):
    ids = await _seed_everything(sessions)
    async with sessions() as db:
        await privacy.delete_customer(
            db, business_id=str(BUSINESS_ID), customer_id=ids["customer_id"], actor=_user()
        )
        await db.commit()
    async with sessions() as db:
        rows = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "data_deleted")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert "Maria" not in rows[0].summary
    assert rows[0].subject_id == ids["customer_id"]


async def test_deleting_another_tenants_customer_is_refused(sessions):
    await _seed_everything(sessions)
    other = await _seed_everything(sessions, business_id=OTHER_BUSINESS_ID)
    async with sessions() as db:
        assert not await privacy.delete_customer(
            db, business_id=str(BUSINESS_ID), customer_id=other["customer_id"]
        )
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Customer)
                .where(Customer.business_id == OTHER_BUSINESS_ID)
            )
        ) == 1


async def test_deleting_a_malformed_customer_id_is_refused_not_crashed(sessions):
    await _seed_everything(sessions)
    async with sessions() as db:
        assert not await privacy.delete_customer(
            db, business_id=str(BUSINESS_ID), customer_id="not-a-uuid"
        )


# -- Export --------------------------------------------------------------------


async def test_the_export_includes_generated_copy_and_assistant_transcripts(sessions):
    """"A copy of my data" means what the product produced about their
    customers as much as what it ingested."""
    await _seed_everything(sessions)
    async with sessions() as db:
        payload = await privacy.export_business_data(db, business_id=str(BUSINESS_ID))

    assert payload["business"]["name"] == "Hayward Coffee Co."
    assert len(payload["customers"]) == 1
    assert payload["customers"][0]["email"] == "maria@example.com"
    assert payload["campaign_sends"][0]["body"] == "Come back, Maria!"
    assert payload["recoveries"][0]["estimated_value"] == 640.0
    assert payload["assistant_conversations"][0]["messages"][0]["content"] == (
        "Who is at risk?"
    )
    assert payload["business_knowledge"][0]["content"] == "Warm and local"
    assert payload["audit_log"]


async def test_the_export_is_scoped_to_one_tenant(sessions):
    await _seed_everything(sessions)
    await _seed_everything(sessions, business_id=OTHER_BUSINESS_ID)
    async with sessions() as db:
        payload = await privacy.export_business_data(db, business_id=str(BUSINESS_ID))
    assert len(payload["customers"]) == 1
    assert len(payload["campaigns"]) == 1


async def test_the_export_is_json_serializable(sessions):
    """It's handed to a browser as a download, so it has to survive dumps()."""
    await _seed_everything(sessions)
    async with sessions() as db:
        payload = await privacy.export_business_data(db, business_id=str(BUSINESS_ID))
    assert json.loads(json.dumps(payload, default=str))


# -- API -----------------------------------------------------------------------


async def test_the_export_endpoint_returns_a_download(client, sessions):
    await _seed_everything(sessions)
    resp = client.get("/api/privacy/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "churnary-data-export.json" in resp.headers["content-disposition"]
    assert resp.json()["customers"][0]["first_name"] == "Maria"


async def test_an_export_is_recorded_in_the_audit_log(client, sessions):
    await _seed_everything(sessions)
    client.get("/api/privacy/export")
    async with sessions() as db:
        actions = [
            r.action
            for r in (await db.execute(select(AuditLog))).scalars().all()
        ]
    assert "data_export_requested" in actions


async def test_deletion_requires_an_explicit_typed_confirmation(client, sessions):
    """Irreversible and un-undoable, so it must not be reachable by a stray POST."""
    await _seed_everything(sessions)
    resp = client.post("/api/privacy/delete", json={"scope": "all"})
    assert resp.status_code == 422
    assert "Nothing was deleted" in resp.json()["detail"]

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customer)) == 1


async def test_a_wrong_confirmation_phrase_deletes_nothing(client, sessions):
    await _seed_everything(sessions)
    resp = client.post("/api/privacy/delete", json={"scope": "all", "confirm": "yes"})
    assert resp.status_code == 422
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customer)) == 1


async def test_a_confirmed_deletion_reports_what_it_removed(client, sessions):
    await _seed_everything(sessions)
    resp = client.post("/api/privacy/delete", json={"scope": "all", "confirm": "DELETE "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "all"
    assert body["rows_deleted"] > 0
    assert body["deleted"]["customers"] == 1


async def test_the_delete_endpoint_rejects_an_unknown_scope(client, sessions):
    await _seed_everything(sessions)
    resp = client.post("/api/privacy/delete", json={"scope": "nonsense", "confirm": "delete"})
    assert resp.status_code == 422


async def test_the_single_customer_endpoint_deletes_and_404s_appropriately(client, sessions):
    ids = await _seed_everything(sessions)
    assert client.delete(f"/api/privacy/customers/{ids['customer_id']}").status_code == 204
    assert client.delete(f"/api/privacy/customers/{ids['customer_id']}").status_code == 404
    assert client.delete("/api/privacy/customers/not-a-uuid").status_code == 404
