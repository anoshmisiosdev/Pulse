"""Pulse API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, campaigns, health, integrations
from app.core.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("pulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: create tables if a DB is reachable. Production uses Alembic.
    if not settings.is_production:
        try:
            from app import models  # noqa: F401 — register tables on metadata
            from app.core.database import Base, engine

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
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
    allow_origins=settings.cors_origins + [settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(integrations.router, prefix=API_PREFIX)
app.include_router(campaigns.router, prefix=API_PREFIX)


@app.get("/")
async def root() -> dict:
    return {"service": "pulse-api", "docs": "/docs", "health": "/api/health"}
