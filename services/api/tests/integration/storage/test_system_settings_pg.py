"""Integration: `SqlAlchemySystemSettings` on real Postgres 16 (E42-T01). The shared contract runs
here as against the fake, plus what only the database shows: the stored row, scope isolation from
per-user rows, the advisory lock that queues writers, a timed-out hook freeing it, and an
unreachable database. CI integration lane (no docker in WSL; also run on a scratch Postgres).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.system_settings import StoredSetting
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from tests.unit.storage.system_settings_contract import (
    KEY,
    SystemSettingsContract,
    noop,
    recording,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_WAITERS = "SELECT count(DISTINCT pid) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"


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
def clean_settings(pg_dsn: str) -> None:
    """Every test starts from an empty `settings` table (the database is shared by the module)."""
    with _sync(pg_dsn) as c:
        c.execute("DELETE FROM settings")


@pytest.fixture
def actor(pg_dsn: str) -> UUID:
    """A real user: `settings.updated_by` is a foreign key."""
    uid = uuid.uuid4()
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid}@example.test", f"u{uid.hex[:12]}"),
        )
    return uid


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest.fixture
def store(relational: SqlAlchemyRelationalRepository) -> SqlAlchemySystemSettings:
    return SqlAlchemySystemSettings(relational, audit_timeout_s=60)  # outlasts the lock test's poll


@pytest.fixture
def tick() -> Callable[[], None]:
    return lambda: None  # the database clock moves by itself


class TestPostgresSystemSettings(SystemSettingsContract):
    pass


def _row(pg_dsn: str, scope: str = "system") -> tuple[Any, ...]:
    with _sync(pg_dsn) as c:
        return (
            c.execute(
                "SELECT value, value_type, is_secret, updated_by, created_at, updated_at, "
                "jsonb_typeof(value) FROM settings WHERE scope = %s AND key = %s",
                (scope, KEY),
            ).fetchone()
            or ()
        )


async def test_the_row_is_a_json_string_with_its_writer_and_its_creation_time_kept(
    pg_dsn: str, store: SqlAlchemySystemSettings, actor: UUID
) -> None:
    first = await store.put_string(KEY, "regular", updated_by=actor, write_ahead=noop)
    value, vtype, secret, by, created, updated, kind = _row(pg_dsn)
    assert (value, vtype, secret, kind) == ("regular", "string", False, "string")
    assert (by, updated) == (actor, first.updated_at)
    again = await store.put_string(KEY, "business_kyc", updated_by=actor, write_ahead=noop)
    row = _row(pg_dsn)
    assert (row[0], row[4]) == ("business_kyc", created)  # `created_at` is the first write's
    assert row[5] == again.updated_at > first.updated_at


async def test_a_per_user_row_of_the_same_key_is_neither_read_nor_written(
    pg_dsn: str, store: SqlAlchemySystemSettings, actor: UUID
) -> None:
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO settings (id, scope, user_id, key, value, value_type) "
            "VALUES (%s, 'user', %s, %s, %s, 'string')",
            (uuid.uuid4(), actor, KEY, Jsonb("business_kyc")),
        )
    seen: list[StoredSetting | None] = []
    assert await store.get_string(KEY) is None  # the user's row is not "the" setting
    await store.put_string(KEY, "regular", updated_by=actor, write_ahead=recording(seen))
    assert seen == [None] and _row(pg_dsn, "user")[0] == "business_kyc"  # untouched
    assert _row(pg_dsn)[0] == "regular"


async def _until_waiting(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on an advisory lock (`pg_locks` is live)."""
    for _ in range(400):
        if (await probe.execute(sa.text(_WAITERS))).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} writers never queued on the key's advisory lock")


async def test_writers_of_one_key_queue_and_the_second_sees_the_first(
    pg_dsn: str, store: SqlAlchemySystemSettings, actor: UUID
) -> None:
    held, release = asyncio.Event(), asyncio.Event()
    seen: list[StoredSetting | None] = []

    async def first_hook(_before: StoredSetting | None) -> None:
        held.set()
        await release.wait()

    engine = create_async_engine(pg_dsn)
    try:
        first = asyncio.create_task(
            store.put_string(KEY, "regular", updated_by=actor, write_ahead=first_hook)
        )
        await asyncio.wait_for(held.wait(), 30)
        second = asyncio.create_task(
            store.put_string(KEY, "business_kyc", updated_by=actor, write_ahead=recording(seen))
        )
        async with engine.connect() as probe:
            await _until_waiting(probe, 1)  # the second writer is parked on the first's lock
        assert seen == []
        release.set()
        written = await first
        await second
    finally:
        await engine.dispose()
    assert seen == [written]  # it read the first writer's committed row, not an empty table


async def test_a_hook_that_outlives_its_bound_writes_nothing_and_frees_the_lock(
    relational: SqlAlchemyRelationalRepository, actor: UUID
) -> None:
    quick = SqlAlchemySystemSettings(relational, audit_timeout_s=0.2)

    async def hang(_before: StoredSetting | None) -> None:
        await asyncio.Event().wait()

    with pytest.raises(WriteAheadTimeout):
        await quick.put_string(KEY, "regular", updated_by=actor, write_ahead=hang)
    assert await quick.get_string(KEY) is None
    again = quick.put_string(KEY, "regular", updated_by=actor, write_ahead=noop)
    assert (await asyncio.wait_for(again, 30)).value == "regular"  # the advisory lock is free


async def test_an_unreachable_database_is_a_store_outage_never_no_row(actor: UUID) -> None:
    dead = SqlAlchemyRelationalRepository("postgresql+asyncpg://cv:cv@127.0.0.1:1/none")
    try:
        gone = SqlAlchemySystemSettings(dead)
        with pytest.raises(StorageTierUnavailable):
            await gone.get_string(KEY)
        with pytest.raises(StorageTierUnavailable):
            await gone.put_string(KEY, "regular", updated_by=actor, write_ahead=noop)
    finally:
        await dead.dispose()
