"""Integration: the hotkey profile store on real Postgres 16 (E10-T05, #5211). Every case of
tests/hotkey_profiles/_store_contract.py, which the in-memory fake runs too, over
`SqlAlchemyHotkeyProfileStore`; then what only a database shows: the write-ahead record runs before
the commit, two replaces holding one version (exactly one wins), two creates racing for the last
place under the cap and two activations racing (one active profile at the end, `ux_hk_active`
never tripped). `testcontainers`: CI, or locally when the host's load allows.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.hotkey_profiles import (
    MAX_PROFILES,
    HotkeyProfileFields,
    HotkeyProfileLimitError,
    HotkeyProfileRow,
    HotkeyProfileStaleError,
)
from candleviewer.storage.repositories.hotkey_profiles_sqlalchemy import (
    SqlAlchemyHotkeyProfileStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.hotkey_profiles._store_contract import CASES, FIELDS, Recorder

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_APP = "hotkey-profiles-it"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        sync = dsn.replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, check=True,
            env={**os.environ, "CV_PG_DSN": sync}, timeout=120,
        )  # fmt: skip
        yield dsn


def _sync(dsn: str) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(dsn: str) -> uuid.UUID:
    uid = uuid.uuid4()
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{str(uid)[:8]}@x.io", f"u{str(uid)[:8]}"),
        )
    return uid


@pytest_asyncio.fixture
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyHotkeyProfileStore]:
    relational = SqlAlchemyRelationalRepository(pg_dsn, _APP)
    try:
        yield SqlAlchemyHotkeyProfileStore(relational)
    finally:
        await relational.dispose()


class _PgHarness:
    def __init__(self, dsn: str, store: SqlAlchemyHotkeyProfileStore) -> None:
        self.dsn, self.store = dsn, store

    async def owner(self) -> uuid.UUID:
        return await asyncio.to_thread(_user, self.dsn)


@pytest.mark.parametrize("name", sorted(CASES))
async def test_postgres_holds_the_store_contract(
    name: str, pg_dsn: str, store: SqlAlchemyHotkeyProfileStore
) -> None:
    await CASES[name](_PgHarness(pg_dsn, store))


async def test_the_record_runs_before_the_commit(
    pg_dsn: str, store: SqlAlchemyHotkeyProfileStore
) -> None:
    owner, pid, seen = await asyncio.to_thread(_user, pg_dsn), uuid.uuid4(), []

    async def ahead(_before: HotkeyProfileRow | None, _after: HotkeyProfileRow | None) -> None:
        def look() -> object:
            with _sync(pg_dsn) as c:  # another session: the row is not committed yet
                return c.execute("SELECT 1 FROM hotkey_profiles WHERE id = %s", (pid,)).fetchone()

        seen.append(await asyncio.to_thread(look))

    await store.create(owner, pid, FIELDS, write_ahead=ahead)
    assert seen == [None] and await store.get_own(owner, pid) is not None


async def test_two_replaces_holding_one_version_exactly_one_wins(
    pg_dsn: str, store: SqlAlchemyHotkeyProfileStore
) -> None:
    owner = await asyncio.to_thread(_user, pg_dsn)
    made = await store.create(owner, uuid.uuid4(), FIELDS, write_ahead=Recorder().write)

    async def replace(name: str) -> HotkeyProfileRow:
        fields = HotkeyProfileFields(name, {"ticket.side_buy": "Alt+B"})
        return await store.replace(owner, made.id, fields, expected_version=1,
                                   write_ahead=Recorder().write)  # fmt: skip

    results = await asyncio.gather(replace("First"), replace("Second"), return_exceptions=True)
    won = [r for r in results if isinstance(r, HotkeyProfileRow)]
    lost = [r for r in results if isinstance(r, HotkeyProfileStaleError)]
    assert len(won) == len(lost) == 1 and won[0].version == 2 and lost[0].version == 2
    assert await store.get_own(owner, made.id) == won[0]


async def test_two_creates_racing_for_the_last_place_one_is_refused(
    pg_dsn: str, store: SqlAlchemyHotkeyProfileStore
) -> None:
    owner = await asyncio.to_thread(_user, pg_dsn)
    for n in range(MAX_PROFILES - 1):
        await store.create(owner, uuid.uuid4(), HotkeyProfileFields(f"P{n}", {}),
                           write_ahead=Recorder().write)  # fmt: skip

    async def create(name: str) -> HotkeyProfileRow:
        return await store.create(owner, uuid.uuid4(), HotkeyProfileFields(name, {}),
                                  write_ahead=Recorder().write)  # fmt: skip

    results = await asyncio.gather(create("Last A"), create("Last B"), return_exceptions=True)
    assert sorted(type(r).__name__ for r in results) == ["HotkeyProfileLimitError",
                                                         "HotkeyProfileRow"]  # fmt: skip
    assert len(await store.list_own(owner)) == MAX_PROFILES
    with pytest.raises(HotkeyProfileLimitError):
        await create("Past the cap")


async def test_two_activations_racing_leave_one_active_profile(
    pg_dsn: str, store: SqlAlchemyHotkeyProfileStore
) -> None:
    owner, rec = await asyncio.to_thread(_user, pg_dsn), Recorder()
    one = await store.create(
        owner, uuid.uuid4(), HotkeyProfileFields("One", {}), write_ahead=rec.write
    )
    two = await store.create(
        owner, uuid.uuid4(), HotkeyProfileFields("Two", {}), write_ahead=rec.write
    )
    rec.calls.clear()
    results = await asyncio.gather(
        store.activate(owner, one.id, write_ahead=rec.activation),
        store.activate(owner, two.id, write_ahead=rec.activation),
    )
    assert all(r.is_active for r in results)
    active = [r for r in await store.list_own(owner) if r.is_active]
    assert len(active) == 1 and await store.get_active(owner) == active[0]
    previous = [call[2] for call in rec.calls]  # the second deactivated the first one's profile
    assert previous[0] is None and previous[1] in {one.id, two.id} and len(previous) == 2
