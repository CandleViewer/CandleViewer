"""Integration (#2510) on real Postgres 16, in its own module (own database: the mutual-
demotion test in `test_user_roles_pg.py` needs exactly two owners). CI `integration` only."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from scripts.seed_fixture_user import seed
from tests.integration.auth.test_user_roles_pg import _floor, pg_dsn

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # the module-scoped Postgres fixture: a fresh container for this module


async def test_hung_write_ahead_audit_times_out_and_releases_the_locks(pg_dsn: str) -> None:
    """A hung WAL append under the user and owner locks times out; the rollback frees them."""
    ids = [await seed(pg_dsn, name, "correct horse battery") for name in ("owner-c", "owner-d")]
    c, d = (uuid.UUID(str(i)) for i in ids)
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    store = SqlAlchemyUserRoleStore(rel, owner_floor=_floor, audit_timeout_s=0.2)

    async def hang(before: frozenset[str]) -> None:
        await asyncio.Event().wait()

    async def accept(before: frozenset[str]) -> None:
        return None

    demote = frozenset({"viewer"})
    try:
        with pytest.raises(WriteAheadTimeout):
            await store.apply_roles(c, demote, actor=d, audit=hang)
        assert await store.get_roles(c) == frozenset({"owner"})  # rolled back
        async with asyncio.timeout(5):  # blocks on any lock the timeout left held
            assert await store.apply_roles(c, demote, actor=d, audit=accept) is True
        assert await store.get_roles(c) == demote
    finally:
        await rel.dispose()
