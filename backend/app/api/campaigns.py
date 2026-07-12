"""Campaign copy generation. Approve-to-send is the default mode product-wide."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.generator import CampaignContext, generate_campaign
from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep
from app.schemas.api import GenerateCampaignIn, GeneratedCopyOut
from app.services.rag.knowledge_store import search_knowledge

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("/generate", response_model=GeneratedCopyOut)
async def generate(
    payload: GenerateCampaignIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> GeneratedCopyOut:
    if payload.channel not in ("email", "sms"):
        raise HTTPException(status_code=422, detail="channel must be 'email' or 'sms'")

    retrieval_query = (
        f"win-back {payload.channel} for {payload.customer_name}. "
        f"Reasons: {'; '.join(payload.risk_reasons)}. Incentive: {payload.incentive or 'none'}."
    )
    knowledge = await search_knowledge(db, business_id=user.business_id, query=retrieval_query)

    ctx = CampaignContext(
        business_name=payload.business_name,
        business_type=payload.business_type,
        customer_name=payload.customer_name,
        channel=payload.channel,
        tone=payload.tone,
        incentive=payload.incentive,
        risk_reasons=payload.risk_reasons,
        history_summary=payload.history_summary,
        knowledge_snippets=[row.content for row in knowledge],
    )
    copy = await generate_campaign(ctx)
    return GeneratedCopyOut(
        channel=payload.channel,
        subject=copy.subject,
        body=copy.body,
        generated_by=copy.generated_by,
        model=copy.model,
    )
