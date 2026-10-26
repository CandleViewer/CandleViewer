"""Integration, #913 slice 3 L2 (SEC-S3N-01): the OMS's per-environment advisory lock on real
Postgres 16, as `oms_wiring.pg_stores` builds it: `SqlAlchemySessionLock` keyed by
`environment_lock_key`, each process's on its own pool. The first process of an environment holds
it, its session's keepalives set (CR-S3L2-03), and its watchdog's probe confirms it; a second, a
deploy overlapping on another host, is refused at once, without waiting, and keeps no connection;
another environment's key is its own; a release gives it to the next process, after its pool's
dispose too (CR-S3L2-06), and so does the end of the holder's session (its backend terminated, as
a cut connection or a Postgres restart ends it), which the holder's probe then cannot confirm.
Real Postgres 16 via testcontainers (needs Docker); CI's `integration` job runs it."""

from __future__ import annotations

import asyncio
import contextlib

import psycopg
import pytest
import sqlalchemy as sa

from candleviewer.oms_wiring import ENVIRONMENT_LOCK_TIMEOUT_S, environment_lock_key
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.session_lock_sqlalchemy import (
    KEEPALIVE,
    SqlAlchemySessionLock,
)
from tests.integration.audit.test_two_writers_one_chain import pg_dsn

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]

#: The backend of the session holding a 64-bit advisory lock: its key's two 32-bit halves are the
#: `classid` and `objid` of its `pg_locks` row (`objsubid` 1). Terminated, waited for up to 5 s.
_TERMINATE = (
    "SELECT pg_terminate_backend(pid, 5000) FROM pg_locks WHERE locktype = 'advisory' AND granted "
    "AND classid::bigint = %s AND objid::bigint = %s AND objsubid = 1"
)
#: The holder's own session settings, read on its connection: `pg_settings` is per session.
_KEEPALIVES = sa.text(
    "SELECT name, setting FROM pg_settings WHERE name IN ('tcp_keepalives_idle', "
    "'tcp_keepalives_interval', 'tcp_keepalives_count', 'tcp_user_timeout')"
)


def _end_holder(dsn: str, key: int) -> list[bool]:
    halves = ((key >> 32) & 0xFFFF_FFFF, key & 0xFFFF_FFFF)
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as db:
        return [bool(row[0]) for row in db.execute(_TERMINATE, halves).fetchall()]


def _lock(pool: SqlAlchemyRelationalRepository, environment: str) -> SqlAlchemySessionLock:
    key = environment_lock_key(environment)
    return SqlAlchemySessionLock(pool.engine, key, timeout_s=ENVIRONMENT_LOCK_TIMEOUT_S)


async def _keepalives(lock: SqlAlchemySessionLock) -> dict[str, str]:
    held = lock._held
    assert held is not None
    rows = (await held.execute(_KEEPALIVES)).all()
    await held.commit()
    return {name: setting for name, setting in rows}


async def _processes(dsn: str) -> None:
    pools = [SqlAlchemyRelationalRepository(dsn, f"oms-{n}") for n in range(4)]
    first, second, live = _lock(pools[0], "demo"), _lock(pools[1], "demo"), _lock(pools[2], "live")
    third = _lock(pools[3], "demo")
    try:
        assert await first.acquire() and await first.confirm()
        assert await _keepalives(first) == {
            "tcp_keepalives_idle": KEEPALIVE["idle"],
            "tcp_keepalives_interval": KEEPALIVE["interval"],
            "tcp_keepalives_count": KEEPALIVE["count"],
            "tcp_user_timeout": KEEPALIVE["user_timeout"],
        }
        assert not await second.acquire() and not second.held  # a deploy overlap: refused
        assert await live.acquire()  # another environment's lock is its own
        await pools[0].dispose()  # the stop's order: the pool, then the lock (CR-S3L2-06)
        await first.release()
        assert await second.acquire() and await second.confirm()  # the next process takes it
        ended = await asyncio.to_thread(_end_holder, dsn, environment_lock_key("demo"))
        assert ended == [True]  # the holder's session ends: the lock goes with it
        with pytest.raises(StorageTierUnavailable):  # its watchdog's probe cannot confirm it
            await second.confirm()
        assert await third.acquire()
    finally:
        for lock in (first, second, live, third):
            with contextlib.suppress(Exception):  # the second's session is gone
                await lock.release()
        for pool in pools:
            await pool.dispose()


def test_one_oms_process_holds_its_environments_lock_and_a_second_is_refused(
    pg_dsn: str,
) -> None:
    asyncio.run(_processes(pg_dsn))
