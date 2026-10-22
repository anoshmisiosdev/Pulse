"""Team invites, membership resolution, and owner-only gates.

Membership resolution decides which business every request is scoped to, so
it's tested directly against the database rather than through a stubbed
`get_current_user`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.core.deps import CurrentUser, get_current_user, resolve_membership
from app.main import app, fastapi_app
from app.models import Business, Subscription, TeamInvite, User
from app.services import team

OWNER_BIZ = uuid.uuid4()
OTHER_BIZ = uuid.uuid4()


@pytest.fixture(autouse=True)
def no_email(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def _fake(to, subject, text):
        from app.services.senders import SendResult

        sent.append((to, text))
        return SendResult(ok=False, error="resend_not_configured")

    monkeypatch.setattr("app.services.team.send_email", _fake)
    return sent


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(Business(id=OWNER_BIZ, name="Hayward Coffee Co.", vertical="cafe"))
        db.add(Business(id=OTHER_BIZ, name="Glow Studio", vertical="salon"))
        await db.commit()
    yield factory
    await engine.dispose()


def _claims(sub: str, email: str, **app_meta) -> dict:
    return {"sub": sub, "email": email, "app_metadata": app_meta, "user_metadata": {}}


def _owner() -> CurrentUser:
    return CurrentUser(
        user_id="owner-sub",
        email="owner@hayward.coffee",
        business_id=str(OWNER_BIZ),
        business_name="Hayward Coffee Co.",
        role="owner",
    )


# -- Membership resolution ----------------------------------------------------


async def test_a_new_user_resolves_to_their_own_business(sessions):
    async with sessions() as db:
        user = await resolve_membership(db, _claims("lone-sub", "lone@x.com"))
    assert user.business_id == "lone-sub"
    assert user.role == "owner"


async def test_the_first_request_records_the_owner_once_the_business_exists(sessions):
    """Regression: nothing ever wrote a `users` row, so the weekly digest --
    addressed to the owner -- always had nobody to send to."""
    async with sessions() as db:
        await resolve_membership(db, _claims(str(OWNER_BIZ), "owner@hayward.coffee"))
        await resolve_membership(db, _claims(str(OWNER_BIZ), "owner@hayward.coffee"))
    async with sessions() as db:
        rows = (await db.execute(select(User))).scalars().all()
    assert len(rows) == 1  # once, not once per request
    assert rows[0].role == "owner"
    assert rows[0].email == "owner@hayward.coffee"


async def test_no_owner_row_is_written_before_the_business_exists(sessions):
    """The users row has a foreign key to businesses; writing it for a brand-new
    signup who hasn't imported anything would fail on Postgres."""
    async with sessions() as db:
        await resolve_membership(db, _claims("brand-new", "new@x.com"))
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0


async def test_a_member_resolves_to_the_business_that_invited_them(sessions):
    async with sessions() as db:
        db.add(
            User(
                business_id=OWNER_BIZ, supabase_user_id="staff-sub",
                email="staff@x.com", role="staff",
            )
        )
        await db.commit()
        user = await resolve_membership(db, _claims("staff-sub", "staff@x.com"))
    assert user.business_id == str(OWNER_BIZ)
    assert user.role == "staff"
    assert user.business_name == "Hayward Coffee Co."


async def test_service_role_app_metadata_wins_over_a_membership_row(sessions):
    """app_metadata can only be written with Supabase's service role, so it's
    the most authoritative source and must not be overridden by our table."""
    async with sessions() as db:
        db.add(
            User(
                business_id=OWNER_BIZ, supabase_user_id="dual", email="d@x.com", role="staff"
            )
        )
        await db.commit()
        user = await resolve_membership(
            db, _claims("dual", "d@x.com", business_id=str(OTHER_BIZ))
        )
    assert user.business_id == str(OTHER_BIZ)


async def test_a_membership_row_cannot_strip_a_platform_admin_role(sessions):
    async with sessions() as db:
        db.add(
            User(
                business_id=OWNER_BIZ, supabase_user_id="admin-sub",
                email="admin@churnary.com", role="staff",
            )
        )
        await db.commit()
        claims = _claims("admin-sub", "admin@churnary.com", role="admin")
        user = await resolve_membership(db, claims)
    assert user.role == "admin"


