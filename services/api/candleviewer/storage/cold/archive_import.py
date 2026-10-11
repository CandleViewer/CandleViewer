"""Cold-tier writer + ledger for imported public trade archives (E16-T10).

Imported days land in the E16-T05 layout (`trades/symbol=<SYM>/dt=<YYYY-MM-DD>/part-NNNN.parquet`)
with a manifest entry (SHA-256 + row count + `[day_lo, day_hi)` range) written after the
atomic rename, exactly like the exporter. A partition is never rewritten: an import adds one
new part file, and a day whose manifest already holds an import entry for that range is a
no-op. Rows whose natural key (`storage.natural_keys`) already exists in the partition are
dropped, so no duplicate trade is created even if a recorded file is already present.

Columns match the hot `trades` table (21 section 4) so the DuckDB view unions cleanly;
`recv_ts`, `is_block` and `seq` are null for archive rows and `_source` is `archive`.

`FileImportLedger` is the per-file checkpoint and the archive-coverage registry: one JSON
document per symbol under `_manifests/_imports/trades/symbol=<SYM>.json`, written atomically
(tmp + fsync + rename, the #2213 watermark pattern). No Postgres migration.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from candleviewer.domain.archive import ArchiveTrade
from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.cold.partition_lock import partition_write_lock
from candleviewer.storage.cold.writer import (
    MARKET_DATA_PROFILE,
    AtomicParquetWriter,
    add_provenance_columns,
)
from candleviewer.storage.models import StreamKind
from candleviewer.storage.natural_keys import NATURAL_KEY

IMPORT_RUN_PREFIX = "archive-import-"
_LEDGER_SYMBOL = re.compile(r"^[A-Z0-9]{2,30}$")
_PART_RE = re.compile(r"^part-(\d{4})\.parquet$")
_DEC = pa.decimal128(38, 18)
_SCHEMA = pa.schema(
    [
        ("ts", pa.timestamp("us", tz="UTC")),
        ("recv_ts", pa.timestamp("us", tz="UTC")),
        ("symbol", pa.string()),
        ("side", pa.string()),
        ("price", pa.float64()),
        ("size", pa.float64()),
        ("notional", pa.float64()),
        ("trade_id", pa.string()),
        ("tick_dir", pa.string()),
        ("is_block", pa.bool_()),
        ("seq", pa.int64()),
    ]
)
#: Natural key of `trades` minus `symbol` (constant within a partition).
_KEY = tuple(c for c in NATURAL_KEY[StreamKind.TRADES] if c != "symbol")


@dataclass(frozen=True, slots=True)
class DayWrite:
    rows_written: int
    rows_duplicate: int
    file: str | None
    already_done: bool = False


def _to_double(values: list[Decimal]) -> pa.Array:
    """Decimal -> DOUBLE exactly once, at the Parquet boundary (21 section 5.2)."""
    return pc.cast(pa.array(values, type=_DEC), pa.float64())


def _table(rows: Sequence[ArchiveTrade]) -> pa.Table:
    n = len(rows)
    nulls_ts = pa.nulls(n, pa.timestamp("us", tz="UTC"))
    return pa.Table.from_arrays(
        [
            pa.array([r.ts_us for r in rows], pa.int64()).cast(pa.timestamp("us", tz="UTC")),
            nulls_ts,
            pa.array([r.symbol for r in rows], pa.string()),
            pa.array([r.side for r in rows], pa.string()),
            _to_double([r.price for r in rows]),
            _to_double([r.size for r in rows]),
            _to_double([r.price * r.size for r in rows]),
            pa.array([r.trade_id for r in rows], pa.string()),
            pa.array([r.tick_dir for r in rows], pa.string()),
            pa.nulls(n, pa.bool_()),
            pa.nulls(n, pa.int64()),
        ],
        schema=_SCHEMA,
    )


def _existing_keys(partition_dir: Path, entries: list[ManifestEntry]) -> set[tuple[object, ...]]:
    keys: set[tuple[object, ...]] = set()
    for e in entries:
        t = pq.read_table(partition_dir / e.file, columns=list(_KEY))
        cols = [pc.cast(t.column("ts"), pa.int64()).to_pylist()] + [
            t.column(c).to_pylist() for c in _KEY[1:]
        ]
        keys.update(zip(*cols, strict=True))
    return keys


def _is_import_part(path: Path) -> bool:
    try:
        t = pq.read_table(path, columns=["_export_run_id"])
    except (OSError, KeyError, pa.ArrowException):
        return False
    ids = t.column("_export_run_id").to_pylist()
    return bool(ids) and str(ids[0]).startswith(IMPORT_RUN_PREFIX)


class _DaySession:
    """Blocking: streams one archive day into a new part file of its partition."""

    def __init__(self, registry: DatasetRegistry, symbol: str, day: date, lo: int, hi: int):
        self.paths = registry.resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": symbol, "dt": day.isoformat()}
        )
        self.store = ManifestStore(self.paths.manifests_dir)
        self.lo, self.hi = lo, hi
        self.entries = self.store.read(self.paths.partition_dir, self.paths.root)
        self.done = next(
            (
                e for e in self.entries
                if e.export_run_id.startswith(IMPORT_RUN_PREFIX)
                and (e.range_start_us, e.range_end_us) == (lo, hi)
                and (self.paths.partition_dir / e.file).is_file()
            ),
            None,
        )  # fmt: skip
        self.run_id = f"{IMPORT_RUN_PREFIX}{uuid.uuid4()}"
        self.seen: set[tuple[object, ...]] = set()
        self.duplicates = 0
        self.writer: AtomicParquetWriter | None = None
        if self.done is None:
            self._reconcile_orphans()
            self.seen = _existing_keys(self.paths.partition_dir, self.entries)
            used = {int(m.group(1)) for e in self.entries if (m := _PART_RE.match(e.file))}
            # Also skip names present on disk (another writer's in-flight part): never clobber.
            on_disk = {
                int(m.group(1))
                for p in self.paths.partition_dir.glob("part-*.parquet*")
                if (m := _PART_RE.match(p.name.removesuffix(".tmp")))
            } if self.paths.partition_dir.is_dir() else set()  # fmt: skip
            nxt = max(used | on_disk, default=-1) + 1
            self.file = f"part-{nxt:04d}.parquet"

    def _reconcile_orphans(self) -> None:
        """Remove only THIS importer's crash leftovers: an unmanifested part whose
        `_export_run_id` provenance is an import run. Parts being written by the exporter,
        compactor or downsampler (no partition lock is shared across them) are never touched,
        and `.tmp` files are left alone: readers only follow the manifest, and the exporter's
        own `sweep_stale_temps` reclaims them. New part names skip anything on disk."""
        known = {e.file for e in self.entries}
        if not self.paths.partition_dir.is_dir():
            return
        for part in self.paths.partition_dir.glob("part-*.parquet"):
            if part.name in known or not _is_import_part(part):
                continue
            part.unlink(missing_ok=True)

    def write(self, rows: Sequence[ArchiveTrade], exported_at_us: int) -> None:
        keep: list[ArchiveTrade] = []
        for r in rows:
            if not self.lo <= r.ts_us < self.hi:
                raise ValueError("row outside the partition day")
            key = (r.ts_us, r.trade_id)
            if key in self.seen:
                self.duplicates += 1
                continue
            self.seen.add(key)
            keep.append(r)
        if not keep:
            return
        batch = add_provenance_columns(
            _table(keep), export_run_id=self.run_id, exported_at_us=exported_at_us, source="archive"
        )
        if self.writer is None:
            self.writer = AtomicParquetWriter(
                self.paths.partition_dir / self.file, batch.schema, profile=MARKET_DATA_PROFILE
            )
        self.writer.write(batch)

    def commit(self, exported_at_us: int) -> DayWrite:
        if self.writer is None:
            return DayWrite(0, self.duplicates, None)
        try:
            rows = self.writer.commit()
        except BaseException:
            self.writer.abort()
            raise
        dest = self.paths.partition_dir / self.file
        entry = ManifestEntry(
            file=self.file,
            sha256=sha256_of(dest),
            row_count=rows,
            source_table=StreamKind.TRADES.value,
            export_run_id=self.run_id,
            exported_at_us=exported_at_us,
            range_start_us=self.lo,
            range_end_us=self.hi,
        )
        self.store.append_reconciled(self.paths.partition_dir, self.paths.root, entry)
        return DayWrite(rows, self.duplicates, self.file)

    def abort(self) -> None:
        if self.writer is not None:
            self.writer.abort()


class ColdDaySink:
    """Async handle on one day's import; every blocking call runs off the loop."""

    def __init__(self, session: _DaySession) -> None:
        self._s = session

    @property
    def already_done(self) -> DayWrite | None:
        e = self._s.done
        return None if e is None else DayWrite(e.row_count, 0, e.file, already_done=True)

    async def write(self, rows: Sequence[ArchiveTrade], now_us: int) -> None:
        await asyncio.to_thread(self._s.write, rows, now_us)

    async def commit(self, now_us: int) -> DayWrite:
        return await asyncio.to_thread(self._s.commit, now_us)

    async def abort(self) -> None:
        await asyncio.to_thread(self._s.abort)


