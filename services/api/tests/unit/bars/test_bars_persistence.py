"""E12-T02 (#345): row mapping, DDL vs doc, write backpressure, upsert, stale build_version."""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.bars.errors import SyntheticBarPersistError
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, build_range_query
from candleviewer.bars.rows import (
    BarPersistError,
    bar_param_for,
    bar_row,
    row_checksum,
    to_double,
)
from candleviewer.bars.writer import BarBufferFull, BarWriter
from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import BAR_SCHEMAS_BY_FAMILY

ROOT = Path(__file__).resolve().parents[5]
SPEC = BarSpec(kind="time", interval_ms=300_000)


def _bar(**kw: object) -> Bar:
    base = dict(
        spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=3, open_time=1_700_000_000_000_000,
        close_time=1_700_000_299_999_999, open=Decimal("100.1"), high=Decimal("101"),
        low=Decimal("99.5"), close=Decimal("100.5"), volume=Decimal("10"),
        buy_volume=Decimal("6"), sell_volume=Decimal("4"), delta=Decimal("2"),
        min_delta=Decimal("-1"), max_delta=Decimal("3"), trade_count=7, turnover=Decimal("1001"),
        vwap=Decimal("100.3"), closed=True, partial=False, gap_before=False,
    )  # fmt: skip
    base.update(kw)
    return Bar.model_validate(base)


def test_to_double_rounds_to_nearest_binary64_and_refuses_non_finite() -> None:
    assert to_double(Decimal("0.1")) == 0.1
    assert to_double(Decimal("-0")) == 0.0 and str(to_double(Decimal("-0"))) == "0.0"
    # exact midpoint of 1.0 and 1+2**-52: ties-to-even picks 1.0; just above it rounds up
    mid = Decimal("1.00000000000000011102230246251565404236316680908203125")
    assert to_double(mid) == 1.0
    assert to_double(mid + Decimal("1e-30")) == 1.0000000000000002
    assert Decimal(repr(to_double(Decimal("100.1")))) == Decimal("100.1")
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("1e999")):
        with pytest.raises(BarPersistError):
            to_double(bad)


@pytest.mark.parametrize(
    ("spec", "param"),
    [
        (BarSpec(kind="time", interval_ms=300_000), "5m"),
        (BarSpec(kind="time", interval_ms=3_600_000), "1h"),
        (BarSpec(kind="time", interval_ms=86_400_000), "1d"),
        (BarSpec(kind="tick", tick_count=500), "tick:500"),
        (BarSpec(kind="volume", volume_threshold=Decimal(1000)), "vol:1000"),
        (BarSpec(kind="range", range_ticks=20), "range:20"),
        (BarSpec(kind="renko", range_ticks=10), "renko:10"),
        (BarSpec(kind="delta", delta_threshold=Decimal(500)), "delta:500"),
    ],
)
def test_bar_param_is_human_readable_never_the_hash(spec: BarSpec, param: str) -> None:
    assert bar_param_for(spec) == param


def test_unrenderable_spec_is_refused() -> None:
    with pytest.raises(BarPersistError):
        bar_param_for(BarSpec(kind="time", interval_ms=60_000, price_source="mark"))


def test_row_golden_ilp_line() -> None:
    row = bar_row(_bar(), SPEC, generation=0)
    row["row_checksum"] = 0
    line = serialize_ilp_line(
        BAR_SCHEMAS_BY_FAMILY["time"],
        {k: v for k, v in row.items() if k != "ts"},
        int(str(row["ts"])),
    )
    assert line == (
        "bars_time,symbol=BTCUSDT,bar_param=5m,source=tape "
        "close_ts=1700000299999999t,open=100.1,high=101.0,"
        "low=99.5,close=100.5,volume=10.0,buy_volume=6.0,sell_volume=4.0,delta=2.0,min_delta=-1.0,"
        "max_delta=3.0,delta_pct=20.0,trade_count=7i,vwap=100.3,is_closed=true,build_version=1i,"
        "generation=0i,index=3i,row_checksum=0i 1700000000000000000"
    )


def test_checksum_is_independent_of_tag_field_placement() -> None:
    row = bar_row(_bar(), SPEC, generation=0)
    reordered = dict(reversed(list(row.items())))
    assert row_checksum(reordered) == row["row_checksum"]


def test_checksum_changes_with_values() -> None:
    a = bar_row(_bar(), SPEC, generation=0)
    b = bar_row(_bar(close=Decimal("100.6")), SPEC, generation=0)
    assert a["row_checksum"] == row_checksum(a) != b["row_checksum"]


def test_synthetic_bar_is_refused() -> None:
    with pytest.raises(SyntheticBarPersistError):
        bar_row(_bar(synthetic=True), SPEC, generation=0)


