"""Team: list members, invite, accept, change roles, remove.

Reading the team is open to any member. Changing it is owner-only. Accepting an
invite is open to any authenticated user, because the invitee isn't a member of
the business yet -- the email binding in services/team.py is what stops a
forwarded link from being used by the wrong person.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, CurrentUserDep, OwnerDep
from app.core.posthog_client import capture_event
from app.models import TeamInvite, User
from app.schemas.team import (
    AcceptIn,
    InviteCreatedOut,
    InviteIn,
    InviteOut,
    MemberOut,
    RoleIn,
    TeamOut,
)
from app.services import team

router = APIRouter(prefix="/team", tags=["team"])


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _member_out(row: User, user: CurrentUser) -> MemberOut:
    return MemberOut(
        id=str(row.id),
        email=row.email,
        role=row.role,
        is_you=row.supabase_user_id == user.user_id,
        joined_at=_iso(row.created_at),
    )


def _invite_out(row: TeamInvite) -> InviteOut:
    return InviteOut(
        id=str(row.id),
        email=row.email,
        role=row.role,
        expires_at=_iso(row.expires_at),
        created_at=_iso(row.created_at),
    )


@router.get("", response_model=TeamOut)
async def get_team(
    db: AsyncSession = Depends(get_db), user: CurrentUser = CurrentUserDep
) -> TeamOut:
    members = await team.list_members(db, business_id=user.business_id)
    # Pending invites name people who haven't joined; only owners see them.
    invites = (
        await team.list_pending_invites(db, business_id=user.business_id)
        if user.role == "owner"
        else []
    )
    return TeamOut(
        members=[_member_out(m, user) for m in members],
        invites=[_invite_out(i) for i in invites],
        your_role=user.role,
    )


@router.post("/invites", response_model=InviteCreatedOut, status_code=201)
async def invite(
    payload: InviteIn, db: AsyncSession = Depends(get_db), owner: CurrentUser = OwnerDep
) -> InviteCreatedOut:
    try:
        created = await team.create_invite(
            db, owner=owner, email=payload.email, role=payload.role
        )
    except team.TeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    capture_event(
        "team_invite_sent",
        distinct_id=owner.user_id,
        properties={"role": payload.role, "emailed": created.emailed},
    )
    return InviteCreatedOut(
        invite=_invite_out(created.invite), link=created.link, emailed=created.emailed
    )


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke(
    invite_id: str, db: AsyncSession = Depends(get_db), owner: CurrentUser = OwnerDep
) -> None:
    try:
        await team.revoke_invite(db, owner=owner, invite_id=invite_id)
    except team.TeamError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    await db.commit()


@router.post("/accept", response_model=MemberOut)
async def accept(
    payload: AcceptIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = CurrentUserDep,
) -> MemberOut:
    try:
        member = await team.accept_invite(db, user=user, raw_token=payload.token)
    except team.TeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    capture_event("team_invite_accepted", distinct_id=user.user_id)
    return _member_out(member, user)


@router.patch("/members/{member_id}", response_model=MemberOut)
async def set_role(
    member_id: str,
    payload: RoleIn,
    db: AsyncSession = Depends(get_db),
    owner: CurrentUser = OwnerDep,
) -> MemberOut:
    try:
        member = await team.change_role(db, owner=owner, member_id=member_id, role=payload.role)
    except team.TeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    return _member_out(member, owner)


@router.delete("/members/{member_id}", status_code=204)
async def remove(
    member_id: str, db: AsyncSession = Depends(get_db), owner: CurrentUser = OwnerDep
) -> None:
    try:
        await team.remove_member(db, owner=owner, member_id=member_id)
    except team.TeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
