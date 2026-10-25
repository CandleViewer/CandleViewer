"""A Postgres session advisory lock held on a connection of its own (#913 slice 3 L2, SEC-S3N-01).

`acquire()` asks `pg_try_advisory_lock(key)`, which never waits, and on success sets the server's
TCP keepalives on that session (CR-S3L2-03) and keeps the connection it asked on until `release()`;
that session holds the lock, so a holder whose session ends (a crash, a cut connection, a Postgres
restart) loses it with the session, and the keepalives bound how long Postgres keeps the session
of a holder whose host or network died: about `STALE_HOLDER_S`, the stale-holder window.
`confirm()` asks, on that session, whether it still holds the key (its `pg_locks` row), the OMS
lane's watchdog's probe.
`release()` asks `pg_advisory_unlock(key)`, then ends the session whatever the unlock did, so the
lock is gone either way. The OMS runtime holds one per environment for its facade's life
(`oms_wiring.environment_lock_key`); `storage.retention.locks.PgAdvisoryRunLock` is the reaper's
per-run form. One literal statement each, the key a bound parameter; a failure leaves with its
type and SQLSTATE only, never the server's text (#2748)."""

from __future__ import annotations

import asyncio
from types import MappingProxyType
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import strip_driver_text

_TRY: Final = sa.text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK: Final = sa.text("SELECT pg_advisory_unlock(:key)")
#: CR-S3L2-03: the server's keepalives on the holder's session, set for the session's life (it is
#: never returned to the pool): 10 s idle, then 3 probes 5 s apart, and 25 s for a send left
#: unacknowledged, so Postgres ends a dead holder's session, and its lock, within `STALE_HOLDER_S`.
_KEEPALIVE: Final = sa.text(
    "SELECT set_config('tcp_keepalives_idle', :idle, false),"
    " set_config('tcp_keepalives_interval', :interval, false),"
    " set_config('tcp_keepalives_count', :count, false),"
    " set_config('tcp_user_timeout', :user_timeout, false)"
)
KEEPALIVE: Final = MappingProxyType(
    {"idle": "10", "interval": "5", "count": "3", "user_timeout": "25000"}
)
STALE_HOLDER_S: Final = 25
#: Whether this session holds the lock: its `pg_locks` row, the key's two unsigned 32-bit halves
#: as `classid` and `objid` (`objsubid` 1), on this backend.
_HELD: Final = sa.text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
    " AND pid = pg_backend_pid() AND classid::bigint = :high AND objid::bigint = :low"
    " AND objsubid = 1)"
)


class SqlAlchemySessionLock:
    """One session advisory lock on `engine`'s pool, keyed by the signed 64-bit `key`."""

    def __init__(self, engine: AsyncEngine, key: int, *, timeout_s: float) -> None:
        self._engine, self._key, self._timeout_s = engine, key, timeout_s
        self._halves = {"high": (key >> 32) & 0xFFFF_FFFF, "low": key & 0xFFFF_FFFF}
        self._held: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._held is not None

    async def acquire(self) -> bool:
        """True once the lock is held, on a connection kept for it, its session's keepalives set
        (`KEEPALIVE`); False, keeping nothing, while another session holds it.
        `StorageTierUnavailable`, keeping nothing, when the pool gives no connection, or the
        statement no answer, within `timeout_s` each. `RuntimeError` while this lock is held
        already."""
        if self._held is not None:
            raise RuntimeError("the session lock is held already")
        connection = await self._connected()
        try:
            async with asyncio.timeout(self._timeout_s):
                got = bool((await connection.execute(_TRY, {"key": self._key})).scalar())
                if got:  # never held without them: a failure here ends the session, and the lock
                    await connection.execute(_KEEPALIVE, dict(KEEPALIVE))
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

    async def confirm(self) -> bool:
        """Whether this lock's session still holds it, asked on that session within `timeout_s`
        (the OMS lane's watchdog, CR-S3L2-03): False when it is not held here, or the session no
        longer holds the key. `StorageTierUnavailable`, stripped, when the session cannot answer
        (ended, or past the bound): the caller cannot tell, and takes it as lost."""
        connection = self._held
        if connection is None:
            return False
        try:
            async with asyncio.timeout(self._timeout_s):
                held = bool((await connection.execute(_HELD, self._halves)).scalar())
                await connection.commit()
        except Exception as failed:
            strip_driver_text(failed)
            raise StorageTierUnavailable("the session lock could not be confirmed") from None
        return held

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
