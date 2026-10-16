"""Integration (E42-T04 S3, #965): `SqlAlchemyUserLifecycleStore` on real Postgres 16: one
transaction with the audit hook ahead of the commit, whole rollback on any failure, the soft
revoke (O4), the owner floor under the lock it shares with the role store (AC6) and AC5. Not
run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_lifecycle import GrantLevel, UserStatusChange
from candleviewer.storage.repositories.user_lifecycle_sqlalchemy import (
    SqlAlchemyUserLifecycleStore,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
#: Bounds every wait on another task: a regression fails instead of hanging CI.
_WAIT_S = 30.0
_NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', 'active')"
)
_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), id FROM roles "
    "WHERE name::text = :role"
)
_SESSION = sa.text(
    "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at, revoked_at, "
    "revoked_reason) VALUES (CAST(:id AS uuid), CAST(:user AS uuid), :hash, "
    "now() + interval '1 day', :revoked_at, :reason)"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
    "VALUES (CAST(:id AS uuid), 'bybit', 'demo', 'main', :uid, :label)"
)
_GRANT = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade) "
    "VALUES (CAST(:user AS uuid), CAST(:account AS uuid), :view, :trade)"
)
# What `risk.freeze_manager` (E39) writes on a manager's grant row.
_FREEZE = sa.text(
    "UPDATE user_account_access SET frozen = true, frozen_at = now(), "
    "frozen_by = CAST(:by AS uuid), frozen_reason = 'drawdown', max_daily_loss_usd = 250 "
    "WHERE user_id = CAST(:id AS uuid)"
)
_STATUS = sa.text("SELECT status::text, updated_at FROM users WHERE id = CAST(:id AS uuid)")
_SESSIONS = sa.text(
    "SELECT id, revoked_at, revoked_reason FROM sessions WHERE user_id = CAST(:id AS uuid)"
)
_GRANTS = sa.text(
    "SELECT exchange_account_id, can_view, can_trade, frozen, frozen_at, frozen_by, "
    "frozen_reason, max_daily_loss_usd, granted_by FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid)"
)
_ACTIVE_OWNERS = sa.text(
    "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
    "JOIN roles r ON r.id = ur.role_id WHERE r.name = 'owner' AND u.status = 'active' "
    "AND u.deleted_at IS NULL ORDER BY u.id"
)
# Other tests' owners would keep the floor met: disable every active owner but `keep`.
_ONLY_OWNERS = sa.text(
    "UPDATE users SET status = 'disabled' WHERE status = 'active' "
    "AND id <> ALL(CAST(:keep AS uuid[])) AND id IN (SELECT ur.user_id FROM user_roles ur "
    "JOIN roles r ON r.id = ur.role_id WHERE r.name = 'owner')"
)
_HOLD = sa.text(
    "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "WHERE r.name = 'owner' FOR UPDATE OF ur"
)
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
# A failure injected into one cascade statement: an UPDATE of a marked (table, user) raises.
_CASCADE_TABLES = ("users", "sessions", "user_account_access")
_FAIL_DDL = (
    "CREATE TABLE IF NOT EXISTS cv_test_fail_on (tbl text NOT NULL, user_id uuid NOT NULL)",
    "CREATE OR REPLACE FUNCTION cv_test_fail_on_fn() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "BEGIN IF EXISTS (SELECT 1 FROM cv_test_fail_on f WHERE f.tbl = TG_TABLE_NAME AND f.user_id "
    "= (to_jsonb(OLD) ->> CASE TG_TABLE_NAME WHEN 'users' THEN 'id' ELSE 'user_id' END)::uuid) "
    "THEN RAISE EXCEPTION 'injected failure on %', TG_TABLE_NAME; END IF; RETURN NEW; END $$",
    *(
        f"CREATE OR REPLACE TRIGGER cv_test_fail_on BEFORE UPDATE ON {t} "
        "FOR EACH ROW EXECUTE FUNCTION cv_test_fail_on_fn()"
        for t in _CASCADE_TABLES
    ),
)
_FAIL_ON = sa.text("INSERT INTO cv_test_fail_on VALUES (:tbl, CAST(:id AS uuid))")


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


class _Hook:
    """Audit hook: records each call, holds until `gate` is set, then may raise `error`."""

    def __init__(self, gate: asyncio.Event | None = None, error: Exception | None = None) -> None:
        self.calls: list[object] = []
        self.entered, self.gate, self.error = asyncio.Event(), gate, error

    async def __call__(self, change: object) -> None:
        self.calls.append(change)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


def _store(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyUserLifecycleStore:
    return SqlAlchemyUserLifecycleStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _user(engine: AsyncEngine, role: str) -> uuid.UUID:
    """An active user holding `role`. The owner-floor trigger refuses the role row while no
    owner is active, so every test creates its acting owner first (`_member`)."""
    uid = uuid.uuid4()
    name = f"u-{uid.hex[:12]}"
    async with engine.begin() as conn:
        await conn.execute(_USER, {"id": str(uid), "email": f"{name}@x.invalid", "name": name})
        await conn.execute(_ROLE, {"id": str(uid), "role": role})
    return uid


async def _session(engine: AsyncEngine, user: uuid.UUID, *, ended: bool = False) -> uuid.UUID:
    """A session of `user`: live, or ended by a logout an hour before `_NOW`."""
    sid, end = uuid.uuid4(), (_NOW - timedelta(hours=1), "logout") if ended else (None, None)
    params = {"id": str(sid), "user": str(user), "hash": secrets.token_hex(32)}
    await _exec(engine, _SESSION, **params, revoked_at=end[0], reason=end[1])
    return sid


async def _grant(
    engine: AsyncEngine, user: uuid.UUID, *, view: bool = True, trade: bool = False
) -> uuid.UUID:
    account = uuid.uuid4()
    label, uid = f"a-{account.hex[:12]}", str(account.int % 10**12)
    await _exec(engine, _ACCOUNT, id=str(account), uid=uid, label=label)
    await _exec(engine, _GRANT, user=str(user), account=str(account), view=view, trade=trade)
    return account


async def _member(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """An acting owner, then a manager with one live session and one live `trade` grant."""
    actor, user = await _user(engine, "owner"), await _user(engine, "manager")
    return actor, user, await _session(engine, user), await _grant(engine, user, trade=True)


async def _snapshot(engine: AsyncEngine, user: uuid.UUID) -> tuple[Any, ...]:
    """The user's status row, sessions and grants, as another connection sees them."""
    async with engine.connect() as conn:
        status = tuple((await conn.execute(_STATUS, {"id": str(user)})).one())
        sessions = {r[0]: tuple(r[1:]) for r in await conn.execute(_SESSIONS, {"id": str(user)})}
        grants = {r[0]: tuple(r[1:]) for r in await conn.execute(_GRANTS, {"id": str(user)})}
    return status, sessions, grants


