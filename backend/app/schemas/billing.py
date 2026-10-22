"""Billing request/response shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TierOut(BaseModel):
    name: str
    label: str
    monthly_price_usd: int
    annual_price_usd: int
    max_customers: int | None
    max_integrations: int | None
    channels: list[str]
    automation: bool
    multi_location: bool
    blurb: str
    highlights: list[str]


class UsageMeterOut(BaseModel):
    key: str
    label: str
    used: int
    limit: int | None
    severity: Literal["ok", "approaching", "over"]
    message: str | None


class SubscriptionOut(BaseModel):
    tier: str
    status: str
    active: bool
    trial_days_left: int | None
    current_period_end: str | None
    channels: list[str]
    automation: bool
    multi_location: bool
    meters: list[UsageMeterOut]
    # False when Stripe has no secret key / no prices configured. The UI uses
    # this to show "billing not set up" instead of a checkout button that 503s.
    billing_configured: bool
    # Whether this tenant has ever been through Checkout, which decides between
    # "Choose a plan" and "Manage billing".
    has_payment_method: bool


class PlansOut(BaseModel):
    tiers: list[TierOut]
    trial_days: int
    current_tier: str
    billing_configured: bool


class CheckoutIn(BaseModel):
    tier: Literal["starter", "growth", "pro"]
    annual: bool = False
    coupon: str | None = Field(default=None, max_length=64)


class CheckoutOut(BaseModel):
    url: str
    session_id: str


class PortalOut(BaseModel):
    url: str
