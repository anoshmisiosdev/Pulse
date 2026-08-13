"""Authenticated public-sample import reaches the persisted portfolio API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.core import database as database_module
from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user
from app.main import app, fastapi_app


@pytest.fixture
async def sample_client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "engine", engine)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()


async def test_uci_sample_import_reaches_portfolio(sample_client):
    user = CurrentUser(
        user_id=str(uuid.uuid4()),
        email="owner@example.com",
        business_id=str(uuid.uuid4()),
        business_name="Sample Shop",
    )
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = sample_client.post(
            "/api/integrations/samples/uci-online-retail/import",
            params={"vertical": "other", "business_name": "Public Retail Demo"},
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["business_name"] == "Public Retail Demo"
    assert body["currency"] == "GBP"
    assert body["summary"]["total_customers"] == 60
    assert len(body["customers"]) == 60
    assert {customer["band"] for customer in body["customers"]} == {"low", "med", "high"}
    assert any(customer["favorite_item"] for customer in body["customers"])
    assert body["summary"]["revenue_series"]
