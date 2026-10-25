"""Bounded Parquet read path for `/market/klines` (E12 cold tier, issue #2048).

Layout `klines/symbol=<S>/interval=<I>/ym=<YYYY-MM>/part-*.parquet` (`21-database-schema.md`
Sec.5.1). Every path is built by `DatasetRegistry.resolve_partition`, which validates the
symbol/interval/month against a closed charset *before* any join (SR-097), so `../x` never
reaches the filesystem. The scan is bounded: only the months the (already capped) window
touches are opened, only manifest-listed + verified files are read, the DuckDB statement is
fully parameterised, `LIMIT` is pushed down, and the blocking call runs off the event loop
under a timeout (C-2.18) that interrupts the read's DuckDB cursor. Reads share one in-memory
DuckDB instance per reader, each on its own `cursor()` (#2523): no per-read connect/close.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import structlog

from candleviewer.observability.context import thread_future
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import StorageExportVerifyFailed, StorageTierUnavailable
from candleviewer.storage.models import StreamKind

_MAX_MONTHS = 120
_DEFAULT_MAX_ROWS = 5_100
_DEFAULT_CONCURRENCY = 2
_MEMORY_LIMIT = "256MiB"
_THREADS = 2


class ColdKlineReadTimeout(StorageTierUnavailable):
    """The DuckDB kline read exceeded its deadline (route maps this to 503)."""

    code = "COLD_KLINE_READ_TIMEOUT"


class ColdKlineReadError(StorageTierUnavailable):
    """Integrity failure (checksum/row-count mismatch, quarantined partition: the whole cold
    read fails, never a partial window), schema drift or a corrupt file.

    DuckDB/Parquet could not serve the read (schema drift, corrupt file): route -> 503."""

    code = "COLD_KLINE_READ_ERROR"


@dataclass(frozen=True, slots=True)
class ColdKlineRow:
    """One Parquet kline, shaped like `ingestion.kline_read.KlineRowLike`."""

    ts_us: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool
    source: str


def _num(value: object) -> str:
    """Decimal text of a Parquet value, equal to `format(Decimal(repr(v)), "f")` for floats.

    #2523: a float `repr` with no exponent (`e`) and not `inf`/`nan` (`n`) is already that
    text, so the Decimal round-trip runs only for the forms that need it."""
    if isinstance(value, float):
        text = repr(value)
        # exponent forms hold "e"; the only reprs holding "n" are inf, -inf and nan
        if "e" in text or "n" in text:
            return format(Decimal(text), "f")
        return text
    return str(value)


def months_between(start_us: int, end_us: int) -> list[str]:
    """`YYYY-MM` keys of every month overlapping `[start_us, end_us)`, oldest first."""
    if end_us <= start_us:
        return []
    first = datetime.fromtimestamp(start_us / 1_000_000, tz=UTC)
    last = datetime.fromtimestamp((end_us - 1) / 1_000_000, tz=UTC)
    out: list[str] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out[-_MAX_MONTHS:]


class ParquetKlineReader:
    """`ColdKlineReader` (see `ingestion.kline_read`) over the cold lake."""

    def __init__(
        self,
        registry: DatasetRegistry,
        *,
        events: SystemEventSink | None = None,
        timeout_s: float = 5.0,
        max_rows: int = _DEFAULT_MAX_ROWS,
        max_concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self._registry = registry
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._timeout_s = timeout_s
        self._max_rows = max_rows
        # C-2.18: bound concurrent DuckDB scans (each is a thread + a cursor on the one shared
        # in-memory instance, so `memory_limit` / `threads` cap all of them together).
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._verified: dict[Path, tuple[int, int]] = {}
        self._db: _SharedDuckDB | None = None

    def close(self) -> None:
        """Release the shared DuckDB instance; it closes once no read still holds a cursor.
        A later read opens a fresh one."""
        if self._db is not None:
            self._retire(self._db)

    def _retire(self, db: _SharedDuckDB) -> None:
        # Closing the instance closes its cursors, so an in-flight read keeps it open until
        # its worker returns (`_release`). Only the event loop thread runs this.
        if self._db is db:
            self._db = None
        db.retired = True
        if db.users == 0:
            db.con.close()

    def _shared(self) -> _SharedDuckDB:
        """The shared instance, opened on first use. Limits go through connect-config."""
        if self._db is None:
            con = duckdb.connect(
                ":memory:", config={"memory_limit": _MEMORY_LIMIT, "threads": str(_THREADS)}
            )
            self._db = _SharedDuckDB(con)
        return self._db

    def _cursor(self) -> tuple[_SharedDuckDB, duckdb.DuckDBPyConnection]:
        """A cursor for one read. A broken instance (`cursor()` fails) is retired and replaced
        once; if the fresh one fails too, the read fails typed (503)."""
        db = self._shared()
        try:
            cur = db.con.cursor()
        except duckdb.Error:
            self._retire(db)
            db = self._shared()
            try:
                cur = db.con.cursor()
            except duckdb.Error as exc:
                self._retire(db)
                raise ColdKlineReadError(f"cold kline read failed: {type(exc).__name__}") from exc
        db.users += 1
        return db, cur

    def _release(self, db: _SharedDuckDB, fut: asyncio.Future[list[ColdKlineRow]]) -> None:
        """Done-callback of a read's worker future (event loop thread). It runs only once the
        worker thread has returned: `thread_future` is a plain executor future that nothing but
        this reader could cancel, and it never does. So a caller cancelled mid-read, or the
        loop tearing down (which cancels Tasks, never this future), leaves the read counted
        until its worker is out of DuckDB, and a retired instance is never closed under it.
        Any failure other than our own timeout's interrupt retires the instance, so a poisoned
        one is never reused."""
        db.users -= 1
        exc = fut.exception()
        if exc is not None and not isinstance(exc.__cause__, duckdb.InterruptException):
            self._retire(db)
        elif db.retired and db.users == 0:
            db.con.close()

    def _partition(self, symbol: str, interval: str, ym: str) -> ColdPaths:
        return self._registry.resolve_partition(
            StreamKind.KLINES, partition_values={"symbol": symbol, "interval": interval, "ym": ym}
        )

    async def _files(self, paths: ColdPaths) -> list[str]:
        store = ManifestStore(paths.manifests_dir)
        read = store.read_with_quarantine
        try:
            entries, quarantined = await asyncio.to_thread(read, paths.partition_dir, paths.root)
        except OSError:  # its text names the path: typed, with no chain (503)
            raise ColdKlineReadError("cold kline partition could not be listed") from None
        if quarantined:
            # #3477: the manifest no longer names the quarantined part, so the month's other
            # parts would pass for all of it. Fail the cold read (503) until it is cleared.
            raise ColdKlineReadError("cold kline partition holds a quarantined part")
        files = [paths.partition_dir / e.file for e in entries]
        if not files:
            return []
        stamps = await asyncio.to_thread(_stamps, files)
        if any(self._verified.get(f) != stamps[f] for f in files):
            try:
                await verify_partition(paths, self._events)
            except StorageExportVerifyFailed as exc:
                # B1: a quarantined partition is an integrity event. Fail the cold read (503)
                # rather than silently serving a partial window.
                raise ColdKlineReadError("cold kline partition failed verification") from exc
            self._verified.update(stamps)
        return [f.as_posix() for f in files]

    async def __call__(self, symbol: str, interval: str, rng: Any) -> list[ColdKlineRow]:
        lo, hi = int(rng.start_us), int(rng.end_us)
        files: list[str] = []
        # Validation happens inside `_partition` for every component, before any I/O.
        for ym in months_between(lo, hi):
            files.extend(await self._files(self._partition(symbol, interval, ym)))
        if not files:
            return []
        return await self._query(files, lo, hi)

    async def _query(self, files: list[str], lo: int, hi: int) -> list[ColdKlineRow]:
        async with self._sem:
            return await self._query_unbounded(files, lo, hi)

    async def _query_unbounded(self, files: list[str], lo: int, hi: int) -> list[ColdKlineRow]:
        # N4: take this read's cursor BEFORE the worker thread starts so `interrupt()` can never
        # be a no-op; it interrupts this cursor only (#2523). The worker closes the cursor.
        db, cur = self._cursor()
        # Not `spawn(to_thread(...))`: cancelling that Task would cancel the executor future
        # while the thread still runs, and `_release` would drop the count early (see there).
        fut = thread_future(_read_rows, cur, files, lo, hi, self._max_rows)
        fut.add_done_callback(lambda f: self._release(db, f))
        try:
            async with asyncio.timeout(self._timeout_s):
                return await asyncio.shield(fut)
        except TimeoutError as exc:
            # The worker may close its cursor just as the deadline fires; `interrupt()` on a
            # closed cursor raises ConnectionException, and the caller still gets the typed
            # timeout (503), never that raw error.
            with contextlib.suppress(duckdb.ConnectionException):
                cur.interrupt()
            raise ColdKlineReadTimeout(f"cold kline read exceeded {self._timeout_s}s") from exc
        finally:
            if not fut.done():  # timed out or cancelled: nobody awaits the worker's outcome
                fut.add_done_callback(_log_late_failure)


@dataclass(slots=True, eq=False)
class _SharedDuckDB:
    """The reader's one in-memory DuckDB instance; each read runs on its own `cursor()` (a
    connection to the same database, one per worker thread, as DuckDB documents)."""

    con: duckdb.DuckDBPyConnection
    users: int = 0  # reads holding a cursor (event loop thread only)
    retired: bool = False


def _log_late_failure(fut: asyncio.Future[list[ColdKlineRow]]) -> None:
    """Debug trace of a worker that failed after its caller stopped waiting (timeout or
    cancel); `_release` consumes the exception. Type names only: no paths, no values."""
    exc = fut.exception()
    if exc is not None:
        # Resolved per call: a module-level logger pins a stale processor chain (#2008).
        structlog.get_logger(__name__).debug(
            "cold_kline_read_late_failure",
            error=type(exc).__name__,
            cause=type(exc.__cause__).__name__,  # "NoneType" when it has no cause
        )


def _stamps(files: list[Path]) -> dict[Path, tuple[int, int]]:
    out: dict[Path, tuple[int, int]] = {}
    for f in files:
        st = f.stat() if f.is_file() else None
        out[f] = (st.st_size, st.st_mtime_ns) if st else (-1, -1)
    return out


def _column(table: pa.Table, name: str, default: object) -> list[Any]:
    """`name`'s values, or `default` per row when no file carries it (union_by_name)."""
    if name in table.column_names:
        values: list[Any] = table.column(name).to_pylist()
        return values
    return [default] * table.num_rows


