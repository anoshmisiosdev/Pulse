"""Data export / deletion shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DeletionRequestIn(BaseModel):
    # "all" is the privacy-request path; the narrower scopes exist for the
    # ordinary support case of re-importing customers without destroying the
    # brand kit or the assistant history.
    scope: Literal["retention", "social", "assistant", "knowledge", "all"] = "all"
    # Typed by the owner. Deletion is irreversible, so it must not be reachable
    # by a stray POST with an empty body.
    confirm: str = Field(default="", max_length=32)


class DeletionReportOut(BaseModel):
    scope: str
    rows_deleted: int
    # Per-table counts, shown back as confirmation of what went.
    deleted: dict[str, int]
