"""Integration (#2492): `SqlAlchemyUserRoleStore` on real Postgres 16.

Both owners demoted at once: the locked owner count lets exactly one change win and
the other is refused by the owner floor, so one active owner remains (E09-Q06 #2100
race). Not run locally (no docker); exercised by CI `integration`.
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
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


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


async def test_concurrent_demotion_of_both_owners_leaves_exactly_one(pg_dsn: str) -> None:
    ids = [await seed(pg_dsn, name, "correct horse battery") for name in ("owner-a", "owner-b")]
    a, b = (uuid.UUID(str(i)) for i in ids)
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    store = SqlAlchemyUserRoleStore(rel, owner_floor=_floor)
    try:
        assert await store.count_active_owners() == 2
        demote = frozenset({"viewer"})
        results = await asyncio.gather(
            store.apply_roles(a, demote), store.apply_roles(b, demote), return_exceptions=True
        )
        assert sum(r is True for r in results) == 1, results
        assert sum(isinstance(r, OwnerFloorError) for r in results) == 1, results
        assert await store.count_active_owners() == 1
        roles = {await store.get_roles(a), await store.get_roles(b)}
        assert roles == {frozenset({"owner"}), demote}
        assert await store.get_roles(uuid.uuid4()) is None
        assert await store.apply_roles(uuid.uuid4(), demote) is False
    finally:
        await rel.dispose()