async def test_removing_a_member_takes_effect_on_their_next_request(sessions):
    """Why membership lives in our DB and not in a JWT claim: a claim would
    keep working until the token expired."""
    async with sessions() as db:
        db.add(User(business_id=OWNER_BIZ, supabase_user_id="owner-sub",
                    email="owner@hayward.coffee", role="owner"))
        member = User(business_id=OWNER_BIZ, supabase_user_id="leaver",
                      email="leaver@x.com", role="staff")
        db.add(member)
        await db.commit()
        before = await resolve_membership(db, _claims("leaver", "leaver@x.com"))
        assert before.business_id == str(OWNER_BIZ)

        await team.remove_member(db, owner=_owner(), member_id=str(member.id))
        await db.commit()

        after = await resolve_membership(db, _claims("leaver", "leaver@x.com"))
    assert after.business_id == "leaver"  # back to their own, empty business


# -- Invites ------------------------------------------------------------------


async def test_only_a_hash_of_the_invite_token_is_stored(sessions):
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="new@x.com")
        await db.commit()
        stored = await db.get(TeamInvite, created.invite.id)
    assert created.raw_token not in stored.token_hash
    assert stored.token_hash == team.hash_token(created.raw_token)
    assert created.raw_token in created.link


async def test_accepting_an_invite_joins_the_business(sessions):
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="New@X.com")
        await db.commit()
        invitee = CurrentUser(user_id="new-sub", email="new@x.com", business_id="new-sub")
        member = await team.accept_invite(db, user=invitee, raw_token=created.raw_token)
        await db.commit()
    assert member.business_id == OWNER_BIZ
    assert member.role == "staff"


async def test_an_invite_cannot_be_used_by_someone_with_a_different_email(sessions):
    """A forwarded or leaked link is useless to whoever holds it."""
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="intended@x.com")
        await db.commit()
        stranger = CurrentUser(user_id="s", email="stranger@x.com", business_id="s")
        with pytest.raises(team.TeamError, match="sent to intended@x.com"):
            await team.accept_invite(db, user=stranger, raw_token=created.raw_token)


async def test_an_invite_can_only_be_used_once(sessions):
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="once@x.com")
        await db.commit()
        user = CurrentUser(user_id="once", email="once@x.com", business_id="once")
        await team.accept_invite(db, user=user, raw_token=created.raw_token)
        await db.commit()
        with pytest.raises(team.TeamError, match="isn't valid"):
            await team.accept_invite(db, user=user, raw_token=created.raw_token)


async def test_an_expired_invite_is_refused(sessions):
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="late@x.com")
        created.invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    async with sessions() as db:  # fresh session: naive datetime off SQLite
        user = CurrentUser(user_id="late", email="late@x.com", business_id="late")
        with pytest.raises(team.TeamError, match="expired"):
            await team.accept_invite(db, user=user, raw_token=created.raw_token)


async def test_a_wrong_token_and_a_revoked_token_give_the_same_answer(sessions):
    """No oracle for which tokens exist."""
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="r@x.com")
        await db.commit()
        await team.revoke_invite(db, owner=_owner(), invite_id=str(created.invite.id))
        await db.commit()
        user = CurrentUser(user_id="r", email="r@x.com", business_id="r")
        with pytest.raises(team.TeamError) as revoked:
            await team.accept_invite(db, user=user, raw_token=created.raw_token)
        with pytest.raises(team.TeamError) as bogus:
            await team.accept_invite(db, user=user, raw_token="x" * 43)
    assert str(revoked.value) == str(bogus.value)


async def test_reinviting_supersedes_the_earlier_link(sessions):
    async with sessions() as db:
        first = await team.create_invite(db, owner=_owner(), email="twice@x.com")
        second = await team.create_invite(db, owner=_owner(), email="twice@x.com")
        await db.commit()
        user = CurrentUser(user_id="tw", email="twice@x.com", business_id="tw")
        with pytest.raises(team.TeamError):
            await team.accept_invite(db, user=user, raw_token=first.raw_token)
        await team.accept_invite(db, user=user, raw_token=second.raw_token)


async def test_you_cannot_invite_yourself_or_an_existing_member(sessions):
    async with sessions() as db:
        db.add(User(business_id=OWNER_BIZ, supabase_user_id="m", email="m@x.com", role="staff"))
        await db.commit()
        with pytest.raises(team.TeamError, match="already on this team"):
            await team.create_invite(db, owner=_owner(), email="owner@hayward.coffee")
        with pytest.raises(team.TeamError, match="already on this team"):
            await team.create_invite(db, owner=_owner(), email="M@X.com")


