"""Integration (E42-T09, #2649): the user admin store and routes on real Postgres 16.

AC4: ten rounds, each from two enabled owners, of a parallel cross-demotion through the routes
(`PATCH /users/{userId}` both ways, or one `PATCH` against one `PUT /users/{userId}/roles`): a third
connection holds every owner grant until both calls queue on it, then exactly one wins and the
other is 409 `conflict` (refused by the count it read under the lock, not by the trigger), and one
enabled owner remains. AC6: a demotion racing a disable, ten rounds, keeps an enabled owner and the
loser writes no change record. R6: a re-enable restores no session and no grant. The PATCH disable
runs the whole cascade (SR-029) and, while positions are unknown, needs the acknowledgement (AC7);
its `If-Match` is judged under the disable's own lock, so a role change committed before that lock
refuses it. O3: a rename never clears `mfa_required`. Needs Docker (testcontainers); not run
locally. CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.errors import UserVersionConflictError
from candleviewer.api.users import (
    make_user_admin_router,
    make_users_router,
    representation,
    user_etag,
)
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Settings
from candleviewer.storage.errors import ActorNotAuthorised
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_lifecycle import UserPatch
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    DROP_ROLES,
    GRANT_ROLES,
    SqlAlchemyUserRoleStore,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserAdminStore
from tests.integration.admin.test_user_disable_route_pg import _M as _ROUTE_M
from tests.integration.admin.test_user_disable_route_pg import _OWNER as _ROUTE_OWNER
from tests.integration.admin.test_user_disable_route_pg import _kept, _Parked, _seed
from tests.integration.admin.test_user_lifecycle_pg import (
    _HOLD,
    _HOLD_USER,
    _ONLY_OWNERS,
    _WAIT_S,
    _active_owners,
    _exec,
    _floor,
    _grant,
    _Hook,
    _session,
    _snapshot,
    _store,
    _until_blocked,
    _user,
)
from tests.security.auth.test_disable_user_drill import _Clock
from tests.security.auth.test_disable_user_e2e import (
    _settings,
    deployed,
    rule_disarmed,
    scenario,
    sessions_ended,
)
from tests.security.auth.test_user_admin_e2e import patch_disable

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
_ROLES_OF = sa.text(
    "SELECT array_agg(r.name::text ORDER BY r.name::text) FROM user_roles ur "
    "JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = CAST(:id AS uuid)"
)


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


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyRelationalRepository, AsyncEngine]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        yield rel, engine
    finally:
        await rel.dispose()
        await engine.dispose()


async def _roles(engine: AsyncEngine, user: uuid.UUID) -> list[str]:
    async with engine.connect() as conn:
        found = (await conn.execute(_ROLES_OF, {"id": str(user)})).scalar_one()
    return list(found or ())


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.records.append({"action": action, **kwargs})

    def of(self, actor: uuid.UUID) -> list[tuple[str, str | None]]:
        return [(r["action"], r.get("reason")) for r in self.records if r["actor_user_id"] == actor]


class _Elevated:
    """The session and step-up seams: every bearer is a live, `users`-elevated session."""

    step_up_is_active = sessions_is_active = True

    def __init__(self) -> None:
        self.sessions = self.step_up = self

    async def authenticate_access_token(self, token: str, **_: Any) -> Any:
        return SimpleNamespace(view_as=None, id=uuid.uuid5(uuid.NAMESPACE_URL, token), user_id=None)

    async def peek_access_token(self, token: str) -> Any:
        return None

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        return None


class _Pushes:
    async def roles_changed(self, user_id: uuid.UUID) -> None:
        return None


def _admin_app(rel: SqlAlchemyRelationalRepository, audit: _Audit) -> FastAPI:
    """Both role routes over the real stores, each caller an Owner named by `x-actor`."""

    def resolve(request: Request) -> PrincipalSnapshot:
        actor = uuid.UUID(request.headers["x-actor"])
        return PrincipalSnapshot(actor, frozenset({"owner"}), frozenset(Permission))

    resolver: Any = SimpleNamespace(resolve=resolve)
    auth: Any = _Elevated()
    pushes: Any = _Pushes()
    admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    roles = SqlAlchemyUserRoleStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    app = FastAPI()
    app.include_router(make_users_router(roles, audit, resolver, pushes, auth=auth))
    app.include_router(make_user_admin_router(admin, audit, resolver, pushes, auth=auth))
    return app


async def _demote(
    client: httpx.AsyncClient, actor: uuid.UUID, target: uuid.UUID, *, put: bool
) -> httpx.Response:
    headers = {"x-actor": str(actor), "Authorization": f"Bearer {actor}"}
    if put:  # `PUT /users/{userId}/roles` (#2508)
        return await client.put(
            f"/users/{target}/roles", json={"roles": ["manager"]}, headers=headers
        )
    return await client.patch(f"/users/{target}", json={"roles": ["manager"]}, headers=headers)


async def test_ten_parallel_demotions_one_wins(db: Any) -> None:
    """AC4 (AC-ADM-28, SR-055, D6): in each of 10 rounds, from two enabled owners A and B, A's
    call demotes B while B's demotes A. Exactly one answers 200; the other, whose own owner role
    the winner has just revoked, is refused by its actor's re-read under the owner lock (#2593):
    the 403 `forbidden` a fresh request of B's gets at entry, one `rbac.denied`
    (`actor_role_revoked`) and no change record (UL-F13); one enabled owner remains. Odd rounds
    race a `PATCH` against a `PUT`: both take the one owner lock."""
    rel, engine = db
    audit = _Audit()
    transport = httpx.ASGITransport(app=_admin_app(rel, audit))
    survivor = await _user(engine, "owner")
    async with httpx.AsyncClient(transport=transport, base_url="http://cv.test") as client:
        for i in range(10):
            a, b = survivor, await _user(engine, "owner")
            await _exec(engine, _ONLY_OWNERS, keep=[str(a), str(b)])
            assert sorted(await _active_owners(engine)) == sorted([a, b]), i
            audit.records.clear()
            async with engine.connect() as probe:
                async with engine.begin() as holder:
                    await holder.execute(_HOLD)
                    first = asyncio.create_task(_demote(client, a, b, put=False))
                    await _until_blocked(probe, 1)
                    second = asyncio.create_task(_demote(client, b, a, put=i % 2 == 1))
                    await _until_blocked(probe, 2)
                async with asyncio.timeout(_WAIT_S):
                    won, lost = await asyncio.gather(first, second)
            assert (won.status_code, lost.status_code) == (200, 403), (i, won.text, lost.text)
            assert lost.json() == {
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
                "code": "forbidden",
                "reason": "missing_permission",
            }, i
            assert audit.of(b) == [("rbac.denied", "actor_role_revoked")], i  # one denial
            assert sorted(act for act, _ in audit.of(a)) == ["roles.grant", "roles.revoke"], i
            assert await _active_owners(engine) == [a], i
            assert await _roles(engine, b) == ["manager"] and await _roles(engine, a) == ["owner"]
            survivor = a


async def test_patch_disable_vs_demote_keeps_owner(db: Any) -> None:
    """AC6: of the last two owners one is demoted by a `PATCH` while the other is disabled (the
    store the PATCH and DELETE disable share), 10 rounds behind the lock-hold barrier: the first
    to queue wins, the loser, whose actor the winner has just demoted or disabled, is refused by
    its actor's re-read under the lock (#2593) and its audit hook is never called, and one enabled
    owner remains."""
    rel, engine = db
    admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    lifecycle = _store(rel)
    survivor = await _user(engine, "owner")
    for i in range(10):
        newcomer = await _user(engine, "owner")
        await _exec(engine, _ONLY_OWNERS, keep=[str(survivor), str(newcomer)])
        demoted, disabled = (survivor, newcomer) if i % 2 == 0 else (newcomer, survivor)
        demote_first = i % 4 < 2
        hooks = {"demote": _Hook(), "disable": _Hook()}
        demote = admin.update_user(
            demoted,
            UserPatch(roles=frozenset({"viewer"})),
            actor=disabled,
            check=lambda _: None,
            audit=hooks["demote"],
        )
        disable = lifecycle.disable(disabled, actor=demoted, now=_NOW, audit=hooks["disable"])
        calls = (demote, disable) if demote_first else (disable, demote)
        async with engine.connect() as probe:
            async with engine.begin() as holder:
                await holder.execute(_HOLD)
                first = asyncio.create_task(calls[0])
                await _until_blocked(probe, 1)
                second = asyncio.create_task(calls[1])
                await _until_blocked(probe, 2)
            async with asyncio.timeout(_WAIT_S):
                won, lost = await asyncio.gather(first, second, return_exceptions=True)
        winner, loser = ("demote", "disable") if demote_first else ("disable", "demote")
        assert not isinstance(won, BaseException), (i, won)
        assert isinstance(lost, ActorNotAuthorised) and lost.__context__ is None, (i, lost)
        assert len(hooks[winner].calls) == 1 and hooks[loser].calls == [], i
        survivor = disabled if demote_first else demoted
        assert await _active_owners(engine) == [survivor], i


async def test_enable_no_regrant(db: Any) -> None:
    """R6 (UL3-E2): a disabled manager is re-enabled through the user admin store: `users.enable`
    is handed before and after, the status is `active` again, and nothing comes back: the
    revoked session stays revoked and the soft-revoked grant stays off."""
    rel, engine = db
    owner, manager = await _user(engine, "owner"), await _user(engine, "manager")
    session, account = await _session(engine, manager), await _grant(engine, manager, trade=True)
    await _store(rel).disable(manager, actor=owner, now=_NOW, audit=_Hook())
    disabled = await _snapshot(engine, manager)
    hook = _Hook()
    admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    change = await admin.update_user(
        manager, UserPatch(enable=True), actor=owner, check=lambda _: None, audit=hook
    )
    enabled = await _snapshot(engine, manager)
    assert change is not None and hook.calls == [change]
    assert (change.before["status"], change.after["status"]) == ("disabled", "active")
    assert enabled[0][0] == "active"
    assert enabled[1] == disabled[1] and enabled[1][session][1] == "user_disabled"
    assert enabled[2] == disabled[2] and enabled[2][account][:2] == (False, False)
    assert await _roles(engine, manager) == ["manager"]


async def test_a_rename_never_clears_mfa_required(db: Any) -> None:
    """O3 (C-12.2) on the real statement: a rename of a user whose `mfa_required` is true (the
    column's default) sends `require_mfa` false, and the update's `OR` keeps the flag true."""
    rel, engine = db
    owner, viewer = await _user(engine, "owner"), await _user(engine, "viewer")
    admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    patch = UserPatch(display_name="renamed", set_display_name=True)
    change = await admin.update_user(
        viewer, patch, actor=owner, check=lambda _: None, audit=_Hook()
    )
    assert change is not None and change.before["mfa_required"] is True
    assert (change.after["display_name"], change.after["mfa_required"]) == ("renamed", True)
    stored = await admin.get_user(viewer)
    assert stored is not None and stored["mfa_required"] is True


async def test_a_stale_precondition_and_a_refused_record_change_nothing(db: Any) -> None:
    """412 and 503 at the store: the precondition and the audit hook run under the locks, and
    either raising rolls the whole change back."""
    rel, engine = db
    owner, viewer = await _user(engine, "owner"), await _user(engine, "viewer")
    admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    before = await _snapshot(engine, viewer)

    def stale(_: object) -> None:
        raise LookupError("stale")

    with pytest.raises(LookupError):
        await admin.update_user(
            viewer, UserPatch(roles=frozenset({"manager"})), actor=owner, check=stale, audit=_Hook()
        )
    with pytest.raises(RuntimeError):
        await admin.update_user(
            viewer,
            UserPatch(roles=frozenset({"manager"}), display_name="x", set_display_name=True),
            actor=owner,
            check=lambda _: None,
            audit=_Hook(error=RuntimeError("audit down")),
        )
    assert await _snapshot(engine, viewer) == before and await _roles(engine, viewer) == ["viewer"]


async def test_a_role_change_committed_before_the_disable_lock_refuses_it(db: Any) -> None:
    """UL3-T1 (the #2649 review): a PATCH to `disabled` carries its `If-Match` into
    the disable's own transaction. Another owner's role change holds M's row and the disable
    queues behind it; once that change commits, the disable reads the changed user under its own
    lock and its precondition refuses (412 at the route): nothing is disabled, revoked or
    recorded, and the role change stands."""
    rel, engine = db
    owner, manager = await _user(engine, "owner"), await _user(engine, "manager")
    session = await _session(engine, manager)
    admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    read = await admin.get_user(manager)
    assert read is not None
    tag = user_etag(representation(read))  # the version the PATCH names
    hook, seen = _Hook(), list[list[str]]()

    def unchanged(locked: Any) -> None:
        seen.append(list(locked["roles"]))
        if user_etag(representation(locked)) != tag:
            raise UserVersionConflictError(str(manager))

    to_viewer = {"id": str(manager), "roles": ["viewer"]}
    async with engine.connect() as probe:
        async with engine.begin() as holder:  # the role change, holding M's row until it commits
            await holder.execute(_HOLD_USER, {"id": str(manager)})
            await holder.execute(DROP_ROLES, to_viewer)
            await holder.execute(GRANT_ROLES, to_viewer | {"by": str(owner)})
            disable = asyncio.create_task(
                _store(rel).disable(manager, actor=owner, now=_NOW, audit=hook, check=unchanged)
            )
            await _until_blocked(probe, 1)
        with pytest.raises(UserVersionConflictError):
            async with asyncio.timeout(_WAIT_S):
                await disable
    assert seen == [["viewer"]] and hook.calls == []
    status, sessions, _ = await _snapshot(engine, manager)
    assert status[0] == "active" and sessions[session][0] is None
    assert await _roles(engine, manager) == ["viewer"]


def test_patch_disable_runs_disable_cascade(pg_dsn: str) -> None:
    """SR-029 on Postgres: the S7 scenario of `test_user_disable_route_pg.py` with the disable sent
    as a PATCH: both sessions end (REST 401), all four sockets close 4403 within 5 s on the test
    clock, the rule is disarmed through B9 and audited, one `users.disable` is written, and every
    row of M stays (disabled, its role kept, the grant soft-revoked with freeze and cap kept)."""
    asyncio.run(_seed(pg_dsn))
    w = SimpleNamespace(clock=_Clock())
    w.clock.now = datetime.now(UTC).replace(microsecond=0)
    settings: Settings = _settings().model_copy(update={"pg_dsn": SecretStr(pg_dsn)})
    relational = SqlAlchemyRelationalRepository(pg_dsn, "it-t09")
    w.repo = _Parked(relational)
    with pytest.MonkeyPatch.context() as mp, deployed(mp, settings, w) as (app, client):
        w.rules = app.state.app_context.rules._store
        scenario(app, client, w, str(_ROUTE_OWNER), str(_ROUTE_M), disable=patch_disable)
        assert client.portal is not None
        client.portal.call(relational.dispose)
    sessions_ended(w, answer=200)
    rule_disarmed(w, _ROUTE_OWNER, _ROUTE_M)
    # AC7: the first, unacknowledged PATCH was refused before anything changed.
    assert (w.unacked.status_code, w.unacked.json()["code"]) == (409, "positions_unknown")
    kept, sessions = asyncio.run(_kept(pg_dsn))
    assert kept == ("disabled", 1, False, False, True, "drawdown", Decimal(250))
    assert sessions == ["rotated", "rotated", "user_disabled", "user_disabled"]
