"""Unit: roll-off storage adapters (E16-T05) — `ColdArchiver` over the real
`ColdExporter` + tmp_path Parquet, read-back verification (count AND content
checksum), quarantine with reason sidecar, `QuestDbHotPartitions` SQL shape,
watermark store, path containment, downsample, and the compaction pass.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from structlog.testing import capture_logs

from candleviewer.storage.cold.compaction_run import compact_all
from candleviewer.storage.cold.compactor import Compactor
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.rolloff_ops import (
    DOWNSAMPLE_RUN_ID,
    CanonicalDigest,
    ColdArchiver,
    ColdDownsampler,
    QuestDbHotPartitions,
    _downsample_table,
)
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.errors import StorageExportVerifyFailed, StoragePartitionDropNotApplied
from candleviewer.storage.models import StreamKind, TimeRange
from tests.unit.storage.cold._helpers import (
    DAY_START_US,
    FakeHotSource,
    RecordingSink,
    day_range,
    fixed_clock,
    trades_table,
)

T = StreamKind.TRADES


def _walk(root: Path) -> list[Path]:
    return list(root.rglob("*"))


PART = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"


class TamperingSource(FakeHotSource):
    """Second read (the verification re-read) returns different content."""

    async def iter_partition(self, symbol, stream, rng, *, batch_rows):  # type: ignore[no-untyped-def]  # fake
        self.reads += 1
        table = self.table
        if self.reads > 1:
            table = table.set_column(2, "price", pa.array([1.0] * table.num_rows))
        for start in range(0, table.num_rows, batch_rows):
            yield table.slice(start, batch_rows)


def _archiver(root: Path, source: FakeHotSource, sink: RecordingSink) -> ColdArchiver:
    reg = DatasetRegistry(root)
    exporter = ColdExporter(reg, source, clock=fixed_clock, events=sink, rows_per_group=100)
    return ColdArchiver(reg, source, exporter=exporter, events=sink, batch_rows=64)


async def test_archive_day_writes_documented_layout_and_verifies(tmp_path: Path) -> None:
    sink = RecordingSink()
    out = await _archiver(tmp_path, FakeHotSource(trades_table(500)), sink).archive_day(
        "BTCUSDT", T, day_range()
    )
    assert out.verified and out.rows == 500 and out.bytes > 0
    assert (tmp_path / PART / "part-0000.parquet").is_file()
    entries = ManifestStore(tmp_path / "_manifests").read(tmp_path / PART, tmp_path)
    assert [e.row_count for e in entries] == [500]
    assert not any(code.startswith("archive.") for _, code, _ in sink.events)


async def test_archive_day_count_mismatch_alerts_and_writes_nothing(tmp_path: Path) -> None:
    sink = RecordingSink()
    src = FakeHotSource(trades_table(500), count_override=501)
    out = await _archiver(tmp_path, src, sink).archive_day("BTCUSDT", T, day_range())
    assert not out.verified and out.reason == "archive_verification_failed"
    assert ("CRITICAL", "archive.verification_failed") in [(s, c) for s, c, _ in sink.events]
    assert not (tmp_path / PART / "part-0000.parquet").exists()


async def test_archive_day_checksum_mismatch_quarantines_with_reason_sidecar(
    tmp_path: Path,
) -> None:
    sink = RecordingSink()
    out = await _archiver(tmp_path, TamperingSource(trades_table(300)), sink).archive_day(
        "BTCUSDT", T, day_range()
    )
    assert not out.verified and out.reason == "archive_verification_failed"
    q = tmp_path / "_quarantine" / PART
    sidecar = q / "part-0000.reason.json"
    assert (q / "part-0000.parquet").is_file()
    assert json.loads(sidecar.read_text("utf-8"))["reason"] == "checksum"
    # quarantined files are dropped from the manifest -> never in a view
    assert ManifestStore(tmp_path / "_manifests").read(tmp_path / PART, tmp_path) == []
    assert any(c == "archive.verification_failed" for _, c, _ in sink.events)


async def test_archive_day_corrupted_file_fails_manifest_sha(tmp_path: Path) -> None:
    sink = RecordingSink()
    src = FakeHotSource(trades_table(200))
    reg = DatasetRegistry(tmp_path)

    class Corrupting(ColdExporter):
        async def export_partition(self, *a, **kw):  # type: ignore[no-untyped-def]  # test override
            run = await super().export_partition(*a, **kw)
            f = tmp_path / PART / "part-0000.parquet"
            f.write_bytes(f.read_bytes()[:-8] + b"\0" * 8)
            return run

    arch = ColdArchiver(reg, src, exporter=Corrupting(reg, src, clock=fixed_clock), events=sink)
    out = await arch.archive_day("BTCUSDT", T, day_range())
    assert not out.verified


async def test_archive_day_with_no_rows_is_trivially_verified(tmp_path: Path) -> None:
    src = FakeHotSource(trades_table(0))
    out = await _archiver(tmp_path, src, RecordingSink()).archive_day("BTCUSDT", T, day_range())
    assert out.verified and out.rows == 0


async def test_export_path_contained_for_hostile_symbol(tmp_path: Path) -> None:
    arch = _archiver(tmp_path / "cold", FakeHotSource(trades_table(5)), RecordingSink())
    for hostile in ("../../etc", "..", "C:\\x", "BTC/USDT"):
        out = await arch.archive_day(hostile, T, day_range())
        assert not out.verified and out.reason == "archive_write_failed"
    assert not any(p.suffix == ".parquet" for p in _walk(tmp_path))


def test_canonical_digest_is_independent_of_batching() -> None:
    t = trades_table(1000)
    cols = t.column_names

    def dig(sizes: list[int]) -> str:
        schema = pa.schema([pa.field("ts", pa.timestamp("us", tz="UTC")), *list(t.schema)[1:]])
        d = CanonicalDigest(cols, schema)
        start = 0
        for n in sizes:
            d.update(t.slice(start, n))
            start += n
        return d.hexdigest()

    assert dig([1000]) == dig([1, 999]) == dig([333, 333, 334])


class FakePg:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        return self.rows


async def test_hot_partitions_closed_days_parses_and_filters() -> None:
    pg = FakePg([{"name": "2026-10-17"}, {"name": "2026-10-18"}, {"name": "default"}])
    hot = QuestDbHotPartitions(pg)
    days = await hot.closed_days(T, DAY_START_US + 86_400_000_000)
    assert days == [DAY_START_US]
    assert pg.calls[0][0] == "SELECT name, diskSize FROM table_partitions('trades')"


async def test_hot_partitions_disk_bytes_sums_disk_size_over_tables() -> None:
    pg = FakePg([{"name": "2026-10-17", "diskSize": 7}, {"name": "2026-10-18", "diskSize": None}])
    assert await QuestDbHotPartitions(pg).disk_bytes([T, StreamKind.TICKERS]) == 14
    assert [sql.split("(")[1] for sql, _ in pg.calls] == ["'trades')", "'tickers')"]


async def test_hot_partitions_symbols_bind_naive_utc_ts_params() -> None:
    pg = FakePg([{"symbol": "ETHUSDT", "n": 4}, {"symbol": "BTCUSDT", "n": 7}])
    syms = await QuestDbHotPartitions(pg).symbols_in(T, day_range())
    assert syms == ["BTCUSDT", "ETHUSDT"]
    counts = await QuestDbHotPartitions(pg).row_counts(T, day_range())
    assert counts == {"BTCUSDT": 7, "ETHUSDT": 4}
    sql, params = pg.calls[0]
    assert "$1" in sql and "$2" in sql and "trades" in sql
    assert all(isinstance(p, datetime) and p.tzinfo is None for p in params)


async def test_hot_partitions_drop_uses_allowlisted_table_and_date_literal() -> None:
    pg = FakePg()
    await QuestDbHotPartitions(pg).drop_day(StreamKind.ORDERBOOK_DELTA, DAY_START_US)
    assert pg.calls[0] == ("ALTER TABLE orderbook_deltas DROP PARTITION LIST '2026-10-17'", ())
    poll = pg.calls[1][0]
    assert poll == "SELECT name, numRows, minTimestamp FROM table_partitions('orderbook_deltas')"
    assert "2026-10-17" not in poll  # the day is matched Python-side, never spliced into SQL


DAY = "2026-10-17"
LIVE: dict[str, object] = {"name": DAY, "numRows": 120, "minTimestamp": datetime(2026, 10, 17)}
OTHER: dict[str, object] = {
    "name": "2026-10-18",
    "numRows": 7,
    "minTimestamp": datetime(2026, 10, 18),
}


class FakeClock:
    """Monotonic seconds; the fake `sleep` advances it, so wall-clock bounds need no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert self.now < 1_000.0, "runaway wait: the wall-clock bound never tripped"
        self.slept.append(seconds)
        self.now += seconds


