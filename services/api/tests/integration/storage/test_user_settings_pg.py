"""Integration: `SqlAlchemyUserSettings` on real Postgres 16 (E02-T13, #5181). The shared contract
runs here as against the fake, plus what only the database shows: the rows as `0025_settings`
stores them (`st_key_fmt`, `value_type`, `ux_settings_user`), two users' rows kept apart, one
user's writers serialised by the advisory lock, system-scope rows never read or written, a COMMIT
that fails after the record, and an unreachable database. Runs in the CI integration lane."""

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

from candleviewer.storage.errors import StorageConstraintViolated, StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_settings import LeafChange
from candleviewer.storage.repositories.user_settings_sqlalchemy import SqlAlchemyUserSettings
from tests.unit.storage.user_settings_contract import (
    DENSITY,
    THEME,
    UserSettingsContract,
    noop,
    recording,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_WAITERS = "SELECT count(DISTINCT pid) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
_FAIL_COMMIT = """
CREATE FUNCTION cv_test_fail_commit() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN RAISE EXCEPTION 'refused at commit' USING ERRCODE = '40001'; END $f$;
CREATE CONSTRAINT TRIGGER cv_test_fail_commit AFTER INSERT OR UPDATE OR DELETE ON settings
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cv_test_fail_commit();
"""
_DROP_FAIL_COMMIT = (
    "DROP TRIGGER cv_test_fail_commit ON settings; DROP FUNCTION cv_test_fail_commit();"
)


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


def _new_user(pg_dsn: str) -> UUID:
    """A real user: `settings.user_id` and `updated_by` are foreign keys."""
    uid = uuid.uuid4()
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid}@example.test", f"u{uid.hex[:12]}"),
        )
    return uid


@pytest.fixture
def user(pg_dsn: str) -> UUID:
    return _new_user(pg_dsn)


@pytest.fixture
def other(pg_dsn: str) -> UUID:
    return _new_user(pg_dsn)


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest.fixture
def store(relational: SqlAlchemyRelationalRepository) -> SqlAlchemyUserSettings:
    return SqlAlchemyUserSettings(relational, audit_timeout_s=60)  # outlasts the lock test's poll


@pytest.fixture
def tick() -> Callable[[], None]:
    return lambda: None  # the database clock moves by itself


class TestPostgresUserSettings(UserSettingsContract):
    pass


def _rows(pg_dsn: str) -> list[tuple[Any, ...]]:
    """Every row of the table, by key: scope, user_id, key, value, value_type, is_secret,
    updated_by, created_at, updated_at."""
    with _sync(pg_dsn) as c:
        return c.execute(
            "SELECT scope, user_id, key, value, value_type, is_secret, updated_by, created_at, "
            "updated_at FROM settings ORDER BY key, scope"
        ).fetchall()


async def test_user_settings_rows_round_trip_one_per_leaf_typed_and_written_by_the_user(
    pg_dsn: str, store: SqlAlchemyUserSettings, user: UUID
) -> None:
    patch: dict[str, object] = {
        THEME: "light",
        "appearance.font_scale": 1.25,
        "appearance.reduce_motion": True,
        "notifications.quiet_hours": {"from": "22:00"},
        "trading.default_qty_presets": ["0.01"],
    }
    await store.apply(user, patch, write_ahead=noop)
    rows = _rows(pg_dsn)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("user", user, key, patch[key]) for key in sorted(patch)
    ]
    assert [r[4] for r in rows] == ["number", "boolean", "string", "object", "array"]
    assert {(r[5], r[6]) for r in rows} == {(False, user)}  # never secret; written by the user


async def test_user_settings_a_rewrite_updates_the_users_one_row_in_place(
    pg_dsn: str, store: SqlAlchemyUserSettings, user: UUID
) -> None:
    await store.apply(user, {THEME: "dark"}, write_ahead=noop)
    ((*_, created, first),) = _rows(pg_dsn)
    await store.apply(user, {THEME: "light"}, write_ahead=noop)
    ((*_, value, _vt, _s, _by, created_again, updated),) = _rows(pg_dsn)  # `ux_settings_user`
    assert (value, created_again) == ("light", created) and updated > first


async def test_user_settings_a_key_outside_st_key_fmt_is_refused_by_the_table(
    store: SqlAlchemyUserSettings, user: UUID
) -> None:
    with pytest.raises(StorageConstraintViolated) as refused:  # a CHECK, never a stored row
        await store.apply(user, {"Appearance.Theme": "dark"}, write_ahead=noop)
    assert (refused.value.sqlstate, refused.value.constraint) == ("23514", "st_key_fmt")


