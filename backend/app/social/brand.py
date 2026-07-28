"""Brand kit: the voice and look every piece of generated copy inherits.

Saves are append-only. Splay overwrote a single JSON file, which left the
``brand_kit_version`` stamped on each post pointing at nothing; here every save
inserts a row, so a post can always be traced back to the exact kit that wrote
it. Version 0 is never stored — it's the synthetic "not set up yet" default,
and ``version < 1`` is what blocks campaign generation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social import BrandKitVersion
from app.schemas.social import BrandColors, BrandKitIn, BrandKitOut, BrandTypography
from app.social.inbox_rules import BrandVoice

# Churnary's own palette (frontend/src/index.css) so an owner who never opens
# the brand screen still gets copy that looks like the product around it.
DEFAULT_COLORS = BrandColors(
    primary="#B4532A",
    secondary="#A23B1E",
    accent="#EFE3D3",
    background="#FBF6EE",
    text="#2A211C",
)
DEFAULT_TYPOGRAPHY = BrandTypography(
    heading_family="Spectral",
    body_family="Hanken Grotesk",
    heading_weight=600,
    body_weight=400,
    scale="balanced",
)


def default_kit(business_name: str = "Your business") -> BrandKitOut:
    """The kit returned before an owner has saved one. Never persisted."""
    from datetime import UTC, datetime

    return BrandKitOut(
        version=0,
        updated_at=datetime.fromtimestamp(0, UTC),
        name=business_name,
        tagline="Add your tagline.",
        audience="Describe the customers you serve.",
        tone="warm, specific, local",
        positioning="Describe what you do and why regulars keep coming back.",
        avoid=["unsupported claims", "fake urgency", "generic hype"],
        colors=DEFAULT_COLORS,
        typography=DEFAULT_TYPOGRAPHY,
        logo_url=None,
    )


def to_out(row: BrandKitVersion) -> BrandKitOut:
    return BrandKitOut(
        version=row.version,
        updated_at=row.created_at,
        name=row.name,
        tagline=row.tagline,
        audience=row.audience,
        tone=row.tone,
        positioning=row.positioning,
        avoid=list(row.avoid or []),
        colors=BrandColors(
            primary=row.color_primary,
            secondary=row.color_secondary,
            accent=row.color_accent,
            background=row.color_background,
            text=row.color_text,
        ),
        typography=BrandTypography(
            heading_family=row.heading_family,
            body_family=row.body_family,
            heading_weight=row.heading_weight,
            body_weight=row.body_weight,
            scale=row.scale,
        ),
        logo_url=row.logo_url,
    )


async def current_row(db: AsyncSession, *, business_id: str) -> BrandKitVersion | None:
    """The latest saved kit row, or None if this business has never saved one."""
    result = await db.execute(
        select(BrandKitVersion)
        .where(BrandKitVersion.business_id == uuid.UUID(business_id))
        .order_by(BrandKitVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def load(
    db: AsyncSession, *, business_id: str, business_name: str = "Your business"
) -> BrandKitOut:
    """Always returns a kit — the v0 default when nothing has been saved."""
    row = await current_row(db, business_id=business_id)
    return to_out(row) if row else default_kit(business_name)


async def save(db: AsyncSession, *, business_id: str, payload: BrandKitIn) -> BrandKitOut:
    """Insert the next version. Every save bumps the counter, changed or not."""
    bid = uuid.UUID(business_id)
    highest = await db.scalar(
        select(func.max(BrandKitVersion.version)).where(BrandKitVersion.business_id == bid)
    )
    row = BrandKitVersion(
        business_id=bid,
        version=(highest or 0) + 1,
        name=payload.name,
        tagline=payload.tagline,
        audience=payload.audience,
        tone=payload.tone,
        positioning=payload.positioning,
        avoid=payload.avoid,
        color_primary=payload.colors.primary,
        color_secondary=payload.colors.secondary,
        color_accent=payload.colors.accent,
        color_background=payload.colors.background,
        color_text=payload.colors.text,
        heading_family=payload.typography.heading_family,
        body_family=payload.typography.body_family,
        heading_weight=payload.typography.heading_weight,
        body_weight=payload.typography.body_weight,
        scale=payload.typography.scale,
        logo_url=payload.logo_url,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return to_out(row)


async def voice(
    db: AsyncSession, *, business_id: str, business_name: str = "Your business"
) -> BrandVoice:
    """The slice of the kit the reply drafter needs."""
    kit = await load(db, business_id=business_id, business_name=business_name)
    return BrandVoice(name=kit.name, positioning=kit.positioning, tone=kit.tone)
