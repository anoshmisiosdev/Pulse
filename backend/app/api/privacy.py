"""Per-business data export and deletion (the CLAUDE.md compliance endpoint).

Deletion is irreversible and destroys the tenant's working data, so it requires
an explicit typed confirmation in the request body rather than being reachable
by a stray POST. The product has no undo for this and shouldn't pretend to.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.core.posthog_client import capture_event
from app.schemas.privacy import DeletionReportOut, DeletionRequestIn
from app.services import privacy
from app.services.generation_log import record_audit

logger = logging.getLogger("pulse.api.privacy")
router = APIRouter(prefix="/privacy", tags=["privacy"])

# Typed by the owner to confirm. Matched case-insensitively after stripping, so
# "delete " passes but an empty or absent field never does.
CONFIRMATION_PHRASE = "delete"


@router.get("/export")
async def export_data(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> Response:
    """Download everything we hold for this business as JSON.

    Returned as an attachment rather than a JSON body so the browser saves it;
    an owner asking for their data wants a file, not a rendered API response.
    """
    payload = await privacy.export_business_data(db, business_id=user.business_id)
    await record_audit(
        db,
        business_id=user.business_id,
        action="data_export_requested",
        actor=user,
        subject_type="business",
        subject_id=user.business_id,
        summary=(
            f"Exported {len(payload.get('customers', []))} customer(s) and associated history"
        ),
    )
    await db.commit()
    capture_event("data_exported", distinct_id=user.user_id)

    body = json.dumps(payload, indent=2, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="churnary-data-export.json"'
        },
    )


@router.post("/delete", response_model=DeletionReportOut)
async def delete_data(
    payload: DeletionRequestIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> DeletionReportOut:
    """Erase this business's data. Irreversible.

    ``scope="all"`` is the privacy-request path. The narrower scopes exist for
    the ordinary support case — "re-import my customers and start the scores
    over" — which shouldn't also destroy a brand kit.
    """
    if payload.confirm.strip().casefold() != CONFIRMATION_PHRASE:
        raise HTTPException(
            422,
            detail=f"To confirm, send confirm=\"{CONFIRMATION_PHRASE}\". Nothing was deleted.",
        )
    try:
        report = await privacy.delete_business_data(
            db, business_id=user.business_id, scope=payload.scope, actor=user
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()

    logger.info(
        "data deletion requested by %s scope=%s rows=%s",
        user.user_id,
        payload.scope,
        report.total,
    )
    capture_event(
        "data_deleted",
        distinct_id=user.user_id,
        properties={"scope": payload.scope, "rows_deleted": report.total},
    )
    return DeletionReportOut(
        scope=report.scope, rows_deleted=report.total, deleted=report.deleted
    )


@router.delete("/customers/{customer_id}", status_code=204)
async def delete_one_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> None:
    """Erase one customer and all of their history (right to be forgotten)."""
    deleted = await privacy.delete_customer(
        db, business_id=user.business_id, customer_id=customer_id, actor=user
    )
    if not deleted:
        raise HTTPException(404, "Not found")
    await db.commit()
    capture_event("customer_deleted", distinct_id=user.user_id)
