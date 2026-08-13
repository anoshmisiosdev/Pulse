from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["health"])
logger = logging.getLogger("pulse.health")


@router.get("/health", response_model=None)
async def health(db: AsyncSession = Depends(get_db)) -> dict | JSONResponse:
    """Liveness + readiness probe. Checks DB connectivity.

    ``revision`` is the commit the running image was built from — it's what the
    deploy workflow polls to confirm a rollout really replaced the old container,
    rather than assuming a successful `docker push` means new code is live.
    """
    revision = settings.app_revision or "unknown"
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "fail"
        logger.warning("Health check DB probe failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "revision": revision, "checks": checks},
        )
    return {
        "status": "ok",
        "service": "pulse-api",
        "revision": revision,
        "checks": checks,
    }
