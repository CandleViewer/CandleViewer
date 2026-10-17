"""Integration (E42-T08 S8 to S9c, #2648): `SqlAlchemyAccountAccessStore` on real Postgres 16.

The audit record is written ahead of the commit, and a refused one changes nothing. A soft
revoke keeps the freeze state and the cap. An unknown account or a user who is not active
rolls the whole set back. A replacement racing a disable leaves no live grant in either order
(a third connection sees the second caller queued in `pg_locks`). The ids read back are plain
UUIDs. Onboarding ignores revoked grants. S9a: a grant and an account soft delete queue behind
each other in either order, as a user soft delete does; a lock wait past `lock_timeout` changes
nothing; no grant write leaves a frozen manager an unfrozen grant, and an inherited freeze
never copies the cap. S9b: the read behind `GET /users/{userId}/account-access` lists only the
user's live grants of live accounts and takes no row lock. S9c: a replacement answers the new
set (label, environment, last granter) read under its own locks, so the `PUT` reads nothing
after the commit.
Not run locally (no docker); exercised by CI `integration`.
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
from typing import Any

import orjson
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.account_access import (
    AccessAuditUnavailableError,
    AccessBusyError,
    AccessGrant,
    AccessLevel,
    AccessUnknownAccountError,
    AccessUserNotActiveError,
    AccessUserNotFoundError,
    RemovalContext,
)
from candleviewer.storage.repositories.account_access_sqlalchemy import (
    SqlAlchemyAccountAccessStore,
)
from candleviewer.storage.repositories.onboarding_sqlalchemy import SqlAlchemyOnboardingStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
#: Bounds every wait on another task: a regression fails instead of hanging CI.
_WAIT_S = 30.0
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', CAST(:status AS user_status))"
)
_OWNER = sa.text(
    "INSERT INTO user_roles (user_id, role_id) "
    "SELECT CAST(:id AS uuid), id FROM roles WHERE name = 'owner'"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
    "VALUES (CAST(:id AS uuid), 'bybit', 'demo', 'main', :uid, :label)"
)
_SOFT_DELETE = sa.text(
    "UPDATE exchange_accounts SET deleted_at = now() WHERE id = CAST(:id AS uuid)"
)
_ROWS = sa.text(
    "SELECT exchange_account_id, can_view, can_trade, frozen, frozen_at, frozen_by, "
    "frozen_reason, max_daily_loss_usd FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid) ORDER BY exchange_account_id"
)
# What `risk.freeze_manager` (E39) writes on a manager's grant row.
_FREEZE = sa.text(
    "UPDATE user_account_access SET frozen = true, frozen_at = now(), "
    "frozen_by = CAST(:by AS uuid), frozen_reason = 'drawdown', max_daily_loss_usd = 250 "
    "WHERE user_id = CAST(:id AS uuid)"
)
# One grant row frozen at its own time, by its own actor, for its own reason.
_FREEZE_ROW = sa.text(
    "UPDATE user_account_access SET frozen = true, frozen_at = CAST(:at AS timestamptz), "
    "frozen_by = CAST(:by AS uuid), frozen_reason = :reason "
    "WHERE user_id = CAST(:id AS uuid) AND exchange_account_id = CAST(:account AS uuid)"
)
# What the E42-T04 disable store does in one transaction: lock the user row first, then set
# the status and soft-revoke every grant.
_DISABLE = (
    sa.text("SELECT 1 FROM users WHERE id = CAST(:id AS uuid) FOR NO KEY UPDATE"),
    sa.text("UPDATE users SET status = 'disabled' WHERE id = CAST(:id AS uuid)"),
    sa.text(
        "UPDATE user_account_access SET can_view = false, can_trade = false "
        "WHERE user_id = CAST(:id AS uuid)"
    ),
)
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
_ACK = RemovalContext(acknowledged_unknown_positions=True)  # O2: these tests read no counts
_USER_SOFT_DELETE = sa.text("UPDATE users SET deleted_at = now() WHERE id = CAST(:id AS uuid)")
#: A grant row written outside the store, live or soft-revoked and never frozen.
_ROW = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view) "
    "VALUES (CAST(:id AS uuid), CAST(:account AS uuid), :view)"
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


class _Audit:
    """Records each write-ahead record; with a `gate` the emit holds until the gate is set."""

    def __init__(self, gate: asyncio.Event | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.entered, self.gate, self.error = asyncio.Event(), gate, error

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error


def _store(
    rel: SqlAlchemyRelationalRepository, audit: _Audit | None = None
) -> SqlAlchemyAccountAccessStore:
    return SqlAlchemyAccountAccessStore(rel, audit=audit or _Audit(), audit_timeout_s=60.0)


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _setup(
    engine: AsyncEngine, accounts: int, status: str = "active"
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """An active owner (the actor), a user with `status`, and live accounts in id order."""
    owner, user, ids = uuid.uuid4(), uuid.uuid4(), sorted(uuid.uuid4() for _ in range(accounts))
    for uid, st in ((owner, "active"), (user, status)):
        name = f"u-{uid.hex[:12]}"
        await _exec(engine, _USER, id=str(uid), email=f"{name}@x.invalid", name=name, status=st)
    await _exec(engine, _OWNER, id=str(owner))
    for a in ids:
        await _exec(engine, _ACCOUNT, id=str(a), uid=str(a.int % 10**12), label=f"a-{a.hex[:12]}")
    return owner, user, ids


async def _rows(engine: AsyncEngine, user: uuid.UUID) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(_ROWS, {"id": str(user)})).all())


async def _access(engine: AsyncEngine, user: uuid.UUID) -> dict[uuid.UUID, tuple[bool, bool]]:
    return {r[0]: (r[1], r[2]) for r in await _rows(engine, user)}


async def _until_blocked(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on a lock (pg_locks is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} callers never blocked on a row lock")


async def _disable(engine: AsyncEngine, user: uuid.UUID) -> None:
    async with engine.begin() as conn:
        for stmt in _DISABLE:
            await conn.execute(stmt, {"id": str(user)})


async def test_replace_write_ahead_audit(db: Any) -> None:
    """While the record is written, another connection still sees the old grants."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    gate = asyncio.Event()
    audit = _Audit(gate=gate)
    call = asyncio.create_task(
        _store(rel, audit).replace_grants(user, {b: "trade"}, actor_user_id=owner, removal=_ACK)
    )
    async with asyncio.timeout(_WAIT_S):
        await audit.entered.wait()
    at_emit = await _access(engine, user)
    gate.set()
    async with asyncio.timeout(_WAIT_S):
        await call
    assert at_emit == {a: (True, False)}
    assert await _access(engine, user) == {a: (False, False), b: (True, True)}


