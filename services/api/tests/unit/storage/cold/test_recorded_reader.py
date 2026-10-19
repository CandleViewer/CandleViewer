"""`ParquetRecordedReader` (E26-T02) over partitions the production `ColdExporter` wrote."""

from __future__ import annotations

import asyncio
import gc
import importlib
import inspect
import json
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from candleviewer.observability.context import executor_future
from candleviewer.storage.cold import recorded_reader
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore, SchemaRegistry
from candleviewer.storage.cold.observability import Severity, SystemEventSink
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import ColdReplayReadError, ColdReplayReadTimeout
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    ManifestCoverage,
    RecordedEvent,
    RecordedQueryRejected,
    RecordedStreamReader,
    RecordedTrade,
    event_from_row,
)
from tests.unit.storage.cold._replay_rows import (
    H0,
    HOUR,
    SYMBOL,
    MemHotSource,
    generated_rows,
    rows_in,
)

FIRST_HOUR = TimeRange(start_us=H0, end_us=H0 + HOUR)
MINUTE = 60_000_000
NEW_YEAR_2027 = 1_798_761_600_000_000  # 2027-01-01T00:00:00Z


async def _export(root: Path, rows: dict[StreamKind, list[dict[str, object]]]) -> DatasetRegistry:
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource(rows), rows_per_group=64)
    await exporter.export_partition(SYMBOL, StreamKind.TRADES, FIRST_HOUR)
    await exporter.export_partition(
        SYMBOL, StreamKind.ORDERBOOK_DELTA, FIRST_HOUR, partition_extra={"hour": "00"}
    )
    return registry


async def test_exported_rows_read_back_equal_to_the_rows_the_hot_tier_held(
    tmp_path: Path,
) -> None:
    rows = generated_rows()
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", rows))
    window = TimeRange(start_us=H0 + 600_000_000, end_us=H0 + 1_200_000_000)

    trades = await reader.read(SYMBOL, StreamKind.TRADES, window, depth=200, limit=1_000)
    deltas = await reader.read(SYMBOL, StreamKind.ORDERBOOK_DELTA, window, depth=200, limit=1_000)

    want = [event_from_row(StreamKind.TRADES, r) for r in rows_in(rows[StreamKind.TRADES], window)]
    assert trades == want
    assert isinstance(trades[0].payload, RecordedTrade)
    assert len(deltas) == len(rows_in(rows[StreamKind.ORDERBOOK_DELTA], window))
    assert [e.ts_us for e in deltas] == sorted(e.ts_us for e in deltas)


async def test_reads_honour_the_limit_the_depth_and_the_half_open_window(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    edge = TimeRange(start_us=H0 + 20_000_000, end_us=H0 + 60_000_000)

    capped = await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=3)
    in_edge = await reader.read(SYMBOL, StreamKind.TRADES, edge, depth=200, limit=100)
    other_depth = await reader.read(
        SYMBOL, StreamKind.ORDERBOOK_DELTA, FIRST_HOUR, depth=50, limit=100
    )

    assert [e.ts_us for e in capped] == [H0, H0 + 20_000_000, H0 + 40_000_000]
    assert [e.ts_us for e in in_edge] == [H0 + 20_000_000, H0 + 40_000_000]
    assert other_depth == []


@pytest.mark.parametrize("limit", [0, -1, True])
async def test_a_limit_below_one_is_refused_before_any_manifest_is_read(
    tmp_path: Path, limit: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The port's contract (`RecordedStreamReader.read`): refused, never an empty read."""
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))

    def listing_forbidden(*_: object) -> list[object]:
        raise AssertionError("storage was read")

    monkeypatch.setattr(reader, "_partitions", listing_forbidden)

    with pytest.raises(RecordedQueryRejected):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=limit)


async def test_a_window_without_manifested_partitions_reads_nothing(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    later = TimeRange(start_us=H0 + 5 * HOUR, end_us=H0 + 6 * HOUR)

    assert await reader.read(SYMBOL, StreamKind.TRADES, later, depth=200, limit=10) == []
    assert await reader.snapshot_at(SYMBOL, 200, H0 + HOUR, not_before_us=H0) is None


async def test_a_re_export_returns_both_copies_in_part_order_so_the_newest_wins(
    tmp_path: Path,
) -> None:
    rows = generated_rows()
    registry = await _export(tmp_path / "cold", rows)
    rows[StreamKind.TRADES][0] = rows[StreamKind.TRADES][0] | {"size": 9.0}  # a late upsert
    second = TimeRange(start_us=H0, end_us=H0 + 1_800_000_000)
    await ColdExporter(registry, MemHotSource(rows)).export_partition(
        SYMBOL, StreamKind.TRADES, second
    )
    first_instant = TimeRange(start_us=H0, end_us=H0 + 1)

    got = await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.TRADES, first_instant, depth=200, limit=10
    )

    assert [e.tiebreak for e in got] == [("t0000",), ("t0000",)]
    assert [str(e.payload.size) for e in got if isinstance(e.payload, RecordedTrade)] == [
        "0.001",
        "9.0",
    ]


async def test_the_anchor_is_the_latest_snapshot_inside_the_lookback(tmp_path: Path) -> None:
    snaps: list[dict[str, object]] = [
        {
            "ts": H0 + minute * 60_000_000,
            "symbol": SYMBOL,
            "depth": 200,
            "update_id": minute,
            "cross_seq": minute * 10,
            "bids": '[["65000.0","1.5"]]',
            "asks": '[["65000.5","2"]]',
        }
        for minute in range(10)
    ]
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({StreamKind.ORDERBOOK_SNAPSHOT: snaps}))
    await exporter.export_partition(SYMBOL, StreamKind.ORDERBOOK_SNAPSHOT, FIRST_HOUR)
    reader = ParquetRecordedReader(registry)

    anchor = await reader.snapshot_at(SYMBOL, 200, H0 + 330_000_000, not_before_us=H0)
    too_old = await reader.snapshot_at(
        SYMBOL, 200, H0 + 330_000_000, not_before_us=H0 + 310_000_000
    )

    assert anchor is not None and anchor.tiebreak[0] == 5
    assert too_old is None


async def test_a_path_shaped_symbol_is_refused_before_any_read(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))

    with pytest.raises(ColdReplayReadError):
        await reader.read("../../etc", StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)


async def test_a_manifest_naming_a_file_outside_its_partition_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    manifest = root / "_manifests" / "trades" / f"symbol={SYMBOL}" / "dt=2026-10-01.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["entries"][0]["file"] = "../../../outside.parquet"
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks; junction variant below")
async def test_a_part_file_symlinked_outside_the_cold_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    part = next((root / "trades").rglob("part-*.parquet"))
    outside = tmp_path / "outside.parquet"
    part.rename(outside)
    os.symlink(outside, part)

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junction variant of the symlink test")
async def test_a_partition_junction_escaping_the_cold_root_is_refused(tmp_path: Path) -> None:
    winapi = importlib.import_module("_winapi")  # Windows-only stdlib module

    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    partition = root / "trades" / f"symbol={SYMBOL}" / "dt=2026-10-01"
    outside = tmp_path / "outside"
    partition.rename(outside)
    winapi.CreateJunction(str(outside), str(partition))

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


class _Events:
    """A `SystemEventSink` that keeps what it is sent."""

    def __init__(self) -> None:
        self.emitted: list[tuple[Severity, str, dict[str, str | int]]] = []

    async def emit(self, severity: Severity, code: str, detail: dict[str, str | int]) -> None:
        self.emitted.append((severity, code, detail))


def _part(root: Path) -> Path:
    return next((root / "trades").rglob("part-*.parquet"))


def _trades_manifest(root: Path, symbol: str = SYMBOL) -> Path:
    return root / "_manifests" / "trades" / f"symbol={symbol}" / "dt=2026-10-01.json"


