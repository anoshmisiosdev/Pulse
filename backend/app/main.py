"""Pulse API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, campaigns, competitor_prices, health, integrations, knowledge, portfolio
from app.core.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("pulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables exist (idempotent). Runs in production too — the deploy story is
    # a single container against Supabase, so create_all doubles as the migration
    # path until Alembic is wired into CI.
    try:
        from sqlalchemy import text

        from app import models  # noqa: F401 — register tables on metadata
        from app.core.database import Base, engine

        # Idempotent column patches for tables that predate a model change —
        # create_all never ALTERs. Stands in for Alembic until it's wired into CI.
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


# The FastAPI instance itself — kept under its own name so tests can still
# reach FastAPI-only attributes (e.g. `dependency_overrides`) after `app` below
# is reassigned to the CORS-wrapped ASGI callable.
fastapi_app = FastAPI(
    title="Pulse API",
    version="0.1.0",
    summary="AI customer retention for small local businesses",
    lifespan=lifespan,
)

API_PREFIX = "/api"
fastapi_app.include_router(health.router, prefix=API_PREFIX)
fastapi_app.include_router(auth.router, prefix=API_PREFIX)
fastapi_app.include_router(integrations.router, prefix=API_PREFIX)
fastapi_app.include_router(portfolio.router, prefix=API_PREFIX)
fastapi_app.include_router(campaigns.router, prefix=API_PREFIX)
fastapi_app.include_router(competitor_prices.router, prefix=API_PREFIX)
fastapi_app.include_router(knowledge.router, prefix=API_PREFIX)


@fastapi_app.get("/")
async def root() -> dict:
    return {"service": "pulse-api", "docs": "/docs", "health": "/api/health"}


# Wrapped around the finished app, not added via app.add_middleware: Starlette
# special-cases 500/Exception handlers into ServerErrorMiddleware, which sits
# outside every middleware added the normal way. A CORSMiddleware added via
# add_middleware never sees those responses, so a real unhandled crash comes
# back with no Access-Control-Allow-Origin header — the browser then reports
# it as a CORS failure and hides the actual 500. Wrapping here puts CORS
# outside ServerErrorMiddleware too, so every response gets the header.
app = CORSMiddleware(
    fastapi_app,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