async def test_replace_audits_the_live_grants_before_and_after(db: Any) -> None:
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    audit = _Audit()
    await _store(rel, audit).replace_grants(user, {b: "trade"}, actor_user_id=owner, removal=_ACK)
    ((action, kwargs),) = audit.calls
    assert action == "users.access_change"
    before = [{"exchange_account_id": str(a), "level": "read", "frozen": False}]
    after = [{"exchange_account_id": str(b), "level": "trade", "frozen": False}]
    assert kwargs["before_state"] == {"grants": before}
    assert kwargs["after_state"] == {
        "grants": after,
        "positions_decision": "leave",
        "open_position_count": None,
        "open_order_count": None,
        "acknowledged_unknown_positions": True,
    }


async def test_refused_audit_changes_nothing(db: Any) -> None:
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    refusing = _Audit(error=RuntimeError("audit WAL unavailable"))
    with pytest.raises(AccessAuditUnavailableError):
        await _store(rel, refusing).replace_grants(
            user, {b: "trade"}, actor_user_id=owner, removal=_ACK
        )
    assert await _access(engine, user) == {a: (True, False)}


async def test_replace_returns_plain_uuids(db: Any) -> None:
    """asyncpg reads ids back as its own UUID subclass, which orjson refuses."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    change = await _store(rel).replace_grants(user, {b: "trade"}, actor_user_id=owner, removal=_ACK)
    body = orjson.dumps(
        {"before": change.before, "after": change.after}, option=orjson.OPT_NON_STR_KEYS
    )
    assert orjson.loads(body) == {"before": {str(a): "read"}, "after": {str(b): "trade"}}


async def test_keeps_freeze_and_cap(db: Any) -> None:
    rel, engine = db
    owner, user, (s,) = await _setup(engine, 1)
    store = _store(rel)
    await store.replace_grants(user, {s: "trade"}, actor_user_id=owner)
    await _exec(engine, _FREEZE, id=str(user), by=str(owner))
    frozen = [r[3:] for r in await _rows(engine, user)]
    await store.replace_grants(user, {}, actor_user_id=owner, removal=_ACK)
    revoked = await _rows(engine, user)
    await store.replace_grants(user, {s: "read"}, actor_user_id=owner)
    regranted = await _rows(engine, user)
    assert frozen[0][0] is True and frozen[0][2:] == (owner, "drawdown", Decimal("250"))
    assert [r[1:3] for r in revoked] == [(False, False)] and [r[3:] for r in revoked] == frozen
    assert [r[1:3] for r in regranted] == [(True, False)] and [r[3:] for r in regranted] == frozen


async def test_unknown_account_rolls_back(db: Any) -> None:
    rel, engine = db
    owner, user, (a, deleted) = await _setup(engine, 2)
    await _exec(engine, _SOFT_DELETE, id=str(deleted))
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    missing, audit = uuid.uuid4(), _Audit()
    with pytest.raises(AccessUnknownAccountError) as err:
        await _store(rel, audit).replace_grants(
            user, {a: "trade", missing: "read", deleted: "read"}, actor_user_id=owner
        )
    assert err.value.account_ids == frozenset({missing, deleted}) and not audit.calls
    assert await _access(engine, user) == {a: (True, False)}


@pytest.mark.parametrize("status", ["invited", "locked", "disabled"])
async def test_non_active_user_409(db: Any, status: str) -> None:
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1, status)
    audit = _Audit()
    with pytest.raises(AccessUserNotActiveError):
        await _store(rel, audit).replace_grants(user, {a: "read"}, actor_user_id=owner)
    assert await _access(engine, user) == {} and not audit.calls


async def test_disable_vs_replace_race_no_live_grant(db: Any) -> None:
    """The disable locks the user row first: the replacement queues, then sees `disabled`."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    async with engine.connect() as probe:
        async with engine.begin() as disabler:
            for stmt in _DISABLE:
                await disabler.execute(stmt, {"id": str(user)})
            call = asyncio.create_task(
                _store(rel).replace_grants(user, {a: "trade", b: "read"}, actor_user_id=owner)
            )
            await _until_blocked(probe, 1)
        with pytest.raises(AccessUserNotActiveError):
            async with asyncio.timeout(_WAIT_S):
                await call
    assert await _access(engine, user) == {a: (False, False)}


