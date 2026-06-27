"""Campaign copy generation. Approve-to-send is the default mode product-wide."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.campaigns.generator import CampaignContext, generate_campaign
from app.schemas.api import GenerateCampaignIn, GeneratedCopyOut

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("/generate", response_model=GeneratedCopyOut)
async def generate(payload: GenerateCampaignIn) -> GeneratedCopyOut:
    if payload.channel not in ("email", "sms"):
        raise HTTPException(status_code=422, detail="channel must be 'email' or 'sms'")

    ctx = CampaignContext(
        business_name=payload.business_name,
        business_type=payload.business_type,
        customer_name=payload.customer_name,
        channel=payload.channel,
        tone=payload.tone,
        incentive=payload.incentive,
        risk_reasons=payload.risk_reasons,
        history_summary=payload.history_summary,
    )
    copy = await generate_campaign(ctx)
    return GeneratedCopyOut(
        channel=payload.channel,
        subject=copy.subject,
        body=copy.body,
        generated_by=copy.generated_by,
        model=copy.model,
    )
