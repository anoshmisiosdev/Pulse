"""Strict request bodies for public, first-party product analytics."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _LandingMetric(BaseModel):
    """Only declared, bounded properties may reach PostHog."""

    model_config = ConfigDict(extra="forbid")


class LandingViewedMetric(_LandingMetric):
    event: Literal["landing_viewed"]
    path: Literal["/", "/landing"]
    referrer_host: str | None = Field(default=None, max_length=253)
    utm_source: str | None = Field(default=None, max_length=100)
    utm_medium: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=100)


class LandingSectionViewedMetric(_LandingMetric):
    event: Literal["landing_section_viewed"]
    section: Literal["demo", "pricing", "waitlist"]


class LandingCtaClickedMetric(_LandingMetric):
    event: Literal["landing_cta_clicked"]
    cta: Literal["join_waitlist", "live_demo", "sign_in"]
    location: Literal["navbar", "hero", "pricing", "waitlist", "footer"]
    destination: Literal["waitlist", "demo", "login"]
    plan: Literal["starter", "growth", "pro"] | None = None


class LandingDemoInteractedMetric(_LandingMetric):
    event: Literal["landing_demo_interacted"]
    control: Literal["vertical", "days"]
    vertical: Literal["cafe", "fitness", "salon"]
    risk_band: Literal["healthy", "watch", "needs_attention"]


class LandingWaitlistStartedMetric(_LandingMetric):
    event: Literal["landing_waitlist_started"]


class LandingWaitlistValidationFailedMetric(_LandingMetric):
    event: Literal["landing_waitlist_validation_failed"]
    reason: Literal["missing_name", "invalid_email"]


class LandingWaitlistSubmitFailedMetric(_LandingMetric):
    event: Literal["landing_waitlist_submit_failed"]
    reason: Literal["request_failed"]


LandingMetricIn = Annotated[
    LandingViewedMetric
    | LandingSectionViewedMetric
    | LandingCtaClickedMetric
    | LandingDemoInteractedMetric
    | LandingWaitlistStartedMetric
    | LandingWaitlistValidationFailedMetric
    | LandingWaitlistSubmitFailedMetric,
    Field(discriminator="event"),
]