async def test_replace_vs_disable_race_no_live_grant(db: Any) -> None:
    """The replacement locks the user row first and holds it through the audit and the
    commit: the disable queues, then soft-revokes every grant the replacement committed."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    gate = asyncio.Event()
    audit = _Audit(gate=gate)
    async with engine.connect() as probe:
        call = asyncio.create_task(
            _store(rel, audit).replace_grants(user, {a: "trade", b: "read"}, actor_user_id=owner)
        )
        async with asyncio.timeout(_WAIT_S):
            await audit.entered.wait()
        disable = asyncio.create_task(_disable(engine, user))
        await _until_blocked(probe, 1)
        gate.set()
        async with asyncio.timeout(_WAIT_S):
            change = await call
            await disable
    assert change.after == {a: "trade", b: "read"}  # committed first, not refused
    assert await _access(engine, user) == {a: (False, False), b: (False, False)}


async def test_onboarding_ignores_revoked(db: Any) -> None:
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    store, onboarding = _store(rel), SqlAlchemyOnboardingStore(rel)
    await store.replace_grants(user, {a: "read"}, actor_user_id=owner)
    bound = await onboarding.has_account_binding(user), await onboarding.latest_binding_at(user)
    await store.replace_grants(user, {}, actor_user_id=owner, removal=_ACK)
    revoked = await onboarding.has_account_binding(user), await onboarding.latest_binding_at(user)
    assert bound[0] is True and bound[1] is not None
    assert revoked == (False, None)


async def test_account_soft_delete_first_refuses_the_grant(db: Any) -> None:
    """The delete holds the account row; the grant queues on `FOR SHARE`, then finds it gone."""
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    audit = _Audit()
    async with engine.connect() as probe:
        async with engine.begin() as deleter:
            await deleter.execute(_SOFT_DELETE, {"id": str(a)})
            call = asyncio.create_task(
                _store(rel, audit).replace_grants(user, {a: "read"}, actor_user_id=owner)
            )
            await _until_blocked(probe, 1)
        with pytest.raises(AccessUnknownAccountError):
            async with asyncio.timeout(_WAIT_S):
                await call
    assert await _access(engine, user) == {} and not audit.calls


async def test_grant_first_blocks_the_account_soft_delete_until_commit(db: Any) -> None:
    """The grant holds the account `FOR SHARE` through its audit and commit: the delete queues.
    A grant that committed first stays live after the delete (an E27 follow-up, not S9)."""
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    gate = asyncio.Event()
    audit = _Audit(gate=gate)
    async with engine.connect() as probe:
        call = asyncio.create_task(
            _store(rel, audit).replace_grants(user, {a: "read"}, actor_user_id=owner)
        )
        async with asyncio.timeout(_WAIT_S):
            await audit.entered.wait()
        delete = asyncio.create_task(_exec(engine, _SOFT_DELETE, id=str(a)))
        await _until_blocked(probe, 1)
        gate.set()
        async with asyncio.timeout(_WAIT_S):
            change = await call
            await delete
    assert change.after == {a: "read"} and await _access(engine, user) == {a: (True, False)}


async def test_user_soft_delete_first_refuses_the_grant(db: Any) -> None:
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    audit = _Audit()
    async with engine.connect() as probe:
        async with engine.begin() as deleter:
            await deleter.execute(_USER_SOFT_DELETE, {"id": str(user)})
            call = asyncio.create_task(
                _store(rel, audit).replace_grants(user, {a: "read"}, actor_user_id=owner)
            )
            await _until_blocked(probe, 1)
        with pytest.raises(AccessUserNotFoundError):
            async with asyncio.timeout(_WAIT_S):
                await call
    assert await _access(engine, user) == {} and not audit.calls


async def test_lock_timeout_refuses_and_changes_nothing(db: Any) -> None:
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    audit = _Audit()
    store = SqlAlchemyAccountAccessStore(rel, audit=audit, lock_timeout_ms=200)
    async with engine.begin() as holder:  # holds the user row past the store's bound
        await holder.execute(_DISABLE[0], {"id": str(user)})
        with pytest.raises(AccessBusyError):
            async with asyncio.timeout(_WAIT_S):
                await store.replace_grants(user, {a: "read"}, actor_user_id=owner)
    assert await _access(engine, user) == {} and not audit.calls


#: Scenarios of writes to a frozen manager's grants, each from the same start: `a` trade and `b`
#: read, both frozen and capped at 250, and `e` soft-revoked and never frozen. The last is the
#: Q1 security rider: no sequence of writes leaves an unfrozen live grant.
_FROZEN_MANAGER_WRITES = [
    pytest.param([{"a": "trade", "b": "read", "c": "read"}], id="a-new-grant"),
    pytest.param([{"a": "read", "b": "trade"}], id="a-frozen-grant-narrowed-another-widened"),
    pytest.param([{"d": "trade"}], id="every-account-swapped"),
    pytest.param([{"a": "trade", "b": "read", "e": "read"}], id="a-never-frozen-row-revived"),
    pytest.param([{"a": "trade"}, {"a": "trade", "b": "read"}], id="a-frozen-row-revived"),
    pytest.param([{}, {"f": "read"}], id="every-grant-revoked-then-a-new-account-granted"),
    pytest.param(
        [
            {"a": "trade", "b": "read", "c": "read"},
            {"a": "read"},
            {"a": "trade", "e": "trade"},
            {"d": "trade"},
            {},
            {"f": "read"},
            {"b": "read", "c": "trade", "e": "read"},
        ],
        id="a-sequence-of-every-kind-of-write",
    ),
]


@pytest.mark.parametrize("steps", _FROZEN_MANAGER_WRITES)
async def test_no_grant_write_leaves_a_frozen_manager_an_unfrozen_grant(
    db: Any, steps: list[dict[str, AccessLevel]]
) -> None:
    """#2648 Q1: a row a write inserts or revives for a frozen manager takes the donor's freeze
    (time, actor, reason) and never its cap, and no write lowers a freeze."""
    rel, engine = db
    owner, user, ids = await _setup(engine, 6)
    named = dict(zip("abcdef", ids, strict=True))
    a, b, e = named["a"], named["b"], named["e"]
    await _store(rel).replace_grants(user, {a: "trade", b: "read"}, actor_user_id=owner)
    await _exec(engine, _FREEZE, id=str(user), by=str(owner))
    await _exec(engine, _ROW, id=str(user), account=str(e), view=False)
    freeze = (await _rows(engine, user))[0][3:7]  # (frozen, frozen_at, frozen_by, reason)
    audit = _Audit()
    for step in steps:
        grants = {named[name]: level for name, level in step.items()}
        await _store(rel, audit).replace_grants(user, grants, actor_user_id=owner, removal=_ACK)
        assert [r[3:7] for r in await _rows(engine, user) if r[1]] == [freeze] * len(grants)
    caps = {r[0]: r[7] for r in await _rows(engine, user) if r[7] is not None}
    assert caps == {a: Decimal(250), b: Decimal(250)}  # never copied
    states = [kw[k] for _, kw in audit.calls for k in ("before_state", "after_state")]
    assert len(audit.calls) == len(steps)
    assert all(g["frozen"] for state in states for g in state["grants"])  # the audit agrees


async def test_rows_already_frozen_keep_their_own_freeze(db: Any) -> None:
    """#2648 Q1: the latest freeze is copied onto the rows a write inserts or revives, never
    over a row that is frozen already, widened or not: it keeps its time, actor and reason."""
    rel, engine = db
    owner, user, (a, b, c) = await _setup(engine, 3)
    await _store(rel).replace_grants(user, {a: "read", b: "read"}, actor_user_id=owner)
    older = (datetime(2026, 1, 1, tzinfo=UTC), owner, "drawdown")
    latest = (datetime(2026, 2, 1, tzinfo=UTC), user, "manual")  # the donor
    for account, (at, by, reason) in ((a, older), (b, latest)):
        freeze = {"id": str(user), "account": str(account), "at": at, "by": str(by)}
        await _exec(engine, _FREEZE_ROW, reason=reason, **freeze)
    await _store(rel).replace_grants(user, {a: "trade", b: "read", c: "read"}, actor_user_id=owner)
    freezes = {r[0]: r[3:7] for r in await _rows(engine, user)}
    assert freezes == {a: (True, *older), b: (True, *latest), c: (True, *latest)}


async def test_partial_freeze_is_not_extended(db: Any) -> None:
    rel, engine = db
    owner, user, (a, b, c) = await _setup(engine, 3)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    await _exec(engine, _FREEZE, id=str(user), by=str(owner))
    await _exec(engine, _ROW, id=str(user), account=str(b), view=True)  # live, not frozen
    await _store(rel).replace_grants(user, {a: "read", b: "read", c: "read"}, actor_user_id=owner)
    assert [r[3] for r in await _rows(engine, user)] == [True, False, False]


@pytest.mark.parametrize("user_row_first", [True, False], ids=["user-row-first", "grant-rows-only"])
async def test_replacement_queued_behind_a_freeze_inherits_it(
    db: Any, user_row_first: bool
) -> None:
    """E39's freeze locks the user row first (21-database-schema.md §3.1.3) and the replacement
    queues on that row; a writer that locks only the grant rows is caught by `_CURRENT`'s
    `FOR NO KEY UPDATE`. Either way it reads the committed freeze, so its new row is frozen."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    async with engine.connect() as probe:
        async with engine.begin() as freezer:
            if user_row_first:
                await freezer.execute(_DISABLE[0], {"id": str(user)})
            await freezer.execute(_FREEZE, {"id": str(user), "by": str(owner)})
            call = asyncio.create_task(
                _store(rel).replace_grants(user, {a: "read", b: "read"}, actor_user_id=owner)
            )
            await _until_blocked(probe, 1)
        async with asyncio.timeout(_WAIT_S):
            await call
    assert [r[3] for r in await _rows(engine, user)] == [True, True]


