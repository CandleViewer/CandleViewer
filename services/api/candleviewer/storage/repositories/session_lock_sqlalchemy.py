"""A Postgres session advisory lock held on a connection of its own (#913 slice 3 L2, SEC-S3N-01).

`acquire()` asks `pg_try_advisory_lock(key)`, which never waits, and on success keeps the
connection it asked on until `release()`; that session holds the lock, so a holder whose session
ends (a crash, a cut connection, a Postgres restart) loses it with the session. `release()` asks
`pg_advisory_unlock(key)`, then ends the session whatever the unlock did, so the lock is gone
either way. The OMS runtime holds one per environment for its facade's life
(`oms_wiring.environment_lock_key`); `storage.retention.locks.PgAdvisoryRunLock` is the reaper's
per-run form. One literal statement each, the key a bound parameter; a failure leaves with its
type and SQLSTATE only, never the server's text (#2748)."""

from __future__ import annotations

import asyncio
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import strip_driver_text

_TRY: Final = sa.text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK: Final = sa.text("SELECT pg_advisory_unlock(:key)")


class SqlAlchemySessionLock:
    """One session advisory lock on `engine`'s pool, keyed by the signed 64-bit `key`."""

    def __init__(self, engine: AsyncEngine, key: int, *, timeout_s: float) -> None:
        self._engine, self._key, self._timeout_s = engine, key, timeout_s
        self._held: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._held is not None

    async def acquire(self) -> bool:
        """True once the lock is held, on a connection kept for it; False, keeping nothing, while
        another session holds it. `StorageTierUnavailable`, keeping nothing, when the pool gives
        no connection, or the statement no answer, within `timeout_s` each. `RuntimeError` while
        this lock is held already."""
        if self._held is not None:
            raise RuntimeError("the session lock is held already")
        connection = await self._connected()
        try:
            async with asyncio.timeout(self._timeout_s):
                got = bool((await connection.execute(_TRY, {"key": self._key})).scalar())
                await connection.commit()  # idle, in no transaction, while it holds the lock
        except BaseException as failed:
            strip_driver_text(failed)
            await _ended(connection)
            if isinstance(failed, Exception):
                raise StorageTierUnavailable("the session lock could not be asked") from None
            raise
        if not got:
            await connection.close()
            return False
        self._held = connection
        return True

    async def _connected(self) -> AsyncConnection:
        try:
            async with asyncio.timeout(self._timeout_s):
                return await self._engine.connect()
        except Exception as failed:
            strip_driver_text(failed)
            raise StorageTierUnavailable("the session lock could not be asked") from None

    async def release(self) -> None:
        """Unlock, then end the session the lock was held on, whatever the unlock did; a lock not
        held is a no-op. An unlock's failure is raised, stripped, once the session has ended."""
        connection, self._held = self._held, None
        if connection is None:
            return
        try:
            await connection.execute(_UNLOCK, {"key": self._key})
            await connection.commit()
        except BaseException as failed:
            strip_driver_text(failed)
            raise
        finally:
            await _ended(connection)


async def _ended(connection: AsyncConnection) -> None:
    """The connection closed and its session ended, never returned to the pool: a session
    advisory lock it held goes with it."""
    try:
        await connection.invalidate()
    finally:
        await connection.close()