def _swap_for_valid_parquet(part: Path) -> None:
    """Rewrite `part` as valid Parquet of the same schema whose sizes all differ."""
    table = pq.read_table(part)
    sizes = pa.array([9.0] * table.num_rows)
    pq.write_table(table.set_column(table.schema.get_field_index("size"), "size", sizes), part)


async def test_a_part_swapped_for_other_valid_parquet_is_refused_and_quarantined(
    tmp_path: Path,
) -> None:
    """The swapped part reads fine as Parquet: only the manifest's SHA-256 can refuse it."""
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    part = _part(root)
    _swap_for_valid_parquet(part)
    events = _Events()

    with pytest.raises(ColdReplayReadError, match="failed verification"):
        await ParquetRecordedReader(registry, events=events).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )

    assert [(severity, code, detail["reason"]) for severity, code, detail in events.emitted] == [
        ("CRITICAL", "STORAGE_COLD_FILE_QUARANTINED", "sha256")
    ]
    quarantined = root / str(events.emitted[0][2]["quarantine"])  # relative to the cold root
    assert not await asyncio.to_thread(part.exists)
    assert await asyncio.to_thread(quarantined.exists)


@pytest.mark.parametrize("field", ["sha256", "row_count"])
async def test_a_manifest_that_disagrees_with_an_intact_part_is_refused(
    tmp_path: Path, field: str
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    manifest = _trades_manifest(root)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    entry = doc["entries"][0]
    entry[field] = "0" * 64 if field == "sha256" else entry[field] + 1
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ColdReplayReadError, match="failed verification"):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


async def test_every_swapped_part_is_refused_by_verification_never_served(tmp_path: Path) -> None:
    """Verification stops at a partition's first bad part, so the next read verifies again and
    refuses the second, rather than serve it as if the failed pass had cleared it."""
    root = tmp_path / "cold"
    rows = generated_rows()
    registry = await _export(root, rows)
    half_hour = TimeRange(start_us=H0, end_us=H0 + 1_800_000_000)  # another range: a second part
    await ColdExporter(registry, MemHotSource(rows)).export_partition(
        SYMBOL, StreamKind.TRADES, half_hour
    )
    parts = sorted((root / "trades").rglob("part-*.parquet"))
    assert len(parts) == 2
    for part in parts:
        _swap_for_valid_parquet(part)
    events = _Events()
    reader = ParquetRecordedReader(registry, events=events)

    for _ in parts:
        with pytest.raises(ColdReplayReadError, match="failed verification"):
            await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    assert [detail["reason"] for _, _, detail in events.emitted] == ["sha256", "sha256"]


def _count_verifications(monkeypatch: pytest.MonkeyPatch) -> list[ColdPaths]:
    calls: list[ColdPaths] = []
    real = verify_partition

    async def counting(paths: ColdPaths, events: SystemEventSink) -> bool:
        calls.append(paths)
        return await real(paths, events)

    monkeypatch.setattr(recorded_reader, "verify_partition", counting)
    return calls


async def test_a_partition_is_verified_once_then_again_when_a_part_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verified on first read; an unchanged part is not hashed again; a new mtime or a new
    ctime alone (what `utime` cannot set back) re-verifies."""
    root = tmp_path / "cold"
    reader = ParquetRecordedReader(await _export(root, generated_rows()))
    calls = _count_verifications(monkeypatch)
    part = _part(root)

    async def read() -> None:
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    await read()
    await read()
    assert len(calls) == 1
    stat = part.stat()
    os.utime(part, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    await read()
    assert len(calls) == 2
    stat = part.stat()
    os.utime(part, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # the same mtime: only ctime moves
    await read()
    assert len(calls) == 3


async def test_a_part_rewritten_to_another_size_is_refused_on_the_next_read(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    reader = ParquetRecordedReader(await _export(root, generated_rows()))
    assert await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=1_000)
    part = _part(root)
    before = part.stat()
    table = pq.read_table(part)
    pq.write_table(table.slice(0, table.num_rows - 1), part)  # still valid Parquet
    os.utime(part, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(ColdReplayReadError):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=1_000)


async def test_a_part_added_after_the_first_read_is_verified_before_it_is_served(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    reader = ParquetRecordedReader(registry)
    await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)
    await ColdExporter(registry, MemHotSource(generated_rows())).export_partition(
        SYMBOL, StreamKind.TRADES, TimeRange(start_us=H0, end_us=H0 + 30 * MINUTE)
    )
    added = _part(root).with_name("part-0001.parquet")
    table = pq.read_table(added)
    pq.write_table(table.slice(0, table.num_rows - 1), added)  # not the manifested bytes

    with pytest.raises(ColdReplayReadError):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)


async def test_coverage_is_what_the_manifests_name_clipped_to_the_range(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    around = TimeRange(start_us=H0 - HOUR, end_us=H0 + 3 * HOUR)
    inside = TimeRange(start_us=H0 + 60_000_000, end_us=H0 + 120_000_000)

    assert await reader.archived(SYMBOL, StreamKind.TRADES, around) == [FIRST_HOUR]
    assert await reader.archived(SYMBOL, StreamKind.ORDERBOOK_DELTA, inside) == [inside]
    assert await reader.archived(SYMBOL, StreamKind.TICKERS, around) == []
    assert await reader.archived("ETHUSDT", StreamKind.TRADES, around) == []


async def test_a_coverage_lookup_the_registry_refuses_is_typed(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))

    with pytest.raises(ColdReplayReadError):
        await reader.archived("../../etc", StreamKind.TRADES, FIRST_HOUR)


async def test_coverage_spans_every_partition_of_the_window(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource(generated_rows()), rows_per_group=64)
    for hour in (0, 1):
        await exporter.export_partition(
            SYMBOL,
            StreamKind.ORDERBOOK_DELTA,
            TimeRange(start_us=H0 + hour * HOUR, end_us=H0 + (hour + 1) * HOUR),
            partition_extra={"hour": f"{hour:02d}"},
        )
    reader = ParquetRecordedReader(registry)
    across = TimeRange(start_us=H0 + 30 * MINUTE, end_us=H0 + 90 * MINUTE)
    both = TimeRange(start_us=H0, end_us=H0 + 2 * HOUR)

    assert await reader.archived(SYMBOL, StreamKind.ORDERBOOK_DELTA, across) == [across]
    assert await reader.archived(SYMBOL, StreamKind.ORDERBOOK_DELTA, both) == [both]


async def test_a_window_that_only_touches_the_archive_is_not_covered(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    after = TimeRange(start_us=H0 + HOUR, end_us=H0 + 2 * HOUR)  # starts where the export ends

    assert await reader.archived(SYMBOL, StreamKind.TRADES, after) == []


async def test_kline_coverage_is_read_from_the_month_trees_of_every_interval(
    tmp_path: Path,
) -> None:
    """Klines keep one month tree per interval: coverage is every tree's manifests, merged."""
    bar: dict[str, object] = {
        "ts": H0,
        "symbol": SYMBOL,
        "interval": "1",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 3.0,
        "turnover": 4.5,
        "confirmed": True,
    }
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    later = TimeRange(start_us=H0 + HOUR, end_us=H0 + 2 * HOUR)
    for interval, rng in (("1", FIRST_HOUR), ("5", later)):
        rows = [bar | {"ts": rng.start_us, "interval": interval}]
        await ColdExporter(registry, MemHotSource({StreamKind.KLINES: rows})).export_partition(
            SYMBOL, StreamKind.KLINES, rng, partition_extra={"interval": interval, "ym": "2026-10"}
        )
    both = TimeRange(start_us=H0, end_us=H0 + 2 * HOUR)

    assert await ParquetRecordedReader(registry).archived(SYMBOL, StreamKind.KLINES, both) == [both]


