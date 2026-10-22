"""Team invites and membership.

Membership is a row in ``users`` keyed by the Supabase ``sub`` (see
``core/deps.py::resolve_membership``). An invite is a single-use, expiring,
email-bound token; accepting it writes that row.

Three rules carry the security weight:

* **Only a hash of the token is stored.** The raw token exists once, in the
  link. A leaked database row can't be replayed into a membership.
* **Invites are bound to an email.** Accepting requires the caller's verified
  email to match, so a forwarded link can't be used by whoever holds it.
* **A business always keeps at least one owner.** Removing or demoting the last
  owner would leave a tenant nobody can bill, export, or manage.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser
from app.models import Business, TeamInvite, User
from app.models.team import TEAM_ROLES
from app.services.generation_log import record_audit
from app.services.senders.resend_client import send_email

INVITE_TTL = timedelta(days=7)


class TeamError(ValueError):
    """A team operation that can't be done; the message is owner-facing."""


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def invite_link(raw_token: str) -> str:
    return f"{settings.frontend_origin.rstrip('/')}/join?token={raw_token}"


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes for timezone=True columns; see
    billing/store.py::_as_aware for the bug this guards against."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _normalize_email(email: str) -> str:
    return email.strip().casefold()


@dataclass
class CreatedInvite:
    invite: TeamInvite
    raw_token: str
    link: str
    emailed: bool


async def create_invite(
    db: AsyncSession, *, owner: CurrentUser, email: str, role: str = "staff"
) -> CreatedInvite:
    email = _normalize_email(email)
    if "@" not in email or len(email) > 320:
        raise TeamError("That doesn't look like an email address.")
    if role not in TEAM_ROLES:
        raise TeamError(f"Role must be one of: {', '.join(TEAM_ROLES)}.")
    if owner.email and _normalize_email(owner.email) == email:
        raise TeamError("You're already on this team.")

    bid = _uuid(owner.business_id)
    already = (
        await db.execute(
            select(User.id).where(User.business_id == bid, func.lower(User.email) == email)
        )
    ).first()
    if already:
        raise TeamError(f"{email} is already on this team.")

    # Re-inviting supersedes the earlier link rather than leaving two live
    # tokens for the same person.
    now = datetime.now(UTC)
    for previous in (
        await db.execute(
            select(TeamInvite).where(
                TeamInvite.business_id == bid,
                TeamInvite.email == email,
                TeamInvite.accepted_at.is_(None),
                TeamInvite.revoked_at.is_(None),
            )
        )
    ).scalars():
        previous.revoked_at = now

    raw = secrets.token_urlsafe(32)
    invite = TeamInvite(
        business_id=bid,
        email=email,
        role=role,
        token_hash=hash_token(raw),
        invited_by_user_id=owner.user_id,
        expires_at=now + INVITE_TTL,
    )
    db.add(invite)
    await db.flush()

    link = invite_link(raw)
    business = await db.get(Business, bid)
    business_name = business.name if business else owner.business_name
    result = await send_email(
        email,
        f"You're invited to join {business_name} on Churnary",
        (
            f"{owner.email or 'The owner'} invited you to help run {business_name} "
            f"on Churnary as {'an owner' if role == 'owner' else 'staff'}.\n\n"
            f"Accept the invite (link expires in 7 days):\n{link}\n\n"
            "If you weren't expecting this, you can ignore it."
        ),
    )
    await record_audit(
        db,
        business_id=bid,
        action="team_invited",
        actor=owner,
        subject_type="team_invite",
        subject_id=str(invite.id),
        summary=f"Invited {email} as {role}",
    )
    return CreatedInvite(invite=invite, raw_token=raw, link=link, emailed=result.ok)


