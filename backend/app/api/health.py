from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "pulse-api",
        "environment": settings.environment,
        "model": settings.anthropic_model,
    }