async def _active_owners(engine: AsyncEngine) -> list[uuid.UUID]:
    async with engine.connect() as conn:
        return [r[0] for r in await conn.execute(_ACTIVE_OWNERS)]


async def _until_blocked(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on a lock (pg_locks is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} callers never blocked on the held owner grants")


async def test_disable_revokes_all_live_sessions_and_grants_in_one_transaction(db: Any) -> None:
    """AC1, store half: while the audit hook runs, another connection still sees nothing
    changed; after the commit every live session and grant is revoked, and no row is gone."""
    rel, engine = db
    actor, user, s1, trade = await _member(engine)
    s2, ended = await _session(engine, user), await _session(engine, user, ended=True)
    read, revoked = await _grant(engine, user), await _grant(engine, user, view=False)
    before, gate = await _snapshot(engine, user), asyncio.Event()
    hook = _Hook(gate=gate)
    call = asyncio.create_task(_store(rel).disable(user, actor=actor, now=_NOW, audit=hook))
    async with asyncio.timeout(_WAIT_S):
        await hook.entered.wait()
    during = await _snapshot(engine, user)
    gate.set()
    async with asyncio.timeout(_WAIT_S):
        change = await call
    (status, _), sessions, grants = await _snapshot(engine, user)
    revoking: dict[uuid.UUID, GrantLevel] = {trade: "trade", read: "read"}
    expected = UserStatusChange(
        user, "active", "disabled", frozenset({"manager"}), tuple(sorted((s1, s2))), revoking
    )
    assert during == before and status == "disabled"
    assert change == hook.calls[0] == expected
    assert all(type(i) is uuid.UUID for i in (*change.revoked_session_ids, *change.revoked_grants))
    gone = (_NOW, "user_disabled")
    assert sessions == {s1: gone, s2: gone, ended: before[1][ended]}
    access = {a: g[:2] for a, g in grants.items()}
    assert access == {a: (False, False) for a in (trade, read, revoked)}


async def test_disable_rolls_back_wholly_when_audit_hook_raises(db: Any) -> None:
    """C-2.9 write-ahead: a refused audit record leaves the status, sessions and grants as
    they were."""
    rel, engine = db
    actor, user, _, _ = await _member(engine)
    before, hook = await _snapshot(engine, user), _Hook(error=AuditUnavailable("WAL unwritable"))
    with pytest.raises(AuditUnavailable):
        await _store(rel).disable(user, actor=actor, now=_NOW, audit=hook)
    assert len(hook.calls) == 1 and await _snapshot(engine, user) == before


@pytest.mark.parametrize("table", _CASCADE_TABLES)
async def test_disable_rolls_back_when_a_cascade_statement_fails(db: Any, table: str) -> None:
    rel, engine = db
    actor, user, _, _ = await _member(engine)
    async with engine.begin() as conn:
        for ddl in _FAIL_DDL:
            await conn.exec_driver_sql(ddl)
        await conn.execute(_FAIL_ON, {"tbl": table, "id": str(user)})
    before, hook = await _snapshot(engine, user), _Hook()
    with pytest.raises(sa.exc.DBAPIError, match=f"injected failure on {table}"):
        await _store(rel).disable(user, actor=actor, now=_NOW, audit=hook)
    assert hook.calls == [] and await _snapshot(engine, user) == before


async def test_disable_last_active_owner_refused_under_lock(db: Any) -> None:
    """The owner floor: refused by the count read under the owner lock, before the deferred
    trigger, with nothing changed and no audit."""
    rel, engine = db
    actor, owner = await _user(engine, "owner"), await _user(engine, "owner")
    await _session(engine, owner)
    await _exec(engine, _ONLY_OWNERS, keep=[str(owner)])
    before, hook = await _snapshot(engine, owner), _Hook()
    with pytest.raises(OwnerFloorError) as refused:
        await _store(rel).disable(owner, actor=actor, now=_NOW, audit=hook)
    assert refused.value.__context__ is None
    assert hook.calls == [] and await _snapshot(engine, owner) == before
    assert await _active_owners(engine) == [owner]


async def test_concurrent_demote_and_disable_keep_owner(db: Any) -> None:
    """AC6, 10 rounds: of the last two owners one is demoted while the other is disabled. A
    third connection holds every owner grant until both callers queue on it; the first to
    queue wins, and the other is refused by the count it read under the lock (not by the
    deferred trigger) and writes no audit. Who is demoted and who queues first alternate, so
    the demotion wins in some rounds and the disable in others; one active owner remains."""
    rel, engine = db
    roles, store = SqlAlchemyUserRoleStore(rel, owner_floor=_floor), _store(rel)
    survivor = await _user(engine, "owner")
    for i in range(10):
        newcomer = await _user(engine, "owner")
        await _exec(engine, _ONLY_OWNERS, keep=[str(survivor), str(newcomer)])
        demoted, disabled = (survivor, newcomer) if i % 2 == 0 else (newcomer, survivor)
        demote_first = i % 4 < 2
        audits = {"demote": _Hook(), "disable": _Hook()}
        demote = roles.apply_roles(
            demoted, frozenset({"viewer"}), actor=disabled, audit=audits["demote"]
        )
        disable = store.disable(disabled, actor=demoted, now=_NOW, audit=audits["disable"])
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
        assert isinstance(lost, OwnerFloorError) and lost.__context__ is None, (i, lost)
        assert len(audits[winner].calls) == 1 and audits[loser].calls == [], i
        survivor = disabled if demote_first else demoted
        assert await _active_owners(engine) == [survivor], i


async def test_disable_already_disabled_user_is_noop(db: Any) -> None:
    """AC5: a second disable writes nothing and calls no audit hook."""
    rel, engine = db
    actor, user, _, _ = await _member(engine)
    first = await _store(rel).disable(user, actor=actor, now=_NOW, audit=_Hook())
    disabled, hook = await _snapshot(engine, user), _Hook()
    later = _NOW + timedelta(seconds=5)
    again = await _store(rel).disable(user, actor=actor, now=later, audit=hook)
    assert first is not None and first.changed
    assert again == UserStatusChange(user, "disabled", "disabled", frozenset({"manager"}))
    assert hook.calls == [] and await _snapshot(engine, user) == disabled


async def test_revoked_grants_keep_freeze_and_loss_cap_columns(db: Any) -> None:
    """#965 O4: the soft revoke leaves the freeze state, the cap and `granted_by` as they were,
    so a disable and a later re-grant never unfreeze a manager (C-12.5)."""
    rel, engine = db
    actor, user, _, account = await _member(engine)
    await _exec(engine, _FREEZE, id=str(user), by=str(actor))
    frozen = (await _snapshot(engine, user))[2][account]
    await _store(rel).disable(user, actor=actor, now=_NOW, audit=_Hook())
    revoked = (await _snapshot(engine, user))[2][account]
    assert frozen[:3] == (True, True, True) and frozen[4:7] == (actor, "drawdown", Decimal(250))
    assert revoked[:2] == (False, False) and revoked[2:] == frozen[2:]
