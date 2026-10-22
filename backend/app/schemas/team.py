"""Team management shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MemberOut(BaseModel):
    id: str
    email: str
    role: str
    is_you: bool
    joined_at: str


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    expires_at: str
    created_at: str


class TeamOut(BaseModel):
    members: list[MemberOut]
    invites: list[InviteOut]
    your_role: str


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["owner", "staff"] = "staff"


class InviteCreatedOut(BaseModel):
    invite: InviteOut
    # Returned so the owner can share it by hand when email isn't configured.
    # The raw token is never stored, so this response is the only place it exists.
    link: str
    emailed: bool


class AcceptIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class RoleIn(BaseModel):
    role: Literal["owner", "staff"]
