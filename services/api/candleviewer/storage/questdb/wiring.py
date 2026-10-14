"""Production composition of the QuestDB ILP writer (#1701).

`build_hot_tier_writer` is the single place that attaches the PG-wire
readiness probe and committed-row counter, so no caller can build an
unguarded writer by accident. `run_reconcile_loop` periodically compares
rows sent vs committed and exports the gap as `questdb_ilp_unreconciled_rows`
(alert on > 0 sustained).
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import asyncpg

from candleviewer.observability.metrics import Metrics
from candleviewer.storage.questdb.ilp_writer import IlpTransport, IlpWriter, TableSchema
from candleviewer.storage.questdb.reader import (
    PgWireConnection,
    pgwire_committed_counter,
    pgwire_readiness_probe,
)
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

#: Bound on the sink's final ILP drain at shutdown (the default 30 s is too long for bars).
STOP_TIMEOUT_S = 10.0


def build_hot_tier_writer(
    transport: IlpTransport,
    schemas: dict[str, TableSchema],
    connection: PgWireConnection,
    **kwargs: object,
) -> IlpWriter:
    """`IlpWriter` with readiness probe + committed counter always wired.
    The counter is `count()` over every schema table: it MUST be cumulative
    (monotonic) — `IlpWriter` baselines it once at first connect."""
    return IlpWriter(
        transport,
        schemas,
        readiness_probe=pgwire_readiness_probe(connection),
        committed_counter=pgwire_committed_counter(connection, tuple(schemas)),
        **kwargs,  # type: ignore[arg-type]  # forwarded tuning knobs (max_queue_rows, ...)
    )


async def run_reconcile_loop(
    writer: IlpWriter,
    metrics: Metrics,
    *,
    interval_s: float = 30.0,
    iterations: int | None = None,
) -> None:
    """Every `interval_s`, reconcile and set the gap gauge. Probe failures are
    counted, never fatal. `iterations` bounds the loop for tests."""
    gap_gauge = metrics.gauge(
        "questdb_ilp_unreconciled_rows",
        "ILP rows sent but not (yet) committed per QuestDB count().",
    ).child()
    errors = metrics.counter(
        "questdb_ilp_reconcile_errors_total", "Failed sent-vs-committed reconcile attempts."
    ).child()
    done = 0
    while iterations is None or done < iterations:
        await asyncio.sleep(interval_s)
        try:
            await writer.reconcile()
            gap_gauge.set(writer.unreconciled_rows)
        except Exception:
            errors.inc()
        done += 1


class TcpIlpTransport:
    """ILP-over-TCP `IlpTransport` (QuestDB line-protocol port)."""

    def __init__(self, host: str, port: int, *, connect_timeout_s: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._connect_timeout_s = connect_timeout_s
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        await self.close()  # never orphan a previous socket on reconnect
        async with asyncio.timeout(self._connect_timeout_s):
            _, self._writer = await asyncio.open_connection(self._host, self._port)

    async def write(self, data: bytes) -> None:
        if self._writer is None:
            raise ConnectionError("ILP transport is not connected")
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


class LazyPgWire:
    """`PgWireConnection` over one lazily opened asyncpg connection (C-2.18).

    One `asyncio.Lock` serialises connect, reconnect and every query (an asyncpg connection is
    not concurrency-safe), so at most one connection ever exists. Connect and each query run
    under `asyncio.timeout`. A failed connect starts a capped exponential backoff with jitter
    (`backoff_*`): calls inside the window fail fast instead of hammering a dead DB. After
    `degraded_after` consecutive failures `degraded` is True (surfaced by the bars writer
    probe); one success clears it. Any exception - including cancellation - during a query
    discards the connection so the next caller never reuses a half-used one."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        *,
        connect: Callable[..., Awaitable[Any]] = asyncpg.connect,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        connect_timeout_s: float = 5.0,
        query_timeout_s: float = 10.0,
        close_timeout_s: float = 5.0,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 30.0,
        degraded_after: int = 3,
    ) -> None:
        self._args: dict[str, Any] = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": "qdb",
        }
        self._connect = connect
        self._clock = clock
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not crypto
        self._connect_timeout_s = connect_timeout_s
        self._query_timeout_s = query_timeout_s
        self._close_timeout_s = close_timeout_s
        self._base_s = backoff_base_s
        self._max_s = backoff_max_s
        self._degraded_after = degraded_after
        self._lock = asyncio.Lock()
        self._conn: Any = None
        self._failures = 0
        self._retry_at = 0.0

    @property
    def degraded(self) -> bool:
        return self._failures >= self._degraded_after

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return [dict(r) for r in await self.fetch_records(sql, *params)]

    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        """`fetch` without the per-row `dict` copy: the driver's read-only records, for a
        caller that maps them off the event loop (E26-T02, C-2.17)."""
        async with self._lock:
            if self._conn is None:
                await self._open()
            try:
                async with asyncio.timeout(self._query_timeout_s):
                    rows: list[Mapping[str, object]] = await self._conn.fetch(sql, *params)
            except BaseException:  # incl. CancelledError: never reuse a half-used connection
                await self._discard()
                raise
            return rows

    async def _open(self) -> None:
        now = self._clock()
        if now < self._retry_at:
            raise ConnectionError("questdb pg-wire in reconnect backoff")
        try:
            async with asyncio.timeout(self._connect_timeout_s):
                self._conn = await self._connect(**self._args)
        except Exception:
            self._failures += 1
            delay = min(self._max_s, self._base_s * 2 ** (self._failures - 1))
            self._retry_at = now + delay * self._rng.uniform(0.5, 1.5)
            raise
        self._failures = 0
        self._retry_at = 0.0

    async def _discard(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            async with asyncio.timeout(self._close_timeout_s):
                await asyncio.shield(conn.close())
        except BaseException:
            with contextlib.suppress(Exception):
                conn.terminate()

    async def close(self) -> None:
        """Bounded: a hung `close()` is abandoned via `terminate()` after `close_timeout_s`."""
        async with self._lock:
            await self._discard()


class QuestDbRowSink:
    """Bars `RowSink` over the hot-tier `IlpWriter` (transport + PG-wire via
    `build_hot_tier_writer`). The writer connects on first flush (retrying with backoff);
    `stop()` drains it, closes the transport, then the PG-wire connection."""

    def __init__(
        self,
        ilp: str,
        pg: str,
        user: str,
        password: str,
        *,
        transport: IlpTransport | None = None,
        pgwire: LazyPgWire | None = None,
    ) -> None:
        ilp_host, _, ilp_port = ilp.partition(":")
        pg_host, _, pg_port = pg.partition(":")
        self.pgwire = pgwire or LazyPgWire(pg_host, int(pg_port or 8812), user, password)
        self.writer = build_hot_tier_writer(
            transport or TcpIlpTransport(ilp_host, int(ilp_port or 9009)),
            ALL_SCHEMAS,
            self.pgwire,
        )

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        await self.writer.write_rows(table, rows, ts_us_key)

    async def stop(self) -> None:
        try:
            # Drain then close the ILP transport, bounded so a dead QuestDB cannot stall shutdown.
            async with asyncio.timeout(STOP_TIMEOUT_S + 5.0):
                await self.writer.stop(timeout_s=STOP_TIMEOUT_S)
        finally:
            await self.pgwire.close()