class ColdArchiveDayWriter:
    """Opens per-day sinks under `CV_COLD_ROOT` (paths only via `DatasetRegistry`, SR-097)."""

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry

    def day_lock(self, symbol: str, day: date) -> AbstractAsyncContextManager[None]:
        """The shared per-partition writer lock (exporter/compactor/downsampler use it too);
        the importer holds it over open -> write -> manifest -> checkpoint for the day."""
        paths = self._registry.resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": symbol, "dt": day.isoformat()}
        )
        return partition_write_lock(paths.partition_dir)

    async def open_day(self, symbol: str, day: date, lo: int, hi: int) -> ColdDaySink:
        return ColdDaySink(
            await asyncio.to_thread(_DaySession, self._registry, symbol, day, lo, hi)
        )


class LedgerCorrupt(ValueError):
    """The import ledger document is unreadable; fail closed: the job ends `failed` with
    error `import_ledger_corrupt` and nothing is fetched or written."""

    code = "import_ledger_corrupt"


class FileImportLedger:
    """Per-file checkpoint + archive-coverage registry (atomic JSON, #2213 pattern).

    Document: `{"version": 1, "files": {"<YYYY-MM-DD>": {"lo": us, "hi": us, "rows": n,
    "sha256": hex, "file": "part-NNNN.parquet" | null, "discarded_overlap": n,
    "discarded_duplicate": n}}}`, so per-day counts survive a crash + re-run. A day is
    recorded only after its Parquet file and manifest entry are durable, so a crash re-does
    at most one day.
    """

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._lock = asyncio.Lock()

    def _path(self, symbol: str) -> Path:
        # Closed charset (no separator, no dot) => the name cannot leave `base` (SR-097); no
        # `resolve()` of a not-yet-existing path (Windows may return a `\?\` form for it).
        if not _LEDGER_SYMBOL.fullmatch(symbol):
            raise DatasetNotRegistered("unsafe symbol for the import ledger")
        return self._registry.root / "_manifests" / "_imports" / "trades" / f"symbol={symbol}.json"

    def _read_sync(self, symbol: str) -> dict[str, dict[str, object]]:
        path = self._path(symbol)
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            files = raw["files"]
            if raw.get("version") != 1 or not isinstance(files, dict):
                raise LedgerCorrupt("unexpected ledger shape")
            return {str(k): dict(v) for k, v in files.items()}
        except (ValueError, KeyError, TypeError) as exc:
            raise LedgerCorrupt("import ledger is not valid") from exc

    def _write_sync(self, symbol: str, files: dict[str, dict[str, object]]) -> None:
        path = self._path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "files": files}, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def done_days(self, symbol: str) -> set[date]:
        files = await asyncio.to_thread(self._read_sync, symbol)
        return {date.fromisoformat(d) for d in files}

    async def mark_done(
        self,
        symbol: str,
        day: date,
        lo: int,
        hi: int,
        rows: int,
        sha256: str,
        file: str | None,
        *,
        discarded: int = 0,
        duplicate: int = 0,
    ) -> None:
        async with self._lock:
            files = await asyncio.to_thread(self._read_sync, symbol)
            files[day.isoformat()] = {
                "lo": lo, "hi": hi, "rows": rows, "sha256": sha256, "file": file,
                "discarded_overlap": discarded, "discarded_duplicate": duplicate,
            }  # fmt: skip
            await asyncio.to_thread(self._write_sync, symbol, files)

    async def day_counts(self, symbol: str) -> dict[date, tuple[int, int, int]]:
        """Persisted `(rows_written, discarded_overlap, discarded_duplicate)` per finished day."""
        files = await asyncio.to_thread(self._read_sync, symbol)

        def num(v: dict[str, object], key: str) -> int:
            x = v.get(key, 0)
            return x if isinstance(x, int) else 0

        return {
            date.fromisoformat(d): (
                num(v, "rows"),
                num(v, "discarded_overlap"),
                num(v, "discarded_duplicate"),
            )
            for d, v in files.items()
        }

    async def archive_windows(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]:
        """Imported `[lo, hi)` windows intersecting the query (coverage `source='archive'`).
        Only days that actually produced rows count."""
        files = await asyncio.to_thread(self._read_sync, symbol)
        out: list[tuple[int, int]] = []
        for v in files.values():
            a, b, n = v.get("lo"), v.get("hi"), v.get("rows")
            if isinstance(a, int) and isinstance(b, int) and isinstance(n, int) and n > 0:
                if a < hi and b > lo:
                    out.append((max(a, lo), min(b, hi)))
        return sorted(out)