def test_source_must_be_known() -> None:
    with pytest.raises(BarPersistError):
        bar_row(_bar(), SPEC, source="guess", generation=0)


def test_ddl_matches_schema_doc() -> None:
    doc = (ROOT / "docs/plan/21-database-schema.md").read_text("utf-8")
    block = doc[doc.index("### 4.8") : doc.index("### 4.9")]
    doc_cols = re.findall(
        r"^\s{2}(\w+)\s+(?:TIMESTAMP|SYMBOL|DOUBLE|LONG|INT|BOOLEAN)", block, re.M
    )
    doc_cols += re.findall(r"\b(open|high|low|close)\s+DOUBLE", block)
    # Dedup keys are doc-derived too, so the strict xfail flips to a loud XPASS failure
    # exactly when the DDL catches up with §4.8 (migration 0004, #2016).
    doc_keys_m = re.search(r"DEDUP UPSERT KEYS\(([^)]*)\)", block)
    assert doc_keys_m is not None
    doc_keys = tuple(k.strip().strip('"') for k in doc_keys_m.group(1).split(","))
    tables = {
        t.name: t for t in parse_ddl_dir(ROOT / "backend/db/questdb") if t.name.startswith("bars_")
    }
    assert sorted(tables) == sorted(
        f"bars_{k}" for k in ("time", "tick", "volume", "range", "renko", "delta")
    )
    base = set(doc_cols)
    for name, t in tables.items():
        extra = {"open_source_ts"} if name in ("bars_renko", "bars_range") else set()
        assert set(t.columns) - {"source", "row_checksum"} == base | extra, name
        assert t.partition_by == "MONTH" and t.ts_col == "ts"
        assert t.dedup_keys == doc_keys
        assert {"source", "row_checksum"} <= set(t.columns)


async def _settle() -> None:
    """Let every ready task run to its next await (no wall-clock sleep)."""
    for _ in range(25):
        await asyncio.sleep(0)


class _SlowSink:
    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.rows: list[dict[str, object]] = []

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.entered.set()
        await self.gate.wait()
        self.rows.extend(rows)


@pytest.mark.asyncio
async def test_backpressure_awaits_and_drops_nothing() -> None:
    sink = _SlowSink()
    w = BarWriter(sink, max_buffered=3, batch_rows=1)
    await w.start()
    bars = [_bar(index=i, open_time=1_700_000_000_000_000 + i) for i in range(12)]
    producer = asyncio.create_task(w.submit(bars, SPEC, generation=0))
    await sink.entered.wait()
    await _settle()
    assert not producer.done()  # blocked, awaiting space
    assert w.depth <= 3
    sink.gate.set()
    await producer
    await w.stop()
    assert len(sink.rows) == 12


@pytest.mark.asyncio
async def test_new_spec_refused_when_saturated_but_known_spec_waits() -> None:
    sink = _SlowSink()
    w = BarWriter(sink, max_buffered=4, batch_rows=1, refuse_new_specs_at=0.5)
    await w.start()
    await w.submit([_bar(index=0)], SPEC, generation=0)
    more = [_bar(index=i, open_time=1_700_000_000_000_000 + i) for i in range(1, 5)]
    await w.submit(more, SPEC, generation=0)
    await sink.entered.wait()
    await _settle()
    other = BarSpec(kind="tick", tick_count=100)
    assert not w.healthy
    with pytest.raises(BarBufferFull):
        await w.submit([_bar(spec_hash=other.spec_hash)], other, generation=0)
    sink.gate.set()
    await w.stop()


@pytest.mark.asyncio
async def test_sink_failure_retries_and_loses_nothing() -> None:
    calls = 0

    class Flaky:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("down")
            self.rows.extend(rows)

    sink = Flaky()

    async def no_sleep(_: float) -> None:
        return None

    w = BarWriter(sink, sleep=no_sleep)
    await w.start()
    await w.submit([_bar()], SPEC, generation=0)
    await w.stop()
    assert len(sink.rows) == 1 and calls == 2


@pytest.mark.asyncio
async def test_amended_close_has_same_dedup_key() -> None:
    first = bar_row(_bar(), SPEC, generation=0)
    amended = bar_row(_bar(close=Decimal("100.9")), SPEC, generation=0)

    def key(r: dict[str, object]) -> tuple[object, ...]:
        return (r["ts"], r["symbol"], r["bar_param"], r["generation"], r["index"])

    assert key(first) == key(amended) and first["close"] != amended["close"]
    assert amended["row_checksum"] != first["row_checksum"]


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.sqls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.sqls.append((sql, params))
        return self.rows