async def test_an_empty_coverage_window_names_nothing(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    empty = TimeRange(start_us=H0 + 5, end_us=H0 + 5)

    assert await reader.archived(SYMBOL, StreamKind.TRADES, empty) == []


async def test_coverage_reads_its_manifests_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    threads: list[int] = []
    real = ManifestStore.read

    def spy(self: ManifestStore, partition_dir: Path, cold_root: Path) -> list[Any]:
        threads.append(threading.get_ident())
        return real(self, partition_dir, cold_root)

    monkeypatch.setattr(ManifestStore, "read", spy)

    assert await reader.archived(SYMBOL, StreamKind.TRADES, FIRST_HOUR) == [FIRST_HOUR]
    assert threads and threading.get_ident() not in threads  # never the loop's thread


@pytest.mark.parametrize("bad", ["0", None, 1.5, True, [0]], ids=repr)
@pytest.mark.parametrize("field", ["range_start_us", "range_end_us"])
async def test_a_coverage_range_that_is_not_integral_is_a_typed_error(
    tmp_path: Path, field: str, bad: object
) -> None:
    """Corrupt coverage metadata is refused typed, never a bare `TypeError` from the span
    arithmetic, and never coverage a bool or a float happens to compare as."""
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    manifest = _trades_manifest(root)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["entries"][0][field] = bad
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).archived(SYMBOL, StreamKind.TRADES, FIRST_HOUR)


def test_the_cold_reader_is_addressed_by_stream_id_never_by_path(tmp_path: Path) -> None:
    """SR-097 / ticket AC 5: the public surface takes a registry, never a filesystem path."""
    reader = ParquetRecordedReader(DatasetRegistry(tmp_path))
    assert isinstance(reader, RecordedStreamReader) and isinstance(reader, ManifestCoverage)
    for member in (
        ParquetRecordedReader.__init__,
        ParquetRecordedReader.read,
        ParquetRecordedReader.snapshot_at,
        ParquetRecordedReader.archived,
    ):
        for name, param in inspect.signature(member).parameters.items():
            assert "path" not in name and "path" not in str(param.annotation).lower()


@pytest.mark.parametrize(
    ("template", "hours", "keys"),
    [
        (
            ("symbol", "dt", "hour"),
            2,
            [{"dt": "2026-10-01", "hour": "00"}, {"dt": "2026-10-01", "hour": "01"}],
        ),
        (("symbol", "dt"), 30, [{"dt": "2026-10-01"}, {"dt": "2026-10-02"}]),
        (("symbol", "ym"), 24 * 31 + 1, [{"ym": "2026-10"}, {"ym": "2026-11"}]),
        (("symbol", "y"), 24 * 366, [{"y": "2026"}, {"y": "2027"}]),
    ],
)
def test_time_keys_name_every_partition_overlapping_the_window(
    template: tuple[str, ...], hours: int, keys: list[dict[str, str]]
) -> None:
    assert recorded_reader._time_keys(template, H0, H0 + hours * HOUR) == keys


async def test_klines_are_read_across_their_interval_partitions(tmp_path: Path) -> None:
    bar: dict[str, object] = {
        "ts": H0,
        "symbol": SYMBOL,
        "interval": "1",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 3.0,
        "turnover": 4.5,
        "confirmed": True,
    }
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({StreamKind.KLINES: [bar]}))
    await exporter.export_partition(
        SYMBOL, StreamKind.KLINES, FIRST_HOUR, partition_extra={"interval": "1", "ym": "2026-10"}
    )

    got = await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.KLINES, FIRST_HOUR, depth=200, limit=10
    )

    assert [e.tiebreak for e in got] == [("1",)]


async def test_a_day_without_any_export_reads_nothing(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    next_day = TimeRange(start_us=H0 + 24 * HOUR, end_us=H0 + 25 * HOUR)

    assert await reader.read(SYMBOL, StreamKind.TRADES, next_day, depth=200, limit=10) == []


async def test_a_reader_asked_for_no_concurrency_still_runs_one_scan(tmp_path: Path) -> None:
    registry = await _export(tmp_path / "cold", generated_rows())
    reader = ParquetRecordedReader(registry, max_concurrency=0)

    async with asyncio.timeout(30):  # a semaphore of no slots would never let the read in
        got = await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    assert got and got == await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
    )


async def test_a_read_spanning_too_many_partitions_is_refused(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))
    fifty_days = TimeRange(start_us=H0, end_us=H0 + 50 * 24 * HOUR)

    with pytest.raises(ColdReplayReadError):
        await reader.read(SYMBOL, StreamKind.ORDERBOOK_DELTA, fifty_days, depth=200, limit=10)


async def test_a_manifest_naming_a_missing_part_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    part = next((root / "trades").rglob("part-*.parquet"))
    part.rename(part.with_name("part-0042.parquet"))

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


def test_a_duckdb_failure_is_a_typed_cold_read_error(tmp_path: Path) -> None:
    """DuckDB's own text may name a path (RP-I02): the typed error holds neither it nor a
    chain."""
    files: dict[str, object] = {"files": [(tmp_path / "gone" / "part-0000.parquet").as_posix()]}

    with pytest.raises(ColdReplayReadError) as caught:
        recorded_reader._Scan(tmp_path).run(
            "SELECT * FROM read_parquet($files)", files, StreamKind.TRADES
        )

    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert str(tmp_path) not in str(caught.value)


def test_the_scan_connection_may_open_nothing_outside_the_cold_root(tmp_path: Path) -> None:
    """Defence in depth behind the path checks (SR-097): DuckDB itself refuses the file."""
    root = tmp_path / "cold"
    root.mkdir()
    outside = tmp_path / "outside.parquet"
    pq.write_table(pa.table({"ts": [1]}), outside)
    sql = "SELECT * FROM read_parquet($files)"

    with pytest.raises(ColdReplayReadError):
        recorded_reader._Scan(root).run(sql, {"files": [outside.as_posix()]}, StreamKind.TRADES)


def test_a_scan_connection_is_memory_and_thread_bounded() -> None:
    con = recorded_reader._connect()
    try:
        limit = con.execute("SELECT current_setting('memory_limit')").fetchone()
        threads = con.execute("SELECT current_setting('threads')").fetchone()
    finally:
        con.close()
    assert limit is not None and str(limit[0]).startswith("256") and "MiB" in str(limit[0])
    assert threads is not None and int(threads[0]) == 2


def test_no_statement_of_a_scan_can_loosen_its_bounds(tmp_path: Path) -> None:
    """The scan's configuration is locked once it is confined: raising the memory limit is
    refused (unlocked, the SET would pass and only the row mapping would fail)."""
    with pytest.raises(ColdReplayReadError):
        recorded_reader._Scan(tmp_path).run(
            "SET memory_limit = '8GiB'; SELECT 1 AS ts", {}, StreamKind.TRADES
        )


class _Con:
    """A DuckDB connection stand-in for the scan machinery. Like DuckDB, it drops an
    `interrupt()` unless a statement is running. Its main statement ends with rows, its own
    failure, or (by default) only once interrupted, then lingers until `linger` is set."""

    def __init__(self, outcome: Literal["interrupted", "fails", "rows"] = "interrupted") -> None:
        self.outcome = outcome
        self.statements: list[str] = []
        self.reached = threading.Event()  # the worker is at the main statement
        self.arrivals = threading.Semaphore(0)  # released once per main statement reached
        self.go = threading.Event()  # the main statement may start running
        self.go.set()
        self.interrupted = threading.Event()
        self.linger = threading.Event()
        self.linger.set()
        self.closed_on: int | None = None
        self._running = False
        self._lock = threading.Lock()

    def execute(self, sql: str, params: object = None) -> _Con:
        self.statements.append(sql)
        if sql.startswith("SET "):
            return self
        self.reached.set()
        self.arrivals.release()
        assert self.go.wait(timeout=5), "the test never let the statement start"
        if self.outcome == "rows":
            return self
        if self.outcome == "fails":
            raise duckdb.IOException("IO Error: no such file")
        with self._lock:
            self._running = True
        try:
            assert self.interrupted.wait(timeout=5), "the statement was never interrupted"
            assert self.linger.wait(timeout=5)
            raise duckdb.InterruptException("INTERRUPT Error: Interrupted!")
        finally:
            with self._lock:
                self._running = False

    def to_arrow_table(self) -> pa.Table:
        return pa.table({"ts": pa.array([], pa.int64())})

    def interrupt(self) -> None:
        with self._lock:
            if self._running:
                self.interrupted.set()

    def close(self) -> None:
        self.closed_on = threading.get_ident()


