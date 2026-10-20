"""Unit tests: `ColdExporter` — Sec.5.3 flow, verify mismatch, schema drift,
crash-point resume and idempotency (E07-T04 AC 1, 2, 4, 5)."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.storage.cold import exporter as cold_exporter
from candleviewer.storage.cold.exporter import ColdExporter, _off_loop
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore, SchemaRegistry
from candleviewer.storage.errors import StorageExportVerifyFailed, StorageSchemaDrift
from candleviewer.storage.models import ExportRun, StreamKind, TimeRange
from tests.unit.storage.cold._helpers import (
    DAY_START_US,
    FakeHotSource,
    RecordingSink,
    SimulatedKill,
    day_range,
    fixed_clock,
    trades_table,
)
from tests.unit.storage.cold._replay_rows import MemHotSource

PART = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"
DELTAS = Path("orderbook_deltas") / "symbol=BTCUSDT" / "dt=2026-10-17"
HOUR_US = 3_600_000_000
#: PGWire's shape of a QuestDB TIMESTAMP: a tz-naive datetime holding UTC.
NAIVE_EPOCH = datetime(1970, 1, 1)
REPLAY_COLUMNS = frozenset({"prev_update_id", "ts_match"})


def _exporter(root: Path, source: FakeHotSource, **kw: object) -> ColdExporter:
    return ColdExporter(DatasetRegistry(root), source, clock=fixed_clock, **kw)  # type: ignore[arg-type]  # test-only kwargs passthrough


def _manifest(root: Path) -> ManifestStore:
    return ManifestStore(root / "_manifests")


async def test_export_symbol_day_writes_part_0000_zstd6_sorted_with_provenance(
    tmp_path: Path,
) -> None:
    source = FakeHotSource(trades_table(25))
    run = await _exporter(tmp_path, source, rows_per_group=10).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    dest = tmp_path / PART / "part-0000.parquet"
    pf = pq.ParquetFile(dest)
    assert run.row_count == 25 and pf.metadata.num_rows == 25
    assert pf.metadata.format_version == "2.6"
    assert pf.metadata.num_row_groups == 3
    assert pf.metadata.row_group(0).column(0).compression == "ZSTD"
    table = pf.read()
    assert {"_export_run_id", "_exported_at", "_source"} <= set(table.column_names)
    assert set(table.column("_source").to_pylist()) == {"questdb"}
    assert set(table.column("_export_run_id").to_pylist()) == {run.run_id}
    ts = table.column("ts")
    assert pc.all(pc.greater_equal(ts.slice(1), ts.slice(0, len(ts) - 1))).as_py()


async def test_manifest_records_sha256_row_count_and_source_equal_to_count(
    tmp_path: Path,
) -> None:
    from candleviewer.storage.cold.manifest import sha256_of

    await _exporter(tmp_path, FakeHotSource(trades_table(7))).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    [entry] = _manifest(tmp_path).read(tmp_path / PART, tmp_path)
    assert entry.row_count == 7
    assert entry.source_table == "trades"
    assert entry.sha256 == sha256_of(tmp_path / PART / entry.file)
    assert (entry.range_start_us, entry.range_end_us) == (
        day_range().start_us,
        day_range().end_us,
    )


@pytest.mark.parametrize(
    ("name", "next_part"),
    [
        ("part-0007.parquet", "part-0008.parquet"),
        ("part-0007.parquet\n", "part-0001.parquet"),
        ("part-0007.parquet\r\n", "part-0001.parquet"),
    ],
    ids=["legal", "lf", "crlf"],
)
async def test_a_manifest_name_ending_in_a_newline_is_no_part_name(
    tmp_path: Path, name: str, next_part: str
) -> None:
    """#3555: `$` also matches before a final newline, so `match` counted `part-0007.parquet\\n`
    as part 7 and the next export took 8. Outside the pattern it is not a part name: the new
    part's name is free, never an existing one, and the first part is untouched."""
    table = trades_table(5)
    await _exporter(tmp_path, FakeHotSource(table)).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    store, part = _manifest(tmp_path), tmp_path / PART
    [first] = store.read(part, tmp_path)
    before = (part / first.file).read_bytes()
    other = replace(first, file=name, range_start_us=0, range_end_us=1)
    store.write(part, tmp_path, [first, other])
    hour = TimeRange(start_us=DAY_START_US, end_us=DAY_START_US + 3_600_000_000)
    await _exporter(tmp_path, FakeHotSource(table)).export_partition(
        "BTCUSDT", StreamKind.TRADES, hour
    )
    assert sorted(e.file for e in store.read(part, tmp_path)) == sorted(
        ["part-0000.parquet", name, next_part]
    )
    assert (part / "part-0000.parquet").read_bytes() == before
    assert pq.ParquetFile(part / next_part).metadata.num_rows == 5