async def test_user_settings_two_users_rows_never_cross(
    pg_dsn: str, store: SqlAlchemyUserSettings, user: UUID, other: UUID
) -> None:
    await store.apply(other, {THEME: "dark", DENSITY: "spacious"}, write_ahead=noop)
    await store.apply(user, {THEME: "light", DENSITY: None}, write_ahead=noop)
    assert [(r[2], r[3]) for r in _rows(pg_dsn) if r[1] == other] == [
        (DENSITY, "spacious"),
        (THEME, "dark"),
    ]
    assert [(r.key, r.value) for r in await store.read(user)] == [(THEME, "light")]


async def test_user_settings_system_scope_rows_are_never_read_or_written(
    pg_dsn: str, store: SqlAlchemyUserSettings, user: UUID
) -> None:
    with _sync(pg_dsn) as c:
        for key, value in ((THEME, "system"), ("accounts.subaccount_tier", "regular")):
            c.execute(
                "INSERT INTO settings (id, scope, key, value, value_type) "
                "VALUES (%s, 'system', %s, %s, 'string')",
                (uuid.uuid4(), key, Jsonb(value)),
            )
    assert await store.read(user) == ()
    seen: list[tuple[LeafChange, ...]] = []
    await store.apply(user, {THEME: "light"}, write_ahead=recording(seen))
    assert seen == [(LeafChange(THEME, None, "light"),)]  # the system row is no "before"
    assert [(r[2], r[3]) for r in _rows(pg_dsn) if r[0] == "system"] == [
        ("accounts.subaccount_tier", "regular"),
        (THEME, "system"),
    ]


async def _until_waiting(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on an advisory lock (`pg_locks` is live)."""
    for _ in range(400):
        if (await probe.execute(sa.text(_WAITERS))).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} writers never queued on the user's advisory lock")


async def test_user_settings_two_concurrent_patches_of_one_user_are_serialised(
    pg_dsn: str, store: SqlAlchemyUserSettings, user: UUID
) -> None:
    held, release = asyncio.Event(), asyncio.Event()
    seen: list[tuple[LeafChange, ...]] = []

    async def first_hook(_changes: tuple[LeafChange, ...]) -> None:
        held.set()
        await release.wait()

    engine = create_async_engine(pg_dsn)
    try:
        first = asyncio.create_task(store.apply(user, {THEME: "dark"}, write_ahead=first_hook))
        await asyncio.wait_for(held.wait(), 30)
        second = asyncio.create_task(
            store.apply(user, {THEME: "light"}, write_ahead=recording(seen))
        )
        async with engine.connect() as probe:
            await _until_waiting(probe, 1)  # the second writer is parked on the first's lock
        assert seen == []
        release.set()
        await first
        rows = await second
    finally:
        await engine.dispose()
    assert seen == [(LeafChange(THEME, "dark", "light"),)]  # it read the first's committed row
    assert [(r.key, r.value) for r in rows] == [(THEME, "light")]


async def test_user_settings_a_commit_that_fails_after_the_record_keeps_the_setting(
    pg_dsn: str, store: SqlAlchemyUserSettings, user: UUID
) -> None:
    kept = await store.apply(user, {THEME: "dark"}, write_ahead=noop)
    seen: list[tuple[LeafChange, ...]] = []
    with _sync(pg_dsn) as c:
        c.execute(_FAIL_COMMIT)
    try:
        with pytest.raises(StorageTierUnavailable):  # 40001 at COMMIT: retry, never "done"
            await store.apply(user, {THEME: "light"}, write_ahead=recording(seen))
    finally:
        with _sync(pg_dsn) as c:
            c.execute(_DROP_FAIL_COMMIT)
    assert seen == [(LeafChange(THEME, "dark", "light"),)]  # the record was written ...
    assert await store.read(user) == kept  # ... and the setting is unchanged, never the reverse


async def test_user_settings_an_unreachable_database_is_a_store_outage_never_no_rows(
    user: UUID,
) -> None:
    dead = SqlAlchemyRelationalRepository("postgresql+asyncpg://cv:cv@127.0.0.1:1/none")
    try:
        gone = SqlAlchemyUserSettings(dead)
        with pytest.raises(StorageTierUnavailable):
            await gone.read(user)
        with pytest.raises(StorageTierUnavailable):
            await gone.apply(user, {THEME: "light"}, write_ahead=noop)
    finally:
        await dead.dispose()
