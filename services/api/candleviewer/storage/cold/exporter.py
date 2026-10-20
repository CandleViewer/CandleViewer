"""Hot -> cold exporter — `21-database-schema.md` Sec.5.3's flow as code.

`export_partition` never drops the hot partition itself (that is E07-T05's
reaper, per this ticket's "Out of scope"); it only writes Parquet, verifies,
and records the manifest entry, returning an `ExportRun` the reaper can then
act on. The ordering invariant — file+checksum+manifest before any drop
decision — is enforced simply by this module never calling a drop.
"""

from __future__ import annotations

import asyncio
import re
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, Protocol

import pyarrow as pa
import structlog

from candleviewer.observability import spawn
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import (
    ManifestEntry,
    ManifestStore,
    SchemaRegistry,
    sha256_of,
)
from candleviewer.storage.cold.observability import (
    LoggingSystemEventSink,
    SystemEventSink,
    storage_export_bytes_total,
    storage_export_duration_seconds,
    storage_export_rows_total,
    storage_export_verify_failures_total,
)
from candleviewer.storage.cold.partition_lock import partition_write_lock
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.cold.writer import (
    DEFAULT_ROWS_PER_GROUP,
    MARKET_DATA_PROFILE,
    AtomicParquetWriter,
    add_provenance_columns,
    normalise_ts,
    sweep_stale_temps,
)
from candleviewer.storage.errors import StorageExportVerifyFailed, StorageSchemaDrift
from candleviewer.storage.models import ExportRun, StreamKind, TimeRange

_PART_RE = re.compile(r"^part-(\d{4})\.parquet$")

#: Default wall-clock bound for one partition export (C-2.18: every external
#: await is bounded). A symbol-day of trades at >=200 MB/s is far below this.
DEFAULT_EXPORT_TIMEOUT_S = 1800.0

_UTC_MICROS: Final = pa.timestamp("us", tz="UTC")

#: The columns a dataset's registered schema may gain (21 Sec.5.2, C-5.8), keyed by the dataset
#: key the registry uses (`StreamKind.value`), each with the Arrow type every part writes it as,
#: an all-NULL batch included. A column joins in the PR that ships its migration; an added column
#: missing here still fails the drift check closed. E26-T03 (QuestDB 0006): the book columns a
#: replay re-emits as recorded (24 Sec.13.7).
ALLOWED_ADDITIONS: Final[Mapping[str, Mapping[str, pa.DataType]]] = MappingProxyType(
    {
        StreamKind.ORDERBOOK_DELTA.value: MappingProxyType(
            {"prev_update_id": pa.int64(), "ts_match": _UTC_MICROS}
        ),
        StreamKind.ORDERBOOK_SNAPSHOT.value: MappingProxyType({"ts_match": _UTC_MICROS}),
    }
)
_NO_ADDITIONS: Final[Mapping[str, pa.DataType]] = MappingProxyType({})

#: `_check_drift` reads, decides and rewrites the one registry file every dataset shares; this
#: keeps two exports in one process from losing each other's registration.
_REGISTRY_LOCK = threading.Lock()


AFTER_PARQUET_WRITE = "AFTER_PARQUET_WRITE"
AFTER_CHECKSUM = "AFTER_CHECKSUM"
AFTER_MANIFEST = "AFTER_MANIFEST"

# Test-only crash breakpoints (E07-Q04): a chaos test registers a callable that
# raises/kills at the exact Sec.5.3 instruction boundary. No env var, flag or
# config can arm one: the registry is empty in every process and only
# `arm_test_hook` fills it, which refuses unless running under pytest.
_TEST_HOOKS: dict[str, Callable[[], None]] = {}
_HOOK_POINTS = frozenset({"AFTER_PARQUET_WRITE", "AFTER_CHECKSUM", "AFTER_MANIFEST"})


def arm_test_hook(name: str, hook: Callable[[], None]) -> None:
    """Register a crash hook; test processes only (pytest must be imported)."""
    if "pytest" not in sys.modules:
        raise RuntimeError("exporter test hooks are only available under pytest")
    if name not in _HOOK_POINTS:
        raise ValueError(f"unknown hook point {name!r}")
    _TEST_HOOKS[name] = hook