class _Started(list[recorded_reader._Scan]):
    """The scans a reader started, in order; `reach(n)` waits until `n` have started."""

    def __init__(self) -> None:
        super().__init__()
        self._waits: dict[int, asyncio.Event] = {}

    def add(self, scan: recorded_reader._Scan) -> None:
        self.append(scan)
        for count, event in self._waits.items():
            if len(self) >= count:
                event.set()

    async def reach(self, count: int) -> None:
        if len(self) < count:
            await asyncio.wait_for(self._waits.setdefault(count, asyncio.Event()).wait(), 5)


def _with_con(monkeypatch: pytest.MonkeyPatch, con: _Con) -> _Started:
    """Every `_Scan` the reader starts, connected to `con`."""
    monkeypatch.setattr(recorded_reader, "_connect", lambda: con)
    started = _Started()

    class _Seen(recorded_reader._Scan):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            started.add(self)

    monkeypatch.setattr(recorded_reader, "_Scan", _Seen)
    return started


async def _registry(tmp_path: Path) -> DatasetRegistry:
    return await _export(tmp_path / "cold", generated_rows())


def _read(reader: ParquetRecordedReader) -> asyncio.Task[list[RecordedEvent]]:
    return asyncio.create_task(
        reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)
    )


async def test_a_scan_past_its_deadline_is_interrupted_closed_by_its_worker_and_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _Con()
    _with_con(monkeypatch, con)
    reader = ParquetRecordedReader(await _registry(tmp_path), timeout_s=0.05)

    with pytest.raises(ColdReplayReadTimeout):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    assert con.interrupted.is_set()
    assert con.closed_on is not None and con.closed_on != threading.get_ident()  # not the loop


async def test_a_scan_failing_by_itself_is_typed_and_closed_by_its_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _Con("fails")
    _with_con(monkeypatch, con)

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(await _registry(tmp_path)).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )

    assert con.closed_on is not None and con.closed_on != threading.get_ident()


async def test_a_duckdb_failure_at_connect_is_typed_and_frees_the_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def out_of_memory() -> duckdb.DuckDBPyConnection:
        raise duckdb.OutOfMemoryException("Out of Memory Error: could not allocate a block")

    monkeypatch.setattr(recorded_reader, "_connect", out_of_memory)
    reader = ParquetRecordedReader(await _registry(tmp_path), max_concurrency=1)

    with pytest.raises(ColdReplayReadError):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    assert not reader._sem.locked()


async def test_a_cancelled_read_holds_its_slot_until_the_scan_has_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18: no DuckDB scan outlives its slot, even if cancelled again while it stops."""
    con = _Con()
    _with_con(monkeypatch, con)
    con.linger.clear()  # the scan lingers after its interrupt
    task = _read(ParquetRecordedReader(await _registry(tmp_path), max_concurrency=1))
    assert await asyncio.to_thread(con.reached.wait, 5)

    task.cancel()
    assert await asyncio.to_thread(con.interrupted.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()  # still holding the slot: the scan has not stopped yet
    con.linger.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert con.closed_on is not None and con.closed_on != threading.get_ident()


async def test_an_interrupt_lost_before_the_statement_starts_is_repeated_until_it_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DuckDB drops an interrupt that arrives before a statement runs: the read repeats it."""
    con = _Con()
    _with_con(monkeypatch, con)
    con.go.clear()  # the worker sits just before the statement
    task = _read(ParquetRecordedReader(await _registry(tmp_path)))
    assert await asyncio.to_thread(con.reached.wait, 5)

    task.cancel()
    for _ in range(3):
        await asyncio.sleep(0)
    assert not con.interrupted.is_set()  # lost: nothing was running yet
    con.go.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert con.interrupted.is_set()


async def test_a_read_stopped_before_its_scan_starts_never_runs_the_statement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _Con("rows")
    entered, gate = threading.Event(), threading.Event()

    def slow_connect() -> _Con:
        entered.set()
        assert gate.wait(timeout=5)
        return con

    started = _with_con(monkeypatch, con)
    monkeypatch.setattr(recorded_reader, "_connect", slow_connect)
    task = _read(ParquetRecordedReader(await _registry(tmp_path)))
    assert await asyncio.to_thread(entered.wait, 5)

    task.cancel()
    await started.reach(1)
    assert await asyncio.to_thread(started[0].stop.wait, 5)
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert all(sql.startswith("SET ") for sql in con.statements)
    assert con.closed_on is not None and con.closed_on != threading.get_ident()


def _submissions(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Set once the reader hands a scan to its pool."""
    submitted = asyncio.Event()
    real = executor_future

    def spy(pool: Executor, fn: Callable[..., Any], /, *args: Any) -> asyncio.Future[Any]:
        job = real(pool, fn, *args)
        submitted.set()
        return job

    monkeypatch.setattr(recorded_reader, "executor_future", spy)
    return submitted


async def _occupy(reader: ParquetRecordedReader) -> tuple[threading.Event, Future[None]]:
    """Take the reader's only pool thread until the returned event is set."""
    busy, free = threading.Event(), threading.Event()

    def hold() -> None:
        busy.set()
        assert free.wait(timeout=5)

    held = reader._pool.submit(hold)
    assert await asyncio.to_thread(busy.wait, 5)
    return free, held


async def test_a_scan_queued_when_its_read_is_cancelled_runs_stops_and_frees_the_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan still waiting for a thread when its read is cancelled (by a supervisor, or by
    event-loop teardown, which cancels every task) is never lost: once a thread frees it runs,
    sees the stop and returns without connecting, and the read holds its slot until then."""
    connected: list[int] = []

    def connect() -> duckdb.DuckDBPyConnection:
        connected.append(threading.get_ident())
        return duckdb.connect(":memory:")

    monkeypatch.setattr(recorded_reader, "_connect", connect)
    submitted = _submissions(monkeypatch)
    reader = ParquetRecordedReader(await _registry(tmp_path), max_concurrency=1)
    free, held = await _occupy(reader)
    task = _read(reader)
    await asyncio.wait_for(submitted.wait(), 5)

    task.cancel()
    for _ in range(3):
        await asyncio.sleep(0)
    assert not task.done()  # holds its slot: the queued scan has not run yet
    free.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert connected == []
    assert not reader._sem.locked()
    await asyncio.wrap_future(held)


async def test_a_shut_down_reader_refuses_a_read_typed(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _registry(tmp_path))
    reader.shutdown()

    with pytest.raises(ColdReplayReadError, match="shut down"):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)


async def test_a_scan_queued_at_shutdown_fails_its_read_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dropped scan's read fails typed, and its cancelled future is never reported to the
    loop as an error (marking it retrieved must not touch a cancelled future)."""
    reports: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, context: reports.append(context))
    try:
        submitted = _submissions(monkeypatch)
        reader = ParquetRecordedReader(await _registry(tmp_path), max_concurrency=1)
        free, held = await _occupy(reader)
        task = _read(reader)
        await asyncio.wait_for(submitted.wait(), 5)

        reader.shutdown()

        with pytest.raises(ColdReplayReadError, match="shut down"):
            await task
        free.set()
        await asyncio.wrap_future(held)
    finally:
        loop.set_exception_handler(None)

    assert [r["message"] for r in reports] == []


