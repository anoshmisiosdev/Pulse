"""Pulse API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, campaigns, competitor_prices, health, integrations, portfolio
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

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # A response raised from here still passes back through CORSMiddleware,
    # unlike an exception that propagates past it to Starlette's outer
    # ServerErrorMiddleware — that path emits a 500 with no CORS headers,
    # which browsers then misreport as a CORS failure instead of a 500.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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