# -- S9b: the read behind `GET /users/{userId}/account-access` (#2648) ---------------------------


_DELETE_USER = sa.text("DELETE FROM users WHERE id = CAST(:id AS uuid)")


def _label(account: uuid.UUID) -> str:
    return f"a-{account.hex[:12]}"  # as `_setup` names it


def _pairs(grants: list[AccessGrant]) -> list[tuple[uuid.UUID, str]]:
    return [(g.exchange_account_id, g.level) for g in grants]


async def test_list_grants_returns_only_live_grants_of_live_accounts(db: Any) -> None:
    """A soft-revoked grant and a grant on a soft-deleted account are not listed; a re-grant is."""
    rel, engine = db
    owner, user, (a, b, c, d) = await _setup(engine, 4)
    store = _store(rel)
    await store.replace_grants(
        user, {a: "read", b: "trade", c: "read", d: "read"}, actor_user_id=owner
    )
    await store.replace_grants(
        user, {a: "read", b: "trade", d: "read"}, actor_user_id=owner, removal=_ACK
    )
    await _exec(engine, _SOFT_DELETE, id=str(d))  # d's grant row stays live, on a dead account
    await _exec(engine, _FREEZE, id=str(user), by=str(owner))  # a frozen grant is listed too
    assert _pairs(await store.list_grants(user)) == [(a, "read"), (b, "trade")]
    await store.replace_grants(
        user, {a: "read", b: "trade", c: "trade"}, actor_user_id=owner, removal=_ACK
    )
    assert _pairs(await store.list_grants(user)) == [(a, "read"), (b, "trade"), (c, "trade")]


