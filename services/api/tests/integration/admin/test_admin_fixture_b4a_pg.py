"""Integration (E42-Q01, #962): FLAG-OVERRIDE-ROWS on a migrated Postgres 16.

The seed passes its own check, a second run changes no row (nor any row's version), and a database
not named for tests is refused. Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from candleviewer.admin.flags.registry import LIVE_ENABLED, MAINTENANCE_MODE
from candleviewer.db import models as m
from tests.fixtures.admin.flag_overrides import (
    UNREADABLE,
    check_flag_overrides,
    seed_flag_overrides,
)
from tests.fixtures.admin.seed import FixtureRefused, connect_test_database, seed_admin_world
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; database and login `test`
_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
_XMIN = sa.cast(sa.column("xmin"), sa.Text).label("xmin")  # a rewrite, even of an equal row, shows


def _admin(dsn: str) -> psycopg.Connection[Any]:
    """The container's superuser, on its database named for tests: it makes roles and databases."""
    return connect_test_database(dsn.replace("postgresql+asyncpg", "postgresql"))


@pytest.fixture(scope="module")
def other_dsn(pg_dsn: str) -> str:
    """An empty database not named for tests: a refused seed finds nothing to read there."""
    with _admin(pg_dsn) as c:
        c.execute("DROP DATABASE IF EXISTS candleviewer")
        c.execute("CREATE DATABASE candleviewer")
    return pg_dsn.rsplit("/", 1)[0] + "/candleviewer"


@pytest.fixture
async def engine(pg_dsn: str) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(pg_dsn)
    try:
        async with created.begin() as conn:
            await seed_admin_world(conn, now=_NOW)  # slice A's world, which each seed builds on
        yield created
    finally:
        await created.dispose()


async def _rows(engine: AsyncEngine, *reads: tuple[sa.Table, Any]) -> list[list[tuple[Any, ...]]]:
    """Each table's rows that its condition selects, with their `xmin`; never `encryption_ref`."""
    async with engine.connect() as conn:
        found: list[list[tuple[Any, ...]]] = []
        for table, where in reads:
            columns = [c for c in table.c if c.name != "encryption_ref"]
            rows = (await conn.execute(sa.select(*columns, _XMIN).where(where))).all()
            found.append(sorted((tuple(r) for r in rows), key=str))
        return found


async def _is_refused_elsewhere(other_dsn: str, seed: Callable[..., Awaitable[None]]) -> None:
    """`seed` on a connection to the database not named for tests: refused, before a row is read."""
    other = create_async_engine(other_dsn)
    try:
        async with other.begin() as conn:
            with pytest.raises(FixtureRefused):
                await seed(conn)
    finally:
        await other.dispose()


async def test_the_flag_override_rows_pass_their_check_and_a_second_seed_changes_none(
    engine: AsyncEngine,
) -> None:
    f, o = m.feature_flags, m.feature_flag_overrides
    reads = ((f, f.c.key.in_([LIVE_ENABLED, MAINTENANCE_MODE, UNREADABLE])), (o, sa.true()))
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
    async with engine.connect() as conn:
        await check_flag_overrides(conn)
    before = await _rows(engine, *reads)
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
    assert await _rows(engine, *reads) == before


async def test_the_flag_seed_is_refused_on_a_database_not_named_for_tests(other_dsn: str) -> None:
    await _is_refused_elsewhere(other_dsn, seed_flag_overrides)