async def test_verify_mismatch_raises_emits_critical_and_writes_nothing(tmp_path: Path) -> None:
    sink = RecordingSink()
    source = FakeHotSource(trades_table(3), count_override=4)
    with pytest.raises(StorageExportVerifyFailed):
        await _exporter(tmp_path, source, events=sink).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )
    assert [(s, c) for s, c, _ in sink.events] == [("CRITICAL", "STORAGE_EXPORT_VERIFY_FAILED")]
    assert not list((tmp_path / PART).glob("*"))
    assert _manifest(tmp_path).read(tmp_path / PART, tmp_path) == []


async def test_empty_source_fails_verify(tmp_path: Path) -> None:
    source = FakeHotSource(trades_table(0), count_override=0)
    with pytest.raises(StorageExportVerifyFailed):
        await _exporter(tmp_path, source, events=RecordingSink()).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )


async def test_schema_drift_fails_closed_and_exports_nothing(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path / "_manifests" / "schema-registry.json")
    registry.register("trades", frozenset(trades_table(1).column_names))
    drifted = trades_table(3).append_column("is_rpi", pa.array([False] * 3))
    source = FakeHotSource(drifted)
    with pytest.raises(StorageSchemaDrift, match="is_rpi"):
        await _exporter(tmp_path, source).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )
    assert not (tmp_path / PART).exists() or not list((tmp_path / PART).iterdir())
    assert source.count_override is None  # hot data untouched: the source is read-only


async def test_schema_drift_on_missing_column_also_fails_closed(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path / "_manifests" / "schema-registry.json")
    registry.register("trades", frozenset(trades_table(1).column_names))
    with pytest.raises(StorageSchemaDrift, match="missing"):
        await _exporter(tmp_path, FakeHotSource(trades_table(3).drop(["side"]))).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )


# --- schema widening (21 Sec.5.2): the book replay columns of QuestDB 0006 (E26-T03) ---


def _hour(h: int) -> TimeRange:
    return TimeRange(start_us=DAY_START_US + h * HOUR_US, end_us=DAY_START_US + (h + 1) * HOUR_US)


def _deltas(n: int, h: int = 0, **extra: pa.Array) -> pa.Table:
    """`orderbook_deltas` rows of hour `h` as the hot tier serves them; `extra` adds columns."""
    start = _hour(h).start_us
    table = pa.table(
        {
            "ts": pa.array([start + i for i in range(n)], type=pa.int64()),
            "symbol": ["BTCUSDT"] * n,
            "depth": pa.array([200] * n, type=pa.int32()),
            "side": ["bid" if i % 2 else "ask" for i in range(n)],
            "price": [65000.0 + i for i in range(n)],
            "size": [1.5] * n,
            "update_id": pa.array(range(100, 100 + n), type=pa.int64()),
            "cross_seq": pa.array(range(1000, 1000 + n), type=pa.int64()),
        }
    )
    for name, column in extra.items():
        table = table.append_column(name, column)
    return table


def _replay_columns(n: int, h: int = 0) -> dict[str, pa.Array]:
    """The 0006 columns as PGWire returns them: a LONG and a tz-naive TIMESTAMP (UTC)."""
    start = _hour(h).start_us
    return {
        "prev_update_id": pa.array(range(99, 99 + n), type=pa.int64()),
        "ts_match": pa.array(
            [NAIVE_EPOCH + timedelta(microseconds=start + i - 3) for i in range(n)]
        ),
    }


async def _export_deltas(root: Path, table: pa.Table, h: int = 0) -> ExportRun:
    return await _exporter(root, FakeHotSource(table)).export_partition(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, _hour(h), partition_extra={"hour": f"{h:02d}"}
    )


def _registered(root: Path) -> frozenset[str] | None:
    return SchemaRegistry(root / "_manifests" / "schema-registry.json").columns_for(
        "orderbook_delta"
    )


