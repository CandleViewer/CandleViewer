"""E26-K01 read sources: the cold tier (real Parquet via the E16-T05 exporter) + a HOT STAND-IN.

`ColdSource` reads partitions resolved by `DatasetRegistry` (a registered dataset id + partition
values, never a caller path - SR-097) with pyarrow (filter push-down on row-group stats) or plain
DuckDB `read_parquet` - no `INSTALL postgres` attach (#2194), so no network.

`HotStandIn` is NOT QuestDB: there is no docker on the spike laptop. It holds the day in memory and
materialises each range as `list[dict]` rows, the shape `QuestDbReader.run()` returns over PGWire,
so it prices row materialisation but not QuestDB's scan or the wire. Real hot-tier numbers come from
`tests/integration/bench/test_e26_replay_seek_questdb.py` in CI's `integration` job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.models import StreamKind, TimeRange

US_HOUR = 3_600_000_000

STREAM_TABLE = {
    StreamKind.ORDERBOOK_DELTA: "deltas",
    StreamKind.ORDERBOOK_SNAPSHOT: "snapshots",
    StreamKind.TRADES: "trades",
}


class Source(Protocol):
    label: str

    def snapshot_at(self, ts_us: int) -> dict[str, object]: ...

    def range(self, stream: StreamKind, start_us: int, end_us: int) -> pa.Table: ...


class _MemHotTier:
    """`HotTierSource` for the exporter: in-memory batches, as E16-T05's tests do."""

    def __init__(self, tables: dict[StreamKind, pa.Table]) -> None:
        self._t = tables

    def _slice(self, stream: StreamKind, rng: TimeRange) -> pa.Table:
        t = self._t[stream]
        ts = t.column("ts").to_numpy()
        a, b = np.searchsorted(ts, [rng.start_us, rng.end_us], side="left")
        return t.slice(int(a), int(b - a))

    async def iter_partition(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, batch_rows: int
    ) -> AsyncIterator[pa.Table]:
        t = self._slice(stream, rng)
        for off in range(0, t.num_rows, batch_rows):
            yield t.slice(off, batch_rows)

    async def count_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> int:
        return int(self._slice(stream, rng).num_rows)


def _partitions(
    stream: StreamKind, start_us: int, end_us: int
) -> list[tuple[TimeRange, dict[str, str]]]:
    hourly = stream is StreamKind.ORDERBOOK_DELTA
    step = US_HOUR if hourly else 24 * US_HOUR
    out: list[tuple[TimeRange, dict[str, str]]] = []
    t = start_us - start_us % step
    while t < end_us:
        extra = {"hour": datetime.fromtimestamp(t / 1e6, tz=UTC).strftime("%H")} if hourly else {}
        out.append((TimeRange(start_us=max(t, start_us), end_us=min(t + step, end_us)), extra))
        t += step
    return out


async def export_cold(
    root: Path,
    symbol: str,
    tables: dict[StreamKind, pa.Table],
    start_us: int,
    end_us: int,
    rows_per_group: int,
) -> DatasetRegistry:
    """Write the synthetic day with the real `ColdExporter` (E16-T05 layout, ZSTD-6 profile)."""
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    exporter = ColdExporter(registry, _MemHotTier(tables), rows_per_group=rows_per_group)
    for stream in tables:
        for rng, extra in _partitions(stream, start_us, end_us):
            await exporter.export_partition(symbol, stream, rng, partition_extra=extra or None)
    return registry


def _ts(us: int) -> pa.Scalar:
    return pa.scalar(us, pa.timestamp("us", tz="UTC"))


class ColdSource:
    label = "cold (Parquet, pyarrow)"

    def __init__(self, registry: DatasetRegistry, symbol: str) -> None:
        self._registry = registry
        self._symbol = symbol
        self._ds: dict[StreamKind, ds.Dataset] = {}

    def files(self, stream: StreamKind) -> list[str]:
        """Part files of the manifested partitions (discovered from `_manifests/`, SR-097)."""
        out: list[str] = []
        for paths in self._registry.manifested_partitions(stream, self._symbol):
            out += sorted(str(p) for p in paths.partition_dir.glob("part-*.parquet"))
        return out

    def _dataset(self, stream: StreamKind) -> ds.Dataset:
        if stream not in self._ds:
            self._ds[stream] = ds.dataset(self.files(stream), format="parquet")
        return self._ds[stream]

    def snapshot_at(self, ts_us: int) -> dict[str, object]:
        d = self._dataset(StreamKind.ORDERBOOK_SNAPSHOT)
        t = d.to_table(filter=pc.field("ts") <= _ts(ts_us))
        i = int(np.argmax(t.column("ts").cast(pa.int64()).to_numpy()))
        row: dict[str, object] = t.slice(i, 1).to_pylist()[0]
        return row

    def range(self, stream: StreamKind, start_us: int, end_us: int) -> pa.Table:
        flt = (pc.field("ts") >= _ts(start_us)) & (pc.field("ts") < _ts(end_us))
        return self._dataset(stream).to_table(filter=flt)

    def duckdb_scan(self, stream: StreamKind) -> int:
        """Full sequential scan via DuckDB `read_parquet` over the manifested files (no attach)."""
        con = duckdb.connect(":memory:")
        try:
            reader = con.execute(
                "SELECT ts, price, size FROM read_parquet(?) ORDER BY ts", [self.files(stream)]
            ).fetch_record_batch(65_536)
            return sum(b.num_rows for b in reader)
        finally:
            con.close()


class HotStandIn:
    """IN-MEMORY STAND-IN for QuestDB (labelled in every table). Rows come back as dicts."""

    label = "hot STAND-IN (in-memory, not QuestDB)"

    def __init__(self, tables: dict[StreamKind, pa.Table]) -> None:
        self._t = tables
        self._ts = {k: v.column("ts").to_numpy() for k, v in tables.items()}

    def snapshot_at(self, ts_us: int) -> dict[str, object]:
        ts = self._ts[StreamKind.ORDERBOOK_SNAPSHOT]
        i = int(np.searchsorted(ts, ts_us, side="right")) - 1
        row: dict[str, object] = self._t[StreamKind.ORDERBOOK_SNAPSHOT].slice(i, 1).to_pylist()[0]
        return row

    def range(self, stream: StreamKind, start_us: int, end_us: int) -> pa.Table:
        a, b = np.searchsorted(self._ts[stream], [start_us, end_us], side="left")
        # PGWire materialises every row as a record; price that, then hand back Arrow.
        rows = self._t[stream].slice(int(a), int(b - a)).to_pylist()
        return pa.Table.from_pylist(rows) if rows else self._t[stream].slice(0, 0)
