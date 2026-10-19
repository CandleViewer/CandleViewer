"""E26-T02 throughput benchmark: `ReplaySource` events/s against the E26-K01 baseline.

E26-K01 (ADR-0035 proposed, PR #2226) measured these figures on a synthetic dense 200-depth
day: cold Parquet through DuckDB at 7.3 M events/s, the `(ts_event, seq)` merge alone at
2.6 M events/s, and 0.41 M events/s required to sustain 100x through the busiest minute.

This harness replays a deterministic busiest minute with the K01 dense profile (242 k book-delta
rows and 1.2 k trades) through the whole source: cursors, merge, dedup, read-ahead queue and
consumer. It runs twice: once over an in-memory tier (the source's own cost) and once over the
real cold tier (Parquet written by the production exporter, read through DuckDB). It reports
events/s p50 over `--runs`. No network. Run:

    uv run python bench/replay_source.py --runs 5
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import statistics
import tempfile
import time
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa

from candleviewer.replay import ReplayRequest, ReplaySource, ReplayTiers
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent, event_from_row
from candleviewer.storage.testing import StaticGapReader, StaticManifestCoverage

K01_BASELINE = {"merge": 2_600_000, "cold_duckdb": 7_300_000, "required_100x": 410_000}
H0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
MINUTE = 60_000_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
STREAMS = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA)


def busiest_minute(delta_rows: int, trades: int) -> dict[StreamKind, list[dict[str, object]]]:
    """Two-level updates evenly spread over one minute; prices walk deterministically."""
    updates = delta_rows // 2
    deltas: list[dict[str, object]] = [
        {
            "ts": H0 + i * MINUTE // updates,
            "symbol": "BTCUSDT",
            "depth": 200,
            "side": side,
            "price": 65_000.0 + offset + (i % 200) * 0.5,
            "size": 0.0 if i % 9 == 0 else 1.0 + i % 7,
            "update_id": i,
            "cross_seq": 2 * i,
        }
        for i in range(updates)
        for side, offset in (("bid", -100.0), ("ask", 100.5))
    ]
    prints: list[dict[str, object]] = [
        {
            "ts": H0 + i * MINUTE // trades,
            "symbol": "BTCUSDT",
            "side": "buy" if i % 2 else "sell",
            "price": 65_000.0 + i % 11,
            "size": 0.001 * (1 + i % 5),
            "trade_id": f"t{i}",
            "seq": 2 * i * (updates // trades) + 1,
            "is_block": False,
        }
        for i in range(trades)
    ]
    return {StreamKind.TRADES: prints, StreamKind.ORDERBOOK_DELTA: deltas}


class SortedTier:
    """In-memory `RecordedStreamReader` with bisect range reads, so the bench measures the
    source rather than the tier."""

    def __init__(self, events: Sequence[RecordedEvent]) -> None:
        self._by_stream = {
            s: sorted((e for e in events if e.stream is s), key=lambda e: e.ts_us) for s in STREAMS
        }
        self._ts = {s: [e.ts_us for e in rows] for s, rows in self._by_stream.items()}

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        ts = self._ts[stream]
        lo = bisect.bisect_left(ts, rng.start_us)
        hi = bisect.bisect_left(ts, rng.end_us)
        return self._by_stream[stream][lo : min(hi, lo + limit)]

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        return None


class _MemHotSource:
    def __init__(self, rows: dict[StreamKind, list[dict[str, object]]]) -> None:
        self._rows = rows

    async def iter_partition(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, batch_rows: int
    ) -> AsyncIterator[pa.Table]:
        rows = self._rows[stream]
        for start in range(0, len(rows), batch_rows):
            yield pa.Table.from_pylist(rows[start : start + batch_rows])

    async def count_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> int:
        return len(self._rows[stream])


def _request(tier: str) -> ReplayRequest:
    return ReplayRequest.model_validate(
        {
            "symbols": ("BTCUSDT",),
            "streams": STREAMS,
            "start": EPOCH + timedelta(microseconds=H0),
            "end": EPOCH + timedelta(microseconds=H0 + MINUTE),
            "source_tier": tier,
        }
    )


async def _drain(tiers: ReplayTiers, tier: str) -> tuple[int, float]:
    started = time.perf_counter()
    count = 0
    async with ReplaySource(_request(tier), tiers) as source:
        async for _ in source:
            count += 1
    return count, time.perf_counter() - started


async def run(delta_rows: int, trades: int, runs: int, workdir: Path) -> dict[str, object]:
    rows = busiest_minute(delta_rows, trades)
    events = [event_from_row(s, r) for s, stream_rows in rows.items() for r in stream_rows]
    memory = SortedTier(events)
    in_memory = ReplayTiers(
        hot=memory, cold=memory, coverage=StaticManifestCoverage(), gaps=StaticGapReader()
    )
    registry = DatasetRegistry(workdir / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, _MemHotSource(rows))
    minute = TimeRange(start_us=H0, end_us=H0 + MINUTE)
    await exporter.export_partition("BTCUSDT", StreamKind.TRADES, minute)
    await exporter.export_partition(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, minute, partition_extra={"hour": "00"}
    )
    reader = ParquetRecordedReader(registry)
    cold = ReplayTiers(
        hot=memory, cold=reader, coverage=StaticManifestCoverage(), gaps=StaticGapReader()
    )
    results: dict[str, list[float]] = {"in_memory": [], "cold_parquet": []}
    try:
        for _ in range(runs):
            for label, tiers, tier in (
                ("in_memory", in_memory, "questdb"),
                ("cold_parquet", cold, "parquet"),
            ):
                count, seconds = await _drain(tiers, tier)
                if count != len(events):
                    raise RuntimeError(f"{label} replayed {count} of {len(events)} events")
                results[label].append(count / seconds)
    finally:
        reader.shutdown()  # its scan pool, as `ReplayWiring.aclose()` does at app stop
    return {
        "events": len(events),
        "events_per_s_p50": {k: round(statistics.median(v)) for k, v in results.items()},
        "k01_baseline_events_per_s": K01_BASELINE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--delta-rows", type=int, default=242_000)
    parser.add_argument("--trades", type=int, default=1_200)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        report = asyncio.run(run(args.delta_rows, args.trades, args.runs, Path(tmp)))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