@pytest.mark.asyncio
async def test_stale_build_version_served_and_rebuild_scheduled_once() -> None:
    old = bar_row(_bar(), SPEC, generation=0)
    old["build_version"] = 0
    old["row_checksum"] = row_checksum(old)
    scheduled: list[tuple[str, str, int, int]] = []

    async def sched(sym: str, h: str, lo: int, hi: int) -> None:
        scheduled.append((sym, h, lo, hi))

    reader = BarReader(_Conn([old]), sched)
    for _ in range(3):
        page = await reader.read_bars("BTCUSDT", SPEC, 0, 2**55, 10)
        assert page.stale and len(page.rows) == 1
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_read_cursor_and_checksum_drop() -> None:
    good = bar_row(_bar(), SPEC, generation=0)
    bad = replace_row(bar_row(_bar(index=4, open_time=1_700_000_000_000_009), SPEC, generation=0))
    page = await BarReader(_Conn([good, bad]), _sched_noop).read_bars("BTCUSDT", SPEC, 0, 2**55, 2)
    assert page.rows == [good] and page.next_cursor == 1_700_000_000_000_009


def replace_row(r: dict[str, object]) -> dict[str, object]:
    return {**r, "close": 1.0}  # value changed after checksum


async def _sched_noop(sym: str, h: str, lo: int, hi: int) -> None:
    return None


def test_range_query_is_parameterised_and_bounded() -> None:
    sql, params = build_range_query("time", "X'; DROP", "5m", 0, 10, 4, 100)
    assert "DROP" not in sql and params == ("X'; DROP", "5m", ts_param(5), ts_param(10))
    assert sql.endswith("LIMIT 100") and len(params) == len(set(re.findall(r"\$\d+", sql)))
    with pytest.raises(ValueError):
        build_range_query("evil", "X", "5m", 0, 1, None, 1)
    with pytest.raises(ValueError):
        build_range_query("time", "X", "5m", 0, 1, None, 0)
    _ = replace


# ---- r2: source precedence, rebuild registry, integrity events -------------------------------


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
        self.rows.extend(rows)


@pytest.mark.asyncio
async def test_kline_may_not_overwrite_tape_but_other_directions_allowed() -> None:
    from candleviewer.bars.writer import SourceOverwriteRefused, bars_source_overwrite_refused_total

    sink = _Sink()
    w = BarWriter(sink)
    await w.start()
    await w.submit([_bar()], SPEC, source="tape", generation=0)
    await w.submit(
        [_bar(close=Decimal("100.9"))], SPEC, source="tape", generation=0
    )  # amend: allowed
    before = bars_source_overwrite_refused_total.labels("kline", "tape")._value.get()
    with pytest.raises(SourceOverwriteRefused):
        await w.submit([_bar()], SPEC, source="kline", generation=0)
    assert bars_source_overwrite_refused_total.labels("kline", "tape")._value.get() == before + 1
    other = _bar(index=9, open_time=1_700_000_900_000_000)
    await w.submit([other], SPEC, source="kline", generation=0)
    await w.submit([other], SPEC, source="tape", generation=0)  # kline -> tape: allowed
    await w.stop()
    assert len(sink.rows) == 4


@pytest.mark.asyncio
async def test_rebuild_registry_is_single_flight_bucketed_bounded_and_backs_off() -> None:
    from candleviewer.bars import reader as rd

    now = [0.0]
    calls: list[tuple[str, str, int, int]] = []
    fail = [True]

    async def sched(s: str, h: str, lo: int, hi: int) -> None:
        calls.append((s, h, lo, hi))
        if fail[0]:
            raise ConnectionError("x")

    reg = rd.RebuildRegistry(sched, clock=lambda: now[0])
    assert not await reg.request("BTC", "h", 5, 10)  # fails -> backoff
    assert not await reg.request("BTC", "h", 6, 11)  # same bucket, still backing off
    assert len(calls) == 1
    now[0] = 10.0
    fail[0] = False
    assert await reg.request("BTC", "h", 7, 12)  # retry succeeded
    assert not await reg.request("BTC", "h", 8, 13)  # done: deduplicated
    # a client sweeping distinct windows collapses into bounded buckets
    for i in range(100):
        await reg.request("BTC", "h", i * rd.WINDOW_GRID_US, (i + 1) * rd.WINDOW_GRID_US)
    assert len(reg) <= rd.MAX_BUCKETS_PER_SERIES + 1
    now[0] = 10_000.0  # TTL prune
    await reg.request("ETH", "h2", 0, 1)
    assert len(reg) == 1


