"""Integration (#2593): every owner-only write re-reads its actor at the effect, on Postgres 16.

An owner, A, starts an owner-only write after it was authorised at entry; another owner, B,
revokes A's owner role (or disables A) at the same moment. Both take the owner lock
(`require_active_owner`), so exactly one is ordered first, and the two serial orders are forced
on the first transaction itself, never on time: the first one's write-ahead hook parks on an
`asyncio.Event` while it holds the lock, the second is started, the test waits until a backend
is queued on a lock in `pg_locks` (the parked one holds its locks and waits on nothing), then
releases the first. Each store is built with a long audit bound, so the parked side is never
rolled back by the write-ahead timeout on a slow runner.

- Revoke first: A's write is refused (`ActorNotAuthorised`), nothing of it is written and its
  hook never runs, for every covered store (role set, user update, disable, account access, the
  owner TOTP reset, an owner's session revoke, the invite create, re-issue and revoke, the
  view-as start), and the purge scheduled after a `DELETE ?purge=true` disable.
- A disabled rather than demoted: A's grant row is untouched, so only the fresh statement after
  the lock (never the locked id set) sees it; refused alike.
- A's write first: it commits whole, and B's revoke is ordered after it.

Not run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.models import InviteRecord, SessionRecord
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.view_as import ViewAsNotice, ViewAsState
from candleviewer.storage.errors import ActorNotAuthorised
from candleviewer.storage.repositories.account_access_sqlalchemy import (
    SqlAlchemyAccountAccessStore,
)
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.owner_totp_reset_sqlalchemy import SqlAlchemyOwnerTotpReset
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from candleviewer.storage.repositories.user_lifecycle import UserPatch
from candleviewer.storage.repositories.user_lifecycle_sqlalchemy import (
    SqlAlchemyUserLifecycleStore,
)
from candleviewer.storage.repositories.user_purge_sqlalchemy import SqlAlchemyUserPurgeStore
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserAdminStore

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
#: Bounds every wait on another task, and every store's write-ahead bound: a regression fails
#: instead of hanging CI, and a parked hook is never rolled back by its own timeout.
_WAIT_S = 30.0
#: The invite's placeholder: `users_pwd_argon` (0001) admits only an Argon2id head, as
#: `test_invites_pg.py` binds it.
_DIGEST = "$argon2id$x"
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', CAST(:status AS user_status))"
)
_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), id FROM roles "
    "WHERE name::text = :role"
)
_SESSION = sa.text(
    "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at) VALUES "
    "(CAST(:id AS uuid), CAST(:user AS uuid), :hash, now() + interval '1 day')"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
    "VALUES (CAST(:id AS uuid), 'bybit', 'demo', 'main', :uid, :label)"
)
_ROLES_OF = sa.text(
    "SELECT r.name::text FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "WHERE ur.user_id = CAST(:id AS uuid) ORDER BY 1"
)
_STATE = sa.text(
    "SELECT u.status::text, u.mfa_required, u.display_name, "
    "(SELECT count(*) FROM sessions s WHERE s.user_id = u.id AND s.revoked_at IS NULL), "
    "(SELECT count(*) FROM user_account_access a WHERE a.user_id = u.id AND a.can_view), "
    "(SELECT count(*) FROM user_invites i WHERE i.user_id = u.id AND i.revoked_at IS NULL) "
    "FROM users u WHERE u.id = CAST(:id AS uuid)"
)
_VIEWING = sa.text("SELECT view_as_context_id FROM sessions WHERE id = CAST(:id AS uuid)")
_USERS = sa.text("SELECT count(*) FROM users")
_DISABLE = sa.text("UPDATE users SET status = 'disabled' WHERE id = CAST(:id AS uuid)")
_PURGE_AFTER = sa.text("SELECT purge_after FROM users WHERE id = CAST(:id AS uuid)")


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


def _session_record(**fields: Any) -> SessionRecord:
    return SessionRecord.model_validate(fields)


class _Park:
    """A write-ahead hook that records its call, then holds until released (the parked side)."""

    def __init__(self, name: str, order: list[str], *, hold: bool) -> None:
        self.name, self.order = name, order
        self.entered, self.released = asyncio.Event(), asyncio.Event()
        if not hold:
            self.released.set()

    async def __call__(self, *_args: Any, **_kw: Any) -> None:
        self.order.append(self.name)
        self.entered.set()
        async with asyncio.timeout(_WAIT_S):
            await self.released.wait()


@dataclass
class _World:
    """A and B, active owners; T, an active manager with a live session; I, an invited user
    with an open invite (created by B); X, a live account; A's own live session."""

    rel: SqlAlchemyRelationalRepository
    engine: AsyncEngine
    a: uuid.UUID
    b: uuid.UUID
    t: uuid.UUID
    t_session: uuid.UUID
    a_session: uuid.UUID
    invited: uuid.UUID
    account: uuid.UUID

    async def state(self, user: uuid.UUID) -> tuple[Any, ...]:
        """The user's row, live sessions, grants, open invites and roles; A's view-as context;
        and how many users exist (an invite creates one)."""
        async with self.engine.connect() as conn:
            row = (await conn.execute(_STATE, {"id": str(user)})).one()
            roles = [r[0] for r in await conn.execute(_ROLES_OF, {"id": str(user)})]
            viewing = (await conn.execute(_VIEWING, {"id": str(self.a_session)})).scalar_one()
            users = (await conn.execute(_USERS)).scalar_one()
        return (*row, tuple(roles), viewing, users)


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _user(engine: AsyncEngine, role: str, status: str = "active") -> uuid.UUID:
    uid = uuid.uuid4()
    name = f"r-{uid.hex[:12]}"
    await _exec(engine, _USER, id=str(uid), email=f"{name}@x.invalid", name=name, status=status)
    await _exec(engine, _ROLE, id=str(uid), role=role)
    return uid


