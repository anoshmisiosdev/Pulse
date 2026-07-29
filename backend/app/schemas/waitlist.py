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
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    business_name: str | None = Field(default=None, max_length=160)
    vertical: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=1000)

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
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name can't be blank.")
        return v

    @field_validator("business_name", "vertical", "note")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        """An untouched optional input arrives as "" — store nothing for it."""
        return v.strip() or None if v else None


class WaitlistOut(BaseModel):
    ok: bool
    already_joined: bool = False