def _written(root: Path, h: int) -> pa.Table:
    return pq.read_table(root / DELTAS / f"hour={h:02d}" / "part-0000.parquet")


async def test_listed_added_columns_widen_the_registry_and_the_export_goes_on(
    tmp_path: Path,
) -> None:
    await _export_deltas(tmp_path, _deltas(4))
    before = _registered(tmp_path)
    assert before is not None and not before & REPLAY_COLUMNS

    with capture_logs() as logs:
        run = await _export_deltas(tmp_path, _deltas(4, 1, **_replay_columns(4, 1)), 1)

    assert run.row_count == 4 and _registered(tmp_path) == before | REPLAY_COLUMNS
    written = _written(tmp_path, 1)
    assert written.schema.field("prev_update_id").type == pa.int64()
    assert written.schema.field("ts_match").type == pa.timestamp("us", tz="UTC")
    assert written.column("prev_update_id").to_pylist() == [99, 100, 101, 102]
    start = _hour(1).start_us
    assert written.column("ts_match").cast(pa.int64()).to_pylist() == [
        start + i - 3 for i in range(4)
    ]
    widened = [e for e in logs if e["event"] == "cold_export_schema_widened"]
    assert [(e["dataset"], e["added"]) for e in widened] == [
        ("orderbook_delta", ["prev_update_id", "ts_match"])
    ]


async def test_a_second_export_after_the_widening_is_a_no_drift_export(tmp_path: Path) -> None:
    await _export_deltas(tmp_path, _deltas(2))
    await _export_deltas(tmp_path, _deltas(2, 1, **_replay_columns(2, 1)), 1)
    widened = _registered(tmp_path)

    with capture_logs() as logs:
        run = await _export_deltas(tmp_path, _deltas(3, 2, **_replay_columns(3, 2)), 2)

    assert run.row_count == 3 and _registered(tmp_path) == widened
    assert not [e for e in logs if e["event"] == "cold_export_schema_widened"]


async def test_an_unlisted_added_column_fails_closed_beside_listed_ones(tmp_path: Path) -> None:
    await _export_deltas(tmp_path, _deltas(2))
    before = _registered(tmp_path)
    drifted = _deltas(2, 1, **_replay_columns(2, 1), is_rpi=pa.array([False, True]))

    with pytest.raises(StorageSchemaDrift, match="is_rpi"):
        await _export_deltas(tmp_path, drifted, 1)

    assert _registered(tmp_path) == before
    assert not list((tmp_path / DELTAS).glob("hour=01/*"))


async def test_a_column_listed_for_another_dataset_fails_closed(tmp_path: Path) -> None:
    """The table is per dataset: `ts_match` widens the book datasets, never `trades`."""
    registry = SchemaRegistry(tmp_path / "_manifests" / "schema-registry.json")
    registry.register("trades", frozenset(trades_table(1).column_names))
    ts_match = pa.array([NAIVE_EPOCH + timedelta(microseconds=DAY_START_US + i) for i in range(3)])
    source = FakeHotSource(trades_table(3).append_column("ts_match", ts_match))

    with pytest.raises(StorageSchemaDrift, match="ts_match"):
        await _exporter(tmp_path, source).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )

    assert registry.columns_for("trades") == frozenset(trades_table(1).column_names)


async def test_a_removed_column_fails_closed_even_with_listed_additions(tmp_path: Path) -> None:
    await _export_deltas(tmp_path, _deltas(2))
    before = _registered(tmp_path)
    shrunk = _deltas(2, 1, **_replay_columns(2, 1)).drop_columns(["cross_seq"])

    with pytest.raises(StorageSchemaDrift, match=r"missing=\['cross_seq'\]"):
        await _export_deltas(tmp_path, shrunk, 1)

    assert _registered(tmp_path) == before


@pytest.mark.parametrize(
    ("column", "values"),
    [
        ("prev_update_id", pa.array([1.5, 2.5])),
        ("prev_update_id", pa.array(["99", "100"])),
        ("ts_match", pa.array([5, 6], type=pa.int64())),
        ("ts_match", pa.array([5, 6], type=pa.timestamp("ms"))),
    ],
    ids=["long-as-double", "long-as-text", "timestamp-as-long", "timestamp-in-ms"],
)
async def test_a_retyped_listed_column_fails_closed_before_the_registry_widens(
    tmp_path: Path, column: str, values: pa.Array
) -> None:
    await _export_deltas(tmp_path, _deltas(2))
    before = _registered(tmp_path)
    retyped = _deltas(2, 1, **(_replay_columns(2, 1) | {column: values}))

    with pytest.raises(StorageSchemaDrift, match=column):
        await _export_deltas(tmp_path, retyped, 1)

    assert _registered(tmp_path) == before
    assert not list((tmp_path / DELTAS).glob("hour=01/*"))