async def _session(engine: AsyncEngine, user: uuid.UUID) -> uuid.UUID:
    sid = uuid.uuid4()
    await _exec(engine, _SESSION, id=str(sid), user=str(user), hash=uuid.uuid4().hex * 2)
    return sid


@pytest.fixture
async def world(pg_dsn: str) -> Any:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        a, b = await _user(engine, "owner"), await _user(engine, "owner")
        t = await _user(engine, "manager")
        account = uuid.uuid4()
        # Per world: `ux_ea_label (env, lower(label))` and `ux_ea_uid` (0017) span the module's
        # one container, so a constant label refuses the second world's account.
        uid, label = str(account.int % 10**12), f"recheck-{account.hex[:12]}"
        await _exec(engine, _ACCOUNT, id=str(account), uid=uid, label=label)
        invited = uuid.uuid4()
        created = await _invites(rel).create_user_with_invite(
            user_id=invited,
            invite_id=uuid.uuid4(),
            email=f"i-{invited.hex[:12]}@x.invalid",
            username=f"i-{invited.hex[:12]}",
            display_name=None,
            role="viewer",
            placeholder_password_hash=_DIGEST,
            invited_by=b,
            token_hash=uuid.uuid4().hex * 2,
            expires_at=datetime.now(UTC) + timedelta(hours=72),
            audit=_Park("seed", [], hold=False),
        )
        assert created is True
        yield _World(
            rel,
            engine,
            a,
            b,
            t,
            await _session(engine, t),
            await _session(engine, a),
            invited,
            account,
        )
    finally:
        await rel.dispose()
        await engine.dispose()


