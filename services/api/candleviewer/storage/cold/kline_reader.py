"""Bounded Parquet read path for `/market/klines` (E12 cold tier, issue #2048).

Layout `klines/symbol=<S>/interval=<I>/ym=<YYYY-MM>/part-*.parquet` (`21-database-schema.md`
Sec.5.1). Every path is built by `DatasetRegistry.resolve_partition`, which validates the
symbol/interval/month against a closed charset *before* any join (SR-097), so `../x` never
reaches the filesystem. The scan is bounded: only the months the (already capped) window
touches are opened, only manifest-listed + verified files are read, the DuckDB statement is
fully parameterised, `LIMIT` is pushed down, and the blocking call runs off the event loop
under a timeout (C-2.18) that interrupts the DuckDB connection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from candleviewer.observability import spawn
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import StorageExportVerifyFailed, StorageTierUnavailable
from candleviewer.storage.models import StreamKind

_MAX_MONTHS = 120
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
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
    return format(Decimal(repr(value)), "f") if isinstance(value, float) else str(value)


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
        # C-2.18: bound concurrent DuckDB scans (each is a thread + an in-memory instance).
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._verified: dict[Path, tuple[int, int]] = {}

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
        # N4: connect BEFORE the worker thread starts so `interrupt()` can never be a no-op.
        # Limits go through connect-config (no SQL text). The worker closes the connection.
        con = duckdb.connect(
            ":memory:", config={"memory_limit": _MEMORY_LIMIT, "threads": str(_THREADS)}
        )
        task = spawn(
            asyncio.to_thread(_read_rows, con, files, lo, hi, self._max_rows),
            name="cold-kline-read",
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                return await asyncio.shield(task)
        except TimeoutError as exc:
            con.interrupt()
            raise ColdKlineReadTimeout(f"cold kline read exceeded {self._timeout_s}s") from exc


def _stamps(files: list[Path]) -> dict[Path, tuple[int, int]]:
    out: dict[Path, tuple[int, int]] = {}
    for f in files:
        st = f.stat() if f.is_file() else None
        out[f] = (st.st_size, st.st_mtime_ns) if st else (-1, -1)
    return out


def _read_rows(
    con: duckdb.DuckDBPyConnection,
    files: list[str],
    lo: int,
    hi: int,
    max_rows: int,
) -> list[ColdKlineRow]:
    try:
        con.execute("SET TimeZone = 'UTC'")
        # union_by_name tolerates schema drift; optional columns default in Python. Dedup on
        # ts happens before LIMIT so duplicate part-file rows never eat the cap.
        table = con.execute(
            "SELECT * FROM read_parquet($files, hive_partitioning = false, union_by_name = true) "
            "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
            "QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts) = 1 "
            "ORDER BY ts DESC LIMIT $n",
            {"files": files, "lo": lo, "hi": hi, "n": max_rows},
        ).to_arrow_table()
    except duckdb.Error as exc:
        raise ColdKlineReadError(f"cold kline read failed: {type(exc).__name__}") from exc
    finally:
        con.close()
    out: list[ColdKlineRow] = []
    for r in table.to_pylist():
        ts = r["ts"]
        out.append(
            ColdKlineRow(
                ts_us=(ts - _EPOCH) // timedelta(microseconds=1),
                open=_num(r.get("open", "0")),
                high=_num(r.get("high", "0")),
                low=_num(r.get("low", "0")),
                close=_num(r.get("close", "0")),
                volume=_num(r.get("volume", "0")),
                turnover=_num(r.get("turnover", "0")),
                confirmed=bool(r.get("confirmed", True)),
                source=str(r.get("source") or "parquet"),
            )
        )
    out.sort(key=lambda x: x.ts_us)
    return out


__all__ = [
    "ColdKlineReadError",
    "ColdKlineReadTimeout",
    "ColdKlineRow",
    "ParquetKlineReader",
    "months_between",
]
