"""Integration: the roll-off's `PgAdvisoryRunLock` on real Postgres 16 (#2188 S4c, C-13.3).

One roll-off per database: a rival skips (never waits), and after the holder raised or was
cancelled another session acquires the lock. Run by the integration CI job (testcontainers)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.locks import PgAdvisoryRunLock, advisory_key

pytestmark = pytest.mark.integration

_KEY = "rolloff:trades"


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as c:
        yield c.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def lock(dsn: str) -> AsyncIterator[PgAdvisoryRunLock]:
    engine: AsyncEngine = create_async_engine(dsn)
    try:
        yield PgAdvisoryRunLock(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def other(dsn: str) -> AsyncIterator[PgAdvisoryRunLock]:
    """Another process's lock: its own engine, so its own session. A session can take again an
    advisory lock it already holds, so only another session proves a release."""
    engine: AsyncEngine = create_async_engine(dsn)
    try:
        yield PgAdvisoryRunLock(engine)
    finally:
        await engine.dispose()


async def test_a_holder_makes_a_rival_skip_not_wait(lock: PgAdvisoryRunLock) -> None:
    async with lock.hold(_KEY) as first:
        assert first is True
        async with asyncio.timeout(10), lock.hold(_KEY) as rival:
            assert rival is False  # returned at once: skipped, not queued
    async with lock.hold(_KEY) as again:
        assert again is True


async def test_after_an_exception_inside_hold_another_session_acquires(
    lock: PgAdvisoryRunLock, other: PgAdvisoryRunLock
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with lock.hold(_KEY) as got:
            assert got is True
            raise RuntimeError("boom")
    async with other.hold(_KEY) as again:
        assert again is True


async def test_after_a_cancel_inside_hold_another_session_acquires(
    lock: PgAdvisoryRunLock, other: PgAdvisoryRunLock
) -> None:
    held = asyncio.Event()

    async def holder() -> None:
        async with lock.hold(_KEY) as got:
            assert got is True
            held.set()
            await asyncio.Event().wait()

    task = asyncio.ensure_future(holder())
    await asyncio.wait_for(held.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(10), other.hold(_KEY) as again:
        assert again is True


async def test_the_rolloff_keys_are_not_the_retention_managers(lock: PgAdvisoryRunLock) -> None:
    retention = advisory_key("retention:recorder")
    assert all(advisory_key(f"rolloff:{s.value}") != retention for s in StreamKind)
    async with lock.hold("retention:recorder") as ret:
        assert ret is True
        async with lock.hold(_KEY) as rolloff:
            assert rolloff is True  # holding retention's key does not block the roll-off