async def test_list_grants_carries_the_label_environment_and_last_granter(db: Any) -> None:
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    second_owner, _, _ = await _setup(engine, 0)
    store = _store(rel)
    await store.replace_grants(user, {a: "read"}, actor_user_id=owner)
    await store.replace_grants(user, {a: "trade"}, actor_user_id=second_owner)
    granted = AccessGrant(a, "trade", _label(a), "demo", second_owner)
    assert await store.list_grants(user) == [granted]
    await _exec(engine, _DELETE_USER, id=str(second_owner))  # `granted_by` is ON DELETE SET NULL
    assert await store.list_grants(user) == [AccessGrant(a, "trade", _label(a), "demo", None)]


async def test_list_grants_never_returns_another_users_grants(db: Any) -> None:
    rel, engine = db
    owner, user, (a, b, c) = await _setup(engine, 3)
    other_owner, other, _ = await _setup(engine, 0)
    store = _store(rel)
    await store.replace_grants(user, {a: "read", b: "trade"}, actor_user_id=owner)
    await store.replace_grants(other, {a: "trade", c: "read"}, actor_user_id=owner)
    await store.replace_grants(owner, {b: "read"}, actor_user_id=other_owner)  # the caller's own
    assert _pairs(await store.list_grants(user)) == [(a, "read"), (b, "trade")]
    assert _pairs(await store.list_grants(other)) == [(a, "trade"), (c, "read")]


