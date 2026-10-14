"""`RecordedStreamReader` and `ManifestCoverage` over the Parquet cold tier via DuckDB (E26-T02).

Partitions are resolved only through `DatasetRegistry`, from `(StreamKind, symbol, time)`. A
caller never supplies a path (SR-097). Every file a manifest names must be a `part-NNNN.parquet`
that, after symlink resolution, still lies inside its own partition and inside `CV_COLD_ROOT`, and
DuckDB is handed that resolved path; the DuckDB connection itself may open nothing outside the
cold root (`allowed_directories`, external access off, configuration locked). So neither a
crafted manifest entry nor a planted or swapped symlink can widen the read. A partition is
verified (manifest SHA-256 and row count, `verify_partition`) the first time it is read and
whenever a file's size, mtime or ctime changes (ctime: a rewrite that restores size and mtime
still shows). A failure fails the read with a typed error, never a silently partial window, and
a window spanning more partitions than one read may open is refused before any is listed.
`archived` reports the manifests' coverage, which `source_tier="auto"` routes on: roll-off
writes a manifest before it may drop the hot day (21 Sec.5.3).

DuckDB runs on the reader's own pool of `max_concurrency` threads, under a semaphore with as
many slots (C-2.18), with a memory limit; the worker opens and closes its connection, so the
event loop never blocks on DuckDB (C-2.17). The read waits on the pool's plain future, which
nothing but the read can cancel, so neither cancelling the read nor event-loop teardown can lose
a scan still queued for a thread. On the scan's deadline (below the replay merge's) or a
cancellation, the read stops the scan and holds its slot until the scan's thread has returned: a
stop flag the worker checks before connecting and before the statement, and an interrupt
repeated until then, since DuckDB drops one that arrives before a statement starts. Abandoned
scans never pile up. `shutdown()` refuses new scans and drops queued ones, whose reads fail
typed. Rows map through `event_from_row`, the mapping the hot tier shares, inside the worker.
They come back ordered by `ts`, then part file, then row: the storage order the replay merge's
"copy read last wins" dedup relies on when a re-export left a row in two parts (21 Sec.5.3).
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import duckdb

from candleviewer.domain.sql_names import EPOCH
from candleviewer.observability.context import executor_future
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
    covered_parts,
    event_from_row,
    order_key,
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
#: The anchor lookup reads the newest 16 snapshots, newest copy first, and orders those sharing
#: the latest instant by `order_key`, as the hot tier does (24 Sec.13.7).
_ANCHOR_ROWS: Final = 16
_ANCHOR_SQL: Final = (
    _SOURCE + "WHERE depth = $depth AND ts >= make_timestamptz($lo::BIGINT) "
    "AND ts <= make_timestamptz($hi::BIGINT) "
    "ORDER BY ts DESC, filename DESC, file_row_number DESC LIMIT 16"
)
#: Below the replay merge's 30 s storage deadline, so a slow scan fails here, typed, first.
DEFAULT_TIMEOUT_S: Final = 20.0
#: How often a stopping read interrupts its scan again until the scan's thread has returned.
_STOP_POLL_S: Final = 0.1
_US_PER_DAY: Final = 24 * _US_PER_HOUR


class ColdReplayReadError(StorageTierUnavailable):
    """The cold read was refused or failed: a path outside the registry, a manifest that names
    a foreign file, a partition that failed verification, or a DuckDB error."""

    code = "COLD_REPLAY_READ_ERROR"


class ColdReplayReadTimeout(StorageTierUnavailable):
    """The DuckDB scan exceeded its deadline and was interrupted."""

    code = "COLD_REPLAY_READ_TIMEOUT"


def _too_many() -> ColdReplayReadError:
    return ColdReplayReadError("cold read spans too many partitions")


def _moment(us: int) -> datetime:
    try:
        return EPOCH + timedelta(microseconds=us)
    except OverflowError:
        raise ColdReplayReadError("cold read window is out of range") from None


def _months(lo_us: int, hi_us: int) -> list[str]:
    """`YYYY-MM` of every month overlapping `[lo_us, hi_us)`, refused rather than cut when there
    are more than one read may open (`months_between` keeps only the newest ones)."""
    if hi_us - lo_us > _MAX_PARTITIONS * 31 * _US_PER_DAY:
        raise _too_many()
    first, last = _moment(lo_us), _moment(hi_us - 1)
    expected = (last.year - first.year) * 12 + last.month - first.month + 1
    months = months_between(lo_us, hi_us)
    if len(months) != expected or expected > _MAX_PARTITIONS:
        raise _too_many()
    return months


def _time_keys(template: tuple[str, ...], lo_us: int, hi_us: int) -> list[dict[str, str]]:
    """Partition keys of every `dt`/`hour`/`ym`/`y` partition overlapping `[lo_us, hi_us)`. More
    than `_MAX_PARTITIONS` are refused before any key is built; an empty window names none."""
    if hi_us <= lo_us:
        return []
    if "ym" in template:
        return [{"ym": ym} for ym in _months(lo_us, hi_us)]
    if "y" in template:  # `_moment` bounds a year window to the calendar
        first, last = _moment(lo_us).year, _moment(hi_us - 1).year
        if last - first + 1 > _MAX_PARTITIONS:
            raise _too_many()
        return [{"y": f"{year:04d}"} for year in range(first, last + 1)]
    step = _US_PER_HOUR if "hour" in template else _US_PER_DAY
    at = lo_us - lo_us % step
    if -(-(hi_us - at) // step) > _MAX_PARTITIONS:
        raise _too_many()
    keys: list[dict[str, str]] = []
    while at < hi_us:
        moment = _moment(at)
        key = {"dt": moment.strftime("%Y-%m-%d")}
        if "hour" in template:
            key["hour"] = moment.strftime("%H")
        keys.append(key)
        at += step
    return keys


def _contained(paths: ColdPaths, file_name: object) -> Path:
    """A manifest's file, resolved: refused unless it is a part file that lies inside its own
    partition and inside the root. The resolved path is what DuckDB opens, so a symlink swapped
    after this check is not followed. The refusal names no path, and carries none in its chain."""
    if not isinstance(file_name, str) or not _PART_FILE.fullmatch(file_name):
        raise ColdReplayReadError("a cold manifest names a file that is not a part file")
    try:
        resolved = (paths.partition_dir / file_name).resolve(strict=True)
        resolved.relative_to(paths.partition_dir.resolve(strict=True))
        resolved.relative_to(paths.root)
    except (OSError, RuntimeError, ValueError):  # RuntimeError: a symlink loop on 3.12
        raise ColdReplayReadError(
            "a cold part file is missing or escapes its partition or the cold root"
        ) from None
    return resolved


@contextmanager
def _typed_listing() -> Iterator[None]:
    """Registry refusals and filesystem errors while listing partitions, and a manifest that is
    not text, become one typed error that names no path and carries none in its chain."""
    try:
        yield
    except (DatasetNotRegistered, ManifestCorrupt, UnicodeDecodeError):
        raise ColdReplayReadError("the cold registry refused the read (SR-097)") from None
    except OSError as exc:
        raise ColdReplayReadError(f"cold partition listing failed: {type(exc).__name__}") from None


def _stamps(files: list[Path]) -> dict[Path, tuple[int, int, int]]:
    """Size, mtime and ctime of each file: a change of any one re-verifies its partition."""
    stamps: dict[Path, tuple[int, int, int]] = {}
    for f in files:
        st = f.stat()
        stamps[f] = (st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    return stamps


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        ":memory:", config={"memory_limit": _MEMORY_LIMIT, "threads": str(_THREADS)}
    )


class _Scan:
    """One DuckDB scan, run on a pool thread, and the read's handle on it.

    The worker connects, locks the connection down to the cold root, runs the statement, maps
    the rows and closes the connection. The read stops it with `stop` (checked before
    connecting and before the statement) and `interrupt()` (repeated, never blocking the event
    loop)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.stop = threading.Event()
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None

    def interrupt(self) -> None:
        """Event loop: interrupt the running statement, if any; a no-op while the worker is
        connecting or closing (the stop flag covers those)."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._con is not None:
                with suppress(duckdb.Error):
                    self._con.interrupt()
        finally:
            self._lock.release()

    def _checkpoint(self) -> None:
        if self.stop.is_set():
            raise ColdReplayReadError("cold replay read stopped")

    def run(self, sql: str, params: dict[str, object], stream: StreamKind) -> list[RecordedEvent]:
        """Worker thread: the scan, start to end. A DuckDB failure, at connect too, is typed
        and carries no chain: its text may name a path."""
        self._checkpoint()
        try:
            con = _connect()
            with self._lock:
                self._con = con
            try:
                con.execute("SET TimeZone = 'UTC'")
                con.execute("SET allowed_directories = $dirs", {"dirs": [self.root.as_posix()]})
                con.execute("SET enable_external_access = false")
                con.execute("SET lock_configuration = true")
                self._checkpoint()
                rows = con.execute(sql, params).to_arrow_table().to_pylist()
            finally:
                with self._lock:
                    self._con = None
                con.close()
        except duckdb.Error as exc:
            raise ColdReplayReadError(f"cold replay read failed: {type(exc).__name__}") from None
        return [event_from_row(stream, row) for row in rows]


async def _stop(scan: _Scan, job: asyncio.Future[list[RecordedEvent]]) -> None:
    """Stop `scan` and wait until its thread has returned, interrupting it again every
    `_STOP_POLL_S` (DuckDB drops an interrupt that arrives before a statement starts), through
    further cancellations: the last is re-raised once the thread has returned. A scan still
    queued for a thread runs, sees `stop` and returns without connecting."""
    scan.stop.set()
    cancelled: asyncio.CancelledError | None = None
    while not job.done():
        scan.interrupt()
        try:
            await asyncio.wait([job], timeout=_STOP_POLL_S)  # never cancels the job
        except asyncio.CancelledError as exc:
            cancelled = exc
    if cancelled is not None:
        raise cancelled


def _retrieve(job: asyncio.Future[list[RecordedEvent]]) -> None:
    """Mark a scan's outcome as seen: the read raises its own error for it."""
    if not job.cancelled():
        job.exception()


