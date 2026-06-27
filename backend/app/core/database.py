"""Async SQLAlchemy engine, session factory, and declarative base."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base with created/updated timestamps available to all models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