async def test_at_most_max_concurrency_scans_run_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _Con("rows")
    con.go.clear()
    started = _with_con(monkeypatch, con)
    reader = ParquetRecordedReader(await _registry(tmp_path), max_concurrency=2)
    reads = [_read(reader) for _ in range(3)]

    for _ in range(2):  # two scans run at once: each has reached its statement
        assert await asyncio.to_thread(con.arrivals.acquire, True, 5)
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(started) == 2  # the third read waits for a slot
    con.go.set()
    await asyncio.gather(*reads)
    assert len(started) == 3


async def test_a_cancel_while_a_timed_out_scan_stops_is_re_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancellation that arrives while the read waits for a timed-out scan is not turned
    into the typed timeout."""
    con = _Con()
    _with_con(monkeypatch, con)
    con.linger.clear()
    task = _read(ParquetRecordedReader(await _registry(tmp_path), timeout_s=0.05))
    assert await asyncio.to_thread(con.interrupted.wait, 5)  # the deadline fired

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    con.linger.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_stopped_scan_leaves_no_unretrieved_error_for_the_loop_to_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stopped scan fails in its thread, and the read reports its own error instead: the
    scan's is marked retrieved, so the loop never logs it as one nobody retrieved."""
    reports: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, context: reports.append(context))
    try:
        _with_con(monkeypatch, _Con())
        reader = ParquetRecordedReader(await _registry(tmp_path), timeout_s=0.05)
        with pytest.raises(ColdReplayReadTimeout) as caught:
            await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)
        del caught  # its traceback holds the read's frame, and with it the scan's future
        gc.collect()
    finally:
        loop.set_exception_handler(None)

    assert [r["message"] for r in reports] == []


def _all_resolved(files: list[str]) -> bool:
    return all(Path(f) == Path(f).resolve() for f in files)


def _link_dir(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        importlib.import_module("_winapi").CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


async def test_duckdb_opens_the_resolved_part_path_never_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    partition = root / "trades" / f"symbol={SYMBOL}" / "dt=2026-10-01"
    moved = root / "relocated"
    partition.rename(moved)
    _link_dir(moved, partition)  # a link that stays inside the root is allowed
    opened: list[str] = []
    real = recorded_reader._Scan.run

    def spy(
        self: recorded_reader._Scan, sql: str, params: dict[str, object], stream: StreamKind
    ) -> list[RecordedEvent]:
        files = params["files"]
        assert isinstance(files, list)
        opened.extend(str(f) for f in files)
        return real(self, sql, params, stream)

    monkeypatch.setattr(recorded_reader._Scan, "run", spy)

    got = await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=1_000
    )

    assert len(got) == len(rows_in(generated_rows()[StreamKind.TRADES], FIRST_HOUR))
    assert opened and _all_resolved(opened) and all("relocated" in f for f in opened)


async def _tied(root: Path, update_ids: list[int]) -> ParquetRecordedReader:
    """Snapshots of one depth at one instant, one per book epoch, in a real cold partition."""
    snaps: list[dict[str, object]] = [
        {
            "ts": H0 + 60_000_000,
            "symbol": SYMBOL,
            "depth": 200,
            "epoch_id": epoch,
            "update_id": update_id,
            "cross_seq": None,
            "bids": '[["65000.0","1.5"]]',
            "asks": '[["65000.5","2"]]',
        }
        for epoch, update_id in enumerate(update_ids)
    ]
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({StreamKind.ORDERBOOK_SNAPSHOT: snaps}))
    await exporter.export_partition(SYMBOL, StreamKind.ORDERBOOK_SNAPSHOT, FIRST_HOUR)
    return ParquetRecordedReader(registry)


async def test_snapshots_sharing_the_latest_instant_resolve_by_the_order_key(
    tmp_path: Path,
) -> None:
    """Same row whichever tier answers (24 Sec.13.7): never the part or row order of a tie."""
    reader = await _tied(tmp_path / "cold", [9, 3])

    anchor = await reader.snapshot_at(SYMBOL, 200, H0 + 120_000_000, not_before_us=H0)

    assert anchor is not None and anchor.seq == 9


async def test_an_anchor_tie_wider_than_the_lookup_is_refused_not_guessed(tmp_path: Path) -> None:
    reader = await _tied(tmp_path / "cold", list(range(16)))

    with pytest.raises(ColdReplayReadError):
        await reader.snapshot_at(SYMBOL, 200, H0 + 120_000_000, not_before_us=H0)


async def test_a_tie_one_row_wider_than_the_lookup_is_refused(tmp_path: Path) -> None:
    """17 snapshots share the instant: the 16-row read cannot see them all, so it refuses."""
    reader = await _tied(tmp_path / "cold", list(range(17)))

    with pytest.raises(ColdReplayReadError, match="share one instant"):
        await reader.snapshot_at(SYMBOL, 200, H0 + 120_000_000, not_before_us=H0)


def _book(
    ts: int, epoch: int, update_id: int, bids: str = '[["65000.0","1.5"]]'
) -> dict[str, object]:
    return {
        "ts": ts,
        "symbol": SYMBOL,
        "depth": 200,
        "epoch_id": epoch,
        "update_id": update_id,
        "cross_seq": None,
        "bids": bids,
        "asks": '[["65000.5","2"]]',
    }


async def test_a_full_read_spanning_two_instants_is_resolved_at_the_newest_instant(
    tmp_path: Path,
) -> None:
    """15 snapshots at the newest instant and an older one fill the 16-row read: no tie, and
    the older snapshot never wins, though its update id is the largest."""
    newest = H0 + 2 * MINUTE
    ids = [4, 11, 7, 2, 9, 5, 13, 1, 8, 3, 12, 6, 10, 14, 0]
    rows = [_book(H0 + MINUTE, 99, 999), *(_book(newest, e, u) for e, u in enumerate(ids))]
    reader = ParquetRecordedReader(await _snapshots(tmp_path / "cold", rows))

    anchor = await reader.snapshot_at(SYMBOL, 200, H0 + 3 * MINUTE, not_before_us=H0)

    assert anchor is not None and (anchor.ts_us, anchor.seq) == (newest, 14)


async def test_the_anchor_lookup_reads_the_newest_rows_and_states_its_bound_once(
    tmp_path: Path,
) -> None:
    """20 snapshots at distinct instants overfill the 16-row read: it must be the newest 16,
    and the read binds the same row count the tie check counts against."""
    rows = [_book(H0 + m * MINUTE, 0, m) for m in range(20)]
    reader = ParquetRecordedReader(await _snapshots(tmp_path / "cold", rows))

    anchor = await reader.snapshot_at(SYMBOL, 200, H0 + 30 * MINUTE, not_before_us=H0)

    assert anchor is not None and (anchor.ts_us, anchor.seq) == (H0 + 19 * MINUTE, 19)
    assert recorded_reader._ANCHOR_SQL.endswith(" LIMIT $n")  # bound: one constant, not two


async def test_snapshots_alike_but_for_their_book_epoch_resolve_by_the_full_order_key(
    tmp_path: Path,
) -> None:
    """Same instant, same update id, two book epochs: the tiebreak decides, not where each row
    happens to sit in its part (the later epoch is written first here)."""
    at = H0 + MINUTE
    rows = [_book(at, 1, 7, bids='[["64999.0","3"]]'), _book(at, 0, 7)]
    reader = ParquetRecordedReader(await _snapshots(tmp_path / "cold", rows))

    anchor = await reader.snapshot_at(SYMBOL, 200, at, not_before_us=H0)

    assert anchor == event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, rows[0])
    assert anchor is not None and anchor.tiebreak == (7, 200, 1)


