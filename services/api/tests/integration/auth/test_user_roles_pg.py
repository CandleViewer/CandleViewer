"""Integration (#2492): `SqlAlchemyUserRoleStore` on real Postgres 16.

Each owner demotes the other at the same moment. A third connection holds every
owner grant until both callers are blocked on it, so the two transactions really
overlap; on release exactly one wins and the other is refused by the owner-floor
check on the count it read under lock (not by the deferred DB trigger), leaving one
active owner. Not run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_HOLD = sa.text(
    "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "WHERE r.name = 'owner' FOR UPDATE OF ur"
)
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
_GRANTED_BY = sa.text(
    "SELECT ur.granted_by FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "WHERE ur.user_id = CAST(:id AS uuid) AND r.name = 'viewer'"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
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


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


async def _until_blocked(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on a lock (pg_locks is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} callers never blocked on the held owner grants")


async def test_mutual_demotion_of_the_two_owners_leaves_exactly_one(pg_dsn: str) -> None:
    ids = [await seed(pg_dsn, name, "correct horse battery") for name in ("owner-a", "owner-b")]
    a, b = (uuid.UUID(str(i)) for i in ids)
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    store = SqlAlchemyUserRoleStore(rel, owner_floor=_floor)
    audited: list[frozenset[str]] = []

    async def audit(before: frozenset[str]) -> None:
        audited.append(before)

    demote = frozenset({"viewer"})
    try:
        assert await store.count_active_owners() == 2
        async with engine.connect() as probe:
            async with engine.begin() as holder:
                await holder.execute(_HOLD)
                calls = [
                    asyncio.create_task(store.apply_roles(x, demote, actor=y, audit=audit))
                    for x, y in ((a, b), (b, a))
                ]
                await _until_blocked(probe, 2)
            results = await asyncio.gather(*calls, return_exceptions=True)
            assert sum(r is True for r in results) == 1, results
            (loser,) = [r for r in results if isinstance(r, OwnerFloorError)]
            assert loser.__context__ is None  # the locked count refused it, not the trigger
            winner = a if results[0] is True else b
            got: uuid.UUID = (await probe.execute(_GRANTED_BY, {"id": str(winner)})).scalar_one()
            assert got == (b if winner == a else a)  # the new grant records its actor
        assert await store.count_active_owners() == 1 and audited == [frozenset({"owner"})]
        assert await store.get_roles(uuid.uuid4()) is None
        assert await store.apply_roles(uuid.uuid4(), demote, actor=a, audit=audit) is False
    finally:
        await rel.dispose()
        await engine.dispose()