def _invites(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyInviteRepository:
    return SqlAlchemyInviteRepository(
        rel, lambda **f: InviteRecord.model_validate(f), audit_timeout_s=_WAIT_S
    )


def _audit_hook(park: _Park, ahead: str = "users.access_change") -> Any:
    """An emitter whose write-ahead record (`ahead`; a closing one too) is `park`."""

    class _Emitter:
        async def emit(self, action: str, **_kw: Any) -> None:
            if action == ahead:
                await park()

    return _Emitter()


#: A's owner-only write, against the world, with `park` as its write-ahead hook.
Effect = Callable[[_World, _Park], Awaitable[Any]]


async def _set_roles(w: _World, park: _Park) -> Any:
    store = SqlAlchemyUserRoleStore(w.rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    return await store.apply_roles(w.t, frozenset({"viewer"}), actor=w.a, audit=park)


async def _update(w: _World, park: _Park) -> Any:
    store = SqlAlchemyUserAdminStore(w.rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    patch = UserPatch(display_name="Renamed", set_display_name=True)
    return await store.update_user(w.t, patch, actor=w.a, check=lambda _u: None, audit=park)


async def _disable(w: _World, park: _Park) -> Any:
    store = SqlAlchemyUserLifecycleStore(w.rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    return await store.disable(w.t, actor=w.a, now=datetime.now(UTC), audit=park)


async def _access(w: _World, park: _Park) -> Any:
    emitter = _audit_hook(park)
    store = SqlAlchemyAccountAccessStore(w.rel, audit=emitter, audit_timeout_s=_WAIT_S)
    return await store.replace_grants(w.t, {w.account: "read"}, actor_user_id=w.a)


async def _reset(w: _World, park: _Park) -> Any:
    store = SqlAlchemyOwnerTotpReset(w.rel, _session_record, audit_timeout_s=_WAIT_S)
    return await store.reset_totp(
        str(w.t), actor_user_id=str(w.a), now=datetime.now(UTC), reason="mfa_reset_by_owner",
        audit=park,
    )  # fmt: skip


async def _revoke_session(w: _World, park: _Park) -> Any:
    store = SqlAlchemySessionRepository(w.rel, _session_record)
    return await store.revoke_by_owner(
        str(w.t_session), user_id=str(w.t), actor_user_id=str(w.a), reason="admin",
        now=datetime.now(UTC), write_ahead=park, audit_timeout_s=_WAIT_S,
    )  # fmt: skip


async def _invite(w: _World, park: _Park) -> Any:
    name = f"n-{w.t.hex[:12]}"
    return await _invites(w.rel).create_user_with_invite(
        user_id=uuid.uuid4(), invite_id=uuid.uuid4(), email=f"{name}@x.invalid", username=name,
        display_name=None, role="viewer", placeholder_password_hash=_DIGEST, invited_by=w.a,
        token_hash=uuid.uuid4().hex * 2, expires_at=datetime.now(UTC) + timedelta(hours=72),
        audit=park,
    )  # fmt: skip


async def _reissue(w: _World, park: _Park) -> Any:
    return await _invites(w.rel).reissue(
        w.invited, invite_id=uuid.uuid4(), token_hash=uuid.uuid4().hex * 2, invited_by=w.a,
        expires_at=datetime.now(UTC) + timedelta(hours=72), now=datetime.now(UTC), audit=park,
    )  # fmt: skip


async def _revoke_invite(w: _World, park: _Park) -> Any:
    return await _invites(w.rel).revoke_open(
        w.invited, actor=w.a, now=datetime.now(UTC), audit=park
    )


async def _view_as(w: _World, park: _Park) -> Any:
    state = ViewAsState.start(uuid.uuid4(), w.t, now=datetime.now(UTC))
    return await SqlAlchemySessionRepository(w.rel, _session_record).start_view_as_unit(
        str(w.a_session), state, now=datetime.now(UTC), notice=ViewAsNotice(w.t, "m", None),
        flush_pending_end=park, write_ahead=park, audit_timeout_s=_WAIT_S,
    )  # fmt: skip


_EFFECTS: dict[str, Effect] = {
    "set_roles": _set_roles,
    "update_user": _update,
    "disable": _disable,
    "account_access": _access,
    "totp_reset": _reset,
    "session_revoke": _revoke_session,
    "invite_create": _invite,
    "invite_reissue": _reissue,
    "invite_revoke": _revoke_invite,
    "view_as_start": _view_as,
}


async def _until_queued(probe: AsyncConnection) -> None:
    """Bounded condition wait: a backend queued on a lock. The parked side holds its locks and
    waits on nothing in the database, so the one waiter is the other side."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= 1:
            return
        await asyncio.sleep(0.025)
    raise AssertionError("the second transaction never queued on the first one's locks")


async def _first_then(
    w: _World,
    first: Callable[[], Awaitable[Any]],
    parked: _Park,
    second: Callable[[], Awaitable[Any]],
) -> tuple[Any, Any]:
    """Run `first` until it parks in its hook (its locks held), start `second`, wait until it
    queues on them, then release `first`: the two run in that serial order."""
    async with w.engine.connect() as probe:
        one = asyncio.create_task(first())
        async with asyncio.timeout(_WAIT_S):
            await parked.entered.wait()
        two = asyncio.create_task(second())
        await _until_queued(probe)
        parked.released.set()
        async with asyncio.timeout(_WAIT_S):
            return tuple(await asyncio.gather(one, two, return_exceptions=True))  # type: ignore[return-value]


async def _schedule_purge(w: _World, park: _Park) -> Any:
    """The eleventh write: the purge scheduled after the disable committed (T disabled first)."""
    store = SqlAlchemyUserPurgeStore(
        w.rel,
        audit=_audit_hook(park, "users.delete"),
        clock=lambda: datetime.now(UTC),
        audit_timeout_s=_WAIT_S,
    )
    return await store.schedule(w.t, actor_user_id=w.a)


def _demote_a(w: _World, park: _Park) -> Callable[[], Awaitable[Any]]:
    store = SqlAlchemyUserRoleStore(w.rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    return lambda: store.apply_roles(w.a, frozenset({"viewer"}), actor=w.b, audit=park)


def _disable_a(w: _World, park: _Park) -> Callable[[], Awaitable[Any]]:
    store = SqlAlchemyUserLifecycleStore(w.rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    return lambda: store.disable(w.a, actor=w.b, now=datetime.now(UTC), audit=park)


@pytest.mark.parametrize("effect", list(_EFFECTS), ids=list(_EFFECTS))
async def test_a_revoke_ordered_first_refuses_the_in_flight_write_with_nothing_written(
    world: _World, effect: str
) -> None:
    w, order = world, list[str]()
    before = (await w.state(w.t), await w.state(w.invited))
    revoke, effects = _Park("revoke", order, hold=True), _Park("effect", order, hold=False)
    revoked, refused = await _first_then(
        w, _demote_a(w, revoke), revoke, lambda: _EFFECTS[effect](w, effects)
    )
    assert revoked is True, revoked
    assert isinstance(refused, ActorNotAuthorised), refused
    assert refused.actor_id == str(w.a)
    assert order == ["revoke"]  # A's write-ahead hook never ran: nothing recorded ahead
    assert (await w.state(w.t), await w.state(w.invited)) == before
    async with w.engine.connect() as conn:
        assert [r[0] for r in await conn.execute(_ROLES_OF, {"id": str(w.a)})] == ["viewer"]


@pytest.mark.parametrize("effect", ["set_roles", "totp_reset", "view_as_start"])
async def test_a_disable_ordered_first_refuses_the_in_flight_write_though_the_grant_stays(
    world: _World, effect: str
) -> None:
    """BQ-03: B disables A; A's owner grant row is untouched, so A is still in the set the lock
    statement returns. Only the fresh statement after the lock sees A disabled."""
    w, order = world, list[str]()
    before = await w.state(w.t)
    disable, effects = _Park("disable", order, hold=True), _Park("effect", order, hold=False)
    disabled, refused = await _first_then(
        w, _disable_a(w, disable), disable, lambda: _EFFECTS[effect](w, effects)
    )
    assert disabled is not None and not isinstance(disabled, BaseException), disabled
    assert isinstance(refused, ActorNotAuthorised), refused
    assert order == ["disable"] and await w.state(w.t) == before
    async with w.engine.connect() as conn:
        assert [r[0] for r in await conn.execute(_ROLES_OF, {"id": str(w.a)})] == ["owner"]


@pytest.mark.parametrize("effect", ["set_roles", "totp_reset", "account_access"])
async def test_an_in_flight_write_ordered_first_commits_and_the_revoke_follows_it(
    world: _World, effect: str
) -> None:
    """The other serial order: A's write holds the owner lock in its write-ahead hook; B's revoke
    queues behind it, then commits after A's effect."""
    w, order = world, list[str]()
    before = await w.state(w.t)
    effects, revoke = _Park("effect", order, hold=True), _Park("revoke", order, hold=False)
    done, revoked = await _first_then(
        w, lambda: _EFFECTS[effect](w, effects), effects, _demote_a(w, revoke)
    )
    assert not isinstance(done, BaseException), done
    assert revoked is True, revoked
    assert order == ["effect", "revoke"]  # A's record and commit precede B's revoke
    assert await w.state(w.t) != before  # A's effect landed whole
    async with w.engine.connect() as conn:
        assert [r[0] for r in await conn.execute(_ROLES_OF, {"id": str(w.a)})] == ["viewer"]


async def test_an_active_owner_demoting_itself_is_not_refused_by_the_recheck(
    world: _World,
) -> None:
    """The actor is re-read before the write, so an active owner's self-demotion passes it (the
    floor guards the last owner); the store answers as before."""
    w = world
    store = SqlAlchemyUserRoleStore(w.rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    park = _Park("self", [], hold=False)
    assert await store.apply_roles(w.a, frozenset({"viewer"}), actor=w.a, audit=park) is True


@pytest.mark.parametrize("revoke_first", [True, False], ids=["revoke-first", "purge-first"])
async def test_the_purge_schedule_after_a_disable_is_ordered_against_a_revoke(
    world: _World, revoke_first: bool
) -> None:
    """The eleventh owner-only write (`DELETE ?purge=true`'s second transaction): T is disabled
    (the first transaction, committed). Revoke first: A's schedule is refused under the owner
    lock, `purge_after` stays NULL and its `users.delete` never runs. Schedule first: it commits
    whole, and B's revoke is ordered after it."""
    w, order = world, list[str]()
    await _exec(w.engine, _DISABLE, id=str(w.t))
    hold, free = ("revoke", "effect") if revoke_first else ("effect", "revoke")
    parked, other = _Park(hold, order, hold=True), _Park(free, order, hold=False)
    revoke = _demote_a(w, parked if revoke_first else other)
    purge = partial(_schedule_purge, w, other if revoke_first else parked)
    if revoke_first:
        revoked, scheduled = await _first_then(w, revoke, parked, purge)
    else:
        scheduled, revoked = await _first_then(w, purge, parked, revoke)
    assert revoked is True, revoked
    async with w.engine.connect() as conn:
        purge_after: datetime | None
        purge_after = (await conn.execute(_PURGE_AFTER, {"id": str(w.t)})).scalar_one()
        roles = [r[0] for r in await conn.execute(_ROLES_OF, {"id": str(w.a)})]
    assert roles == ["viewer"]
    if revoke_first:
        assert isinstance(scheduled, ActorNotAuthorised), scheduled
        assert scheduled.actor_id == str(w.a)
        assert order == ["revoke"] and purge_after is None
    else:
        assert not isinstance(scheduled, BaseException) and scheduled.changed, scheduled
        assert order == ["effect", "revoke"] and purge_after is not None
