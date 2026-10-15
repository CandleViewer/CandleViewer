"""Storage-side adapters for the nightly roll-off (E16-T05).

The recorder's `RollOffJob` (M11) may not import a storage driver (ADR-0003),
so everything that touches pyarrow / QuestDB lives here behind small ports:

* `QuestDbHotPartitions` — closed-day inventory, symbols per day, and the
  `ALTER TABLE ... DROP PARTITION LIST` (table from the closed allowlist via
  `checked_identifier`, the date literal validated before `sql_string_literal`),
  then a wall-clock-bounded wait until QuestDB has applied it (WAL DDL is async).
* `ColdArchiver` — orchestrates the existing `ColdExporter` (never forked) and
  adds the read-back verification the ticket requires: the written file is
  re-read and its row count AND a canonical content digest must equal the hot
  source's, on top of the manifest SHA-256 check (`verify_partition`). A
  mismatch quarantines the file (with a reason sidecar), raises a CRITICAL
  `archive.verification_failed` event and reports `verified=False`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import structlog

from candleviewer.domain.sql_names import column_identifier, ts_param
from candleviewer.observability.metrics import Counter, Gauge
from candleviewer.storage.cold.compactor import IdleGuard
from candleviewer.storage.cold.exporter import ColdExporter, HotTierSource
from candleviewer.storage.cold.layout import (
    ColdPaths,
    DatasetNotRegistered,
    DatasetRegistry,
    partition_template,
)
from candleviewer.storage.cold.manifest import (
    QUARANTINE_DIR,
    ManifestEntry,
    ManifestStore,
    sha256_of,
)
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.partition_lock import partition_write_lock
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.cold.watermarks import ArchiveOutcome
from candleviewer.storage.cold.writer import (
    MARKET_DATA_PROFILE,
    normalise_ts,
    write_parquet_file,
)
from candleviewer.storage.errors import (
    DropNotAppliedReason,
    StorageExportVerifyFailed,
    StoragePartitionDropNotApplied,
)
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.natural_keys import TABLE_BY_STREAM
from candleviewer.storage.questdb.reader import PgWireConnection
from candleviewer.storage.sql_identifiers import checked_identifier, sql_string_literal

US_PER_DAY = 86_400_000_000
_US_PER_HOUR = 3_600_000_000
#: Wall clock for the whole "drop applied" wait, every poll included. Generous on purpose: a WAL
#: backlog (bulk import, E16-T10) must not read as a failure.
DROP_APPLY_TIMEOUT_S = 120.0
DROP_POLL_MIN_S = 0.02
DROP_POLL_MAX_S = 0.2
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROVENANCE = frozenset({"_export_run_id", "_exported_at", "_source"})
_DIGEST_ROWS = 8192
VERIFICATION_FAILED = "archive_verification_failed"
WRITE_FAILED = "archive_write_failed"


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


storage_rolloff_quarantined_total = Counter(
    "storage_rolloff_quarantined_total", "Roll-off files quarantined.", ["reason"]
)
storage_quarantine_bytes = Gauge("storage_quarantine_bytes", "Bytes under the cold _quarantine/.")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _tree_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.is_dir() else 0


def day_name(day_start_us: int) -> str:
    return datetime.fromtimestamp(day_start_us / 1_000_000, tz=UTC).strftime("%Y-%m-%d")


def _hot_table(stream: StreamKind) -> str:
    try:
        return checked_identifier(TABLE_BY_STREAM[stream])
    except KeyError as exc:
        raise DatasetNotRegistered(f"no hot-tier table for {stream!r}") from exc


class CanonicalDigest:
    """SHA-256 over Arrow IPC of fixed-size row chunks in a fixed column order,
    so the digest depends only on the rows — not on how they were batched."""

    def __init__(self, columns: list[str], schema: pa.Schema) -> None:
        self._columns = columns
        self._schema = schema
        self._hash = hashlib.sha256()
        self._buf: pa.Table | None = None
        self.rows = 0

    def _emit(self, chunk: pa.Table) -> None:
        chunk = chunk.take(pa.array(range(chunk.num_rows), type=pa.int64())).combine_chunks()
        for batch in chunk.to_batches():
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, batch.schema) as writer:
                writer.write_batch(batch)
            self._hash.update(sink.getvalue().to_pybytes())

    def update(self, table: pa.Table) -> None:
        canon = normalise_ts(table).select(self._columns).cast(self._schema)
        self.rows += canon.num_rows
        self._buf = canon if self._buf is None else pa.concat_tables([self._buf, canon])
        while self._buf.num_rows >= _DIGEST_ROWS:
            self._emit(self._buf.slice(0, _DIGEST_ROWS))
            self._buf = self._buf.slice(_DIGEST_ROWS)

    def hexdigest(self) -> str:
        if self._buf is not None and self._buf.num_rows:
            self._emit(self._buf)
            self._buf = None
        return self._hash.hexdigest()


_TRUTHY = frozenset({"true", "t", "1"})


def _as_int(value: object) -> int | None:
    try:
        return int(str(value))
    except ValueError:
        return None


def _emptied(row: dict[str, object]) -> bool:
    """A listed partition that holds nothing (QuestDB keeps a dropped one listed until purge).

    Needs positive evidence, so a missing column never reads as "dropped": zero rows, or an
    explicit NULL `minTimestamp`.
    """
    return _as_int(row.get("numRows")) == 0 or (
        "minTimestamp" in row and row["minTimestamp"] is None
    )


#: Cheap value column per hot table for the pre-drop fingerprint.
_FINGERPRINT_COLUMN: dict[StreamKind, str] = {
    StreamKind.TRADES: "size",
    StreamKind.ORDERBOOK_DELTA: "size",
    StreamKind.ORDERBOOK_SNAPSHOT: "update_id",
    StreamKind.TICKERS: "last_price",
    StreamKind.LIQUIDATIONS: "size",
}


class QuestDbHotPartitions:
    """Hot-tier inventory and partition drop over PGWire (every await bounded)."""

    def __init__(
        self,
        connection: PgWireConnection,
        *,
        timeout_s: float = 60.0,
        apply_timeout_s: float = DROP_APPLY_TIMEOUT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._conn = connection
        self._timeout_s = timeout_s
        self._apply_timeout_s = apply_timeout_s
        self._sleep = sleep
        self._clock = clock

    async def _fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        async with asyncio.timeout(self._timeout_s):
            return await self._conn.fetch(sql, *params)

    async def closed_days(self, stream: StreamKind, before_us: int) -> list[int]:
        """Start (UTC µs) of every DAY partition that ends at or before `before_us`."""
        # Table from the TABLE_BY_STREAM allowlist, emitted as an escaped literal.
        literal = sql_string_literal(_hot_table(stream))
        sql = f"SELECT name FROM table_partitions({literal})"  # noqa: S608  # nosec B608 - allowlisted
        days: list[int] = []
        for row in await self._fetch(sql):
            name = str(row.get("name", ""))
            if not _DATE_RE.fullmatch(name):
                continue
            start = int(datetime.strptime(name, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
            start_us = start * 1_000_000
            if start_us + US_PER_DAY <= before_us:
                days.append(start_us)
        return sorted(days)

    async def symbols_in(self, stream: StreamKind, rng: TimeRange) -> list[str]:
        return sorted(await self.row_counts(stream, rng))

    async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
        table = _hot_table(stream)
        sql = f"SELECT symbol, count() AS n FROM {table} WHERE ts >= $1 AND ts < $2"  # noqa: S608  # nosec B608 - table from TABLE_BY_STREAM allowlist via checked_identifier
        rows = await self._fetch(sql, ts_param(rng.start_us), ts_param(rng.end_us))
        return {str(r["symbol"]): int(str(r["n"])) for r in rows if r.get("symbol")}

    async def snapshot(self, stream: StreamKind, rng: TimeRange) -> dict[str, tuple[int, str]]:
        table = _hot_table(stream)
        value = column_identifier(_FINGERPRINT_COLUMN[stream])
        sql = (
            f"SELECT symbol, count() AS n, max(ts) AS hi, sum({value}) AS v FROM {table} "  # noqa: S608  # nosec B608 - allowlisted table/column via checked identifiers
            "WHERE ts >= $1 AND ts < $2"
        )
        rows = await self._fetch(sql, ts_param(rng.start_us), ts_param(rng.end_us))
        return {
            str(r["symbol"]): (int(str(r["n"])), f"{r.get('hi')}|{r.get('v')}")
            for r in rows
            if r.get("symbol")
        }

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
        table = _hot_table(stream)
        name = day_name(day_start_us)
        if not _DATE_RE.fullmatch(name):  # pragma: no cover - strftime guarantees the shape
            raise ValueError("bad partition name")
        # Allowlisted table via checked_identifier; day escaped by sql_string_literal.
        stmt = f"ALTER TABLE {table} DROP PARTITION LIST " + sql_string_literal(name)
        await self._fetch(stmt)
        await self._await_dropped(table, name)

    async def _await_dropped(self, table: str, name: str) -> None:
        """WAL tables apply DDL asynchronously: return only once the day is gone, else raise.

        Gone = absent from `table_partitions`, or listed but emptied (`_emptied`). A suspended WAL
        can never apply the drop: fail fast. `apply_timeout_s` bounds the whole wait, every poll
        included (a hung query too). The DROP is never re-issued; a failure is never success.
        """
        literal = sql_string_literal(table)
        sql = f"SELECT name, numRows, minTimestamp FROM table_partitions({literal})"  # noqa: S608  # nosec B608 - allowlisted table via checked_identifier, escaped by sql_string_literal; the day is matched in Python
        start, delay = self._clock(), DROP_POLL_MIN_S
        try:
            async with asyncio.timeout(self._apply_timeout_s):
                while True:
                    rows = await self._fetch(sql)
                    if rows and not any(r.get("name") for r in rows):
                        raise self._not_applied(table, name, "unexpected_shape", start)
                    if not any(str(r.get("name")) == name and not _emptied(r) for r in rows):
                        return
                    if await self._wal_suspended(table):
                        raise self._not_applied(table, name, "suspended", start)
                    if self._clock() - start >= self._apply_timeout_s:
                        raise self._not_applied(table, name, "timeout", start)
                    await self._sleep(delay)
                    delay = min(delay * 2, DROP_POLL_MAX_S)
        except TimeoutError:
            raise self._not_applied(table, name, "timeout", start) from None

    async def _wal_suspended(self, table: str) -> bool:
        rows = await self._fetch("SELECT suspended FROM wal_tables() WHERE name = $1", table)
        return any(str(r.get("suspended")).lower() in _TRUTHY for r in rows)

    def _not_applied(
        self, table: str, name: str, reason: DropNotAppliedReason, start: float
    ) -> StoragePartitionDropNotApplied:
        """One structured warning per failed wait (never per poll), then the typed error."""
        waited = self._clock() - start
        logger().warning(
            "rolloff_drop_not_applied",
            table=table,
            partition=name,
            reason=reason,
            waited_s=round(waited, 3),
        )
        return StoragePartitionDropNotApplied(
            f"partition {name} of {table} not applied after {waited:.1f}s",
            reason=reason,
            table=table,
            partition=name,
            waited_s=waited,
        )


def _subranges(stream: StreamKind, rng: TimeRange) -> list[tuple[TimeRange, dict[str, str]]]:
    """One export unit per cold partition directory inside `rng`."""
    if "hour" not in partition_template(stream):
        return [(rng, {})]
    out: list[tuple[TimeRange, dict[str, str]]] = []
    for start in range(rng.start_us, rng.end_us, _US_PER_HOUR):
        hour = datetime.fromtimestamp(start / 1_000_000, tz=UTC).strftime("%H")
        out.append((TimeRange(start_us=start, end_us=start + _US_PER_HOUR), {"hour": hour}))
    return out


def _file_digest(path: Path) -> tuple[int, str, list[str], pa.Schema]:
    """Blocking: re-read the written Parquet file (never the in-memory buffer)."""
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    cols = [n for n in schema.names if n not in _PROVENANCE]
    data_schema = pa.schema([schema.field(n) for n in cols])
    digest = CanonicalDigest(cols, data_schema)
    for batch in pf.iter_batches(batch_size=_DIGEST_ROWS, columns=cols):
        digest.update(pa.Table.from_batches([batch]))
    return digest.rows, digest.hexdigest(), cols, data_schema


class ColdArchiver:
    """Export + verify one `(symbol, stream, day)` via the existing exporter."""

    def __init__(
        self,
        registry: DatasetRegistry,
        source: HotTierSource,
        *,
        exporter: ColdExporter | None = None,
        events: SystemEventSink | None = None,
        batch_rows: int = _DIGEST_ROWS,
    ) -> None:
        self._registry = registry
        self._source = source
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._exporter = exporter or ColdExporter(registry, source, events=self._events)
        self._batch_rows = batch_rows

    async def archive_day(self, symbol: str, stream: StreamKind, day: TimeRange) -> ArchiveOutcome:
        rows = 0
        size = 0
        for rng, extra in _subranges(stream, day):
            if await self._source.count_partition(symbol, stream, rng) == 0:
                continue
            try:
                await self._exporter.export_partition(symbol, stream, rng, partition_extra=extra)
            except StorageExportVerifyFailed:
                return await self._fail(symbol, stream, day, VERIFICATION_FAILED, "row_count")
            except (OSError, DatasetNotRegistered, TimeoutError) as exc:
                logger().warning("rolloff_archive_write_failed", error=type(exc).__name__)
                return await self._fail(symbol, stream, day, WRITE_FAILED, type(exc).__name__)
            paths = self._registry.resolve_partition(
                stream, partition_values={"symbol": symbol, "dt": day_name(day.start_us)} | extra
            )
            reason, n, nbytes = await self._read_back(symbol, stream, rng, paths)
            if reason:
                return await self._fail(symbol, stream, day, VERIFICATION_FAILED, reason)
            rows += n
            size += nbytes
        return ArchiveOutcome(symbol, stream, day.start_us, day.end_us, True, rows, size)

    async def _read_back(
        self, symbol: str, stream: StreamKind, rng: TimeRange, paths: ColdPaths
    ) -> tuple[str, int, int]:
        """Return `(reason, rows, bytes)`; `reason` is empty when verified."""
        store = ManifestStore(paths.manifests_dir)
        entries = await asyncio.to_thread(store.read, paths.partition_dir, paths.root)
        want = (rng.start_us, rng.end_us)
        entry = next((e for e in entries if (e.range_start_us, e.range_end_us) == want), None)
        if entry is None:
            return "missing_manifest", 0, 0
        path = paths.partition_dir / entry.file
        try:
            await verify_partition(paths, self._events)  # manifest SHA-256 + row count
        except StorageExportVerifyFailed:
            return "sha256", 0, 0
        file_rows, file_digest, cols, schema = await asyncio.to_thread(_file_digest, path)
        src = CanonicalDigest(cols, schema)
        batches: AsyncIterator[pa.Table] = self._source.iter_partition(
            symbol, stream, rng, batch_rows=self._batch_rows
        )
        async for table in batches:
            src.update(table)
        src_count = await self._source.count_partition(symbol, stream, rng)
        reason = ""
        if file_rows != src_count or file_rows != src.rows:
            reason = "row_count"
        elif file_digest != src.hexdigest():
            reason = "checksum"
        if reason:
            await self._quarantine(store, paths, entry.file, reason)
            return reason, 0, 0
        return "", file_rows, path.stat().st_size

    async def _quarantine(
        self, store: ManifestStore, paths: ColdPaths, file_name: str, reason: str
    ) -> None:
        def _move() -> Path:
            rel = store.quarantine(paths.partition_dir, paths.root, file_name)
            sidecar = (paths.root / rel).with_suffix(".reason.json")
            _atomic_write_text(sidecar, json.dumps({"reason": reason, "file": file_name}))
            return rel

        rel = await asyncio.shield(asyncio.to_thread(_move))
        storage_rolloff_quarantined_total.labels(reason=reason).inc()
        size = await asyncio.to_thread(_tree_bytes, paths.root / QUARANTINE_DIR)
        storage_quarantine_bytes.set(size)
        logger().warning("rolloff_quarantined", file=rel.as_posix(), reason=reason)

    async def _fail(
        self, symbol: str, stream: StreamKind, day: TimeRange, code: str, reason: str
    ) -> ArchiveOutcome:
        failed = code == VERIFICATION_FAILED
        event = "archive.verification_failed" if failed else "archive.write_failed"
        detail: dict[str, str | int] = {"symbol": symbol, "stream": stream.value}
        detail |= {"dt": day_name(day.start_us), "reason": reason}
        await self._events.emit("CRITICAL", event, detail)
        return ArchiveOutcome(symbol, stream, day.start_us, day.end_us, False, reason=code)


#: Cold-cold rollup (21 §5.4): only these streams are downsampled, never merged.
DOWNSAMPLE_STREAMS: dict[StreamKind, tuple[str, ...]] = {
    StreamKind.ORDERBOOK_DELTA: ("depth", "side", "price"),
    StreamKind.HEATMAP_CELLS: ("price",),
}
DOWNSAMPLE_AFTER_DAYS = 180
_US_PER_SECOND = 1_000_000


DOWNSAMPLE_RUN_ID = "downsample-1s"


def _downsample_table(table: pa.Table, level_key: tuple[str, ...]) -> pa.Table:
    """Last row per `(1 s bucket, level)`, stamped at the bucket start: replaying
    the result in `ts` order reproduces the book (or heatmap) as of the end of
    every 1 s bucket. Input must be in source (`ts`) order."""
    data = table.drop_columns([c for c in table.column_names if c in _PROVENANCE])
    ts_us = pc.cast(pc.cast(data.column("ts"), pa.timestamp("us", tz="UTC")), pa.int64())
    bucket = pc.multiply(pc.divide(ts_us, _US_PER_SECOND), _US_PER_SECOND)
    data = data.append_column("_bucket", bucket).append_column(
        "_ord", pa.array(range(data.num_rows), type=pa.int64())
    )
    keys = ["_bucket", *level_key]
    last = data.group_by(keys, use_threads=False).aggregate([("_ord", "max")])
    rows = pc.take(last.column("_ord_max"), pc.sort_indices(last.column("_ord_max")))
    out = data.take(rows)
    out = out.set_column(
        out.column_names.index("ts"),
        "ts",
        pc.cast(out.column("_bucket"), pa.timestamp("us", tz="UTC")),
    )
    out = out.drop_columns(["_bucket", "_ord"])
    return out.append_column("_downsample", pa.repeat(pa.scalar("1s"), out.num_rows))


class DownsampleSourceCorrupt(StorageExportVerifyFailed):
    """A raw cold file failed its manifest SHA-256/row count; it was quarantined
    and the partition was NOT downsampled (corruption is never laundered)."""


def _verify_sources(store: ManifestStore, paths: ColdPaths, entries: list[ManifestEntry]) -> None:
    for e in entries:
        f = paths.partition_dir / e.file
        bad = ""
        if not f.is_file():
            bad = "missing"
        elif sha256_of(f) != e.sha256:
            bad = "sha256"
        elif pq.ParquetFile(f).metadata.num_rows != e.row_count:
            bad = "row_count"
        if bad:
            rel = store.quarantine(paths.partition_dir, paths.root, e.file)
            sidecar = (paths.root / rel).with_suffix(".reason.json")
            _atomic_write_text(sidecar, json.dumps({"reason": bad, "file": e.file}))
            storage_rolloff_quarantined_total.labels(reason=f"downsample_{bad}").inc()
            raise DownsampleSourceCorrupt(f"{e.file}: {bad} mismatch; quarantined")


def _bucket_keys(table: pa.Table, level_key: tuple[str, ...]) -> set[tuple[object, ...]]:
    """Distinct `(1 s bucket, level)` pairs — the exact row set a correct rollup has."""
    ts = pc.cast(pc.cast(table.column("ts"), pa.timestamp("us", tz="UTC")), pa.int64())
    sec = pc.divide(ts, _US_PER_SECOND).to_pylist()
    cols = [table.column(k).to_pylist() for k in level_key]
    return {(b, *vals) for b, *vals in zip(sec, *cols, strict=True)}


def downsample_partition_sync(paths: ColdPaths, stream: StreamKind) -> tuple[bool, int]:
    """Blocking: replace one cold partition's files with its 1 s downsample.

    1. Every source file is verified against its manifest (SHA-256 + row count);
       a mismatch quarantines it and aborts (`DownsampleSourceCorrupt`).
    2. The derived file is re-read and must contain exactly one row per distinct
       `(second, level)` of the source, the same min/max second, and a SHA-256
       that is recorded and re-checked before any original is unlinked.
    Idempotent (a partition already downsampled is a no-op). Returns `(changed, rows_out)`.
    """
    store = ManifestStore(paths.manifests_dir)
    entries = store.read(paths.partition_dir, paths.root)
    if not entries or all(e.export_run_id == DOWNSAMPLE_RUN_ID for e in entries):
        return False, 0
    _verify_sources(store, paths, entries)
    level_key = DOWNSAMPLE_STREAMS[stream]
    tables = [pq.read_table(paths.partition_dir / e.file) for e in entries]
    source = pa.concat_tables(
        [t.drop_columns([c for c in t.column_names if c in _PROVENANCE]) for t in tables],
        promote_options="default",
    )
    source = normalise_ts(source).sort_by([("ts", "ascending")])
    expected = _bucket_keys(source, level_key)
    out = _downsample_table(source, level_key)
    used = [int(m.group(1)) for e in entries if (m := re.match(r"^part-(\d{4})", e.file))]
    dest = paths.partition_dir / f"part-{max(used, default=0) + 1:04d}.parquet"
    write_parquet_file(out, dest, profile=MARKET_DATA_PROFILE)
    digest = sha256_of(dest)
    derived = pq.read_table(dest)
    got = _bucket_keys(derived, level_key)
    if derived.num_rows != len(expected) or got != expected or sha256_of(dest) != digest:
        dest.unlink(missing_ok=True)
        raise StorageExportVerifyFailed(
            f"downsample verification failed: {derived.num_rows} rows, {len(expected)} expected"
        )
    entry = ManifestEntry(
        file=dest.name,
        sha256=digest,
        row_count=derived.num_rows,
        source_table=entries[0].source_table,
        export_run_id=DOWNSAMPLE_RUN_ID,
        exported_at_us=max(e.exported_at_us for e in entries),
        range_start_us=min(e.range_start_us for e in entries),
        range_end_us=max(e.range_end_us for e in entries),
    )
    store.write(paths.partition_dir, paths.root, [entry])
    for old in entries:
        (paths.partition_dir / old.file).unlink(missing_ok=True)
    return True, derived.num_rows


class ColdDownsampler:
    """Cold-cold rollup driver: downsample every manifested partition of
    `(symbol, stream)` whose day ended at or before `before_us`."""

    def __init__(self, registry: DatasetRegistry, idle_guard: IdleGuard | None = None) -> None:
        self._registry = registry
        self._idle_guard = idle_guard

    async def downsample_before(self, symbol: str, stream: StreamKind, before_us: int) -> int:
        """Returns the end (µs) of the newest partition now downsampled (0 if none)."""
        if stream not in DOWNSAMPLE_STREAMS:
            raise DatasetNotRegistered(f"{stream.value} is not a downsample stream")
        through = 0
        parts = await asyncio.to_thread(self._registry.manifested_partitions, stream, symbol)
        for paths in parts:
            dt = next(p.split("=", 1)[1] for p in paths.partition_dir.parts if p.startswith("dt="))
            day_start = int(datetime.strptime(dt, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
            day_end_us = day_start * 1_000_000 + US_PER_DAY
            if day_end_us > before_us:
                continue
            if self._idle_guard is not None:
                session = await self._idle_guard(paths.partition_dir)
                if session is not None:  # replay lease held: never rewrite data being read
                    logger().info("downsample_deferred", code="compaction_deferred")
                    continue
            async with partition_write_lock(paths.partition_dir):
                await asyncio.shield(asyncio.to_thread(downsample_partition_sync, paths, stream))
            through = max(through, day_end_us)
        return through
