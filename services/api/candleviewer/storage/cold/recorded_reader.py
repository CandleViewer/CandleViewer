"""`RecordedStreamReader` over the Parquet cold tier via DuckDB (E26-T02).

Partitions are resolved only through `DatasetRegistry`, from `(StreamKind, symbol, time)`. A
caller never supplies a path (SR-097). Every file a manifest names must be a `part-NNNN.parquet`
that still lies inside `CV_COLD_ROOT` after symlink resolution, and DuckDB is handed that resolved
path, so neither a crafted manifest entry nor a planted or swapped symlink can widen the read. A
partition is verified (manifest SHA-256 and row count, `verify_partition`) the first time it is
read and whenever a file's size or mtime changes. A failure fails the read with a typed error,
never a silently partial window.

DuckDB runs in a worker thread under a semaphore (C-2.18) with a memory limit. On its deadline
(below the replay merge's), a cancellation or any failure, the scan is interrupted and its
worker awaited before the slot is released, so abandoned scans never pile up. Rows map through
`event_from_row`, the mapping the hot tier shares, inside the worker, so the event loop never
pays for it. They come back ordered by `ts`, then part file, then row: the storage order the
replay merge's "copy read last wins" dedup relies on when a re-export left a row in two parts
(21 Sec.5.3).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Final

import duckdb

from candleviewer.domain.sql_names import EPOCH
from candleviewer.observability import spawn
from candleviewer.storage.cold.kline_reader import months_between
from candleviewer.storage.cold.layout import (
    ColdPaths,
    DatasetNotRegistered,
    DatasetRegistry,
    partition_template,
)
from candleviewer.storage.cold.manifest import ManifestCorrupt, ManifestStore
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import StorageExportVerifyFailed, StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    BOOK_STREAMS,
    RecordedEvent,
    RecordedQueryRejected,
    event_from_row,
)

_US_PER_HOUR: Final = 3_600_000_000
_MAX_PARTITIONS: Final = 1_000
_PART_FILE: Final = re.compile(r"^part-\d{4}\.parquet$")
_MEMORY_LIMIT: Final = "256MiB"
_THREADS: Final = 2
_SOURCE: Final = (
    "SELECT * REPLACE (epoch_us(ts) AS ts) FROM read_parquet($files, hive_partitioning = false, "
    "union_by_name = true, filename = true, file_row_number = true) "
)
_RANGE: Final = "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
_RANGE_SQL: Final = _SOURCE + _RANGE + "ORDER BY ts, filename, file_row_number LIMIT $n"
_BOOK_RANGE_SQL: Final = (
    _SOURCE + _RANGE + "AND depth = $depth ORDER BY ts, filename, file_row_number LIMIT $n"
)
_ANCHOR_SQL: Final = (
    _SOURCE + "WHERE depth = $depth AND ts >= make_timestamptz($lo::BIGINT) "
    "AND ts <= make_timestamptz($hi::BIGINT) "
    "ORDER BY ts DESC, filename DESC, file_row_number DESC LIMIT 1"
)
#: Below the replay merge's 30 s storage deadline, so a slow scan fails here, typed, first.
DEFAULT_TIMEOUT_S: Final = 20.0


class ColdReplayReadError(StorageTierUnavailable):
    """The cold read was refused or failed: a path outside the registry, a manifest that names
    a foreign file, a partition that failed verification, or a DuckDB error."""

    code = "COLD_REPLAY_READ_ERROR"


class ColdReplayReadTimeout(StorageTierUnavailable):
    """The DuckDB scan exceeded its deadline and was interrupted."""

    code = "COLD_REPLAY_READ_TIMEOUT"


def _time_keys(template: tuple[str, ...], lo_us: int, hi_us: int) -> list[dict[str, str]]:
    """Partition keys of every `dt`/`hour`/`ym`/`y` partition overlapping `[lo_us, hi_us)`."""
    if "ym" in template:
        return [{"ym": ym} for ym in months_between(lo_us, hi_us)]
    if "y" in template:
        first = (EPOCH + timedelta(microseconds=lo_us)).year
        last = (EPOCH + timedelta(microseconds=hi_us - 1)).year
        return [{"y": f"{year:04d}"} for year in range(first, last + 1)]
    step = _US_PER_HOUR if "hour" in template else 24 * _US_PER_HOUR
    keys: list[dict[str, str]] = []
    at = lo_us - lo_us % step
    while at < hi_us:
        moment = EPOCH + timedelta(microseconds=at)
        key = {"dt": moment.strftime("%Y-%m-%d")}
        if "hour" in template:
            key["hour"] = moment.strftime("%H")
        keys.append(key)
        at += step
    return keys


def _contained(paths: ColdPaths, file_name: str) -> Path:
    """A manifest's file, resolved: refused unless it is a part file inside the root. The
    resolved path is what DuckDB opens, so a symlink swapped after this check is not followed."""
    if not _PART_FILE.fullmatch(file_name):
        raise ColdReplayReadError("a cold manifest names a file that is not a part file")
    try:
        resolved = (paths.partition_dir / file_name).resolve(strict=True)
        resolved.relative_to(paths.root)
    except (OSError, ValueError) as exc:
        raise ColdReplayReadError("a cold part file is missing or escapes the cold root") from exc
    return resolved


@contextmanager
def _typed_listing() -> Iterator[None]:
    """Registry refusals and filesystem errors while listing partitions become one typed error."""
    try:
        yield
    except (DatasetNotRegistered, ManifestCorrupt) as exc:
        raise ColdReplayReadError("the cold registry refused the read (SR-097)") from exc
    except OSError as exc:
        raise ColdReplayReadError(f"cold partition listing failed: {type(exc).__name__}") from exc


def _stamps(files: list[Path]) -> dict[Path, tuple[int, int]]:
    return {f: (f.stat().st_size, f.stat().st_mtime_ns) for f in files}


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        ":memory:", config={"memory_limit": _MEMORY_LIMIT, "threads": str(_THREADS)}
    )


def _scan(
    con: duckdb.DuckDBPyConnection, sql: str, params: dict[str, object], stream: StreamKind
) -> list[RecordedEvent]:
    """Worker thread: run one scan and map its rows (the caller owns and closes `con`)."""
    try:
        con.execute("SET TimeZone = 'UTC'")
        rows = con.execute(sql, params).to_arrow_table().to_pylist()
    except duckdb.Error as exc:
        raise ColdReplayReadError(f"cold replay read failed: {type(exc).__name__}") from exc
    return [event_from_row(stream, row) for row in rows]


async def _settle(task: asyncio.Task[list[RecordedEvent]]) -> None:
    """Wait until an interrupted scan's worker has ended, through further cancellations (the
    last is re-raised once it has), and consume its outcome: the caller raises its own error."""
    cancelled: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError as exc:
            cancelled = exc
    if not task.cancelled():
        task.exception()
    if cancelled is not None:
        raise cancelled


class ParquetRecordedReader:
    """Cold-tier `RecordedStreamReader`: Parquet partitions under `CV_COLD_ROOT`, via DuckDB."""

    def __init__(
        self,
        registry: DatasetRegistry,
        *,
        events: SystemEventSink | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_concurrency: int = 2,
    ) -> None:
        self._registry = registry
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._timeout_s = timeout_s
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._verified: dict[Path, tuple[int, int]] = {}

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if isinstance(limit, bool) or limit < 1:  # the port's refusal, before any manifest read
            raise RecordedQueryRejected("limit must be an int >= 1")
        files = await self._files(symbol, stream, rng.start_us, rng.end_us)
        if not files:
            return []
        params: dict[str, object] = {
            "files": files,
            "lo": rng.start_us,
            "hi": rng.end_us,
            "n": limit,
        }
        sql = _RANGE_SQL
        if stream in BOOK_STREAMS:
            sql, params["depth"] = _BOOK_RANGE_SQL, depth
        return await self._query(sql, params, stream)

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        stream = StreamKind.ORDERBOOK_SNAPSHOT
        files = await self._files(symbol, stream, not_before_us, at_us + 1)
        if not files:
            return None
        params: dict[str, object] = {
            "files": files,
            "lo": not_before_us,
            "hi": at_us,
            "depth": depth,
        }
        found = await self._query(_ANCHOR_SQL, params, stream)
        return found[0] if found else None

    async def _files(self, symbol: str, stream: StreamKind, lo_us: int, hi_us: int) -> list[str]:
        with _typed_listing():
            partitions = await asyncio.to_thread(self._partitions, symbol, stream, lo_us, hi_us)
            files: list[str] = []
            for paths in partitions:
                files += await self._partition_files(paths)
        return files

    def _partitions(
        self, symbol: str, stream: StreamKind, lo_us: int, hi_us: int
    ) -> list[ColdPaths]:
        template = partition_template(stream)
        if "interval" in template:  # klines: one partition tree per interval
            months = set(months_between(lo_us, hi_us))
            listed = self._registry.manifested_partitions(stream, symbol)
            return [p for p in listed if p.partition_dir.name.removeprefix("ym=") in months]
        keys = _time_keys(template, lo_us, hi_us)
        if len(keys) > _MAX_PARTITIONS:
            raise ColdReplayReadError("cold read spans too many partitions")
        values = [{"symbol": symbol} | key for key in keys]
        return [self._registry.resolve_partition(stream, partition_values=v) for v in values]

    async def _partition_files(self, paths: ColdPaths) -> list[str]:
        store = ManifestStore(paths.manifests_dir)
        entries = await asyncio.to_thread(store.read, paths.partition_dir, paths.root)
        if not entries:
            return []
        files = await asyncio.to_thread(lambda: [_contained(paths, e.file) for e in entries])
        stamps = await asyncio.to_thread(_stamps, files)
        if any(self._verified.get(f) != stamps[f] for f in files):
            try:
                await verify_partition(paths, self._events)
            except StorageExportVerifyFailed as exc:
                raise ColdReplayReadError("a cold partition failed verification") from exc
            self._verified.update(stamps)
        return [f.as_posix() for f in files]

    async def _query(
        self, sql: str, params: dict[str, object], stream: StreamKind
    ) -> list[RecordedEvent]:
        async with self._sem:
            # Connect before the worker starts, and close only after it has ended, so
            # `interrupt()` always reaches a live scan.
            con = _connect()
            try:
                task = spawn(asyncio.to_thread(_scan, con, sql, params, stream), name="cold-replay")
                try:
                    async with asyncio.timeout(self._timeout_s):
                        return await asyncio.shield(task)
                except BaseException as exc:
                    # Deadline, cancellation or failure: stop the scan and wait for its worker,
                    # so this slot (and DuckDB's memory) is freed only once the scan has ended.
                    if not task.done():
                        con.interrupt()
                    await _settle(task)
                    if isinstance(exc, TimeoutError):
                        raise ColdReplayReadTimeout(
                            f"cold replay read exceeded {self._timeout_s}s"
                        ) from exc
                    raise
            finally:
                con.close()