async def test_an_all_null_added_column_is_written_with_its_declared_type(tmp_path: Path) -> None:
    """Rows recorded before 0006 hold NULL in both, which Arrow types `null`. The part must still
    carry int64 and timestamp, or no later part could merge or union with it."""
    await _export_deltas(tmp_path, _deltas(3, prev_update_id=pa.nulls(3), ts_match=pa.nulls(3)))

    written = _written(tmp_path, 0)
    assert written.schema.field("prev_update_id").type == pa.int64()
    assert written.schema.field("ts_match").type == pa.timestamp("us", tz="UTC")
    assert written.column("prev_update_id").null_count == written.column("ts_match").null_count == 3


async def test_an_hour_straddling_the_migration_exports_as_one_typed_part(tmp_path: Path) -> None:
    """The deploy hour: rows recorded before 0006 hold NULL, those after it hold values. Built per
    batch as the QuestDB source builds them, the first batch types the columns `null` and the
    second int64 and timestamp; both must write to the one part."""
    rows = _deltas(4).to_pylist()
    for i, row in enumerate(rows):
        after = i >= 2
        row["prev_update_id"] = 99 + i if after else None
        ts_match = NAIVE_EPOCH + timedelta(microseconds=int(str(row["ts"])) - 3)
        row["ts_match"] = ts_match if after else None
    source = MemHotSource({StreamKind.ORDERBOOK_DELTA: rows})
    exporter = ColdExporter(DatasetRegistry(tmp_path), source, clock=fixed_clock, rows_per_group=2)

    run = await exporter.export_partition(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, _hour(0), partition_extra={"hour": "00"}
    )

    written = _written(tmp_path, 0)
    assert run.row_count == 4
    assert written.column("prev_update_id").to_pylist() == [None, None, 101, 102]
    assert written.schema.field("ts_match").type == pa.timestamp("us", tz="UTC")
    assert written.column("ts_match").cast(pa.int64()).to_pylist()[2:] == [
        DAY_START_US + 2 - 3,
        DAY_START_US + 3 - 3,
    ]


# --- crash-point resume (AC 4): after write, after checksum, after manifest ---


async def test_crash_mid_write_leaves_tmp_and_rerun_recovers(tmp_path: Path) -> None:
    table = trades_table(30)
    with pytest.raises(SimulatedKill):
        await _exporter(
            tmp_path, FakeHotSource(table, fail_after_batches=2), rows_per_group=10
        ).export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    # abort() removed the temp; simulate a hard kill that could not clean up
    (tmp_path / PART / "part-0000.parquet.tmp").write_bytes(b"torn")
    run = await _exporter(tmp_path, FakeHotSource(table), rows_per_group=10).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    assert run.row_count == 30
    assert sorted(p.name for p in (tmp_path / PART).iterdir()) == ["part-0000.parquet"]


async def test_crash_after_write_before_manifest_reexports_to_single_entry(
    tmp_path: Path,
) -> None:
    """Kill after the Parquet rename (and after checksumming) but before the
    manifest append: a file exists with no manifest entry."""
    table = trades_table(12)
    await _exporter(tmp_path, FakeHotSource(table)).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    store = _manifest(tmp_path)
    store.write(tmp_path / PART, tmp_path, [])  # manifest step never happened
    source = FakeHotSource(table)
    await _exporter(tmp_path, source).export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    entries = store.read(tmp_path / PART, tmp_path)
    assert len(entries) == 1 and entries[0].row_count == 12
    assert [p.name for p in (tmp_path / PART).glob("*.parquet")] == [entries[0].file]
    assert source.reads == 1  # re-exported; hot source still intact


async def test_crash_after_manifest_rerun_is_noop(tmp_path: Path) -> None:
    table = trades_table(5)
    first = await _exporter(tmp_path, FakeHotSource(table)).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    before = (tmp_path / PART / "part-0000.parquet").read_bytes()
    source = FakeHotSource(table)
    again = await _exporter(tmp_path, source).export_partition(
        "BTCUSDT", StreamKind.TRADES, day_range()
    )
    assert again.run_id == first.run_id and source.reads == 0
    assert (tmp_path / PART / "part-0000.parquet").read_bytes() == before
    assert len(_manifest(tmp_path).read(tmp_path / PART, tmp_path)) == 1


