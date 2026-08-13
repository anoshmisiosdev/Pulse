"""Waitlist request/response bodies."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Pydantic's EmailStr would need the email-validator package, which isn't a
# declared dependency. For a marketing form the useful question is "could this
# plausibly receive mail", not RFC 5322 conformance — a wrong-but-valid address
# bounces either way. Same shape the frontend checks, so the two agree.
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


class WaitlistIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    business_name: str | None = Field(default=None, max_length=160)
    vertical: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=1000)

    # Explicit, bounded acquisition fields. The browser sends only the host of
    # the referrer, never its path/query, which may contain personal data.
    source: str | None = Field(default=None, max_length=100)
    medium: str | None = Field(default=None, max_length=100)
    campaign: str | None = Field(default=None, max_length=100)
    content: str | None = Field(default=None, max_length=100)
    landing_variant: str | None = Field(default=None, max_length=80)
    referrer_host: str | None = Field(default=None, max_length=253)

    # Honeypot. A real form leaves this empty because the input is hidden; a
    # bot that fills every field it finds gives itself away. Named to look
    # worth filling in. The endpoint accepts and silently drops these rather
    # than 4xx-ing, so a scraper learns nothing about why it failed.
    website: str = ""

    @field_validator("email")
    @classmethod
    def _clean_email(cls, v: str) -> str:
        """Normalize here so the unique index sees one spelling per person."""
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter an email address we can reach you at.")
        return v

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator(
        "business_name",
        "vertical",
        "note",
        "source",
        "medium",
        "campaign",
        "content",
        "landing_variant",
    )
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        """An untouched optional input arrives as "" — store nothing for it."""
        return v.strip() or None if v else None

    @field_validator("referrer_host")
    @classmethod
    def _clean_referrer_host(cls, v: str | None) -> str | None:
        if not v or not v.strip():
            return None
        host = v.strip().casefold().rstrip(".")
        # Browser ``URL.hostname`` values contain none of these. Reject a full
        # URL, path, credentials, or port instead of silently storing it.
        if (
            "://" in host
            or "/" in host
            or "?" in host
            or "#" in host
            or "@" in host
            or ":" in host
            or not re.fullmatch(r"[a-z0-9.-]+", host)
            or ".." in host
        ):
            raise ValueError("Send only the referrer's hostname.")
        return host

    def acquisition_touch(self) -> dict[str, str]:
        """Return only provided acquisition fields, using stable storage keys."""
        return {
            key: value
            for key, value in (
                ("source", self.source),
                ("medium", self.medium),
                ("campaign", self.campaign),
                ("content", self.content),
                ("landing_variant", self.landing_variant),
                ("referrer_host", self.referrer_host),
            )
            if value is not None
        }


class WaitlistOut(BaseModel):
    ok: bool
    already_joined: bool = False