async def test_list_grants_of_a_missing_or_deleted_user_raises_not_found(db: Any) -> None:
    rel, engine = db
    owner, user, (a,) = await _setup(engine, 1)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    with pytest.raises(AccessUserNotFoundError):
        await _store(rel).list_grants(uuid.uuid4())
    await _exec(engine, _USER_SOFT_DELETE, id=str(user))
    with pytest.raises(AccessUserNotFoundError):
        await _store(rel).list_grants(user)


@pytest.mark.parametrize("status", ["invited", "locked", "disabled"])
async def test_list_grants_lists_a_user_who_is_not_active(db: Any, status: str) -> None:
    rel, engine = db
    _, user, (a,) = await _setup(engine, 1, status)  # a grant change would be 409 here
    await _exec(engine, _ROW, id=str(user), account=str(a), view=True)
    assert _pairs(await _store(rel).list_grants(user)) == [(a, "read")]


async def test_list_grants_takes_no_row_lock_and_sees_only_committed_grants(db: Any) -> None:
    """With a replacement held at its audit gate (the user row locked, its rows rewritten), the
    read returns at once with the committed grants; it neither queues nor sees the new ones."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    gate = asyncio.Event()
    audit = _Audit(gate=gate)
    call = asyncio.create_task(
        _store(rel, audit).replace_grants(user, {b: "trade"}, actor_user_id=owner, removal=_ACK)
    )
    async with asyncio.timeout(_WAIT_S):
        await audit.entered.wait()
    async with asyncio.timeout(_WAIT_S):  # a read that queued behind the writer never returns
        during = await _store(rel).list_grants(user)
    gate.set()
    async with asyncio.timeout(_WAIT_S):
        await call
    assert _pairs(during) == [(a, "read")]
    assert _pairs(await _store(rel).list_grants(user)) == [(b, "trade")]


async def test_list_grants_then_replacing_with_the_same_set_is_a_no_op(db: Any) -> None:
    """The listing sent back changes nothing and audits nothing, but for a live grant on a
    soft-deleted account: it is not listed, so replacing with the listing revokes it (#3027)."""
    rel, engine = db
    owner, user, (a, b, c) = await _setup(engine, 3)
    store = _store(rel)
    await store.replace_grants(user, {a: "read", b: "trade", c: "read"}, actor_user_id=owner)
    await store.replace_grants(user, {a: "read", b: "trade"}, actor_user_id=owner, removal=_ACK)
    audit = _Audit()
    listed = await store.list_grants(user)
    change = await _store(rel, audit).replace_grants(
        user, {g.exchange_account_id: g.level for g in listed}, actor_user_id=owner
    )
    assert not change.changed and not audit.calls
    assert await _access(engine, user) == {a: (True, False), b: (True, True), c: (False, False)}


async def test_replace_answers_the_new_set_read_under_its_locks(db: Any) -> None:
    """S9c: the `PUT` body, read inside the change; a kept grant keeps its granter."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    other, _, _ = await _setup(engine, 0)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    change = await _store(rel).replace_grants(user, {a: "read", b: "trade"}, actor_user_id=other)
    assert change.granted == (
        AccessGrant(a, "read", _label(a), "demo", owner),
        AccessGrant(b, "trade", _label(b), "demo", other),
    )
