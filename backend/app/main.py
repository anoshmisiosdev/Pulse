"""Pulse API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    analytics,
    auth,
    automations,
    campaigns,
    competitor_prices,
    customers,
    discord_bot,
    health,
    integrations,
    knowledge,
    portfolio,
    social,
    visitors,
    waitlist,
)
from app.core.config import settings
from app.core.logging_setup import setup_logging
from app.core.posthog_client import (
    POSTHOG_DISTINCT_ID_HEADER,
    init_posthog,
    shutdown_posthog,
)
from app.core.ratelimit import RateLimitMiddleware
from app.visitor_intelligence.service import VISITOR_SESSION_ID_HEADER

setup_logging()
logger = logging.getLogger("pulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PostHog analytics — optional; app continues without it if unconfigured.
    if not settings.posthog_disabled and settings.posthog_project_token:
        init_posthog(
            project_api_key=settings.posthog_project_token,
            host=settings.posthog_host,
            debug=(settings.environment == "development"),
        )
    elif not settings.posthog_disabled and settings.environment == "development":
        logger.warning(
            "POSTHOG_PROJECT_TOKEN variable required by PostHog is missing or un-configured, "
            "this causes events to be silently missed. This error stops appearing once "
            "POSTHOG_PROJECT_TOKEN is configured"
        )

    # Ensure tables exist (idempotent) for brand-new databases. Schema *changes*
    # to existing tables live in Alembic (`alembic upgrade head` runs in the
    # container entrypoint) — create_all never ALTERs.
    try:
        from app import models  # noqa: F401 — register tables on metadata
        from app.core.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("DB schema ensured")
    except Exception as exc:  # offline / no DB — API still serves CSV preview
        logger.warning("Skipping DB init (%s)", exc)

    yield

    # Flush queued events and stop the SDK's worker threads.
    shutdown_posthog()


# The FastAPI instance itself — kept under its own name so tests can still
# reach FastAPI-only attributes (e.g. `dependency_overrides`) after `app` below
# is reassigned to the CORS-wrapped ASGI callable.
fastapi_app = FastAPI(
    title="Churnary API",  # brand name; "Pulse" remains the internal codebase name
    version="0.1.0",
    summary="AI customer retention for small local businesses",
    lifespan=lifespan,
)


@fastapi_app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the traceback and return a consistent envelope — never leak internals."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "Something went wrong on our end."},
    )

API_PREFIX = "/api"
fastapi_app.include_router(health.router, prefix=API_PREFIX)
fastapi_app.include_router(auth.router, prefix=API_PREFIX)
fastapi_app.include_router(integrations.router, prefix=API_PREFIX)
fastapi_app.include_router(portfolio.router, prefix=API_PREFIX)
fastapi_app.include_router(customers.router, prefix=API_PREFIX)
fastapi_app.include_router(campaigns.router, prefix=API_PREFIX)
fastapi_app.include_router(competitor_prices.router, prefix=API_PREFIX)
fastapi_app.include_router(knowledge.router, prefix=API_PREFIX)
fastapi_app.include_router(automations.router, prefix=API_PREFIX)
fastapi_app.include_router(social.router, prefix=API_PREFIX)
# Public, strictly allow-listed landing-page interaction metrics.
fastapi_app.include_router(analytics.router, prefix=API_PREFIX)
# Public: the marketing page posts here before anyone has an account.
fastapi_app.include_router(waitlist.router, prefix=API_PREFIX)
# Public provider webhook plus platform-admin reporting endpoints.
fastapi_app.include_router(visitors.router, prefix=API_PREFIX)
# Signed Discord HTTP interactions for private /churnary commands.
fastapi_app.include_router(discord_bot.router, prefix=API_PREFIX)

# Rate limiting: protect auth (brute-force) and competitor research (expensive LLM).
# Applied to the inner app so CORS-wrapped 429s still get Access-Control-Allow-Origin.
fastapi_app.add_middleware(
    RateLimitMiddleware,
    rules={
        "/api/auth": (5, 60),               # 5 per 60s — brute-force protection
        "/api/competitor-prices": (10, 60), # v2 batch queue; tenant quota is authoritative
        "/api/analytics": (60, 60),         # bounded public landing-page metrics
        "/api/waitlist": (5, 60),           # 5 per 60s — unauthenticated public write
        "/api/integrations/webhooks": (240, 60), # signed Stripe/Square deliveries
        "/api/visitors/webhooks": (120, 60), # bounded third-party identity deliveries
        "/api/discord/interactions": (120, 60), # signed Discord command deliveries
    },
)


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
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        POSTHOG_DISTINCT_ID_HEADER,
        VISITOR_SESSION_ID_HEADER,
    ],
)