async def test_of_two_copies_of_the_anchor_in_one_part_the_later_row_is_returned(
    tmp_path: Path,
) -> None:
    """The same key twice in one part: the copy written last wins, as across parts."""
    at = H0 + MINUTE
    rows = [_book(at, 0, 5), _book(at, 0, 5, bids='[["64999.0","3"]]')]
    reader = ParquetRecordedReader(await _snapshots(tmp_path / "cold", rows))

    anchor = await reader.snapshot_at(SYMBOL, 200, at, not_before_us=H0)

    assert anchor == event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, rows[1])


async def test_of_two_exported_copies_of_the_anchor_the_later_part_is_returned(
    tmp_path: Path,
) -> None:
    """A re-export leaves the snapshot in two parts: the anchor is the copy in the later part,
    the one the merge would keep (21 Sec.5.3), never whichever the scan met first."""
    at = H0 + MINUTE
    old, new = _book(at, 0, 5), _book(at, 0, 5, bids='[["64999.0","3"]]')
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    snapshots = StreamKind.ORDERBOOK_SNAPSHOT
    await ColdExporter(registry, MemHotSource({snapshots: [old]})).export_partition(
        SYMBOL, snapshots, FIRST_HOUR
    )
    await ColdExporter(registry, MemHotSource({snapshots: [new]})).export_partition(
        SYMBOL,
        snapshots,
        TimeRange(start_us=H0, end_us=H0 + 30 * MINUTE),  # a second part
    )

    anchor = await ParquetRecordedReader(registry).snapshot_at(SYMBOL, 200, at, not_before_us=H0)

    assert anchor == event_from_row(snapshots, new) != event_from_row(snapshots, old)


async def test_an_unreadable_partition_listing_is_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = await _export(tmp_path / "cold", generated_rows())

    def denied(self: ManifestStore, partition_dir: Path, cold_root: Path) -> list[object]:
        raise PermissionError("cold volume unreadable")

    monkeypatch.setattr(ManifestStore, "read", denied)

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


# --- SR-097: the part-file rule and partition containment, each on its own ------------------
async def test_a_manifest_naming_a_non_part_file_of_its_own_partition_is_refused(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    part = _part(root)
    (part.parent / "notes.parquet").write_bytes(part.read_bytes())  # inside the partition
    manifest = _trades_manifest(root)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["entries"][0]["file"] = "notes.parquet"
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
async def test_a_part_linked_to_another_partitions_part_inside_the_root_is_refused(
    tmp_path: Path,
) -> None:
    """The link is a part-file name inside the root, and the manifest entry matches the bytes
    it reaches: only the partition containment refuses it."""
    root = tmp_path / "cold"
    rows = generated_rows()
    registry = await _export(root, rows)
    eth = {StreamKind.TRADES: [r | {"symbol": "ETHUSDT"} for r in rows[StreamKind.TRADES]]}
    await ColdExporter(registry, MemHotSource(eth), rows_per_group=64).export_partition(
        "ETHUSDT", StreamKind.TRADES, FIRST_HOUR
    )
    theirs = next((root / "trades" / "symbol=ETHUSDT").rglob("part-0000.parquet"))
    os.symlink(theirs, _part(root).with_name("part-0001.parquet"))
    manifest = _trades_manifest(root)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    their_doc = json.loads(_trades_manifest(root, "ETHUSDT").read_text(encoding="utf-8"))
    doc["entries"].append(their_doc["entries"][0] | {"file": "part-0001.parquet"})
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


# --- corrupt storage stays inside the typed family, and names no path -----------------------
async def _refusal(registry: DatasetRegistry) -> ColdReplayReadError:
    with pytest.raises(ColdReplayReadError) as raised:
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )
    return raised.value


