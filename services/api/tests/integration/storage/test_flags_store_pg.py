"""Integration: `SqlAlchemyFlagRepository` on real Postgres 16 (E42-T03): `ensure` is insert-only
and idempotent, `load` returns every row with every override kept, a write replaces the user
overrides of its flag alone, the row lock serialises writers, `updated_at` at the API's precision
and on the database clock, and what is an outage or a missing row. Runs in the CI integration
lane."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.flags import FLAGS
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.flags_sqlalchemy import (
    FlagChange,
    FlagRow,
    FlagRowMissingError,
    FlagSeed,
    RowPrepare,
    SqlAlchemyFlagRepository,
    StaleFlagRowError,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_KEY = "rules.graph_editor"  # boolean, default true
_SEEDS = [FlagSeed(f.key, f.kind, f.description, f.default, f.is_killswitch) for f in FLAGS]
_PCT = FlagSeed("algo.pct", "percentage", "P", 25, False)
_VAR = FlagSeed("ui.mode", "variant", "V", "a", False, ("a", "b"))
_WAITING = (
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
)
_OVERRIDE = "SELECT id, created_at, set_by FROM feature_flag_overrides WHERE user_id = %s"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _sync(pg_dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


@pytest.fixture(autouse=True)
def no_flags(pg_dsn: str) -> None:
    with _sync(pg_dsn) as c:
        c.execute("DELETE FROM feature_flags")  # cascades to the overrides


def _user(pg_dsn: str) -> UUID:
    uid = uuid.uuid4()
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid}@example.test", f"u{uid.hex[:12]}"),
        )
    return uid


def _add_override(pg_dsn: str, key: str, value: object, uid: UUID | None, role: str = "") -> None:
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO feature_flag_overrides (id, feature_flag_id, user_id, role_id, value) "
            "SELECT gen_random_uuid(), f.id, %s, (SELECT id FROM roles WHERE name = %s), %s "
            "FROM feature_flags f WHERE f.key = %s",
            (uid, role or None, Jsonb(value), key),
        )


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield repo
    finally:
        await repo.dispose()


def _repository(
    relational: SqlAlchemyRelationalRepository, budget_ms: int = 2000
) -> SqlAlchemyFlagRepository:
    return SqlAlchemyFlagRepository(relational, read_budget_ms=budget_ms)


def _row(pg_dsn: str, key: str) -> tuple[Any, ...]:
    with _sync(pg_dsn) as c:
        return (
            c.execute(
                "SELECT kind::text, default_value, rollout_pct, variants, is_killswitch, "
                "description, updated_at FROM feature_flags WHERE key = %s",
                (key,),
            ).fetchone()
            or ()
        )


async def test_ensure_inserts_every_flag_once_at_its_default(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo = _repository(relational)
    await repo.ensure([*_SEEDS, _PCT, _VAR])
    first = {s.key: _row(pg_dsn, s.key) for s in [*_SEEDS, _PCT, _VAR]}
    assert first["killswitch.order_entry"][:5] == ("boolean", False, None, None, True)
    assert first["algo.pct"][:4] == ("percentage", False, 25, None)
    assert first["ui.mode"][:4] == ("variant", "a", None, ["a", "b"])
    assert {k: r[5] for k, r in first.items()} == {
        s.key: s.description for s in [*_SEEDS, _PCT, _VAR]
    }
    await repo.ensure([FlagSeed(_KEY, "boolean", "x", False, False)])
    assert {key: _row(pg_dsn, key) for key in first} == first  # nothing re-written
    assert len(await repo.load()) == len(FLAGS) + 2


async def test_load_keeps_every_override_and_an_unreadable_value(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, alice, bob, carol = _repository(relational), _user(pg_dsn), _user(pg_dsn), _user(pg_dsn)
    await repo.ensure(_SEEDS)
    _add_override(pg_dsn, _KEY, False, alice)
    _add_override(pg_dsn, _KEY, {"odd": 1}, bob)  # unreadable: kept, the service counts it
    _add_override(pg_dsn, _KEY, None, carol)  # a JSON null: kept
    _add_override(pg_dsn, _KEY, None, None, "manager")
    with _sync(pg_dsn) as c:
        c.execute("UPDATE feature_flags SET default_value = '\"garbage\"' WHERE key = %s", (_KEY,))
    row = (await repo.load())[_KEY]
    assert (row.value, row.updated_by) == ("garbage", None)
    assert row.user_overrides == {alice: False, bob: {"odd": 1}, carol: None}
    assert row.role_overrides == {"manager": None}


async def test_an_unreachable_database_is_an_outage_for_ensure_and_load() -> None:
    dead = SqlAlchemyRelationalRepository("postgresql+asyncpg://cv:cv@127.0.0.1:1/none")
    try:
        repo = _repository(dead)
        with pytest.raises(StorageTierUnavailable):
            await repo.ensure(_SEEDS)
        with pytest.raises(StorageTierUnavailable):
            await repo.load()
    finally:
        await dead.dispose()


def _to(
    value: object, users: dict[UUID, object], actor: UUID, at: datetime | None = None
) -> RowPrepare:
    """A writer that read the row it is given (or `at`) and sets `value` and `users`."""

    async def prepare(row: FlagRow) -> FlagChange:
        return FlagChange(value, users, at or row.updated_at, actor)

    return prepare


async def _never(row: FlagRow) -> FlagChange:
    raise AssertionError("prepare must not run without the row lock")


async def test_a_write_replaces_its_own_user_overrides_only(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor, bob, alice = _repository(relational), _user(pg_dsn), _user(pg_dsn), _user(pg_dsn)
    await repo.ensure([*_SEEDS, _VAR])
    _add_override(pg_dsn, _KEY, True, None, "viewer")
    _add_override(pg_dsn, _VAR.key, "b", alice)  # another flag's: never touched, never read
    seen: list[FlagRow] = []

    async def first(row: FlagRow) -> FlagChange:
        seen.append(row)
        return await _to(False, {alice: True}, actor)(row)

    written = await repo.write(_KEY, first)
    assert (seen[0].user_overrides, seen[0].role_overrides) == ({}, {"viewer": True})  # its own
    assert (written.value, written.user_overrides) == (False, {alice: True})
    assert written.updated_by == actor
    assert written.role_overrides == {"viewer": True} and (await repo.load())[_KEY] == written
    with _sync(pg_dsn) as c:
        kept = c.execute(_OVERRIDE + " AND value = 'true'", (alice,)).fetchone()
    assert kept is not None and kept[2] == actor  # `set_by` of a changed override
    await repo.write(_KEY, _to(True, {alice: True}, bob))  # bob keeps alice's override as is
    with _sync(pg_dsn) as c:
        assert c.execute(_OVERRIDE + " AND value = 'true'", (alice,)).fetchone() == kept
    await repo.write(_KEY, _to(True, {alice: False}, bob))  # bob changes it in place
    with _sync(pg_dsn) as c:
        changed = c.execute(_OVERRIDE + " AND value = 'false'", (alice,)).fetchone()
    assert changed is not None and changed[:2] == kept[:2] and changed[2] == bob
    cleared = await repo.write(_KEY, _to(True, {}, actor))
    assert (cleared.user_overrides, (await repo.load())[_VAR.key].user_overrides) == (
        {},
        {alice: "b"},
    )


async def test_a_kept_json_null_override_is_written_back(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor, carol = _repository(relational), _user(pg_dsn), _user(pg_dsn)
    await repo.ensure(_SEEDS)
    _add_override(pg_dsn, _KEY, None, carol)

    async def keep(row: FlagRow) -> FlagChange:  # what the writer does when overrides are omitted
        return FlagChange(False, row.user_overrides, row.updated_at, actor)

    written = await repo.write(_KEY, keep)
    assert written.user_overrides == {carol: None} == (await repo.load())[_KEY].user_overrides


async def test_a_percentage_flag_keeps_its_rollout_in_rollout_pct(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor = _repository(relational), _user(pg_dsn)
    await repo.ensure([_PCT])
    assert (await repo.write("algo.pct", _to(60, {}, actor))).value == 60
    assert _row(pg_dsn, "algo.pct")[1:3] == (False, 60)  # `default_value` is left alone
    assert (await repo.load())["algo.pct"].value == 60


async def test_the_updated_at_a_read_renders_is_the_one_a_write_accepts(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor, alice = _repository(relational), _user(pg_dsn), _user(pg_dsn)
    await repo.ensure(_SEEDS)
    with _sync(pg_dsn) as c:
        c.execute(
            "UPDATE feature_flags SET updated_at = '2026-10-16 08:00:00.123456+00' WHERE key = %s",
            (_KEY,),
        )
    read = (await repo.load())[_KEY].updated_at
    rendered = read.isoformat()  # the API's precision
    assert rendered == "2026-10-16T08:00:00.123456+00:00"  # `timestamptz` keeps microseconds
    at = datetime.fromisoformat(rendered)
    written = await repo.write(_KEY, _to(False, {alice: True}, actor, at))
    off = written.updated_at + timedelta(microseconds=1)  # one microsecond off: another state
    with pytest.raises(StaleFlagRowError) as stale:
        await repo.write(_KEY, _to(True, {}, actor, at=off))
    assert stale.value.current == written == (await repo.load())[_KEY]  # its overrides too


async def test_updated_at_moves_on_by_the_database_clock_and_never_back(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor = _repository(relational), _user(pg_dsn)
    await repo.ensure(_SEEDS)
    with _sync(pg_dsn) as c:
        before = c.execute("SELECT clock_timestamp()").fetchone()
        assert before is not None
    assert (await repo.write(_KEY, _to(False, {}, actor))).updated_at >= before[0]
    with _sync(pg_dsn) as c:  # a row stamped ahead of the clock still moves on, one microsecond
        c.execute(
            "UPDATE feature_flags SET updated_at = now() + interval '1 hour' WHERE key = %s",
            (_KEY,),
        )
    ahead = (await repo.load())[_KEY].updated_at
    written = await repo.write(_KEY, _to(True, {}, actor))
    assert written.updated_at - ahead == timedelta(microseconds=1)


async def test_writers_of_one_flag_queue_on_the_row_lock(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor = _repository(relational, budget_ms=30_000), _user(pg_dsn)
    await repo.ensure(_SEEDS)
    read = (await repo.load())[_KEY].updated_at
    held, release, seen = asyncio.Event(), asyncio.Event(), list[FlagRow]()

    async def first_prepare(row: FlagRow) -> FlagChange:
        held.set()
        await release.wait()
        return await _to(False, {}, actor)(row)

    async def second_prepare(row: FlagRow) -> FlagChange:
        seen.append(row)
        return await _to(True, {}, actor, at=read)(row)  # it read before the first committed

    engine = create_async_engine(pg_dsn)
    try:
        first = asyncio.create_task(repo.write(_KEY, first_prepare))
        await asyncio.wait_for(held.wait(), 30)
        second = asyncio.create_task(repo.write(_KEY, second_prepare))
        async with engine.connect() as probe:
            for _ in range(400):  # bounded condition wait: the second writer parks on the lock
                if (await probe.execute(sa.text(_WAITING))).scalar_one() >= 1:
                    break
                await asyncio.sleep(0.025)
            else:
                raise AssertionError("the second writer never queued on the row lock")
        assert seen == []
        release.set()
        written = await first
        with pytest.raises(StaleFlagRowError) as stale:
            await second
    finally:
        await engine.dispose()
    assert seen == [written] and stale.value.current == written  # it locked the first's commit


async def test_what_cannot_be_written_writes_nothing(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, actor = _repository(relational), _user(pg_dsn)
    with pytest.raises(FlagRowMissingError):  # no row: the start-up `ensure` never ran
        await repo.write(_KEY, _never)
    await repo.ensure(_SEEDS)
    before = (await repo.load())[_KEY]
    with pytest.raises(FlagRowMissingError):  # an override user deleted after the writer's check
        await repo.write(_KEY, _to(False, {uuid.uuid4(): True}, actor))
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as holder:
        holder.execute("SELECT 1 FROM feature_flags WHERE key = %s FOR UPDATE", (_KEY,))
        with pytest.raises(StorageTierUnavailable):  # the lock is held past the read budget
            await _repository(relational, budget_ms=100).write(_KEY, _never)
        holder.rollback()
    assert (await repo.load())[_KEY] == before


async def test_an_unreachable_database_is_an_outage_for_a_write() -> None:
    dead = SqlAlchemyRelationalRepository("postgresql+asyncpg://cv:cv@127.0.0.1:1/none")
    try:
        with pytest.raises(StorageTierUnavailable):
            await _repository(dead).write(_KEY, _never)
    finally:
        await dead.dispose()