class DropPg:
    """QuestDB's async WAL apply: `table_partitions` keeps listing the day for `lag` polls.

    `lag=None` never applies; `applied` is the inventory once it has; `suspended` is what
    `wal_tables()` reports; `poll_cost_s` advances `clock` per inventory poll (a slow query).
    """

    def __init__(
        self,
        *,
        lag: int | None = 0,
        applied: list[dict[str, object]] | None = None,
        suspended: bool = False,
        clock: FakeClock | None = None,
        poll_cost_s: float = 0.0,
    ) -> None:
        self.lag, self.suspended, self.clock, self.poll_cost_s = lag, suspended, clock, poll_cost_s
        self.applied = [OTHER] if applied is None else applied
        self.drops: list[str] = []
        self.polls = 0
        self.wal_reads = 0
        self.last_wal: tuple[str, tuple[object, ...]] | None = None  # no per-call log: stay bounded

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        if sql.startswith("ALTER"):
            self.drops.append(sql)
            assert len(self.drops) < 5, "runaway: the DROP is being re-issued"
            return []
        if "wal_tables" in sql:
            self.wal_reads += 1
            self.last_wal = (sql, params)
            return [{"suspended": self.suspended}]
        self.polls += 1
        assert self.polls < 20_000, "runaway polling: the wall-clock bound never tripped"
        if self.clock is not None:
            self.clock.now += self.poll_cost_s
        if self.lag is None or self.polls <= self.lag:
            return [dict(LIVE), dict(OTHER)]
        return [dict(row) for row in self.applied]


