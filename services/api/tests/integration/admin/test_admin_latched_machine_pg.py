"""Integration (E42-Q01, #962): the degraded-snapshot fixture (SC-CHAIN-TRIPS) on Postgres 16.

The seed upserts its row through the composition root's `SnapshotAdapter` over the real snapshot
store; the inspector, reading the rows back with the same test key, lists it degraded; a second
seed leaves the stored row as the first wrote it (its `updated_at`, its sealed envelope and its leaf
ids included); a database not named for tests is refused before any read. Needs Docker
(testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import psycopg
import pytest

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import (
    SnapshotRecord,
    SqlAlchemySnapshotStore,
)
from tests.fixtures.admin.latched_machine import (
    ENTITY_ID,
    ENV,
    KIND,
    check_latched_machine,
    seed_latched_machine,
)
from tests.fixtures.admin.seed import FixtureRefused
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


class _Keys:
    """`HmacKeys` with one test key, never a real one."""

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": b"\x01" * 32}[key_id]


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "fixture")
    try:
        yield repo
    finally:
        await repo.dispose()


async def _stored(rel: SqlAlchemyRelationalRepository) -> SnapshotRecord | None:
    """The `machine_snapshots` row as the store holds it, every column."""
    return await SqlAlchemySnapshotStore(rel).get(KIND, ENTITY_ID, ENV)


async def test_the_seeded_row_is_listed_degraded(rel: SqlAlchemyRelationalRepository) -> None:
    await seed_latched_machine(rel, _Keys(), now=_NOW)
    await check_latched_machine(rel, _Keys(), now=_NOW)


async def test_a_second_seed_leaves_the_stored_row_as_the_first_wrote_it(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    await seed_latched_machine(rel, _Keys(), now=_NOW)
    first = await _stored(rel)
    assert first is not None
    leaves = ("order.lifecycle.triggered", "order.protection.sl_present")  # what cv-api writes
    assert (first.state_ids, first.chain_trips, first.updated_at) == (leaves, 2, _NOW)
    await seed_latched_machine(rel, _Keys(), now=_NOW)
    assert await _stored(rel) == first


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