def _fire_hook(name: str) -> None:
    if not _TEST_HOOKS:
        return
    hook = _TEST_HOOKS.get(name)
    if hook is not None:
        hook()


def _log_worker_failure[T](fut: asyncio.Future[T]) -> None:
    """Logs the failure of a worker whose caller was cancelled: `shield` no longer watches it,
    so nothing else would retrieve it."""
    if not fut.cancelled() and (exc := fut.exception()) is not None:
        structlog.get_logger(__name__).error(
            "cold_export_worker_failed_after_cancel", error=type(exc).__name__
        )


async def _off_loop[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """`asyncio.to_thread`, but on cancellation wait for the worker thread to
    finish before re-raising, so cleanup never races a still-running write."""
    fut = spawn(asyncio.to_thread(fn, *args, **kwargs), name="cold-exporter-off-loop")
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        fut.add_done_callback(_log_worker_failure)
        await asyncio.wait([fut])
        raise


class HotTierSource(Protocol):
    """The minimal read surface the exporter needs from the hot tier — a
    `Protocol` so tests supply in-memory batches and this module never
    builds QuestDB SQL itself (see `questdb_source.QuestDbHotTierSource`)."""

    def iter_partition(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, batch_rows: int
    ) -> AsyncIterator[pa.Table]:
        """Rows for `(symbol, stream, rng)` ordered by `ts` then `price`, in
        batches of at most `batch_rows` rows (bounded memory)."""
        ...

    async def count_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> int:
        """`COUNT(*)` for the same predicate — the AC's exact row-count
        verification against the source."""
        ...


def _partition_key_values(
    symbol: str, stream: StreamKind, rng: TimeRange, *, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Derives partition key/value pairs from `(symbol, stream, rng)` for
    the streams this ticket exports (single-`dt` partitioned streams);
    streams needing extra keys (`bar_param`, `hour`, ...) pass them via
    `extra`."""
    dt = datetime.fromtimestamp(rng.start_us / 1_000_000, tz=UTC).strftime("%Y-%m-%d")
    values = {"symbol": symbol, "dt": dt}
    if extra:
        values.update(extra)
    return values


class ColdExporter:
    """Implements the Sec.5.3 export flow for one `(symbol, stream, rng)`
    partition at a time. Never decides *when* to export or drop the hot
    partition (E07-T05's reaper) — it exposes `export_partition` and
    `verify` only. The ordering invariant (file + checksum + row-count +
    manifest before any drop) holds because this module never drops.
    """

    def __init__(
        self,
        registry: DatasetRegistry,
        source: HotTierSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        rows_per_group: int = DEFAULT_ROWS_PER_GROUP,
        events: SystemEventSink | None = None,
        timeout_s: float = DEFAULT_EXPORT_TIMEOUT_S,
    ) -> None:
        self._registry = registry
        self._source = source
        self._clock = clock
        self._rows_per_group = rows_per_group
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._timeout_s = timeout_s

    def _paths(
        self, symbol: str, stream: StreamKind, rng: TimeRange, extra: dict[str, str] | None
    ) -> ColdPaths:
        values = _partition_key_values(symbol, stream, rng, extra=extra)
        return self._registry.resolve_partition(stream, partition_values=values)

    async def export_partition(
        self,
        symbol: str,
        stream: StreamKind,
        rng: TimeRange,
        *,
        partition_extra: dict[str, str] | None = None,
    ) -> ExportRun:
        """Sec.5.3 steps E->I, bounded by `timeout_s`. Idempotent: if the
        manifest already holds an entry for exactly this range whose file is
        present, the call is a no-op returning that run. Otherwise stale
        `.tmp` files and unmanifested part files (crash leftovers) are
        removed, the partition is streamed to a new part file, and the
        manifest entry is written last (crash ordering: file without
        manifest is recoverable; manifest without file cannot occur)."""
        started = time.perf_counter()
        part_dir = self._paths(symbol, stream, rng, partition_extra).partition_dir
        async with asyncio.timeout(self._timeout_s), partition_write_lock(part_dir):
            run = await self._export(symbol, stream, rng, partition_extra)
        storage_export_duration_seconds.labels(stream=stream.value).observe(
            time.perf_counter() - started
        )
        return run

    async def _export(
        self,
        symbol: str,
        stream: StreamKind,
        rng: TimeRange,
        extra: dict[str, str] | None,
    ) -> ExportRun:
        paths = self._paths(symbol, stream, rng, extra)
        store = ManifestStore(paths.manifests_dir)
        rel_dir = paths.partition_dir.relative_to(paths.root).as_posix()

        existing = await asyncio.to_thread(store.read, paths.partition_dir, paths.root)
        for entry in existing:
            same_range = (entry.range_start_us, entry.range_end_us) == (rng.start_us, rng.end_us)
            if same_range and (paths.partition_dir / entry.file).is_file():
                structlog.get_logger(__name__).info(
                    "cold_export_skip_already_done", partition=rel_dir
                )
                return ExportRun(
                    run_id=entry.export_run_id,
                    symbol=symbol,
                    stream=stream,
                    partition_range=rng,
                    row_count=entry.row_count,
                    verified=False,
                )

        await asyncio.to_thread(_reconcile_orphans, paths, existing)

        source_count = await self._source.count_partition(symbol, stream, rng)
        run_id = str(uuid.uuid4())
        exported_at_us = int(self._clock().timestamp() * 1_000_000)
        used = {int(m.group(1)) for e in existing if (m := _PART_RE.fullmatch(e.file))}
        file_name = f"part-{(max(used) + 1) if used else 0:04d}.parquet"
        dest = paths.partition_dir / file_name

        writer: AtomicParquetWriter | None = None
        schema_registry = SchemaRegistry(paths.schema_registry_path)
        additions = ALLOWED_ADDITIONS.get(stream.value, _NO_ADDITIONS)
        try:
            async for raw in self._source.iter_partition(
                symbol, stream, rng, batch_rows=self._rows_per_group
            ):
                # Typed first: a retyped column fails before the registry can be widened.
                raw = _conform_additions(raw, stream.value, additions)
                if writer is None:
                    await asyncio.to_thread(
                        _check_drift, schema_registry, stream.value, frozenset(raw.column_names)
                    )
                batch = add_provenance_columns(
                    normalise_ts(raw),
                    export_run_id=run_id,
                    exported_at_us=exported_at_us,
                    source="questdb",
                )
                if writer is None:
                    writer = AtomicParquetWriter(
                        dest,
                        batch.schema,
                        profile=MARKET_DATA_PROFILE,
                        rows_per_group=self._rows_per_group,
                    )
                await _off_loop(writer.write, batch)
            written = writer.rows_written if writer is not None else 0
            if writer is None or written != source_count:
                raise StorageExportVerifyFailed(
                    f"{rel_dir}: exported {written} rows, source COUNT(*) {source_count}"
                )
            row_count = await _off_loop(writer.commit)
            _fire_hook(AFTER_PARQUET_WRITE)
        except BaseException as exc:
            if writer is not None:
                await _off_loop(writer.abort)
            if isinstance(exc, StorageExportVerifyFailed):
                storage_export_verify_failures_total.inc()
                storage_export_rows_total.labels(stream=stream.value, result="verify_failed").inc()
                await self._events.emit(
                    "CRITICAL",
                    "STORAGE_EXPORT_VERIFY_FAILED",
                    {"partition": rel_dir, "stream": stream.value, "source_count": source_count},
                )
            raise

        file_sha = await asyncio.to_thread(sha256_of, dest)
        _fire_hook(AFTER_CHECKSUM)
        entry = ManifestEntry(
            file=file_name,
            sha256=file_sha,
            row_count=row_count,
            source_table=stream.value,
            export_run_id=run_id,
            exported_at_us=exported_at_us,
            range_start_us=rng.start_us,
            range_end_us=rng.end_us,
        )
        await asyncio.to_thread(store.append_reconciled, paths.partition_dir, paths.root, entry)
        _fire_hook(AFTER_MANIFEST)
        storage_export_rows_total.labels(stream=stream.value, result="ok").inc(row_count)
        storage_export_bytes_total.labels(stream=stream.value).inc(dest.stat().st_size)
        structlog.get_logger(__name__).info(
            "cold_export_done", partition=rel_dir, file=file_name, rows=row_count
        )
        return ExportRun(
            run_id=run_id,
            symbol=symbol,
            stream=stream,
            partition_range=rng,
            row_count=row_count,
            verified=False,
        )

    async def verify(
        self,
        symbol: str,
        stream: StreamKind,
        rng: TimeRange,
        *,
        partition_extra: dict[str, str] | None = None,
    ) -> bool:
        """Re-verify every manifest entry for this partition (SR-094);
        mismatching files are quarantined and a CRITICAL event raised."""
        paths = self._paths(symbol, stream, rng, partition_extra)
        return await verify_partition(paths, self._events)


def _reconcile_orphans(paths: ColdPaths, existing: list[ManifestEntry]) -> None:
    """Crash recovery: remove `.tmp` leftovers and part files the manifest
    does not reference (written, then killed before the manifest step). They
    are re-exported, so no rows are lost and the manifest ends up with a
    single entry for the range."""
    sweep_stale_temps(paths.partition_dir)
    known = {e.file for e in existing}
    if paths.partition_dir.is_dir():
        for part in paths.partition_dir.glob("part-*.parquet"):
            if part.name not in known:
                part.unlink(missing_ok=True)


def _check_drift(registry: SchemaRegistry, dataset_key: str, incoming: frozenset[str]) -> None:
    """Fail closed on any column-set difference against `schema-registry.json` (Sec.5.2) but
    one: a strict superset whose added columns are all listed for the dataset in
    `ALLOWED_ADDITIONS` is registered as its new column set, and the export goes on. The first
    export registers the schema."""
    with _REGISTRY_LOCK:
        registered = registry.columns_for(dataset_key)
        if registered is None:
            registry.register(dataset_key, incoming)
            return
        if incoming == registered:
            return
        added = incoming - registered
        missing = registered - incoming
        if missing or not added <= ALLOWED_ADDITIONS.get(dataset_key, _NO_ADDITIONS).keys():
            raise StorageSchemaDrift(
                f"{dataset_key}: schema drift vs schema-registry.json "
                f"(added={sorted(added)}, missing={sorted(missing)})"
            )
        registry.register(dataset_key, incoming)
    structlog.get_logger(__name__).info(
        "cold_export_schema_widened", dataset=dataset_key, added=sorted(added)
    )


def _conformable(found: pa.DataType, declared: pa.DataType) -> bool:
    """Arrow `null` (an all-NULL batch), or a timestamp of the declared unit in any zone."""
    if pa.types.is_null(found):
        return True
    timestamps = pa.types.is_timestamp(found) and pa.types.is_timestamp(declared)
    return bool(timestamps and found.unit == declared.unit)


def _conform_additions(
    table: pa.Table, dataset_key: str, additions: Mapping[str, pa.DataType]
) -> pa.Table:
    """Give every allowed-addition column `table` holds its declared type: a batch where the
    column is all NULL arrives as Arrow `null`, and PGWire hands a QuestDB TIMESTAMP back tz-naive
    (UTC). Any other type is a retype and fails closed (`StorageSchemaDrift`, naming no value)."""
    for name, declared in additions.items():
        if name not in table.column_names:
            continue
        column = table.column(name)
        if column.type == declared:
            continue
        if not _conformable(column.type, declared):
            raise StorageSchemaDrift(
                f"{dataset_key}: column {name!r} is {column.type}, not {declared}"
            )
        index = table.column_names.index(name)
        table = table.set_column(index, pa.field(name, declared), column.cast(declared))
    return table