async def test_export_cancellation_removes_temp_and_propagates(tmp_path: Path) -> None:
    gate = asyncio.Event()

    class _Slow(FakeHotSource):
        async def iter_partition(self, *a: object, **k: object):  # type: ignore[no-untyped-def,override]  # test double
            yield self.table.slice(0, 2)
            await gate.wait()
            yield self.table.slice(2)

    exp = _exporter(tmp_path, _Slow(trades_table(4)))
    task = asyncio.create_task(exp.export_partition("BTCUSDT", StreamKind.TRADES, day_range()))
    for _ in range(50):
        await asyncio.sleep(0)
        if (tmp_path / PART / "part-0000.parquet.tmp").exists():
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list((tmp_path / PART).glob("*"))


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(n=st.integers(min_value=1, max_value=60), batch=st.integers(min_value=1, max_value=17))
def test_property_rerun_export_is_byte_identical_noop(
    tmp_path_factory: pytest.TempPathFactory, n: int, batch: int
) -> None:
    root = tmp_path_factory.mktemp("cold")

    async def _go() -> None:
        table = trades_table(n)
        await _exporter(root, FakeHotSource(table), rows_per_group=batch).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )
        snap = {p.name: p.read_bytes() for p in (root / PART).iterdir()}
        manifest = (root / "_manifests" / PART).with_suffix(".json").read_bytes()
        await _exporter(root, FakeHotSource(table), rows_per_group=batch).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )
        assert {p.name: p.read_bytes() for p in (root / PART).iterdir()} == snap
        assert (root / "_manifests" / PART).with_suffix(".json").read_bytes() == manifest
        assert pq.ParquetFile(root / PART / "part-0000.parquet").metadata.num_rows == n

    asyncio.run(_go())


async def test_verify_detects_and_quarantines_corruption(tmp_path: Path) -> None:
    sink = RecordingSink()
    exp = _exporter(tmp_path, FakeHotSource(trades_table(5)), events=sink)
    await exp.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    assert await exp.verify("BTCUSDT", StreamKind.TRADES, day_range()) is True
    f = tmp_path / PART / "part-0000.parquet"
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 0xFF
    f.write_bytes(bytes(data))
    with pytest.raises(StorageExportVerifyFailed):
        await exp.verify("BTCUSDT", StreamKind.TRADES, day_range())
    assert not f.exists()
    assert sink.events[-1][:2] == ("CRITICAL", "STORAGE_COLD_FILE_QUARANTINED")


async def test_export_timeout_is_enforced(tmp_path: Path) -> None:
    class _Hang(FakeHotSource):
        async def count_partition(self, *a: object, **k: object) -> int:
            await asyncio.Event().wait()
            return 0

    with pytest.raises(TimeoutError):
        await _exporter(tmp_path, _Hang(trades_table(1)), timeout_s=0.01).export_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )


async def test_off_loop_re_raises_the_workers_failure() -> None:
    def work() -> None:
        raise OSError("disk full")

    with capture_logs() as logs, pytest.raises(OSError, match="disk full"):
        await _off_loop(work)
    assert logs == []  # raised to its caller, so not also logged as an orphan


async def test_a_worker_failure_racing_a_cancel_is_logged() -> None:
    """The caller is cancelled while the worker runs, then the worker fails: the cancellation
    is what propagates, and the failure, which no one awaits any more, must not be lost."""
    started, release = threading.Event(), threading.Event()

    def work() -> None:
        started.set()
        release.wait(5)  # only bounds the test: the worker is released at once
        raise OSError("disk full")

    task = asyncio.create_task(_off_loop(work))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    asyncio.get_running_loop().call_soon(release.set)  # queued after the cancel reached the task
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await task
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("cold_export_worker_failed_after_cancel", "error", "OSError")
    ]


async def test_a_cancelled_worker_is_not_logged_as_a_failure() -> None:
    fut = asyncio.get_running_loop().create_future()
    fut.cancel()
    with capture_logs() as logs:
        cold_exporter._log_worker_failure(fut)  # a cancelled future has no exception to read
    assert logs == []