def _hot(pg: DropPg | FakePg, clock: FakeClock, **kw: float) -> QuestDbHotPartitions:
    return QuestDbHotPartitions(pg, sleep=clock.sleep, clock=clock, **kw)


async def test_hot_partitions_drop_waits_until_applied() -> None:
    clock, pg = FakeClock(), DropPg(lag=3)
    await _hot(pg, clock).drop_day(T, DAY_START_US)
    assert pg.polls == 4 and len(pg.drops) == 1
    assert clock.slept == [0.02, 0.04, 0.08]
    assert pg.wal_reads == 3  # suspension is only read while the day is still listed


@pytest.mark.parametrize(
    "emptied",
    [
        {"name": DAY, "numRows": 0, "minTimestamp": datetime(2026, 10, 17)},
        {"name": DAY, "numRows": "0", "minTimestamp": datetime(2026, 10, 17)},
        {"name": DAY, "numRows": 5, "minTimestamp": None},
    ],
    ids=["zero-rows", "zero-rows-as-text", "null-min-timestamp"],
)
async def test_hot_partitions_drop_listed_but_emptied_partition_counts_as_applied(
    emptied: dict[str, object],
) -> None:
    """QuestDB can keep an emptied partition listed until purge: zero rows = nothing to lose."""
    clock, pg = FakeClock(), DropPg(lag=0, applied=[emptied, OTHER])
    await _hot(pg, clock).drop_day(T, DAY_START_US)
    assert pg.polls == 1 and clock.slept == [] and pg.wal_reads == 0


@pytest.mark.parametrize(
    "row",
    [
        {"name": DAY},
        {"name": DAY, "numRows": "n/a", "minTimestamp": datetime(2026, 10, 17)},
        {"name": DAY, "numRows": None, "minTimestamp": datetime(2026, 10, 17)},
    ],
    ids=["no-row-evidence", "unparsable-num-rows", "null-num-rows"],
)
async def test_hot_partitions_drop_listed_without_proof_of_emptiness_is_not_applied(
    row: dict[str, object],
) -> None:
    """Fail closed: a listed day counts as gone only on positive evidence that it is empty."""
    clock, pg = FakeClock(), DropPg(lag=0, applied=[row, OTHER])
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        await _hot(pg, clock, apply_timeout_s=1.0).drop_day(T, DAY_START_US)
    assert exc.value.reason == "timeout"


