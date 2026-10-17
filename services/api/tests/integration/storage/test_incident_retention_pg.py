"""Integration: the resolved-incidents purge on real Postgres 16 (E42-T05, `21-database-schema.md`
§7): a `resolved` incident is dropped 24 months after its `last_seen_at`, in batches, oldest
first; open and acknowledged rows are kept however old. Not run locally (no docker); the same
file was run on a scratch Postgres 16.4 first. CI integration lane."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.db.models import incidents
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
#: (n, status, months since last seen, months since first seen): only 1 and 2 are past the horizon
#: and resolved.
_SEED = [
    (1, "resolved", 30, 30),
    (2, "resolved", 25, 25),
    (3, "resolved", 23, 23),  # inside the horizon
    (4, "open", 30, 30),
    (5, "acknowledged", 30, 30),
    (6, "resolved", 1, 30),  # first seen long ago, seen again recently: the horizon is last_seen_at
]
_DELETE_WAITS = sa.text(  # the purge's DELETE, waiting on a row lock in this database
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    " AND wait_event_type = 'Lock' AND query LIKE 'DELETE FROM incidents%'"
)
_INSERT = (
    "INSERT INTO incidents (id, component, signature, severity, status, title, occurrences,"
    " first_seen_at, last_seen_at, acknowledged_at, resolved_at)"
    " SELECT %s, 'recorder', %s, 'error', %s, 'seeded', 1, f, t,"
    " CASE WHEN %s = 'acknowledged' THEN t END, CASE WHEN %s = 'resolved' THEN t END"
    " FROM (SELECT now() - make_interval(months => %s) AS t,"
    " now() - make_interval(months => %s) AS f) AS seen"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env=env,
            check=True,
            timeout=120,
        )
        with psycopg.connect(
            url.replace("postgresql+psycopg2", "postgresql"), autocommit=True
        ) as c:
            for n, status, last, first in _SEED:
                c.execute(_INSERT, (UUID(int=n), f"{n:016x}", status, status, status, last, first))
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield relational
    finally:
        await relational.dispose()


@pytest.fixture
def row_7(pg_dsn: str) -> Iterator[UUID]:
    """A resolved row past the horizon for the reopen race, deleted afterwards so that the module's
    tests pass in any order."""
    dsn = pg_dsn.replace("+asyncpg", "")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(_INSERT, (UUID(int=7), f"{7:016x}", "resolved", "resolved", "resolved", 40, 40))
    yield UUID(int=7)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DELETE FROM incidents WHERE id = %s", (UUID(int=7),))


async def _left(rel: SqlAlchemyRelationalRepository) -> list[int]:
    async with rel.unit_of_work() as uow:
        rows: Any = await uow.session.execute(sa.select(incidents.c.id).order_by(incidents.c.id))
        return [r.id.int for r in rows]


async def test_resolved_rows_past_the_horizon_are_dropped_oldest_first_in_batches(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    store = SqlAlchemyIncidents(rel)
    assert await store.purge_resolved(24, 1) == 1
    assert await _left(rel) == [2, 3, 4, 5, 6]  # the oldest went first
    assert await store.purge_resolved(24, 10) == 1
    assert await store.purge_resolved(24, 10) == 0  # nothing else is expired
    # Recent resolved, open and acknowledged rows stay, and so does a resolved row first seen
    # 30 months ago but seen again a month ago (6): the horizon runs from `last_seen_at`.
    assert await _left(rel) == [3, 4, 5, 6]


async def test_a_row_reopened_while_its_batch_is_deleted_is_kept(
    row_7: UUID, rel: SqlAlchemyRelationalRepository
) -> None:
    reopen = sa.update(incidents).where(incidents.c.id == row_7)
    async with rel.unit_of_work() as writer:  # a new occurrence, uncommitted: it holds the row lock
        await writer.session.execute(reopen.values(status="open", resolved_at=None))
        purge = asyncio.create_task(SqlAlchemyIncidents(rel).purge_resolved(24, 1))
        # No event to wait on: poll until the DELETE, which picked row 7 while resolved, waits.
        # One transaction per poll: pg_stat_activity is a snapshot per transaction.
        for _ in range(500):
            async with rel.unit_of_work() as probe:
                if (await probe.session.execute(_DELETE_WAITS)).scalar_one():
                    break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("the purge's DELETE never waited on the row the writer holds")
        await writer.commit()
    assert await purge == 0  # re-checked against the reopened row: kept
    assert 7 in await _left(rel)
