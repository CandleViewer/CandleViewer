"""Integration (E42-Q01, #962): the admin fixtures on a migrated Postgres 16.

The seed passes its own checks, a second run changes no row, and a database not named for tests is
refused before anything is written. Needs Docker (testcontainers); not run locally while the bench
runner holds the VPS. CI `integration` runs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.db import models as m
from tests.fixtures.admin.handles import ACCOUNTS, FLAGS, USERS
from tests.fixtures.admin.seed import FixtureRefused, check_admin_world, seed_admin_world

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


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
async def engine(pg_dsn: str) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(pg_dsn)
    try:
        yield created
    finally:
        await created.dispose()


async def _seed(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await seed_admin_world(conn, now=_NOW)


async def _rows(conn: AsyncConnection) -> dict[str, list[tuple[Any, ...]]]:
    """Every fixture row of every table the seed writes, in a fixed order."""
    users, accounts = [u.id for u in USERS], [a.id for a in ACCOUNTS]
    reads = {
        "users": sa.select(m.users).where(m.users.c.id.in_(users)),
        "user_roles": sa.select(m.user_roles).where(m.user_roles.c.user_id.in_(users)),
        "user_invites": sa.select(m.user_invites).where(m.user_invites.c.user_id.in_(users)),
        "exchange_accounts": sa.select(m.exchange_accounts).where(
            m.exchange_accounts.c.id.in_(accounts)
        ),
        "user_account_access": sa.select(m.user_account_access).where(
            m.user_account_access.c.user_id.in_(users)
        ),
        "feature_flags": sa.select(m.feature_flags).where(m.feature_flags.c.key.in_(list(FLAGS))),
    }
    return {
        name: sorted((tuple(row) for row in (await conn.execute(read)).all()), key=str)
        for name, read in reads.items()
    }


async def test_the_seeded_world_passes_its_own_checks(engine: AsyncEngine) -> None:
    await _seed(engine)
    async with engine.connect() as conn:
        await check_admin_world(conn, now=_NOW)


async def test_a_second_seed_changes_no_row(engine: AsyncEngine) -> None:
    await _seed(engine)
    async with engine.connect() as conn:
        before = await _rows(conn)
    await _seed(engine)
    async with engine.connect() as conn:
        assert await _rows(conn) == before


async def test_a_database_not_named_for_tests_is_refused(pg_dsn: str) -> None:
    admin = create_async_engine(pg_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text("DROP DATABASE IF EXISTS candleviewer"))
            await conn.execute(sa.text("CREATE DATABASE candleviewer"))
    finally:
        await admin.dispose()
    other = create_async_engine(pg_dsn.rsplit("/", 1)[0] + "/candleviewer")
    try:
        async with other.begin() as conn:
            with pytest.raises(FixtureRefused):
                await seed_admin_world(conn, now=_NOW)
    finally:
        await other.dispose()
