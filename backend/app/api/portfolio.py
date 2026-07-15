"""The tenant's dashboard payload, read from their persisted data.

Returns status="empty" when the business hasn't connected a data source yet —
the frontend uses that to route the owner to the setup page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.schemas.api import PortfolioOut
from app.services.portfolio_service import build_portfolio

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> PortfolioOut:
    return await build_portfolio(db, user)
