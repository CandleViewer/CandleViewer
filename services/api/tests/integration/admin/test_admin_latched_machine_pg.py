"""Integration (E42-Q01, #962): the latched-machine fixture (SC-CHAIN-TRIPS) on Postgres 16.

The seed upserts its row through the composition root's `SnapshotAdapter` over the real snapshot
store; the inspector, reading the rows back with the same test key, lists it degraded; a second
seed changes nothing; a database not named for tests is refused before any read. Needs Docker
(testcontainers); not run locally while the bench runner holds the VPS. CI `integration` runs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.statechart_wiring import SnapshotAdapter
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemySnapshotStore
from tests.fixtures.admin.latched_machine import (
    ENTITY_ID,
    KIND,
    check_latched_machine,
    seed_latched_machine,
)
from tests.fixtures.admin.seed import FixtureRefused

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


class _Keys:
    """`HmacKeys` with one test key, never a real one."""

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": b"\x01" * 32}[key_id]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:  # its database is named `test`
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
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "fixture")
    try:
        yield repo
    finally:
        await repo.dispose()


async def _ours(rel: SqlAlchemyRelationalRepository) -> list[object]:
    rows = await SnapshotAdapter(SqlAlchemySnapshotStore(rel)).snapshots()
    return [r for r in rows if (r.machine_kind, r.entity_id) == (KIND, ENTITY_ID)]


async def test_the_seeded_row_is_listed_degraded(rel: SqlAlchemyRelationalRepository) -> None:
    await seed_latched_machine(rel, _Keys(), now=_NOW)
    await check_latched_machine(rel, _Keys(), now=_NOW)


async def test_a_second_seed_keeps_one_row(rel: SqlAlchemyRelationalRepository) -> None:
    first = await seed_latched_machine(rel, _Keys(), now=_NOW)
    second = await seed_latched_machine(rel, _Keys(), now=_NOW)
    assert second == first
    assert len(await _ours(rel)) == 1


async def test_a_database_not_named_for_tests_is_refused(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS candleviewer")
        c.execute("CREATE DATABASE candleviewer")
    other = SqlAlchemyRelationalRepository(pg_dsn.rsplit("/", 1)[0] + "/candleviewer", "fixture")
    try:
        with pytest.raises(FixtureRefused):
            await seed_latched_machine(other, _Keys(), now=_NOW)
    finally:
        await other.dispose()