async def test_hot_partitions_drop_inventory_without_name_column_fails_closed() -> None:
    """No row carries `name` (shape change): `{""}` must never read as 'the day is gone'."""
    pg = FakePg([{"partition": DAY, "numRows": 0}])
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        await QuestDbHotPartitions(pg).drop_day(T, DAY_START_US)
    assert exc.value.reason == "unexpected_shape" and "reason=unexpected_shape" in str(exc.value)
    assert len(pg.calls) == 2  # the DROP and one poll: no retry on a shape we cannot read


async def test_hot_partitions_drop_suspended_table_fails_fast_and_never_reissues_the_drop() -> None:
    clock, pg = FakeClock(), DropPg(lag=None, suspended=True)
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        await _hot(pg, clock).drop_day(T, DAY_START_US)
    err = exc.value
    assert err.reason == "suspended" and "reason=suspended" in str(err)
    assert (err.table, err.partition) == ("trades", DAY)
    assert len(pg.drops) == 1 and pg.polls == 1 and clock.slept == []  # no second DROP, no wait
    assert pg.last_wal == ("SELECT suspended FROM wal_tables() WHERE name = $1", ("trades",))


async def test_hot_partitions_drop_never_applied_raises_timeout_after_wall_clock_bound() -> None:
    clock, pg = FakeClock(), DropPg(lag=None)
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        await _hot(pg, clock).drop_day(T, DAY_START_US)  # default bound: 120 s
    err = exc.value
    assert err.reason == "timeout" and "reason=timeout" in str(err)
    assert max(clock.slept) == 0.2  # backoff doubles from 20 ms and caps at 200 ms
    assert 120.0 <= err.waited_s < 120.2 and err.waited_s == pytest.approx(sum(clock.slept))
    assert len(pg.drops) == 1 and pg.wal_reads == pg.polls  # one DROP; suspension read per poll


async def test_hot_partitions_drop_wall_clock_bound_counts_slow_polls_not_only_sleeps() -> None:
    clock = FakeClock()
    pg = DropPg(lag=None, clock=clock, poll_cost_s=50.0)  # each inventory poll "takes" 50 s
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        await _hot(pg, clock, apply_timeout_s=120.0).drop_day(T, DAY_START_US)
    assert exc.value.reason == "timeout" and pg.polls == 3
    assert exc.value.waited_s >= 150.0  # 3 polls: the sleeps alone (~0.06 s) never reach 120 s


class HungPg:
    """The DROP is accepted; the first inventory poll never answers."""

    def __init__(self) -> None:
        self.polling = asyncio.Event()

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        if not sql.startswith("ALTER"):
            self.polling.set()
            await asyncio.Event().wait()
        return []


@pytest.mark.parametrize(
    ("poll_timeout_s", "apply_timeout_s"),
    [(3600.0, 0.01), (0.01, 3600.0)],
    ids=["wall-clock-bound", "per-poll-bound"],
)
async def test_hot_partitions_drop_hung_poll_is_a_typed_timeout(
    poll_timeout_s: float, apply_timeout_s: float
) -> None:
    hot = QuestDbHotPartitions(HungPg(), timeout_s=poll_timeout_s, apply_timeout_s=apply_timeout_s)
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        # One bound trips in ~10 ms, the other is an hour away; the guard only fails a hang.
        await asyncio.wait_for(hot.drop_day(T, DAY_START_US), timeout=5)
    assert exc.value.reason == "timeout"


async def test_hot_partitions_drop_cancellation_is_not_swallowed() -> None:
    pg = HungPg()
    task = asyncio.ensure_future(QuestDbHotPartitions(pg).drop_day(T, DAY_START_US))
    await pg.polling.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_hot_partitions_drop_logs_one_warning_per_failure_and_nothing_per_poll() -> None:
    clock = FakeClock()
    with capture_logs() as quiet:
        await _hot(DropPg(lag=5), clock).drop_day(T, DAY_START_US)
    assert quiet == []  # six polls, five waits: nothing logged
    with capture_logs() as logs, pytest.raises(StoragePartitionDropNotApplied):
        await _hot(DropPg(lag=None, suspended=True), clock).drop_day(T, DAY_START_US)
    assert logs == [
        {
            "event": "rolloff_drop_not_applied",
            "log_level": "warning",
            "table": "trades",
            "partition": DAY,
            "reason": "suspended",
            "waited_s": 0.0,
        }
    ]