async def accept_invite(db: AsyncSession, *, user: CurrentUser, raw_token: str) -> User:
    """Join the inviting business. The caller's email must match the invite."""
    invite = (
        await db.execute(
            select(TeamInvite).where(TeamInvite.token_hash == hash_token(raw_token.strip()))
        )
    ).scalar_one_or_none()
    # One message for every "this token is no good" case, so the endpoint can't
    # be used to probe which tokens exist.
    unusable = TeamError("This invite link isn't valid. Ask for a new one.")
    if invite is None or invite.revoked_at is not None or invite.accepted_at is not None:
        raise unusable
    if _aware(invite.expires_at) <= datetime.now(UTC):
        raise TeamError("This invite has expired. Ask for a new one.")
    if not user.email or _normalize_email(user.email) != invite.email:
        raise TeamError(
            f"This invite was sent to {invite.email}. Sign in with that address to accept it."
        )

    # One membership per login: joining a team replaces any previous one.
    await db.execute(delete(User).where(User.supabase_user_id == user.user_id))
    member = User(
        business_id=invite.business_id,
        supabase_user_id=user.user_id,
        email=user.email,
        role=invite.role,
    )
    db.add(member)
    invite.accepted_at = datetime.now(UTC)
    invite.accepted_by_user_id = user.user_id
    await db.flush()
    await record_audit(
        db,
        business_id=invite.business_id,
        action="team_joined",
        actor=user,
        subject_type="user",
        subject_id=user.user_id,
        summary=f"{user.email} joined as {invite.role}",
    )
    return member


async def list_members(db: AsyncSession, *, business_id: str) -> list[User]:
    return list(
        (
            await db.execute(
                select(User)
                .where(User.business_id == _uuid(business_id))
                .order_by(User.created_at)
            )
        )
        .scalars()
        .all()
    )


async def list_pending_invites(db: AsyncSession, *, business_id: str) -> list[TeamInvite]:
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(TeamInvite)
                .where(
                    TeamInvite.business_id == _uuid(business_id),
                    TeamInvite.accepted_at.is_(None),
                    TeamInvite.revoked_at.is_(None),
                )
                .order_by(TeamInvite.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [row for row in rows if _aware(row.expires_at) > now]


async def _member(db: AsyncSession, business_id: str, member_id: str) -> User:
    try:
        row = await db.get(User, _uuid(member_id))
    except ValueError:
        row = None
    if row is None or row.business_id != _uuid(business_id):
        raise TeamError("That person isn't on this team.")
    return row


async def _owner_count(db: AsyncSession, business_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.business_id == business_id, User.role == "owner")
        )
    ) or 0


async def change_role(
    db: AsyncSession, *, owner: CurrentUser, member_id: str, role: str
) -> User:
    if role not in TEAM_ROLES:
        raise TeamError(f"Role must be one of: {', '.join(TEAM_ROLES)}.")
    member = await _member(db, owner.business_id, member_id)
    if member.role == "owner" and role != "owner":
        if await _owner_count(db, member.business_id) <= 1:
            raise TeamError("A business needs at least one owner. Promote someone else first.")
    previous = member.role
    member.role = role
    await db.flush()
    await record_audit(
        db,
        business_id=member.business_id,
        action="team_role_changed",
        actor=owner,
        subject_type="user",
        subject_id=str(member.id),
        summary=f"Changed {member.email} from {previous} to {role}",
    )
    return member


async def remove_member(db: AsyncSession, *, owner: CurrentUser, member_id: str) -> None:
    """Remove someone. Takes effect on their very next request (see deps.py)."""
    member = await _member(db, owner.business_id, member_id)
    if member.supabase_user_id and member.supabase_user_id == owner.user_id:
        raise TeamError("You can't remove yourself. Ask another owner to do it.")
    if member.role == "owner" and await _owner_count(db, member.business_id) <= 1:
        raise TeamError("A business needs at least one owner.")
    email = member.email
    await db.delete(member)
    await db.flush()
    await record_audit(
        db,
        business_id=owner.business_id,
        action="team_removed",
        actor=owner,
        subject_type="user",
        subject_id=member_id,
        summary=f"Removed {email} from the team",
    )


async def revoke_invite(db: AsyncSession, *, owner: CurrentUser, invite_id: str) -> None:
    try:
        invite = await db.get(TeamInvite, _uuid(invite_id))
    except ValueError:
        invite = None
    if invite is None or invite.business_id != _uuid(owner.business_id):
        raise TeamError("That invite doesn't exist.")
    if invite.accepted_at is None and invite.revoked_at is None:
        invite.revoked_at = datetime.now(UTC)
        await db.flush()
