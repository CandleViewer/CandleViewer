"""Integration (E42-T08 S8, #2648): `SqlAlchemyAccountAccessStore` on real Postgres 16.

The audit record is written ahead of the commit, and a refused one changes nothing. A soft
revoke keeps the freeze state and the cap. An unknown account or a user who is not active
rolls the whole set back. A replacement racing a disable leaves no live grant in either order
(a third connection sees the second caller queued in `pg_locks`). The ids read back are plain
UUIDs. Onboarding ignores revoked grants.
Not run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
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
    AccessUnknownAccountError,
    AccessUserNotActiveError,
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
    raise AssertionError(f"{n} callers never blocked on the user row")


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
        _store(rel, audit).replace_grants(user, {b: "trade"}, actor_user_id=owner)
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
    await _store(rel, audit).replace_grants(user, {b: "trade"}, actor_user_id=owner)
    ((action, kwargs),) = audit.calls
    assert action == "users.access_change"
    assert kwargs["before_state"] == {"grants": [{"exchange_account_id": str(a), "level": "read"}]}
    assert kwargs["after_state"] == {"grants": [{"exchange_account_id": str(b), "level": "trade"}]}


async def test_refused_audit_changes_nothing(db: Any) -> None:
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    refusing = _Audit(error=RuntimeError("audit WAL unavailable"))
    with pytest.raises(AccessAuditUnavailableError):
        await _store(rel, refusing).replace_grants(user, {b: "trade"}, actor_user_id=owner)
    assert await _access(engine, user) == {a: (True, False)}


async def test_replace_returns_plain_uuids(db: Any) -> None:
    """asyncpg reads ids back as its own UUID subclass, which orjson refuses."""
    rel, engine = db
    owner, user, (a, b) = await _setup(engine, 2)
    await _store(rel).replace_grants(user, {a: "read"}, actor_user_id=owner)
    change = await _store(rel).replace_grants(user, {b: "trade"}, actor_user_id=owner)
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
    await store.replace_grants(user, {}, actor_user_id=owner)
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
    await store.replace_grants(user, {}, actor_user_id=owner)
    revoked = await onboarding.has_account_binding(user), await onboarding.latest_binding_at(user)
    assert bound[0] is True and bound[1] is not None
    assert revoked == (False, None)
