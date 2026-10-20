"""`ColdTierRepository` implementation over Parquet + DuckDB (E07-T04).

`query()` accepts a registered dataset id (`StreamKind`) plus a `TimeRange`,
never a filesystem path (SR-097). It reads only files listed in the
partition manifests, and verifies each against its manifest SHA-256/row
count before serving it (SR-094 "verify on read"; results are cached by
`(size, mtime_ns)` so an unchanged file is hashed once per process). A
mismatching file is quarantined and the call raises, and so does every later
query of its day until an operator clears the quarantine (#3477).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from candleviewer.storage.cold.exporter import ColdExporter, HotTierSource
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry, partition_template
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import ExportRun, StreamKind, TimeRange

_QUERYABLE_TEMPLATE = ("symbol", "dt")


class DownsampleNotImplemented(NotImplementedError):
    """`action='downsample'` (cold-cold rollup past 180 days) is E16 scope."""


def _day(us: int) -> str:
    return datetime.fromtimestamp(us / 1_000_000, tz=UTC).strftime("%Y-%m-%d")


class ParquetColdTierRepository:
    """`ColdTierRepository` Protocol implementation."""

    def __init__(
        self,
        registry: DatasetRegistry,
        source: HotTierSource,
        *,
        events: SystemEventSink | None = None,
        exporter: ColdExporter | None = None,
    ) -> None:
        self._registry = registry
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._exporter = exporter or ColdExporter(registry, source, events=self._events)
        self._verified: dict[Path, tuple[int, int]] = {}

    async def export_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> ExportRun:
        return await self._exporter.export_partition(symbol, stream, rng)

    def _day_paths(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[ColdPaths]:
        if partition_template(stream) != _QUERYABLE_TEMPLATE:
            raise ValueError(f"stream {stream.value!r} is not addressable by symbol/day")
        start = datetime.fromtimestamp(rng.start_us / 1_000_000, tz=UTC).date()
        last = datetime.fromtimestamp((rng.end_us - 1) / 1_000_000, tz=UTC).date()
        out: list[ColdPaths] = []
        day = start
        while day <= last:
            out.append(
                self._registry.resolve_partition(
                    stream, partition_values={"symbol": symbol, "dt": day.isoformat()}
                )
            )
            day += timedelta(days=1)
        return out

    async def list_manifest(self, symbol: str, stream: StreamKind) -> list[ExportRun]:
        """Every manifested file for `(symbol, stream)`, ascending by range."""
        runs: list[ExportRun] = []
        for paths in await asyncio.to_thread(self._registry.manifested_partitions, stream, symbol):
            store = ManifestStore(paths.manifests_dir)
            for e in await asyncio.to_thread(store.read, paths.partition_dir, paths.root):
                runs.append(
                    ExportRun(
                        run_id=e.export_run_id,
                        symbol=symbol,
                        stream=stream,
                        partition_range=TimeRange(
                            start_us=e.range_start_us,
                            end_us=max(e.range_end_us, e.range_start_us + 1),
                        ),
                        row_count=e.row_count,
                        verified=False,
                    )
                )
        return sorted(runs, key=lambda r: (r.partition_range.start_us, r.run_id))

    async def _verified_files(self, paths: ColdPaths) -> list[str]:
        store = ManifestStore(paths.manifests_dir)
        read = store.read_with_quarantine
        try:
            entries, quarantined = await asyncio.to_thread(read, paths.partition_dir, paths.root)
        except OSError:  # its text names the path: typed, with no chain
            raise StorageExportVerifyFailed("cold partition could not be listed") from None
        if quarantined:
            # #3477: the manifest no longer names that part, so the rest would pass for all of it.
            # `verify_checksums` does not refuse, so a re-export verifies before the clear.
            raise StorageExportVerifyFailed("cold partition holds a quarantined part")
        files = [paths.partition_dir / e.file for e in entries]
        stamps: dict[Path, tuple[int, int]] = {}
        for f in files:
            st = f.stat() if f.is_file() else None
            stamps[f] = (st.st_size, st.st_mtime_ns) if st else (-1, -1)
        if any(self._verified.get(f) != stamps[f] for f in files):
            await verify_partition(paths, self._events)
            self._verified.update(stamps)
        return [f.as_posix() for f in files]

    async def query(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[dict[str, Any]]:
        files: list[str] = []
        for paths in self._day_paths(symbol, stream, rng):
            files.extend(await self._verified_files(paths))
        if not files:
            return []
        return await asyncio.to_thread(_read_rows, files, symbol, rng)

    async def verify_checksums(self, run: ExportRun) -> bool:
        ok = True
        for paths in self._day_paths(run.symbol, run.stream, run.partition_range):
            ok = await verify_partition(paths, self._events) and ok
        return ok


def _read_rows(files: list[str], symbol: str, rng: TimeRange) -> list[dict[str, Any]]:
    """Blocking DuckDB read over an explicit, manifest-derived file list; all
    values are bind parameters. In-memory connection, external access to the
    listed files only. `union_by_name`: a part written before its dataset's schema
    widened (21 Sec.5.2) reads the columns it lacks as NULL; without it DuckDB keeps the
    first file's columns, dropping them, or refuses a later file that lacks them."""
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET TimeZone = 'UTC'")
        table = con.execute(
            "SELECT * FROM read_parquet($files, hive_partitioning = true, union_by_name = true) "
            "WHERE symbol = $sym AND ts >= make_timestamptz($lo::BIGINT) "
            "AND ts < make_timestamptz($hi::BIGINT) ORDER BY ts",
            {"files": files, "sym": symbol, "lo": rng.start_us, "hi": rng.end_us},
        ).to_arrow_table()
        # Via Arrow: tz-aware datetimes use stdlib `zoneinfo` (no `pytz`).
        rows: list[dict[str, Any]] = table.to_pylist()
        return rows
    finally:
        con.close()


def downsample(_stream: StreamKind, _rng: TimeRange) -> None:
    """Cold-cold rollup (`retention_policies.action='downsample'`) for
    `orderbook_deltas`/`heatmap_cells` past 180 days.

    TODO(E16): implement; deferred from E07-T04 per its "Out of scope".
    """
    raise DownsampleNotImplemented(
        "cold-cold downsample rollup is E16 scope; deferred from E07-T04 "
        "(retention_policies action='downsample')"
    )