async def test_a_manifest_that_is_not_text_is_a_typed_error(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    _trades_manifest(root).write_bytes(b"\xff\xfe\x00 not utf-8")

    error = await _refusal(registry)

    assert error.__cause__ is None and error.__suppress_context__


async def test_a_manifest_that_is_not_json_is_a_typed_error(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    _trades_manifest(root).write_text("{not json", encoding="utf-8")

    await _refusal(registry)


async def test_a_manifest_nested_deeper_than_the_parser_can_go_is_a_typed_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    _trades_manifest(root).write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")

    error = await _refusal(registry)

    assert error.__cause__ is None and error.__suppress_context__


async def test_a_manifest_with_an_integer_past_the_digit_limit_is_a_typed_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    doc = '{"layout_version": 1, "entries": [], "x": ' + "9" * 5_000 + "}"
    _trades_manifest(root).write_text(doc, encoding="utf-8")
    limit = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4_300)  # the default, whatever PYTHONINTMAXSTRDIGITS says
    try:
        await _refusal(registry)
    finally:
        sys.set_int_max_str_digits(limit)


async def test_an_unreadable_listing_is_typed_and_chains_no_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = await _export(tmp_path / "cold", generated_rows())

    def denied(self: ManifestStore, partition_dir: Path, cold_root: Path) -> list[object]:
        raise PermissionError(13, "denied", str(tmp_path / "cold" / "secret-path"))

    monkeypatch.setattr(ManifestStore, "read", denied)

    error = await _refusal(registry)

    assert error.__cause__ is None and error.__suppress_context__
    assert str(tmp_path) not in str(error)


async def test_a_failed_verification_chains_no_cause(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    _swap_for_valid_parquet(_part(root))

    error = await _refusal(registry)

    assert error.__cause__ is None and error.__suppress_context__


async def test_a_manifest_entry_whose_file_is_not_text_is_a_typed_error(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    manifest = _trades_manifest(root)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["entries"][0]["file"] = 5
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    await _refusal(registry)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink loop")
async def test_a_part_symlink_loop_is_a_typed_error_that_names_no_path(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    part = _part(root)
    part.unlink()
    os.symlink(part.name, part)  # part-0000.parquet -> part-0000.parquet

    error = await _refusal(registry)

    assert str(tmp_path) not in str(error)
    assert error.__cause__ is None and error.__suppress_context__


# --- partition keys: unaligned windows, the year edge, the cap, refused before built --------
def test_an_unaligned_window_names_every_partition_it_touches() -> None:
    hours = recorded_reader._time_keys(
        ("symbol", "dt", "hour"), H0 + 90 * MINUTE, H0 + 130 * MINUTE
    )
    days = recorded_reader._time_keys(
        ("symbol", "dt"), H0 + 23 * HOUR + 30 * MINUTE, H0 + 24 * HOUR + 30 * MINUTE
    )

    assert [k["hour"] for k in hours] == ["01", "02"]
    assert [k["dt"] for k in days] == ["2026-10-01", "2026-10-02"]


def test_a_window_ending_on_new_year_does_not_name_the_next_year() -> None:
    keys = recorded_reader._time_keys(("symbol", "y"), NEW_YEAR_2027 - HOUR, NEW_YEAR_2027)

    assert keys == [{"y": "2026"}]


@pytest.mark.parametrize(
    "template",
    [("symbol", "dt", "hour"), ("symbol", "dt"), ("symbol", "ym"), ("symbol", "y")],
    ids=["hours", "days", "months", "years"],
)
def test_an_empty_window_names_no_partition(template: tuple[str, ...]) -> None:
    """Mid-period on purpose: the window's last instant (`hi - 1`) then precedes its first."""
    mid_month = H0 + 5 * 24 * HOUR + 30 * MINUTE

    assert recorded_reader._time_keys(template, mid_month, mid_month) == []


@pytest.mark.parametrize(
    ("template", "step", "edge"),
    [(("symbol", "dt", "hour"), HOUR, H0), (("symbol", "dt"), 24 * HOUR, H0 + HOUR)],
    ids=["hours", "days-from-an-unaligned-start"],
)
def test_exactly_the_cap_of_partitions_is_allowed_one_more_is_refused(
    template: tuple[str, ...], step: int, edge: int
) -> None:
    aligned = edge - edge % step
    assert len(recorded_reader._time_keys(template, edge, aligned + 1_000 * step)) == 1_000

    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(template, edge, aligned + 1_000 * step + 1)


def test_a_huge_window_is_refused_before_any_key_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(_us: int) -> object:
        raise AssertionError("a key was built")

    monkeypatch.setattr(recorded_reader, "_moment", never)

    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(("symbol", "dt", "hour"), H0, H0 + 10 * 366 * 24 * HOUR)


@pytest.mark.parametrize(
    "width_us",
    [100 * 366 * 24 * HOUR, recorded_reader._MAX_PARTITIONS * 31 * 24 * HOUR + 1],
    ids=["a-century", "one-past-the-month-guard"],
)
def test_a_month_window_far_wider_than_one_read_is_refused_before_any_key_is_built(
    monkeypatch: pytest.MonkeyPatch, width_us: int
) -> None:
    def never(_us: int) -> object:
        raise AssertionError("a key was built")

    monkeypatch.setattr(recorded_reader, "_moment", never)

    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(("symbol", "ym"), H0, H0 + width_us)


def test_a_year_window_of_more_than_one_read_is_refused() -> None:
    year_3026 = H0 + 1_000 * 366 * 24 * HOUR  # past 3026-10-01: 1 001 year partitions

    assert recorded_reader._time_keys(("symbol", "y"), H0, H0 + 30 * 24 * HOUR) == [{"y": "2026"}]
    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(("symbol", "y"), H0, year_3026)


def test_a_month_window_wider_than_one_read_is_refused_never_cut() -> None:
    fifteen_years = 15 * 366 * 24 * HOUR

    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(("symbol", "ym"), H0, H0 + fifteen_years)


def test_a_window_beyond_the_calendar_is_a_typed_error() -> None:
    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(("symbol", "y"), 2**62, 2**62 + HOUR)


YM: tuple[str, ...] = ("symbol", "ym")
LAST_US = 253_402_300_799_999_999  # 9999-12-31T23:59:59.999999Z, the calendar's last instant


def _at(year: int, month: int, day: int = 1) -> int:
    return (date(year, month, day) - date(1970, 1, 1)).days * 24 * HOUR


def test_a_month_window_ending_on_a_month_boundary_names_only_its_own_months() -> None:
    assert recorded_reader._time_keys(YM, _at(2026, 10, 31), _at(2026, 11)) == [{"ym": "2026-10"}]
    assert recorded_reader._time_keys(YM, _at(2026, 10), _at(2026, 12)) == [
        {"ym": "2026-10"},
        {"ym": "2026-11"},
    ]


def test_a_month_window_across_new_year_names_the_months_of_both_years() -> None:
    keys = recorded_reader._time_keys(YM, _at(2026, 12, 15), _at(2027, 1, 15))

    assert keys == [{"ym": "2026-12"}, {"ym": "2027-01"}]
    assert recorded_reader._time_keys(YM, _at(2026, 12, 31), _at(2027, 1)) == [{"ym": "2026-12"}]


def test_exactly_120_months_are_allowed_and_one_more_is_refused() -> None:
    assert len(recorded_reader._time_keys(YM, _at(2016, 1), _at(2026, 1))) == 120

    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(YM, _at(2016, 1), _at(2026, 1) + 1)


def test_exactly_the_cap_of_years_is_allowed_and_one_more_is_refused() -> None:
    year = ("symbol", "y")
    assert len(recorded_reader._time_keys(year, _at(2026, 1), _at(3026, 1))) == 1_000

    with pytest.raises(ColdReplayReadError):
        recorded_reader._time_keys(year, _at(2026, 1), _at(3026, 1) + 1)


def test_a_window_ending_in_the_calendars_last_microseconds_is_a_typed_error() -> None:
    """`months_between` steps through floats, which round the last instant into year 10000."""
    with pytest.raises(ColdReplayReadError, match="out of range") as caught:
        recorded_reader._time_keys(YM, LAST_US - 30 * 24 * HOUR, LAST_US + 1)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__  # no datetime text


async def test_klines_of_other_months_are_not_opened(tmp_path: Path) -> None:
    bar: dict[str, object] = {
        "ts": H0,
        "symbol": SYMBOL,
        "interval": "1",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 3.0,
        "turnover": 4.5,
        "confirmed": True,
    }
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({StreamKind.KLINES: [bar]}))
    for ym in ("2026-10", "2026-08"):
        await exporter.export_partition(
            SYMBOL, StreamKind.KLINES, FIRST_HOUR, partition_extra={"interval": "1", "ym": ym}
        )

    listed = ParquetRecordedReader(registry)._partitions(SYMBOL, StreamKind.KLINES, H0, H0 + HOUR)

    assert [p.partition_dir.name for p in listed] == ["ym=2026-10"]


async def _klines_registry(
    root: Path, months: tuple[str, ...], intervals: tuple[str, ...] = ("1",)
) -> DatasetRegistry:
    bar: dict[str, object] = {
        "ts": H0,
        "symbol": SYMBOL,
        "interval": "1",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 3.0,
        "turnover": 4.5,
        "confirmed": True,
    }
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({StreamKind.KLINES: [bar]}))
    for interval in intervals:
        for ym in months:
            await exporter.export_partition(
                SYMBOL,
                StreamKind.KLINES,
                FIRST_HOUR,
                partition_extra={"interval": interval, "ym": ym},
            )
    return registry


async def test_an_empty_klines_window_reads_nothing(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _klines_registry(tmp_path / "cold", ("2026-10",)))
    empty = TimeRange(start_us=H0 + 5, end_us=H0 + 5)

    assert await reader.read(SYMBOL, StreamKind.KLINES, empty, depth=200, limit=10) == []


async def test_a_klines_window_ending_on_a_month_boundary_reads_its_month(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _klines_registry(tmp_path / "cold", ("2026-10",)))
    window = TimeRange(start_us=H0, end_us=_at(2026, 11))

    got = await reader.read(SYMBOL, StreamKind.KLINES, window, depth=200, limit=10)

    assert [e.tiebreak for e in got] == [("1",)]


async def test_klines_across_new_year_list_the_months_of_both_years(tmp_path: Path) -> None:
    registry = await _klines_registry(tmp_path / "cold", ("2026-12", "2027-01"))

    parts = ParquetRecordedReader(registry)._partitions(
        SYMBOL, StreamKind.KLINES, _at(2026, 12, 15), _at(2027, 1, 15)
    )

    assert [p.partition_dir.name for p in parts] == ["ym=2026-12", "ym=2027-01"]


async def test_klines_partitions_count_against_the_cap_per_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A month of klines is one partition per interval: 120 months of 13 intervals is 1 560."""
    registry = await _klines_registry(tmp_path / "cold", ("2026-09", "2026-10"), ("1", "5"))
    reader = ParquetRecordedReader(registry)
    monkeypatch.setattr(recorded_reader, "_MAX_PARTITIONS", 3)

    assert len(reader._partitions(SYMBOL, StreamKind.KLINES, _at(2026, 10), _at(2026, 11))) == 2
    with pytest.raises(ColdReplayReadError, match="too many partitions"):
        reader._partitions(SYMBOL, StreamKind.KLINES, _at(2026, 9), _at(2026, 11))
    monkeypatch.setattr(recorded_reader, "_MAX_PARTITIONS", 4)  # exactly the cap is read
    assert len(reader._partitions(SYMBOL, StreamKind.KLINES, _at(2026, 9), _at(2026, 11))) == 4


# --- read() and snapshot_at(): the boundaries the port promises ----------------------------
def _snap(ts: int, update_id: int, depth: int = 200) -> dict[str, object]:
    return {
        "ts": ts,
        "symbol": SYMBOL,
        "depth": depth,
        "update_id": update_id,
        "cross_seq": update_id * 10,
        "bids": '[["1.0","1"]]',
        "asks": '[["2.0","1"]]',
    }


async def _snapshots(
    root: Path, rows: list[dict[str, object]], *ranges: TimeRange
) -> DatasetRegistry:
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({StreamKind.ORDERBOOK_SNAPSHOT: rows}))
    for rng in ranges or (FIRST_HOUR,):
        await exporter.export_partition(SYMBOL, StreamKind.ORDERBOOK_SNAPSHOT, rng)
    return registry


async def test_a_read_spans_partitions_and_reads_every_file_of_each(tmp_path: Path) -> None:
    rows = generated_rows()
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource(rows), rows_per_group=64)
    for hour in (0, 1):
        await exporter.export_partition(
            SYMBOL,
            StreamKind.ORDERBOOK_DELTA,
            TimeRange(start_us=H0 + hour * HOUR, end_us=H0 + (hour + 1) * HOUR),
            partition_extra={"hour": f"{hour:02d}"},
        )
    window = TimeRange(start_us=H0 + 30 * MINUTE, end_us=H0 + 90 * MINUTE)

    got = await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.ORDERBOOK_DELTA, window, depth=200, limit=10_000
    )

    want = [
        event_from_row(StreamKind.ORDERBOOK_DELTA, r)
        for r in rows_in(rows[StreamKind.ORDERBOOK_DELTA], window)
    ]
    assert got == want and len(got) > 100


async def test_the_earliest_rows_win_the_cap_across_part_files(tmp_path: Path) -> None:
    """A backfill leaves the later half in the lower-numbered part: the cap still takes the
    earliest rows by time."""
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource(generated_rows()), rows_per_group=64)
    await exporter.export_partition(
        SYMBOL, StreamKind.TRADES, TimeRange(start_us=H0 + 30 * MINUTE, end_us=H0 + HOUR)
    )
    await exporter.export_partition(
        SYMBOL, StreamKind.TRADES, TimeRange(start_us=H0, end_us=H0 + 30 * MINUTE)
    )

    got = await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=3
    )

    assert [e.ts_us - H0 for e in got] == [0, 20_000_000, 40_000_000]


async def test_a_limit_of_one_reads_one_row(tmp_path: Path) -> None:
    reader = ParquetRecordedReader(await _export(tmp_path / "cold", generated_rows()))

    got = await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=1)

    assert [e.ts_us for e in got] == [H0]


async def test_a_snapshot_read_is_filtered_to_its_depth(tmp_path: Path) -> None:
    rows = [_snap(H0 + m * MINUTE, m) for m in range(3)]
    rows += [_snap(H0 + m * MINUTE + 1, 100 + m, depth=50) for m in range(3)]
    rows.sort(key=lambda r: int(str(r["ts"])))
    reader = ParquetRecordedReader(await _snapshots(tmp_path / "cold", rows))

    got = await reader.read(SYMBOL, StreamKind.ORDERBOOK_SNAPSHOT, FIRST_HOUR, depth=50, limit=100)

    assert [e.tiebreak[0] for e in got] == [100, 101, 102]


async def test_the_anchor_bounds_are_inclusive_and_its_depth_exact(tmp_path: Path) -> None:
    rows = [_snap(H0 + m * MINUTE, m) for m in range(10)]
    rows += [_snap(H0 + m * MINUTE + 1, 100 + m, depth=50) for m in range(10)]
    rows.sort(key=lambda r: int(str(r["ts"])))
    reader = ParquetRecordedReader(await _snapshots(tmp_path / "cold", rows))
    at = H0 + 5 * MINUTE

    at_edge = await reader.snapshot_at(SYMBOL, 200, at, not_before_us=H0)
    lower_edge = await reader.snapshot_at(SYMBOL, 200, at, not_before_us=at)
    other_depth = await reader.snapshot_at(SYMBOL, 50, at + 2, not_before_us=H0)

    assert at_edge is not None and at_edge.tiebreak[0] == 5
    assert lower_edge is not None and lower_edge.tiebreak[0] == 5
    assert other_depth is not None and other_depth.tiebreak[0] == 105
    assert await reader.snapshot_at(SYMBOL, 500, at, not_before_us=H0) is None


async def test_a_snapshot_on_the_first_instant_of_a_day_is_the_anchor(tmp_path: Path) -> None:
    day = H0 + 24 * HOUR
    registry = await _snapshots(
        tmp_path / "cold",
        [_snap(day - MINUTE, 1), _snap(day, 2)],
        TimeRange(start_us=day - HOUR, end_us=day),
        TimeRange(start_us=day, end_us=day + HOUR),
    )

    anchor = await ParquetRecordedReader(registry).snapshot_at(
        SYMBOL, 200, day, not_before_us=day - 30 * MINUTE
    )

    assert anchor is not None and anchor.tiebreak[0] == 2


async def test_the_same_row_reads_the_same_whichever_window_reached_it(tmp_path: Path) -> None:
    """A column first exported in a later partition (21 Sec.5.2 evolves the schema additively)
    must not change how that partition's rows read when an older one is in the window (C-2.15)."""
    rows = generated_rows()[StreamKind.ORDERBOOK_DELTA]
    old_rows = [{k: v for k, v in r.items() if k != "cross_seq"} for r in rows]
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    await ColdExporter(
        registry, MemHotSource({StreamKind.ORDERBOOK_DELTA: old_rows}), rows_per_group=64
    ).export_partition(
        SYMBOL, StreamKind.ORDERBOOK_DELTA, FIRST_HOUR, partition_extra={"hour": "00"}
    )
    schema = SchemaRegistry(registry.root / "_manifests" / "schema-registry.json")
    old_columns = schema.columns_for("orderbook_delta")
    assert old_columns is not None
    schema.register("orderbook_delta", old_columns | {"cross_seq"})
    await ColdExporter(
        registry, MemHotSource({StreamKind.ORDERBOOK_DELTA: rows}), rows_per_group=64
    ).export_partition(
        SYMBOL,
        StreamKind.ORDERBOOK_DELTA,
        TimeRange(start_us=H0 + HOUR, end_us=H0 + 2 * HOUR),
        partition_extra={"hour": "01"},
    )
    reader = ParquetRecordedReader(registry)
    wide = TimeRange(start_us=H0 + 30 * MINUTE, end_us=H0 + 90 * MINUTE)
    narrow = TimeRange(start_us=H0 + HOUR, end_us=H0 + 90 * MINUTE)

    spanning = await reader.read(SYMBOL, StreamKind.ORDERBOOK_DELTA, wide, depth=200, limit=10_000)
    alone = await reader.read(SYMBOL, StreamKind.ORDERBOOK_DELTA, narrow, depth=200, limit=10_000)

    assert alone and [e for e in spanning if e.ts_us >= H0 + HOUR] == alone


class _CountingCon:
    def __init__(self) -> None:
        self.interrupts = 0

    def interrupt(self) -> None:
        self.interrupts += 1


def test_an_interrupt_never_waits_for_a_worker_that_is_connecting_or_closing(
    tmp_path: Path,
) -> None:
    """C-2.17: the event loop skips a round rather than block; the next round lands."""
    scan = recorded_reader._Scan(tmp_path)
    con = _CountingCon()
    scan._con = cast(duckdb.DuckDBPyConnection, con)  # the worker's connection, stood in
    holder_ready, release = threading.Event(), threading.Event()

    def worker_holds_the_lock() -> None:
        with scan._lock:
            holder_ready.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=worker_holds_the_lock, daemon=True)
    holder.start()
    assert holder_ready.wait(timeout=5)
    caller = threading.Thread(target=scan.interrupt, daemon=True)
    caller.start()
    caller.join(timeout=2)
    assert not caller.is_alive() and con.interrupts == 0  # returned at once, delivered nothing
    release.set()
    holder.join(timeout=5)
    scan.interrupt()
    assert con.interrupts == 1
