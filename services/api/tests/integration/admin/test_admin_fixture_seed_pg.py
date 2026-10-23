"""Integration (E42-Q01, #962): the admin fixtures on a migrated Postgres 16: the world and the
backups of BACKUP-VERIFY-FAILED.

Each seed passes its own checks, a second run changes no row (nor any row's version), and a database
not named for tests is refused. Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from candleviewer.db import models as m
from tests.fixtures.admin.handles import ACCOUNTS, BACKUPS, FLAGS, USERS
from tests.fixtures.admin.seed import (
    FixtureRefused,
    check_admin_world,
    check_backups,
    seed_admin_world,
    seed_backups,
)
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
_Seed = Callable[..., Awaitable[None]]
_XMIN = sa.cast(sa.column("xmin"), sa.Text).label("xmin")  # a rewrite, even of an equal row, shows


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
    """Every fixture row of every table the seed writes or a trigger makes, with its `xmin`, in a
    fixed order. The default profile of each account (`trg_ea_default_profile`) has a random id."""
    users, accounts = [u.id for u in USERS], [a.id for a in ACCOUNTS]
    profiles = m.account_profiles
    own = sa.select(profiles.c.id).where(profiles.c.exchange_account_id.in_(accounts))
    reads: list[tuple[sa.Table, sa.Column[Any], Any]] = [
        (m.users, m.users.c.id, users),
        (m.user_roles, m.user_roles.c.user_id, users),
        (m.user_invites, m.user_invites.c.user_id, users),
        (m.exchange_accounts, m.exchange_accounts.c.id, accounts),
        (m.user_account_access, m.user_account_access.c.user_id, users),
        (m.feature_flags, m.feature_flags.c.key, list(FLAGS)),
        (profiles, profiles.c.exchange_account_id, accounts),
        (m.account_profile_revisions, m.account_profile_revisions.c.profile_id, own),
    ]
    snapshot = {}
    for table, column, ids in reads:
        rows = (await conn.execute(sa.select(table, _XMIN).where(column.in_(ids)))).all()
        snapshot[table.name] = sorted((tuple(row) for row in rows), key=str)
    return snapshot


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


@pytest.mark.parametrize("seed", [seed_admin_world, seed_backups])
async def test_a_database_not_named_for_tests_is_refused(pg_dsn: str, seed: _Seed) -> None:
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
                await seed(conn, now=_NOW)
    finally:
        await other.dispose()


async def _seed_backups(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await seed_backups(conn, now=_NOW)


async def _backup_rows(engine: AsyncEngine) -> list[tuple[Any, ...]]:
    """The fixture backups with their `xmin`, in a fixed order; never `encryption_ref` (class S)."""
    columns = [c for c in m.backups.c if c.name != "encryption_ref"]
    read = sa.select(*columns, _XMIN).where(m.backups.c.id.in_([b.id for b in BACKUPS]))
    async with engine.connect() as conn:
        return sorted((tuple(row) for row in (await conn.execute(read)).all()), key=str)


async def test_the_seeded_backups_pass_their_own_checks(engine: AsyncEngine) -> None:
    await _seed_backups(engine)
    async with engine.connect() as conn:
        await check_backups(conn)


async def test_a_second_backups_seed_changes_no_row(engine: AsyncEngine) -> None:
    await _seed_backups(engine)
    before = await _backup_rows(engine)
    await _seed_backups(engine)
    assert await _backup_rows(engine) == before
