"""Cohort retention, score explainability, segments, CSV export, and the digest.

The cohort and digest-copy tests work on literal inputs, because that's the
point of keeping the maths and the templating pure.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app
from app.models import (
    Business,
    CampaignSend,
    Customer,
    RecoveryAttribution,
    Subscription,
    Transaction,
    User,
    Visit,
)
from app.services import insights
from app.services.digest import (
    DigestFacts,
    build_digest_copy,
    collect_facts,
    fallback_digest,
)

BUSINESS_ID = uuid.uuid4()


def _user() -> CurrentUser:
    return CurrentUser(
        user_id="u1",
        email="owner@hayward.coffee",
        business_id=str(BUSINESS_ID),
        business_name="Hayward Coffee Co.",
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from app.services.rag.embeddings import EmbeddingError

    async def _no_embeddings(*_a, **_k):
        raise EmbeddingError("no embeddings in tests")

    monkeypatch.setattr("app.services.rag.knowledge_store.embed_query", _no_embeddings)
    # No LLM by default, so digest copy comes from the deterministic template.
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "bedrock_chat_model", "")
    monkeypatch.setattr(settings, "token_router_api_key", "")


# -- Cohorts (pure) -----------------------------------------------------------


def test_a_cohort_starts_at_full_retention():
    """Offset 0 is the acquisition month, so it's 100% by construction — a chart
    starting at month 1 reads as unexplained first-month churn."""
    cohorts = insights.build_cohorts(
        {"a": date(2026, 1, 10), "b": date(2026, 1, 20)},
        {"a": {"2026-01"}, "b": {"2026-01"}},
    )
    assert len(cohorts) == 1
    assert cohorts[0].cohort_month == "2026-01"
    assert cohorts[0].size == 2
    assert cohorts[0].retention_at(0) == 1.0


def test_retention_decays_as_customers_stop_visiting():
    cohorts = insights.build_cohorts(
        {
            "a": date(2026, 1, 5),
            "b": date(2026, 1, 6),
            "c": date(2026, 1, 7),
            "d": date(2026, 1, 8),
        },
        {
            "a": {"2026-01", "2026-02", "2026-03"},
            "b": {"2026-01", "2026-02"},
            "c": {"2026-01", "2026-02"},
            "d": {"2026-01"},
        },
    )
    cohort = cohorts[0]
    assert cohort.retention_at(0) == 1.0
    assert cohort.retention_at(1) == 0.75
    assert cohort.retention_at(2) == 0.25


def test_cohorts_span_month_and_year_boundaries():
    """December to January must be offset 1, not -11."""
    cohorts = insights.build_cohorts(
        {"a": date(2025, 12, 15)}, {"a": {"2025-12", "2026-01"}}
    )
    assert cohorts[0].retention_at(1) == 1.0


def test_a_small_cohort_is_reported_but_flagged():
    """A retention curve drawn from four people per cohort looks authoritative
    and means nothing, so it carries its own warning."""
    small = insights.build_cohorts({"a": date(2026, 1, 1)}, {"a": {"2026-01"}})[0]
    assert small.size == 1
    assert not small.meaningful

    many = {f"c{i}": date(2026, 1, 1) for i in range(insights.MIN_MEANINGFUL_COHORT)}
    big = insights.build_cohorts(many, {k: {"2026-01"} for k in many})[0]
    assert big.meaningful


def test_cohorts_are_capped_and_newest_months_are_kept():
    first_visits = {f"c{i}": date(2024, 1, 1) + timedelta(days=31 * i) for i in range(40)}
    cohorts = insights.build_cohorts(
        first_visits, {k: set() for k in first_visits}, max_months=6
    )
    assert len(cohorts) == 6
    # Sorted ascending for display, but the six kept must be the latest.
    assert cohorts == sorted(cohorts, key=lambda c: c.cohort_month)
    assert cohorts[-1].cohort_month > cohorts[0].cohort_month


def test_a_visit_before_the_first_visit_is_impossible_and_ignored():
    """Defensive: a negative offset would corrupt the grid."""
    cohort = insights.build_cohorts(
        {"a": date(2026, 6, 1)}, {"a": {"2026-01", "2026-06"}}
    )[0]
    assert cohort.active_by_offset == {0: 1}


def test_no_customers_produces_no_cohorts():
    assert insights.build_cohorts({}, {}) == []


def test_retention_of_an_empty_cohort_is_zero_not_a_division_error():
    cohort = insights.Cohort(cohort_month="2026-01", size=0)
    assert cohort.retention_at(0) == 0.0


# -- Segments (pure) ----------------------------------------------------------


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'i.db'}", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(sessions, *, count: int = 6) -> list[str]:
    """Customers with enough history to score, half of them badly lapsed."""
    ids: list[str] = []
    naive = datetime.now(UTC).replace(tzinfo=None)
    async with sessions() as db:
        db.add(Business(id=BUSINESS_ID, name="Hayward Coffee Co.", vertical="cafe"))
        db.add(Subscription(business_id=BUSINESS_ID, tier="growth", status="active"))
        db.add(
            User(business_id=BUSINESS_ID, email="owner@hayward.coffee", role="owner")
        )
        for i in range(count):
            lapsed = i % 2 == 0
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
            # Weekly visits; lapsed customers stopped 120 days ago.
            offset = 120 if lapsed else 3
            for week in range(10):
                db.add(
                    Visit(
                        business_id=BUSINESS_ID,
                        customer_id=customer.id,
                        source="csv",
                        occurred_at=naive - timedelta(days=offset + week * 7),
                    )
                )
            db.add(
                Transaction(
                    business_id=BUSINESS_ID,
                    customer_id=customer.id,
                    source="csv",
                    amount=50 + i * 10,
                    occurred_at=naive - timedelta(days=offset),
                )
            )
        await db.commit()
    return ids


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


def test_every_segment_has_a_definition_and_a_key():
    assert len(insights.SEGMENTS) == len(insights.SEGMENT_KEYS)
    assert all(s.label and s.description for s in insights.SEGMENTS)


async def test_the_lapsed_segment_matches_the_lapsed_half(client, sessions):
    await _seed(sessions, count=6)
    body = client.get("/api/insights/segments/lapsed_90").json()
    assert body["total"] == 3
    assert len(body["customer_ids"]) == 3


async def test_an_unknown_segment_is_a_404_with_the_valid_options(client, sessions):
    await _seed(sessions, count=2)
    resp = client.get("/api/insights/segments/vip_whales")
    assert resp.status_code == 404
    assert "lapsed_90" in resp.json()["detail"]


async def test_the_contactable_segment_excludes_opt_outs(client, sessions):
    """A segment meant for sending must not include people who said no."""
    ids = await _seed(sessions, count=6)
    before = client.get("/api/insights/segments/contactable_high_risk").json()["total"]
    async with sessions() as db:
        for customer_id in ids:
            customer = await db.get(Customer, uuid.UUID(customer_id))
            customer.unsubscribed_email = True
        await db.commit()
    after = client.get("/api/insights/segments/contactable_high_risk").json()["total"]
    assert after == 0
    assert before >= after


async def test_the_segment_list_reports_real_sizes(client, sessions):
    await _seed(sessions, count=6)
    body = client.get("/api/insights/segments").json()
    by_key = {s["key"]: s for s in body["segments"]}
    assert set(by_key) == set(insights.SEGMENT_KEYS)
    assert by_key["lapsed_90"]["size"] == 3


# -- Score explainability -----------------------------------------------------


async def test_a_score_breaks_down_into_weighted_factors(client, sessions):
    ids = await _seed(sessions, count=6)
    # Pick the lapsed one, which will have a real recency contribution.
    body = client.get(f"/api/insights/customers/{ids[0]}/score").json()
    assert body["score"] > 0
    assert body["reasons"]
    assert body["factors"]
    keys = [f["key"] for f in body["factors"]]
    assert "recency" in keys
    # Sorted most-influential first, which is the whole point of the chart.
    points = [f["points"] for f in body["factors"]]
    assert points == sorted(points, reverse=True)


async def test_factor_shares_roughly_account_for_the_score(client, sessions):
    """The factors are the score's own arithmetic, not a separate estimate."""
    ids = await _seed(sessions, count=6)
    body = client.get(f"/api/insights/customers/{ids[0]}/score").json()
    total_points = sum(f["points"] for f in body["factors"])
    # Within a rounding point of the score the owner sees.
    assert abs(total_points - body["score"]) <= 1.5