async def test_hot_partitions_refuse_stream_without_hot_table() -> None:
    with pytest.raises(DatasetNotRegistered):
        await QuestDbHotPartitions(FakePg()).drop_day(StreamKind.BARS, DAY_START_US)


async def test_watermark_store_persists_monotone_and_attributable(tmp_path: Path) -> None:
    store = FileWatermarkStore(DatasetRegistry(tmp_path))
    await store.advance("BTCUSDT", T, 200, now_us=5)
    await store.advance("BTCUSDT", T, 100, now_us=6)  # never backwards
    reread = await FileWatermarkStore(DatasetRegistry(tmp_path)).get("BTCUSDT", T)
    assert (reread.archived_through_us, reread.updated_at_us) == (200, 5)
    await store.mark_downsampled("BTCUSDT", T, 50, now_us=7)
    await store.mark_downsampled("BTCUSDT", T, 40, now_us=8)
    got = await store.get("BTCUSDT", T)
    assert (got.archived_through_us, got.downsampled_through_us) == (200, 50)
    assert (await store.get("ETHUSDT", T)).archived_through_us == 0


async def test_watermark_store_rejects_traversal(tmp_path: Path) -> None:
    store = FileWatermarkStore(DatasetRegistry(tmp_path))
    with pytest.raises(DatasetNotRegistered):
        await store.advance("../x", T, 1, now_us=1)


def test_downsample_keeps_last_state_per_level_per_second() -> None:
    t = pa.table(
        {
            "ts": pa.array([0, 10, 1_000_001, 1_500_000], pa.int64()),
            "depth": [200] * 4,
            "side": ["bid", "bid", "bid", "ask"],
            "price": [1.0, 1.0, 1.0, 2.0],
            "size": [1.0, 2.0, 3.0, 4.0],
        }
    )
    out = _downsample_table(t, ("depth", "side", "price")).to_pylist()
    assert [(r["side"], r["size"]) for r in out] == [("bid", 2.0), ("bid", 3.0), ("ask", 4.0)]
    assert {r["_downsample"] for r in out} == {"1s"}
    assert int(out[1]["ts"].timestamp()) == 1


async def test_downsampler_replaces_old_book_partitions_not_merges(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path)
    rows = 50
    table = pa.table(
        {
            "ts": pa.array([DAY_START_US + i * 100_000 for i in range(rows)], pa.int64()),
            "symbol": ["BTCUSDT"] * rows,
            "depth": [200] * rows,
            "side": ["bid"] * rows,
            "price": [1.0] * rows,
            "size": [float(i) for i in range(rows)],
        }
    )
    src = FakeHotSource(table)
    rng = TimeRange(start_us=DAY_START_US, end_us=DAY_START_US + 3_600_000_000)
    exp = ColdExporter(reg, src, clock=fixed_clock)
    await exp.export_partition(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, rng, partition_extra={"hour": "00"}
    )
    through = await ColdDownsampler(reg).downsample_before(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, DAY_START_US + 2 * 86_400_000_000
    )
    assert through == DAY_START_US + 86_400_000_000
    part = tmp_path / "orderbook_deltas" / "symbol=BTCUSDT" / "dt=2026-10-17" / "hour=00"
    entries = ManifestStore(tmp_path / "_manifests").read(part, tmp_path)
    assert [e.export_run_id for e in entries] == [DOWNSAMPLE_RUN_ID]
    assert entries[0].row_count == 5  # 50 updates at 100 ms -> 5 one-second snapshots
    assert sorted(p.name for p in part.glob("*.parquet")) == [entries[0].file]
    again = await ColdDownsampler(reg).downsample_before(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, DAY_START_US + 2 * 86_400_000_000
    )
    assert again == through  # idempotent
    assert pq.read_table(part / entries[0].file).num_rows == 5


async def test_downsampler_refuses_non_book_stream(tmp_path: Path) -> None:
    with pytest.raises(DatasetNotRegistered):
        await ColdDownsampler(DatasetRegistry(tmp_path)).downsample_before("BTCUSDT", T, 1)


