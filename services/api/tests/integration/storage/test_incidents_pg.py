"""Integration: `SqlAlchemyIncidents` on real Postgres 16 (E42-T05).

What the statement-compiling unit test cannot show: the keyset order with its `id` tie-break,
each status filter, the types a row maps to, and the SQLSTATE the real driver reports for the
statement timeout (an outage) and for a statement the database refuses (a bug). Not run locally
(no docker); the same statements were run on a scratch Postgres 16.4 first. CI integration
lane."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from structlog.testing import capture_logs
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import incidents_sqlalchemy as repo
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
#: (n, minutes ago, status): incidents 2 and 3 share their `last_seen_at`.
_SEED = [
    (1, 1, "open"),
    (2, 2, "acknowledged"),
    (3, 2, "resolved"),
    (4, 4, "open"),
    (5, 5, "resolved"),
]


_INSERT = (
    "INSERT INTO incidents (id, component, signature, severity, status, title, detail,"
    " occurrences, first_seen_at, last_seen_at, acknowledged_at, resolved_at)"
    " VALUES (%s, 'recorder', %s, 'error', %s, 'title', 'detail', %s, %s, %s,"
    " CASE WHEN %s = 'acknowledged' THEN %s END, CASE WHEN %s = 'resolved' THEN %s END)"
)


def _seed(c: psycopg.Connection[Any]) -> None:
    for n, ago, status in _SEED:
        seen = NOW - timedelta(minutes=ago)
        first = seen - timedelta(hours=1)
        c.execute(
            _INSERT, (UUID(int=n), f"{n:016x}", status, n, first, seen, status, seen, status, seen)
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
            _seed(c)
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def reader(pg_dsn: str) -> AsyncIterator[SqlAlchemyIncidents]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield SqlAlchemyIncidents(relational)
    finally:
        await relational.dispose()


async def test_pages_follow_the_keyset_newest_first_with_ties_broken_by_id(
    reader: SqlAlchemyIncidents,
) -> None:
    seen: list[int] = []
    after = None
    while page := await reader.page(status=None, after=after, limit=2):
        seen += [r.id.int for r in page]
        after = (page[-1].last_seen_at, page[-1].id)
    assert seen == [1, 3, 2, 4, 5]  # 3 before 2: the same time, the larger id first


async def test_a_row_maps_to_python_types_and_the_status_filter_selects_its_rows(
    reader: SqlAlchemyIncidents,
) -> None:
    first, *_ = await reader.page(status=None, after=None, limit=1)
    assert first.last_seen_at == NOW - timedelta(minutes=1)  # aware, to the microsecond
    assert (isinstance(first.id, UUID), first.severity, first.acknowledged_by) == (
        True,
        "error",
        None,
    )
    for status, ids in {"open": [1, 4], "acknowledged": [2], "resolved": [3, 5]}.items():
        rows = await reader.page(status=status, after=None, limit=10)
        assert [r.id.int for r in rows] == ids


async def test_the_statement_timeout_is_an_outage_not_a_bug(
    reader: SqlAlchemyIncidents, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repo, "page_statement", lambda *_: sa.text("SELECT pg_sleep(3)"))
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable):
        await reader.page(status=None, after=None, limit=1)  # `READ_TIMEOUT` (1 s) cut it, not 3 s
    assert logs[0]["sqlstate"] == "57014"  # query_canceled, as the driver reports it


@pytest.mark.parametrize(
    ("statement", "sqlstate"),
    [
        ("SELECT CAST('not-a-uuid' AS uuid)", "22P02"),  # asyncpg: a generic DBAPIError
        ("SELECT 1 / 0", "22012"),
        ("SELECT no_such_column FROM incidents", "42703"),  # asyncpg: a ProgrammingError
    ],
    ids="data-22P02 data-22012 column-42703".split(),
)
async def test_a_refused_statement_is_a_bug_with_the_drivers_own_sqlstate(
    reader: SqlAlchemyIncidents, monkeypatch: pytest.MonkeyPatch, statement: str, sqlstate: str
) -> None:
    monkeypatch.setattr(repo, "page_statement", lambda *_: sa.text(statement))
    with pytest.raises(sa_exc.DBAPIError) as refused:  # keeps its type: not a 503 with a retry
        await reader.page(status=None, after=None, limit=1)
    assert getattr(refused.value.orig, "sqlstate", None) == sqlstate