async def test_the_last_owner_cannot_be_demoted_or_removed(sessions):
    async with sessions() as db:
        owner_row = User(business_id=OWNER_BIZ, supabase_user_id="owner-sub",
                         email="owner@hayward.coffee", role="owner")
        db.add(owner_row)
        await db.commit()
        with pytest.raises(team.TeamError, match="at least one owner"):
            await team.change_role(db, owner=_owner(), member_id=str(owner_row.id), role="staff")


async def test_an_owner_cannot_remove_themselves(sessions):
    async with sessions() as db:
        me = User(business_id=OWNER_BIZ, supabase_user_id="owner-sub",
                  email="owner@hayward.coffee", role="owner")
        db.add(me)
        db.add(User(business_id=OWNER_BIZ, supabase_user_id="o2", email="o2@x.com", role="owner"))
        await db.commit()
        with pytest.raises(team.TeamError, match="can't remove yourself"):
            await team.remove_member(db, owner=_owner(), member_id=str(me.id))


async def test_members_of_another_business_are_out_of_reach(sessions):
    async with sessions() as db:
        theirs = User(business_id=OTHER_BIZ, supabase_user_id="x", email="x@glow.com", role="staff")
        db.add(theirs)
        await db.commit()
        with pytest.raises(team.TeamError, match="isn't on this team"):
            await team.remove_member(db, owner=_owner(), member_id=str(theirs.id))
        with pytest.raises(team.TeamError):
            await team.change_role(db, owner=_owner(), member_id=str(theirs.id), role="owner")


async def test_the_invite_email_carries_the_link(sessions, no_email):
    async with sessions() as db:
        created = await team.create_invite(db, owner=_owner(), email="mail@x.com")
    assert no_email and no_email[0][0] == "mail@x.com"
    assert created.link in no_email[0][1]
    assert created.emailed is False  # Resend not configured -> link shown instead


# -- Owner-only gates through the API -----------------------------------------


@pytest.fixture
def as_role(sessions):
    def _make(role: str):
        async def _db():
            async with sessions() as session:
                yield session
                await session.commit()

        user = CurrentUser(
            user_id=f"{role}-sub", email=f"{role}@x.com",
            business_id=str(OWNER_BIZ), business_name="Hayward Coffee Co.", role=role,
        )
        fastapi_app.dependency_overrides[get_db] = _db
        fastapi_app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _make
    fastapi_app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/billing/checkout", {"tier": "growth"}),
        ("post", "/api/billing/portal", None),
        ("get", "/api/privacy/export", None),
        ("post", "/api/privacy/delete", {"scope": "all", "confirm": "delete"}),
        ("delete", f"/api/privacy/customers/{uuid.uuid4()}", None),
        ("post", "/api/team/invites", {"email": "x@y.com"}),
    ],
)
async def test_staff_are_refused_owner_only_actions(as_role, sessions, method, path, body):
    """Each of these spends money, moves customer data out, or changes access."""
    client = as_role("staff")
    kwargs = {"json": body} if body is not None else {}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 403
    assert "account owner" in resp.json()["detail"]


async def test_staff_can_still_do_the_daily_work(as_role, sessions):
    async with sessions() as db:
        db.add(Subscription(business_id=OWNER_BIZ, tier="growth", status="active"))
        await db.commit()
    client = as_role("staff")
    assert client.get("/api/portfolio").status_code == 200
    assert client.get("/api/campaigns").status_code == 200
    assert client.get("/api/team").status_code == 200
    assert client.get("/api/billing/subscription").status_code == 200


async def test_staff_do_not_see_pending_invites(as_role, sessions):
    """Pending invites name people who haven't joined yet."""
    async with sessions() as db:
        await team.create_invite(db, owner=_owner(), email="secret@x.com")
        await db.commit()
    assert as_role("staff").get("/api/team").json()["invites"] == []
    assert len(as_role("owner").get("/api/team").json()["invites"]) == 1


async def test_the_full_invite_flow_over_the_api(as_role, sessions):
    owner_client = as_role("owner")
    created = owner_client.post("/api/team/invites", json={"email": "staff@x.com"}).json()
    token = created["link"].split("token=")[1]
    assert created["emailed"] is False

    staff_client = as_role("staff")  # email staff@x.com
    joined = staff_client.post("/api/team/accept", json={"token": token})
    assert joined.status_code == 200
    assert joined.json()["role"] == "staff"