def _read_rows(
    cur: duckdb.DuckDBPyConnection,
    files: list[str],
    lo: int,
    hi: int,
    max_rows: int,
) -> list[ColdKlineRow]:
    try:
        cur.execute("SET TimeZone = 'UTC'")
        # union_by_name tolerates schema drift; optional columns default in Python. Dedup on
        # ts happens before LIMIT so duplicate part-file rows never eat the cap. #2523: `ts`
        # leaves DuckDB as int64 epoch us (the WHERE still binds the stored TIMESTAMPTZ, so the
        # predicate is pushed into the scan), never as tz-aware datetimes built in Python.
        table = cur.execute(
            "SELECT * REPLACE (epoch_us(ts) AS ts) "
            "FROM read_parquet($files, hive_partitioning = false, union_by_name = true) "
            "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
            "QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts) = 1 "
            "ORDER BY ts DESC LIMIT $n",
            {"files": files, "lo": lo, "hi": hi, "n": max_rows},
        ).to_arrow_table()
    except duckdb.Error as exc:
        raise ColdKlineReadError(f"cold kline read failed: {type(exc).__name__}") from exc
    finally:
        cur.close()  # N4: the worker closes its own cursor; the shared instance stays open
    # Column-wise: one `to_pylist` per column, no per-row dicts (#2523).
    out = [
        ColdKlineRow(
            ts_us=ts,
            open=_num(o),
            high=_num(h),
            low=_num(lo_),
            close=_num(c),
            volume=_num(v),
            turnover=_num(t),
            confirmed=bool(ok),
            source=str(src or "parquet"),
        )
        for ts, o, h, lo_, c, v, t, ok, src in zip(
            table.column("ts").to_pylist(),
            _column(table, "open", "0"),
            _column(table, "high", "0"),
            _column(table, "low", "0"),
            _column(table, "close", "0"),
            _column(table, "volume", "0"),
            _column(table, "turnover", "0"),
            _column(table, "confirmed", True),
            _column(table, "source", None),
            strict=True,
        )
    ]
    out.sort(key=lambda x: x.ts_us)
    return out


__all__ = [
    "ColdKlineReadError",
    "ColdKlineReadTimeout",
    "ColdKlineRow",
    "ParquetKlineReader",
    "months_between",
]
