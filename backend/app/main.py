"""Pulse API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, campaigns, competitor_prices, health, integrations, portfolio
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger("pulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic runs before the API process in deployed environments. Keep
    # create_all as a compatibility path for the application's older tables,
    # which predate the current Alembic migration chain.
    try:
        from sqlalchemy import text

        from app import models  # noqa: F401 — register tables on metadata
        from app.core.database import Base, engine

        # Compatibility patch for a table that predates the migration chain.
        column_patches = [
            "ALTER TABLE customers ADD COLUMN IF NOT EXISTS favorite_item VARCHAR(255)",
        ]
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for ddl in column_patches:
                await conn.execute(text(ddl))
        logger.info("DB schema ensured")
    except Exception as exc:  # offline / no DB — API still serves CSV preview
        logger.warning("Skipping DB init (%s)", exc)
    yield


app = FastAPI(
    title="Pulse API",
    version="0.1.0",
    summary="AI customer retention for small local businesses",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(integrations.router, prefix=API_PREFIX)
app.include_router(portfolio.router, prefix=API_PREFIX)
app.include_router(campaigns.router, prefix=API_PREFIX)
app.include_router(competitor_prices.router, prefix=API_PREFIX)


@app.get("/")
async def root() -> dict:
    return {"service": "pulse-api", "docs": "/docs", "health": "/api/health"}
