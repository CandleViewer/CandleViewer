"""Integration: `/watchlists` on real Postgres 16 (E08-T07, #4706). The CRUD round trip through
the router over `SqlAlchemyWatchlistStore`; two replaces holding one version, of which
exactly one wins; the record written ahead of the commit (never visible before it, nothing written
when it is refused); `ux_wl_name`; and the owner scope. CI only (testcontainers)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from testcontainers.postgres import PostgresContainer

from candleviewer.api.watchlists import make_watchlists_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.watchlists import (
    WatchlistFields,
    WatchlistNameTakenError,
    WatchlistNotFoundError,
    WatchlistRow,
    WatchlistStaleError,
)
from candleviewer.storage.repositories.watchlists_sqlalchemy import SqlAlchemyWatchlistStore
from tests._corpus import rest
from tests.watchlists._watchlists_env import MAJORS, WRITE, Audit, tag

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PAGE = parse_instruments(rest("rest/instruments_after.json")["result"]["list"], fetched_at_us=0)
_FIELDS = WatchlistFields("Majors", ("BTCUSDT", "ETHUSDT"), ())


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
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyWatchlistStore]:
    relational = SqlAlchemyRelationalRepository(pg_dsn, "watchlists-it")
    try:
        yield SqlAlchemyWatchlistStore(relational)
    finally:
        await relational.dispose()


async def _nothing(_before: WatchlistRow | None, _after: WatchlistRow | None) -> None:
    return None


async def test_the_crud_round_trip_through_the_router(
    pg_dsn: str, store: SqlAlchemyWatchlistStore
) -> None:
    owner, audit = _user(pg_dsn), Audit()

    class _Resolver:
        async def resolve(self, _request: Request) -> AuditPrincipal:
            return AuditPrincipal(owner, "u", WRITE)

    snap = CatalogueSnapshot({i.symbol: i for i in _PAGE.instruments}, 0)
    app = FastAPI()
    app.include_router(make_watchlists_router(lambda: store, _Resolver(), audit, lambda: snap))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        made = (await c.post("/watchlists", json=MAJORS)).json()
        assert (made["symbols"], made["version"]) == (["BTCUSDT", "ETHUSDT"], 1)
        assert (await c.get("/watchlists")).json() == {"items": [made]}
        swapped = {"name": "Majors", "symbols": ["ETHUSDT", "BTCUSDT"]}
        put = await c.put(f"/watchlists/{made['id']}", json=swapped, headers=tag(made))
        assert (put.status_code, put.json()["version"], put.json()["symbols"]) == (
            200, 2, ["ETHUSDT", "BTCUSDT"])  # fmt: skip
        stale = await c.put(f"/watchlists/{made['id']}", json=MAJORS, headers=tag(made))
        assert (stale.status_code, stale.headers["ETag"]) == (412, f'W/"{made["id"]}:2"')
        assert (await c.delete(f"/watchlists/{made['id']}")).status_code == 204
        assert (await c.get("/watchlists")).json() == {"items": []}
    assert audit.actions() == ["watchlist.created", "watchlist.updated", "watchlist.deleted"]


async def _wait_until_blocked(dsn: str) -> None:
    """Poll until a connection of the store's pool waits on a lock: at most 1000 polls, 10 ms
    apart (the recipe of tests/integration/oms/test_submission_pipeline_pg.py)."""

    def blocked() -> bool:
        with _sync(dsn) as c:
            for _ in range(1000):
                row = c.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                    "AND wait_event_type = 'Lock'",
                    ("candleviewer:watchlists-it",),
                ).fetchone()
                if row is not None and row[0] > 0:
                    return True
                c.execute("SELECT pg_sleep(0.01)")
        return False

    assert await asyncio.to_thread(blocked), "the second writer never waited on the row's lock"


async def test_two_replaces_holding_one_version_exactly_one_wins(
    pg_dsn: str, store: SqlAlchemyWatchlistStore
) -> None:
    owner = _user(pg_dsn)
    made = await store.create(owner, uuid.uuid4(), _FIELDS, write_ahead=_nothing)
    first_in = asyncio.Event()

    async def hold(_before: WatchlistRow | None, _after: WatchlistRow | None) -> None:
        if not first_in.is_set():  # the first writer keeps the row locked until the second waits
            first_in.set()
            await _wait_until_blocked(pg_dsn)

    async def replace(name: str) -> WatchlistRow:
        fields = WatchlistFields(name, ("SOLUSDT",), ())
        return await store.replace(owner, made.id, fields, expected_version=1, write_ahead=hold)

    async def second() -> WatchlistRow:
        await first_in.wait()
        return await replace("Second")

    results = await asyncio.gather(replace("First"), second(), return_exceptions=True)
    won = [r for r in results if isinstance(r, WatchlistRow)]
    lost = [r for r in results if isinstance(r, WatchlistStaleError)]
    assert len(won) == len(lost) == 1 and (won[0].name, won[0].version) == ("First", 2)
    assert lost[0].version == 2
    kept = await store.get_own(owner, made.id)
    assert kept is not None and kept.name == "First"


async def test_the_record_is_written_ahead_of_the_commit_and_a_refusal_writes_nothing(
    pg_dsn: str, store: SqlAlchemyWatchlistStore
) -> None:
    owner, wid, seen = _user(pg_dsn), uuid.uuid4(), []

    async def ahead(_before: WatchlistRow | None, after: WatchlistRow | None) -> None:
        with _sync(pg_dsn) as c:  # another session: the row is not committed yet
            seen.append(c.execute("SELECT 1 FROM watchlists WHERE id = %s", (wid,)).fetchone())

    await store.create(owner, wid, _FIELDS, write_ahead=ahead)
    assert seen == [None] and await store.get_own(owner, wid) is not None

    async def refused(_before: WatchlistRow | None, _after: WatchlistRow | None) -> None:
        raise RuntimeError("the record was refused")

    fields = WatchlistFields("Renamed", (), ())
    with pytest.raises(RuntimeError):
        await store.replace(owner, wid, fields, expected_version=1, write_ahead=refused)
    with pytest.raises(RuntimeError):
        await store.delete(owner, wid, write_ahead=refused)
    kept = await store.get_own(owner, wid)
    assert kept is not None and (kept.name, kept.version) == ("Majors", 1)


async def test_names_are_unique_per_owner_and_each_call_is_scoped_to_its_owner(
    pg_dsn: str, store: SqlAlchemyWatchlistStore
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    mine = await store.create(a, uuid.uuid4(), _FIELDS, write_ahead=_nothing)
    with pytest.raises(WatchlistNameTakenError):
        await store.create(a, uuid.uuid4(), WatchlistFields("MAJORS", (), ()), write_ahead=_nothing)
    await store.create(b, uuid.uuid4(), WatchlistFields("majors", (), ()), write_ahead=_nothing)
    assert await store.get_own(b, mine.id) is None
    assert await store.exists_for_other_owner(b, mine.id) is True  # the rbac.denied probe
    assert await store.exists_for_other_owner(a, mine.id) is False
    assert await store.exists_for_other_owner(b, uuid.uuid4()) is False
    assert [r.id for r in await store.list_own(a)] == [mine.id]
    with pytest.raises(WatchlistNotFoundError):
        await store.replace(b, mine.id, _FIELDS, expected_version=1, write_ahead=_nothing)
    with pytest.raises(WatchlistNotFoundError):
        await store.delete(b, mine.id, write_ahead=_nothing)
    with pytest.raises(WatchlistStaleError):
        await store.replace(a, mine.id, _FIELDS, expected_version=None, write_ahead=_nothing)
    assert await store.get_own(a, mine.id) == mine
