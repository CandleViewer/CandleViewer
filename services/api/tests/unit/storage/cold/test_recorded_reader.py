"""`ParquetRecordedReader` (E26-T02) over partitions the production `ColdExporter` wrote."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import sys
import threading
from pathlib import Path

import duckdb
import pytest

from candleviewer.storage.cold import recorded_reader
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.recorded_reader import (
    ColdReplayReadError,
    ColdReplayReadTimeout,
    ParquetRecordedReader,
)
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    RecordedEvent,
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


async def test_a_tampered_part_fails_verification_instead_of_serving_partial_data(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    registry = await _export(root, generated_rows())
    part = next((root / "trades").rglob("part-*.parquet"))
    part.write_bytes(part.read_bytes()[:-16] + b"\x00" * 16)

    with pytest.raises(ColdReplayReadError):
        await ParquetRecordedReader(registry).read(
            SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10
        )


def test_the_cold_reader_is_addressed_by_stream_id_never_by_path(tmp_path: Path) -> None:
    """SR-097 / ticket AC 5: the public surface takes a registry, never a filesystem path."""
    assert isinstance(ParquetRecordedReader(DatasetRegistry(tmp_path)), RecordedStreamReader)
    for member in (
        ParquetRecordedReader.__init__,
        ParquetRecordedReader.read,
        ParquetRecordedReader.snapshot_at,
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


def test_a_duckdb_failure_is_a_typed_cold_read_error() -> None:
    con = duckdb.connect()
    try:
        with pytest.raises(ColdReplayReadError):
            recorded_reader._scan(con, "SELECT nope FROM nowhere", {}, StreamKind.TRADES)
    finally:
        con.close()


class _Scan:
    """A scan that ends only once interrupted (and released), and its recording connection."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.interrupted = threading.Event()
        self.released = threading.Event()
        self.released.set()
        self.ended = threading.Event()
        self.closed = False

    def interrupt(self) -> None:
        self.interrupted.set()

    def close(self) -> None:
        self.closed = True

    def run(self, con: object, sql: str, params: object, stream: StreamKind) -> list[RecordedEvent]:
        self.started.set()
        try:
            if not (self.interrupted.wait(timeout=5) and self.released.wait(timeout=5)):
                raise AssertionError("the scan was never interrupted")
            raise ColdReplayReadError("interrupted")  # what `_scan` raises for an interrupt
        finally:
            self.ended.set()


async def _stuck_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, timeout_s: float
) -> tuple[ParquetRecordedReader, _Scan]:
    scan = _Scan()
    monkeypatch.setattr(recorded_reader, "_connect", lambda: scan)
    monkeypatch.setattr(recorded_reader, "_scan", scan.run)
    registry = await _export(tmp_path / "cold", generated_rows())
    return ParquetRecordedReader(registry, timeout_s=timeout_s, max_concurrency=1), scan


async def test_a_scan_past_its_deadline_is_interrupted_awaited_and_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, scan = await _stuck_reader(tmp_path, monkeypatch, timeout_s=0.05)

    with pytest.raises(ColdReplayReadTimeout):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    assert scan.interrupted.is_set() and scan.ended.is_set() and scan.closed


async def test_a_scan_failing_by_itself_is_typed_awaited_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, scan = await _stuck_reader(tmp_path, monkeypatch, timeout_s=30.0)
    scan.interrupted.set()  # the scan fails on its own, before any deadline or cancellation

    with pytest.raises(ColdReplayReadError):
        await reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)

    assert scan.ended.is_set() and scan.closed


async def test_a_cancelled_read_interrupts_its_scan_and_holds_the_slot_until_it_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18: no DuckDB scan outlives its slot, even if cancelled again while it stops."""
    reader, scan = await _stuck_reader(tmp_path, monkeypatch, timeout_s=30.0)
    scan.released.clear()  # the scan lingers after its interrupt
    task = asyncio.create_task(
        reader.read(SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=10)
    )
    assert await asyncio.to_thread(scan.started.wait, 5)

    task.cancel()
    assert await asyncio.to_thread(scan.interrupted.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()  # still holding the slot: the scan has not stopped yet
    scan.released.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert scan.interrupted.is_set() and scan.ended.is_set() and scan.closed


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
    real = recorded_reader._scan

    def spy(
        con: duckdb.DuckDBPyConnection, sql: str, params: dict[str, object], stream: StreamKind
    ) -> list[RecordedEvent]:
        files = params["files"]
        assert isinstance(files, list)
        opened.extend(str(f) for f in files)
        return real(con, sql, params, stream)

    monkeypatch.setattr(recorded_reader, "_scan", spy)

    got = await ParquetRecordedReader(registry).read(
        SYMBOL, StreamKind.TRADES, FIRST_HOUR, depth=200, limit=1_000
    )

    assert len(got) == len(rows_in(generated_rows()[StreamKind.TRADES], FIRST_HOUR))
    assert opened and _all_resolved(opened) and all("relocated" in f for f in opened)


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