@pytest.mark.asyncio
async def test_rebuild_registry_global_cap_and_attempt_limit() -> None:
    from candleviewer.bars import reader as rd

    async def boom(*a: object) -> None:
        raise ConnectionError

    now = [0.0]
    reg = rd.RebuildRegistry(boom, clock=lambda: now[0])
    for _ in range(rd.MAX_ATTEMPTS + 2):
        now[0] += 20.0  # past every backoff step, inside the TTL
        await reg.request("BTC", "h", 0, 1)
    assert reg._entries[("BTC", "h", 0, 0)].attempts == rd.MAX_ATTEMPTS
    for i in range(rd.MAX_REGISTRY + 10):
        await reg.request(f"S{i}", "h", 0, 1)
    assert len(reg) <= rd.MAX_REGISTRY


@pytest.mark.asyncio
async def test_checksum_mismatch_and_missing_are_integrity_events() -> None:
    from candleviewer.bars.reader import bars_checksum_mismatch_total as m

    good = bar_row(_bar(), SPEC, generation=0)
    bad = {
        **bar_row(_bar(index=4, open_time=1_700_000_000_000_009), SPEC, generation=0),
        "close": 1.0,
    }
    missing = {
        **bar_row(_bar(index=5, open_time=1_700_000_000_000_010), SPEC, generation=0),
        "row_checksum": None,
    }
    legacy = {**missing, "source": None, "ts": 1_700_000_000_000_011}
    b = (
        m.labels("bars_time", "mismatch")._value.get(),
        m.labels("bars_time", "missing")._value.get(),
    )
    page = await BarReader(_Conn([good, bad, missing, legacy]), _sched_noop).read_bars(
        "BTCUSDT", SPEC, 0, 2**55, 10
    )
    assert page.rows == [good, legacy]  # NULL checksum + non-NULL source is NOT trusted
    assert page.integrity_degraded and page.dropped == 2
    assert m.labels("bars_time", "mismatch")._value.get() == b[0] + 1
    assert m.labels("bars_time", "missing")._value.get() == b[1] + 1


def test_checksum_round_trips_through_ilp_floats() -> None:
    row = bar_row(_bar(), SPEC, generation=0)
    assert row_checksum(row) == row["row_checksum"]
    assert row_checksum({**row, "open": float(repr(row["open"]))}) == row["row_checksum"]


class _OrderSink:
    """Fails the first write (the ORIGINAL close); records the order rows land in."""

    def __init__(self) -> None:
        self.landed: list[object] = []
        self.calls = 0

    async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("down")
        self.landed.extend(r["close"] for r in rows)


@pytest.mark.asyncio
async def test_failed_original_retries_before_amend_so_final_row_is_the_amend() -> None:
    sink = _OrderSink()
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    w = BarWriter(sink, batch_rows=1, sleep=fake_sleep)
    await w.start()
    await w.submit([_bar()], SPEC, generation=0)  # original close 100.5 (batch 1 fails once)
    await w.submit([_bar(close=Decimal("100.9"))], SPEC, generation=0)  # amend
    assert await w.stop() == 0
    assert sink.landed == [100.5, 100.9]  # last write wins -> the amend
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_permanent_error_not_retried_transient_bounded_and_counted() -> None:
    from candleviewer.bars import writer as wr

    class Bad:
        calls = 0

        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
            Bad.calls += 1
            raise self.exc

    async def no_sleep(_: float) -> None:
        return None

    perm = wr.bars_write_failed_total.labels("permanent")._value.get()
    w = BarWriter(Bad(ValueError("bad row")), sleep=no_sleep)
    await w.start()
    await w.submit([_bar()], SPEC, generation=0)
    assert await w.stop() == 0
    assert Bad.calls == 1 and w.degraded and w.last_error is not None
    assert wr.bars_write_failed_total.labels("permanent")._value.get() == perm + 1

    Bad.calls = 0
    exh = wr.bars_write_failed_total.labels("transient_exhausted")._value.get()
    w2 = BarWriter(Bad(ConnectionError("down")), sleep=no_sleep)
    await w2.start()
    await w2.submit([_bar()], SPEC, generation=0)
    await w2.stop()
    assert Bad.calls == wr.MAX_ATTEMPTS and w2.degraded
    assert wr.bars_write_failed_total.labels("transient_exhausted")._value.get() == exh + 1


@pytest.mark.asyncio
async def test_stop_is_bounded_and_returns_remaining() -> None:
    sink = _SlowSink()  # never released: QuestDB "down"
    w = BarWriter(sink, batch_rows=1)
    await w.start()
    await w.submit(
        [_bar(index=i, open_time=1_700_000_000_000_000 + i) for i in range(3)], SPEC, generation=0
    )
    assert await w.stop(timeout_s=0.01) == 3
