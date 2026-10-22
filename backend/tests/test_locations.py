"""Multi-location: where activity happened, each customer's home location, and
the per-location rollup (Pro)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.integrations.csv_adapter import parse_csv
from app.integrations.square_adapter import parse_square_payment
from app.main import app, fastapi_app
from app.models import Business, Customer, Subscription, Transaction, Visit
from app.scoring.engine import ScoreResult
from app.services import insights
from app.services.activity import ScoredCustomer

BIZ = uuid.uuid4()


# -- Source parsing -----------------------------------------------------------


def test_square_payments_carry_their_location_name():
    tx = parse_square_payment(
        {
            "id": "p1",
            "status": "COMPLETED",
            "amount_money": {"amount": 1200, "currency": "USD"},
            "location_id": "L1",
            "created_at": "2026-09-01T10:00:00Z",
        },
        {"L1": "Downtown"},
    )
    assert tx.location == "Downtown"


def test_an_unnamed_square_location_falls_back_to_its_id():
    """Better the raw id than silently losing which store it was."""
    tx = parse_square_payment(
        {
            "id": "p1",
            "status": "COMPLETED",
            "amount_money": {"amount": 1200, "currency": "USD"},
            "location_id": "L9",
        },
        {},
    )
    assert tx.location == "L9"


def test_a_csv_location_column_is_picked_up_under_its_common_names():
    for header in ("location", "Store", "branch", "Studio"):
        csv_text = (
            f"name,email,last_visit,amount,{header}\n"
            "Ana Ruiz,ana@x.com,2026-09-01,40,Northside\n"
        )
        result = parse_csv(csv_text)
        assert result.visits[0].location == "Northside", header
        assert result.transactions[0].location == "Northside", header


def test_a_csv_without_a_location_column_still_parses():
    result = parse_csv("name,email,last_visit\nAna Ruiz,ana@x.com,2026-09-01\n")
    assert result.visits[0].location is None


# -- Pure rollup --------------------------------------------------------------


def _scored(customer_id: str, band: str, value: float) -> ScoredCustomer:
    from app.schemas.normalized import NormalizedCustomer

    return ScoredCustomer(
        customer=NormalizedCustomer(external_id=customer_id, source="csv", first_name="X"),
        result=ScoreResult(
            customer_id=customer_id, score=80, band=band, reasons=[], signals={}
        ),
        estimated_annual_value=value,
        days_since_last_visit=30,
        last_visit=None,
        visit_count=5,
        total_spend=value,
        segment="needs_attention",
        pattern=None,
        confidence="medium",
        trend_pct=0,
        return_likelihood=20,
        expected_next_visit=None,
        days_overdue=0,
        payment_issue=False,
    )


def test_the_rollup_weights_revenue_at_risk_like_the_dashboard():
    """All of a high-risk customer's value plus half of a medium one's -- the
    same rule as activity.summarize, so per-location numbers add up to the
    headline instead of disagreeing with it."""
    scored = [
        _scored("a", "high", 1000),
        _scored("b", "med", 400),
        _scored("c", "low", 900),
    ]
    rows = insights.location_breakdown(scored, {"a": "Downtown", "b": "Downtown", "c": "Uptown"})
    downtown = next(r for r in rows if r.location == "Downtown")
    assert downtown.customers == 2
    assert downtown.revenue_at_risk == 1200.0
    assert downtown.high_risk == 1 and downtown.med_risk == 1


def test_the_worst_location_comes_first_and_unassigned_comes_last():
    scored = [
        _scored("a", "high", 100),
        _scored("b", "high", 5000),
        _scored("c", "high", 99999),  # no location: must still sort last
    ]
    rows = insights.location_breakdown(scored, {"a": "Small", "b": "Big"})
    assert [r.location for r in rows] == ["Big", "Small", insights.UNASSIGNED_LOCATION]


def test_customers_without_a_location_are_counted_not_dropped():
    """Location totals must add up to the whole customer list."""
    scored = [_scored("a", "low", 10), _scored("b", "low", 10)]
    rows = insights.location_breakdown(scored, {"a": "Downtown"})
    assert sum(r.customers for r in rows) == 2


def test_filtering_by_location_includes_only_that_location():
    scored = [_scored("a", "high", 1), _scored("b", "high", 1), _scored("c", "high", 1)]
    home = {"a": "Downtown", "b": "Uptown"}
    downtown = insights.filter_by_location(scored, home, "Downtown")
    assert [s.customer.external_id for s in downtown] == ["a"]
    assert [
        s.customer.external_id
        for s in insights.filter_by_location(scored, home, insights.UNASSIGNED_LOCATION)
    ] == ["c"]


# -- Home location from the database ------------------------------------------


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'l.db'}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _customer_with_visits(db, visits: list[tuple[str | None, int]]) -> str:
    """visits: (location, days_ago)."""
    customer = Customer(
        business_id=BIZ, source="csv", first_name="C", email=f"{uuid.uuid4()}@x.com"
    )
    db.add(customer)
    await db.flush()
    now = datetime.now(UTC)
    for location, days_ago in visits:
        db.add(
            Visit(
                business_id=BIZ,
                customer_id=customer.id,
                source="csv",
                location=location,
                occurred_at=now - timedelta(days=days_ago),
            )
        )
    return str(customer.id)


async def test_home_location_is_where_they_visit_most(sessions):
    async with sessions() as db:
        db.add(Business(id=BIZ, name="Glow", vertical="salon"))
        cid = await _customer_with_visits(
            db, [("Downtown", 90), ("Downtown", 60), ("Downtown", 30), ("Uptown", 5)]
        )
        await db.commit()
        home = await insights.home_locations(db, business_id=str(BIZ))
    assert home[cid] == "Downtown"


async def test_a_tie_goes_to_the_more_recent_location(sessions):
    """A regular who moved studios counts as the new one once it evens out."""
    async with sessions() as db:
        db.add(Business(id=BIZ, name="Glow", vertical="salon"))
        cid = await _customer_with_visits(
            db, [("Downtown", 90), ("Downtown", 80), ("Uptown", 10), ("Uptown", 3)]
        )
        await db.commit()
        home = await insights.home_locations(db, business_id=str(BIZ))
    assert home[cid] == "Uptown"


async def test_visits_without_a_location_dont_create_a_home(sessions):
    async with sessions() as db:
        db.add(Business(id=BIZ, name="Glow", vertical="salon"))
        cid = await _customer_with_visits(db, [(None, 10), (None, 5)])
        await db.commit()
        home = await insights.home_locations(db, business_id=str(BIZ))
    assert cid not in home


async def test_home_locations_never_include_another_tenant(sessions):
    other = uuid.uuid4()
    async with sessions() as db:
        db.add(Business(id=BIZ, name="Glow", vertical="salon"))
        db.add(Business(id=other, name="Rival", vertical="salon"))
        customer = Customer(business_id=other, source="csv", first_name="R", email="r@x.com")
        db.add(customer)
        await db.flush()
        db.add(
            Visit(
                business_id=other, customer_id=customer.id, source="csv",
                location="Theirs", occurred_at=datetime.now(UTC),
            )
        )
        await db.commit()
        home = await insights.home_locations(db, business_id=str(BIZ))
    assert home == {}


# -- API + the Pro gate -------------------------------------------------------


@pytest.fixture
def client_for(sessions):
    def _make(tier: str):
        async def _db():
            async with sessions() as session:
                yield session
                await session.commit()

        fastapi_app.dependency_overrides[get_db] = _db
        fastapi_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id="u", email="o@x.com", business_id=str(BIZ), business_name="Glow"
        )
        return TestClient(app)

    yield _make
    fastapi_app.dependency_overrides.clear()


async def _seed_two_locations(sessions, tier: str) -> None:
    async with sessions() as db:
        db.add(Business(id=BIZ, name="Glow", vertical="salon"))
        db.add(Subscription(business_id=BIZ, tier=tier, status="active"))
        for location in ("Downtown", "Downtown", "Uptown"):
            cid = await _customer_with_visits(db, [(location, 200), (location, 160)])
            db.add(
                Transaction(
                    business_id=BIZ, customer_id=uuid.UUID(cid), source="csv", amount=80,
                    location=location, occurred_at=datetime.now(UTC) - timedelta(days=160),
                )
            )
        await db.commit()


async def test_the_location_breakdown_is_a_pro_feature(client_for, sessions):
    await _seed_two_locations(sessions, "growth")
    resp = client_for("growth").get("/api/insights/locations")
    assert resp.status_code == 402
    assert "Pro" in resp.json()["detail"]


async def test_pro_sees_each_location(client_for, sessions):
    await _seed_two_locations(sessions, "pro")
    body = client_for("pro").get("/api/insights/locations").json()
    assert body["has_location_data"] is True
    by_name = {r["location"]: r for r in body["locations"]}
    assert by_name["Downtown"]["customers"] == 2
    assert by_name["Uptown"]["customers"] == 1


async def test_a_segment_can_be_narrowed_to_one_location(client_for, sessions):
    await _seed_two_locations(sessions, "pro")
    client = client_for("pro")
    everyone = client.get("/api/insights/segments/high_risk").json()
    downtown = client.get("/api/insights/segments/high_risk?location=Downtown").json()
    assert downtown["total"] < everyone["total"]
    assert downtown["total"] == 2


async def test_location_filtering_is_gated_too(client_for, sessions):
    """Otherwise the gate on /locations is decorative."""
    await _seed_two_locations(sessions, "starter")
    resp = client_for("starter").get("/api/insights/segments/high_risk?location=Downtown")
    assert resp.status_code == 402