async def _two_files(root: Path) -> None:
    reg = DatasetRegistry(root)
    for half in (0, 1):
        src = FakeHotSource(trades_table(10, start_us=DAY_START_US + half * 1000))
        rng = TimeRange(
            start_us=DAY_START_US + half * 1000, end_us=DAY_START_US + half * 1000 + 999
        )
        await ColdExporter(reg, src, clock=fixed_clock).export_partition("BTCUSDT", T, rng)


async def test_compaction_defers_partition_under_replay_and_completes_rest(
    tmp_path: Path,
) -> None:
    await _two_files(tmp_path)

    async def busy(_p: Path) -> str | None:
        return "replay-1"

    progress: list[float] = []
    summary = await compact_all(
        DatasetRegistry(tmp_path), Compactor(busy), clock=fixed_clock, on_progress=progress.append
    )
    assert summary.deferred == [PART.as_posix()] and summary.compacted == 0
    assert progress == [100.0]
    summary = await compact_all(DatasetRegistry(tmp_path), Compactor(), clock=fixed_clock)
    assert summary.compacted == 1 and summary.as_result()["deferred"] == []


async def test_compaction_filters_by_symbol_and_age(tmp_path: Path) -> None:
    await _two_files(tmp_path)
    reg = DatasetRegistry(tmp_path)
    assert (await compact_all(reg, Compactor(), symbols=["ETHUSDT"])).compacted == 0
    s = await compact_all(reg, Compactor(), older_than_days=30, clock=fixed_clock)
    assert s.compacted == 0  # partition is 1 day old


async def _book_partition(root: Path) -> Path:
    reg = DatasetRegistry(root)
    rows = 50
    table = pa.table(
        {
            "ts": pa.array([DAY_START_US + i * 100_000 for i in range(rows)], pa.int64()),
            "symbol": ["BTCUSDT"] * rows,
            "depth": [200] * rows,
            "side": ["bid"] * rows,
            "price": [1.0] * rows,
            "size": [float(i) for i in range(rows)],
        }
    )
    rng = TimeRange(start_us=DAY_START_US, end_us=DAY_START_US + 3_600_000_000)
    await ColdExporter(reg, FakeHotSource(table), clock=fixed_clock).export_partition(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, rng, partition_extra={"hour": "00"}
    )
    return root / "orderbook_deltas" / "symbol=BTCUSDT" / "dt=2026-10-17" / "hour=00"


async def test_downsample_corrupt_source_is_quarantined_not_laundered(tmp_path: Path) -> None:
    from candleviewer.storage.cold.rolloff_ops import DownsampleSourceCorrupt

    part = await _book_partition(tmp_path)
    f = part / "part-0000.parquet"
    f.write_bytes(f.read_bytes()[:-16] + b"\0" * 16)
    with pytest.raises(DownsampleSourceCorrupt):
        await ColdDownsampler(DatasetRegistry(tmp_path)).downsample_before(
            "BTCUSDT", StreamKind.ORDERBOOK_DELTA, DAY_START_US + 2 * 86_400_000_000
        )
    q = tmp_path / "_quarantine" / part.relative_to(tmp_path)
    assert (q / "part-0000.parquet").is_file()
    assert json.loads((q / "part-0000.reason.json").read_text("utf-8"))["reason"] == "sha256"
    entries = ManifestStore(tmp_path / "_manifests").read(part, tmp_path)
    assert all(e.export_run_id != DOWNSAMPLE_RUN_ID for e in entries)


async def test_downsample_bad_derivation_keeps_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.storage.cold import rolloff_ops

    part = await _book_partition(tmp_path)
    real = rolloff_ops._downsample_table

    def lossy(table: pa.Table, key: tuple[str, ...]) -> pa.Table:
        out = real(table, key)
        return out.slice(0, out.num_rows - 1)  # drops one second: count-only check misses shape

    monkeypatch.setattr(rolloff_ops, "_downsample_table", lossy)
    with pytest.raises(StorageExportVerifyFailed):
        rolloff_ops.downsample_partition_sync(
            DatasetRegistry(tmp_path).resolve_partition(
                StreamKind.ORDERBOOK_DELTA,
                partition_values={"symbol": "BTCUSDT", "dt": "2026-10-17", "hour": "00"},
            ),
            StreamKind.ORDERBOOK_DELTA,
        )
    assert sorted(p.name for p in part.glob("*.parquet")) == ["part-0000.parquet"]
    entries = ManifestStore(tmp_path / "_manifests").read(part, tmp_path)
    assert [e.file for e in entries] == ["part-0000.parquet"]


