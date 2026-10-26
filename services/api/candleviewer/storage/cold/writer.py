"""Parquet writer profiles — `21-database-schema.md` Sec.5.2 encoded as code.

Two profiles, selected by dataset id (never guessed from the data):
`market_data` (DOUBLE prices, the default) and `oms` (DECIMAL(38,18) money
columns) — ticket "Technical notes / design": "two different writer
profiles, selected by dataset id, not by guessing." Only `market_data` is in
scope for this ticket (OMS producers are E41/E29); the profile split exists
now so E41/E29 do not have to touch this module's writer internals.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

#: Sec.5.2: "Dictionary enabled on symbol, side, action, tick_dir".
_DICTIONARY_COLUMNS = ("symbol", "side", "action", "tick_dir")

#: Sec.5.2: "write_statistics=true on ts, price, notional, symbol".
_STATS_COLUMNS = ("ts", "price", "notional", "symbol")

#: Sec.5.2: 128 MiB target row groups; the ticket's own sizing note gives
#: ~1M rows for trades, ~4M for deltas, so callers pass `rows_per_group`
#: explicitly per stream rather than this module guessing from row size.
DEFAULT_ROWS_PER_GROUP = 1_000_000

_PAGE_SIZE_BYTES = 1 << 20  # 1 MiB, Sec.5.2

#: Provenance columns present on every exported file (Sec.5.2).
PROVENANCE_COLUMNS = ("_export_run_id", "_exported_at", "_source")


class UnsortedRowGroup(ValueError):
    """The writer asserts monotonic `ts` per row group and refuses to write
    an unsorted file rather than silently defeating Sec.13.3 pruning
    (ticket "Technical notes / design")."""


@dataclass(frozen=True, slots=True)
class WriterProfile:
    """Compression/encoding knobs for one Parquet writer invocation."""

    compression: str = "zstd"
    compression_level: int = 6
    data_page_size: int = _PAGE_SIZE_BYTES
    version: str = "2.6"
    dictionary_columns: tuple[str, ...] = _DICTIONARY_COLUMNS
    stats_columns: tuple[str, ...] = _STATS_COLUMNS


MARKET_DATA_PROFILE = WriterProfile()

#: OMS profile differs only in intent (money columns use DECIMAL upstream,
#: enforced by the caller's Arrow schema, not by this module) — out of scope
#: for this ticket's producers but the profile exists per the ticket's
#: explicit two-profile requirement.
OMS_PROFILE = WriterProfile()


def assert_sorted_by_ts(
    table: pa.Table | pa.RecordBatch, ts_column: str = "ts", *, floor: Any = None
) -> Any:
    """Fail-fast guard for Sec.5.2's sort rule ("Rows sorted by ts then
    price"). Raises `UnsortedRowGroup` rather than writing a file that
    silently defeats Sec.13.3 min/max pruning. `floor` is the last `ts` of the
    previous batch so monotonicity is enforced across batches too; returns the
    last `ts` seen (vectorised, no per-row Python loop)."""
    if table.num_rows == 0:
        return floor
    col = table.column(ts_column)
    if isinstance(col, pa.ChunkedArray):
        col = col.combine_chunks()
    if table.num_rows > 1:
        head, tail = col.slice(0, len(col) - 1), col.slice(1)
        if pc.any(pc.less(tail, head)).as_py():
            raise UnsortedRowGroup(f"column {ts_column!r} is not monotonically non-decreasing")
    first, last = col[0].as_py(), col[len(col) - 1].as_py()
    if floor is not None and first < floor:
        raise UnsortedRowGroup(f"column {ts_column!r} regresses across batches")
    return last


def normalise_ts(table: pa.Table, ts_column: str = "ts") -> pa.Table:
    """Coerce `ts` to `TIMESTAMP(MICROS, UTC)` (Sec.5.2). Integer inputs are
    interpreted as epoch microseconds (the hot tier's native unit)."""
    if ts_column not in table.column_names:
        return table
    target = pa.timestamp("us", tz="UTC")
    col = table.column(ts_column)
    if col.type == target:
        return table
    if pa.types.is_integer(col.type):
        col = pc.cast(col, pa.int64()).cast(target)
    else:
        col = pc.cast(col, target)
    idx = table.column_names.index(ts_column)
    return table.set_column(idx, ts_column, col)


def add_provenance_columns(
    table: pa.Table, *, export_run_id: str, exported_at_us: int, source: str
) -> pa.Table:
    """Appends `_export_run_id`, `_exported_at`, `_source` (Sec.5.2) to
    every row of `table`. `_exported_at` is written as a microsecond UTC
    timestamp to match the rest of the schema's timestamp resolution."""
    n = table.num_rows
    return (
        table.append_column("_export_run_id", pa.repeat(pa.scalar(export_run_id, pa.string()), n))
        .append_column(
            "_exported_at",
            pa.repeat(pa.scalar(exported_at_us, pa.timestamp("us", tz="UTC")), n),
        )
        .append_column("_source", pa.repeat(pa.scalar(source, pa.string()), n))
    )


def write_parquet_file(
    table: pa.Table,
    dest: Path,
    *,
    profile: WriterProfile = MARKET_DATA_PROFILE,
    rows_per_group: int = DEFAULT_ROWS_PER_GROUP,
) -> int:
    """Write one in-memory `table` atomically (see `write_parquet_batches`)."""
    return write_parquet_batches(
        [table], table.schema, dest, profile=profile, rows_per_group=rows_per_group
    )


def write_parquet_batches(
    batches: Iterable[pa.Table | pa.RecordBatch],
    schema: pa.Schema,
    dest: Path,
    *,
    profile: WriterProfile = MARKET_DATA_PROFILE,
    rows_per_group: int = DEFAULT_ROWS_PER_GROUP,
) -> int:
    """Synchronous convenience wrapper over `AtomicParquetWriter`."""
    # nosemgrep: cv-recorder-fs-write-unvalidated-path reason=atomic-write-primitive owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
    writer = AtomicParquetWriter(dest, schema, profile=profile, rows_per_group=rows_per_group)
    try:
        for batch in batches:
            writer.write(batch)
        return writer.commit()
    except BaseException:
        writer.abort()
        raise


class AtomicParquetWriter:
    """Streams batches into `<dest>.tmp`, then `commit()` fsyncs and
    `os.replace`s it onto `dest` (ticket "Technical notes / design":
    "Atomicity"). Memory is bounded by one batch — a partition is never
    materialised whole. Asserts `ts` monotonicity within and across batches.

    The temp name is deterministic (`<dest>.tmp`) so a crash leaves a file
    the next run's `sweep_stale_temps` recognises and removes. Every method
    is blocking; async callers wrap each call in `asyncio.to_thread`.
    """

    def __init__(
        self,
        dest: Path,
        schema: pa.Schema,
        *,
        profile: WriterProfile = MARKET_DATA_PROFILE,
        rows_per_group: int = DEFAULT_ROWS_PER_GROUP,
    ) -> None:
        if rows_per_group <= 0:
            raise ValueError("rows_per_group must be positive")
        self.dest = dest
        self.tmp_path = dest.with_name(dest.name + ".tmp")
        self._schema = schema
        self._rows_per_group = rows_per_group
        self._floor: Any = None
        self.rows_written = 0
        self._profile = profile
        self._writer: pq.ParquetWriter | None = None
        self._closed = False

    def _open(self) -> pq.ParquetWriter:
        """Lazily create `<dest>.tmp` (blocking) on the first `write`, so the
        object can be constructed on the event loop without I/O."""
        if self._closed:
            raise RuntimeError("writer already closed")
        if self._writer is None:
            p, schema = self._profile, self._schema
            self.dest.parent.mkdir(parents=True, exist_ok=True)
            self._writer = pq.ParquetWriter(
                self.tmp_path,
                schema,
                version=p.version,
                compression=p.compression,
                compression_level=p.compression_level,
                data_page_size=p.data_page_size,
                use_dictionary=[c for c in p.dictionary_columns if c in schema.names] or False,
                write_statistics=[c for c in p.stats_columns if c in schema.names] or True,
            )
        return self._writer

    def write(self, batch: pa.Table | pa.RecordBatch) -> None:
        writer = self._open()
        tbl = batch if isinstance(batch, pa.Table) else pa.Table.from_batches([batch])
        if "ts" in self._schema.names:
            self._floor = assert_sorted_by_ts(tbl, floor=self._floor)
        writer.write_table(tbl, row_group_size=self._rows_per_group)
        self.rows_written += tbl.num_rows

    def commit(self) -> int:
        writer = self._open()
        writer.close()
        self._writer = None
        self._closed = True
        # Reopen read-write: Windows rejects fsync on a read-only fd (EBADF).
        fd = os.open(str(self.tmp_path), os.O_RDWR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(self.tmp_path, self.dest)
        _fsync_dir(self.dest.parent)
        return self.rows_written

    def abort(self) -> None:
        self._closed = True
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self.tmp_path.unlink(missing_ok=True)


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself (POSIX); a no-op where directories cannot be
    opened (Windows)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def sweep_stale_temps(partition_dir: Path) -> list[str]:
    """Remove `*.tmp` leftovers of a crashed write (crash point 1: killed
    mid-write). Returns the removed file names."""
    removed: list[str] = []
    if partition_dir.is_dir():
        for tmp in sorted(partition_dir.glob("*.tmp")):
            tmp.unlink(missing_ok=True)
            removed.append(tmp.name)
    return removed