class ParquetRecordedReader:
    """Cold-tier `RecordedStreamReader` and `ManifestCoverage`: Parquet partitions under
    `CV_COLD_ROOT`, via DuckDB. Its owner calls `shutdown()` when the process stops."""

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
        workers = max(1, max_concurrency)
        self._sem = asyncio.Semaphore(workers)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cv-cold-replay")
        self._verified: dict[Path, tuple[int, int, int]] = {}

    def shutdown(self) -> None:
        """Refuse new scans and drop queued ones, whose reads fail typed; a running scan
        finishes, or is stopped by its read on a deadline or a cancellation."""
        self._pool.shutdown(wait=False, cancel_futures=True)

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
        if len(found) == _ANCHOR_ROWS and found[0].ts_us == found[-1].ts_us:
            raise ColdReplayReadError(
                "more snapshots share one instant than an anchor lookup reads"
            )
        return max(found, key=order_key, default=None)  # the first maximal: the newest copy

    async def archived(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[TimeRange]:
        """`ManifestCoverage`: the spans of `rng` the manifests' entries cover."""
        with _typed_listing():
            spans = await asyncio.to_thread(self._manifested, symbol, stream, rng)
        return covered_parts(spans, rng)

    def _manifested(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[tuple[int, int]]:
        """Worker thread: the time range of every manifest entry of the partitions of `rng`."""
        spans: list[tuple[int, int]] = []
        for paths in self._partitions(symbol, stream, rng.start_us, rng.end_us):
            entries = ManifestStore(paths.manifests_dir).read(paths.partition_dir, paths.root)
            spans += [(e.range_start_us, e.range_end_us) for e in entries]
        return spans

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
            months = set(_months(lo_us, hi_us)) if hi_us > lo_us else set()
            listed = self._registry.manifested_partitions(stream, symbol)
            return [p for p in listed if p.partition_dir.name.removeprefix("ym=") in months]
        keys = _time_keys(template, lo_us, hi_us)
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
            except StorageExportVerifyFailed:
                raise ColdReplayReadError("a cold partition failed verification") from None
            self._verified.update(stamps)
        return [f.as_posix() for f in files]

    async def _query(
        self, sql: str, params: dict[str, object], stream: StreamKind
    ) -> list[RecordedEvent]:
        async with self._sem:
            scan = _Scan(self._registry.root)
            try:
                job = executor_future(self._pool, scan.run, sql, params, stream)
            except RuntimeError:  # the pool is shut down
                raise ColdReplayReadError("the cold reader is shut down") from None
            job.add_done_callback(_retrieve)
            try:
                async with asyncio.timeout(self._timeout_s):
                    await asyncio.wait([job])  # never cancels the job
            except BaseException as exc:
                # Deadline or cancellation: stop the scan and wait for its thread, so this slot
                # (and DuckDB's memory) is freed only once the scan has ended.
                await _stop(scan, job)
                if isinstance(exc, TimeoutError):
                    raise ColdReplayReadTimeout(
                        f"cold replay read exceeded {self._timeout_s}s"
                    ) from exc
                raise
            if job.cancelled():  # a queued scan that `shutdown()` dropped
                raise ColdReplayReadError("the cold reader is shut down")
            return job.result()