async def test_quarantine_sidecar_is_atomic_and_metric_counts(tmp_path: Path) -> None:
    from candleviewer.storage.cold.rolloff_ops import storage_rolloff_quarantined_total

    before = storage_rolloff_quarantined_total.labels(reason="checksum")._value.get()
    await _archiver(tmp_path, TamperingSource(trades_table(50)), RecordingSink()).archive_day(
        "BTCUSDT", T, day_range()
    )
    after = storage_rolloff_quarantined_total.labels(reason="checksum")._value.get()
    assert after == before + 1
    q = tmp_path / "_quarantine" / PART
    assert not [p for p in _walk(q) if p.suffix == ".tmp"]


async def test_corrupt_watermark_fails_closed_with_critical_event(tmp_path: Path) -> None:
    sink = RecordingSink()
    store = FileWatermarkStore(DatasetRegistry(tmp_path), events=sink)
    await store.advance("BTCUSDT", T, 500, now_us=1)
    doc = tmp_path / "_manifests" / "_watermarks" / "trades" / "symbol=BTCUSDT.json"
    doc.write_text("{not json", "utf-8")
    mark = await store.get("BTCUSDT", T)
    assert mark.archived_through_us == 0  # fail-closed: nothing assumed rolled off
    assert ("CRITICAL", "recorder.watermark_corrupt") in [(s, c) for s, c, _ in sink.events]
    healed = await store.advance("BTCUSDT", T, 600, now_us=2)  # next run repairs the doc
    assert healed.archived_through_us == 600
    assert (await store.get("BTCUSDT", T)).archived_through_us == 600


async def test_watermark_concurrent_advance_and_downsample_lose_no_update(tmp_path: Path) -> None:
    import asyncio

    store = FileWatermarkStore(DatasetRegistry(tmp_path))
    await asyncio.gather(
        *(store.advance("BTCUSDT", T, 100 + i, now_us=i) for i in range(10)),
        *(store.mark_downsampled("BTCUSDT", T, 50 + i, now_us=i) for i in range(10)),
    )
    mark = await store.get("BTCUSDT", T)
    assert (mark.archived_through_us, mark.downsampled_through_us) == (109, 59)
    assert mark.version == 20


async def test_watermark_cas_rejects_foreign_writer(tmp_path: Path) -> None:
    from candleviewer.storage.cold.watermarks import RollOffWatermark, WatermarkConflict

    store = FileWatermarkStore(DatasetRegistry(tmp_path))
    await store.advance("BTCUSDT", T, 100, now_us=1)  # version 1 on disk
    with pytest.raises(WatermarkConflict):
        store._write_sync(RollOffWatermark("BTCUSDT", T, 200, version=1), expected=0)


async def test_downsampler_defers_partition_under_replay_lease(tmp_path: Path) -> None:
    part = await _book_partition(tmp_path)

    async def busy(_p: Path) -> str | None:
        return "replay-1"

    through = await ColdDownsampler(DatasetRegistry(tmp_path), busy).downsample_before(
        "BTCUSDT", StreamKind.ORDERBOOK_DELTA, DAY_START_US + 2 * 86_400_000_000
    )
    assert through == 0
    entries = ManifestStore(tmp_path / "_manifests").read(part, tmp_path)
    assert all(e.export_run_id != DOWNSAMPLE_RUN_ID for e in entries)


async def test_hot_partitions_snapshot_is_one_query_with_value_fingerprint() -> None:
    pg = FakePg([{"symbol": "BTCUSDT", "n": 7, "hi": "2026-10-17T23:59", "v": 1.5}])
    snap = await QuestDbHotPartitions(pg).snapshot(T, day_range())
    assert snap == {"BTCUSDT": (7, "2026-10-17T23:59|1.5")}
    assert len(pg.calls) == 1
    sql, params = pg.calls[0]
    assert "count()" in sql and "max(ts)" in sql and "sum(size)" in sql and "FROM trades" in sql
    assert all(isinstance(p, datetime) and p.tzinfo is None for p in params)