async def test_explaining_an_unknown_customer_is_a_404(client, sessions):
    await _seed(sessions, count=1)
    assert client.get(f"/api/insights/customers/{uuid.uuid4()}/score").status_code == 404


# -- CSV export ---------------------------------------------------------------


async def test_the_csv_export_has_a_header_and_one_row_per_customer(client, sessions):
    await _seed(sessions, count=4)
    resp = client.get("/api/insights/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == list(insights.CSV_COLUMNS)
    assert len(rows) == 5


async def test_the_csv_survives_a_reason_containing_a_comma(client, sessions):
    """Quoting matters: these files get opened in Excel, and a shifted column
    makes the whole export untrustworthy."""
    await _seed(sessions, count=2)
    resp = client.get("/api/insights/export.csv")
    rows = list(csv.reader(io.StringIO(resp.text)))
    reasons_index = list(insights.CSV_COLUMNS).index("reasons")
    assert all(len(row) == len(insights.CSV_COLUMNS) for row in rows)
    # Reasons are pipe-joined so a naive comma split can't break them apart.
    assert "," not in rows[1][reasons_index] or " | " in rows[1][reasons_index]


async def test_the_csv_can_be_filtered_by_segment(client, sessions):
    await _seed(sessions, count=6)
    resp = client.get("/api/insights/export.csv?segment=lapsed_90")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 4  # header + 3


async def test_the_csv_rejects_an_unknown_segment(client, sessions):
    await _seed(sessions, count=2)
    assert client.get("/api/insights/export.csv?segment=nope").status_code == 404


# -- Digest copy (pure) -------------------------------------------------------


def _facts(**kwargs) -> DigestFacts:
    base = {"business_name": "Hayward Coffee Co.", "window_days": 7}
    base.update(kwargs)
    return DigestFacts(**base)


def test_the_digest_reports_the_definition_of_done_sentence():
    """The literal "3 customers recovered, ~$640 saved" case."""
    subject, body = fallback_digest(
        _facts(
            recovered_count=3,
            revenue_recovered=640.0,
            recovered_names=["Maria", "Jon", "Avery"],
        )
    )
    assert "3 customers came back" in subject
    assert "$640" in body
    assert "Maria, Jon and Avery" in body


def test_a_single_recovery_is_phrased_in_the_singular():
    subject, body = fallback_digest(_facts(recovered_count=1, revenue_recovered=210.0))
    assert "1 customer came back" in subject
    assert "1 customer came back" in body


def test_extra_recovered_names_are_summarized_not_listed_in_full():
    _subject, body = fallback_digest(
        _facts(
            recovered_count=5,
            revenue_recovered=900.0,
            recovered_names=["A", "B", "C", "D", "E"],
        )
    )
    assert "and 2 others" in body


def test_a_quiet_week_is_not_worth_sending():
    """An empty weekly summary trains people to delete the email, and the one
    week it matters they won't open it."""
    assert not _facts().is_worth_sending
    assert _facts(recovered_count=1).is_worth_sending
    assert _facts(awaiting_approval=2).is_worth_sending
    assert _facts(high_risk_count=4).is_worth_sending
    assert _facts(messages_sent=1).is_worth_sending


def test_pending_approvals_lead_the_subject_when_nothing_was_recovered():
    subject, _body = fallback_digest(_facts(awaiting_approval=4))
    assert "waiting for you" in subject


def test_the_digest_carries_an_unsubscribe_line_when_given_one():
    """CAN-SPAM doesn't care that we think of this as transactional."""
    _subject, body = fallback_digest(
        _facts(recovered_count=1), unsubscribe_url="https://x.test/u/abc"
    )
    assert "https://x.test/u/abc" in body


async def test_digest_copy_falls_back_to_the_template_without_an_llm():
    subject, body, generated_by, model = await build_digest_copy(
        _facts(recovered_count=2, revenue_recovered=400.0)
    )
    assert generated_by == "fallback"
    assert model is None
    assert "2 customers came back" in subject
    assert "$400" in body


async def test_the_ai_digest_is_used_when_it_returns_valid_json(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def _complete(system, user, max_tokens=0):
        # The prompt must carry the exact figures, since the model is forbidden
        # from computing any of its own.
        assert "Customers recovered this week: 3" in user
        assert "$640" in user
        return '{"subject": "Three regulars came back", "body": "Good week."}'

    monkeypatch.setattr("app.services.digest.complete_text", _complete)
    subject, body, generated_by, _model = await build_digest_copy(
        _facts(recovered_count=3, revenue_recovered=640.0)
    )
    assert generated_by == "claude"
    assert subject == "Three regulars came back"
    assert body == "Good week."


async def test_a_broken_model_response_degrades_to_the_template(monkeypatch):
    """There is no path where a model's arithmetic reaches an owner."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def _garbage(system, user, max_tokens=0):
        return "I'm afraid I can't do that."

    monkeypatch.setattr("app.services.digest.complete_text", _garbage)
    subject, body, generated_by, _model = await build_digest_copy(
        _facts(recovered_count=3, revenue_recovered=640.0)
    )
    assert generated_by == "fallback"
    assert "3 customers came back" in subject
    assert "$640" in body


# -- Digest facts + API -------------------------------------------------------


async def test_collect_facts_counts_the_window_not_all_time(sessions):
    ids = await _seed(sessions, count=4)
    async with sessions() as db:
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(ids[0]),
                estimated_value=640,
                recovered_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(ids[1]),
                estimated_value=999,
                recovered_at=datetime.now(UTC) - timedelta(days=60),
            )
        )
        await db.commit()

    async with sessions() as db:
        facts = await collect_facts(db, business_id=str(BUSINESS_ID), window_days=7)

    assert facts.recovered_count == 1
    assert facts.revenue_recovered == 640.0
    assert facts.high_risk_count >= 1
    assert facts.business_name == "Hayward Coffee Co."


async def test_collect_facts_counts_pending_approvals_regardless_of_age(sessions):
    """Something waiting on the owner is worth telling them about even if it was
    queued three weeks ago."""
    ids = await _seed(sessions, count=2)
    async with sessions() as db:
        from app.models import Campaign

        campaign = Campaign(business_id=BUSINESS_ID, name="Old draft", channel="email")
        db.add(campaign)
        await db.flush()
        db.add(
            CampaignSend(
                business_id=BUSINESS_ID,
                campaign_id=campaign.id,
                customer_id=uuid.UUID(ids[0]),
                channel="email",
                body="hi",
                status="pending",
            )
        )
        await db.commit()

    async with sessions() as db:
        facts = await collect_facts(db, business_id=str(BUSINESS_ID), window_days=7)
    assert facts.awaiting_approval == 1


async def test_the_digest_preview_endpoint_sends_nothing(client, sessions, monkeypatch):
    sent: list = []

    async def _spy(*args, **kwargs):
        sent.append(args)
        from app.services import senders

        return senders.SendResult(ok=True)

    monkeypatch.setattr("app.services.digest.send_email", _spy)
    await _seed(sessions, count=4)

    body = client.get("/api/insights/digest").json()
    assert body["window_days"] == 7
    assert body["subject"]
    assert body["generated_by"] == "fallback"
    assert body["recipients"] == ["owner@hayward.coffee"]
    assert sent == []


async def test_sending_the_digest_goes_to_the_owner_not_customers(
    client, sessions, monkeypatch
):
    recipients: list[str] = []

    async def _spy(to, subject, text):
        recipients.append(to)
        from app.services import senders

        return senders.SendResult(ok=True, provider_message_id="m1")

    monkeypatch.setattr("app.services.digest.send_email", _spy)
    ids = await _seed(sessions, count=4)
    async with sessions() as db:
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(ids[0]),
                estimated_value=640,
                recovered_at=datetime.now(UTC),
            )
        )
        await db.commit()

    body = client.post("/api/insights/digest/send").json()
    assert body["sent"] is True
    assert recipients == ["owner@hayward.coffee"]
    assert "cust0@example.com" not in recipients


async def test_a_quiet_week_explains_why_it_sent_nothing(client, sessions, monkeypatch):
    recipients: list[str] = []

    async def _spy(to, subject, text):
        recipients.append(to)
        from app.services import senders

        return senders.SendResult(ok=True)

    monkeypatch.setattr("app.services.digest.send_email", _spy)
    # A business with no customers at all: nothing recovered, nothing at risk.
    async with sessions() as db:
        db.add(Business(id=BUSINESS_ID, name="Brand New", vertical="cafe"))
        db.add(User(business_id=BUSINESS_ID, email="owner@hayward.coffee", role="owner"))
        await db.commit()

    body = client.post("/api/insights/digest/send").json()
    assert body["sent"] is False
    assert body["outcome"] == "nothing_to_report"
    assert "trains people to ignore" in body["message"]
    assert recipients == []


async def test_a_business_with_no_owner_email_is_reported_not_crashed(
    client, sessions, monkeypatch
):
    async def _spy(*_a, **_k):
        from app.services import senders

        return senders.SendResult(ok=True)

    monkeypatch.setattr("app.services.digest.send_email", _spy)
    ids = await _seed(sessions, count=2)
    async with sessions() as db:
        from sqlalchemy import delete

        await db.execute(delete(User).where(User.business_id == BUSINESS_ID))
        db.add(
            RecoveryAttribution(
                business_id=BUSINESS_ID,
                customer_id=uuid.UUID(ids[0]),
                estimated_value=100,
                recovered_at=datetime.now(UTC),
            )
        )
        await db.commit()

    body = client.post("/api/insights/digest/send").json()
    assert body["outcome"] == "no_recipient"
    assert "nowhere to send" in body["message"]


# -- Cohorts through the API --------------------------------------------------


async def test_the_cohorts_endpoint_returns_a_grid(client, sessions):
    await _seed(sessions, count=6)
    body = client.get("/api/insights/cohorts").json()
    assert body["min_meaningful_size"] == insights.MIN_MEANINGFUL_COHORT
    assert body["cohorts"]
    first = body["cohorts"][0]
    assert first["retention"][0] == 1.0
    assert len(first["retention"]) == body["max_offset"] + 1
    assert first["meaningful"] is False  # six customers across several months


async def test_cohorts_for_a_business_with_no_visits_is_empty_not_an_error(client, sessions):
    async with sessions() as db:
        db.add(Business(id=BUSINESS_ID, name="Brand New", vertical="cafe"))
        await db.commit()
    body = client.get("/api/insights/cohorts").json()
    assert body["cohorts"] == []
    assert body["max_offset"] == 0
