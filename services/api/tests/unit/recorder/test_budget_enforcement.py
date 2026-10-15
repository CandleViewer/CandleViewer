"""Unit: E16-T07 enforcement (#491): the B11-safe write gate, the auto-record refusal, the plain
bools and the metrics `DiskBudget` publishes for them. Fakes only, no I/O, no sleeps."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

import candleviewer
from candleviewer.observability.metrics import Gauge
from candleviewer.recorder.budget import US_PER_DAY, US_PER_S, Breakdown, BudgetConfig, Point
from candleviewer.recorder.metrics import (
    disk_free_bytes,
    disk_used_ratio,
    recorder_bytes_per_day,
    recorder_disk_budget_breakdown_age_seconds,
    recorder_disk_budget_last_sample_timestamp_seconds,
    recorder_disk_pressure_level,
    recorder_projected_full_timestamp,
)
from candleviewer.recorder.models import DiskPressureLevel as L
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from candleviewer.recorder.writer import DiskGate, StreamWriter, WriterConfig
from tests.unit.recorder._budget_fakes import (
    CAP,
    GB,
    NOW,
    TOTAL,
    Clock,
    FakeMeter,
    make_budget,
)
from tests.unit.recorder._budget_fakes import FakeStore as SeriesStoreFake
from tests.unit.recorder._writer_helpers import (
    T0,
    FakeClock,
    FakeEvents,
    FakeSink,
    FakeStore,
    FsyncCounter,
    trade,
)
from tests.unit.recorder.conftest import FakeAudit, FakeBus
from tests.unit.recorder.conftest import FakeClock as PolicyClock

HOUR = 3_600 * US_PER_S


@dataclass
class Gate:
    halted_now: bool = True
    positions: set[str] = field(default_factory=set)
    broken: bool = False

    def halted(self) -> bool:
        if self.broken:
            raise RuntimeError("budget unavailable")
        return self.halted_now


def _writer(gate: Gate) -> tuple[StreamWriter, FakeSink, FakeStore, FakeClock]:
    """No `open()`: the gate and the gap buffer never touch the WAL directory."""
    sink, store, clock = FakeSink(), FakeStore(), FakeClock()
    w = StreamWriter(
        lambda _stream: sink,
        store,
        FakeEvents(),
        WriterConfig(wal_dir=Path("unused-wal")),
        clock=clock,
        wall_clock_us=lambda: T0,
        fsync=FsyncCounter(),
        disk_gate=DiskGate(gate.halted, gate.positions.__contains__),
    )
    w.seed(["BTCUSDT", "ETHUSDT"])
    return w, sink, store, clock


def _at(us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us)


async def _drain(w: StreamWriter, clock: FakeClock) -> None:
    clock.advance(1)
    await w.pump("trades")
    await w.flush_gaps()


async def test_halted_gate_drops_no_position_symbols_and_keeps_open_positions() -> None:
    w, sink, store, clock = _writer(Gate(positions={"ETHUSDT"}))
    for i, symbol in enumerate(("BTCUSDT", "ETHUSDT", "BTCUSDT"), start=1):
        await w.on_trade(trade(i, symbol))
    await _drain(w, clock)
    assert [r["symbol"] for r in sink.rows("trades")] == ["ETHUSDT"]
    gap = {"symbol": "BTCUSDT", "stream": "trades", "cause": "backpressure_drop"}
    assert store.gaps == [gap | {"start": _at(T0 + 1), "end": _at(T0 + 3)}]


async def test_gate_lifts_on_release_and_rows_flow_again() -> None:
    gate = Gate()
    w, sink, store, clock = _writer(gate)
    await w.on_trade(trade(1))
    gate.halted_now = False  # the ladder left level 3 (used < 90 %, free >= 10 %)
    await w.on_trade(trade(2))
    await _drain(w, clock)
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t2"]
    assert [(g["start"], g["end"]) for g in store.gaps] == [(_at(T0 + 1), _at(T0 + 2))]


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["BTCUSDT", "ETHUSDT"]), st.booleans(), st.booleans(), st.booleans()
        )
    )
)
def test_an_open_position_never_loses_a_row_and_no_gap_spans_a_written_row(
    steps: list[tuple[str, bool, bool, bool]],
) -> None:
    """ETHUSDT holds a position throughout; BTCUSDT's opens and closes mid-sequence; gaps
    are flushed at random points (C-2.14: a gap never contains a written `exch_ts`)."""

    async def run() -> tuple[FakeStore, list[dict[str, object]]]:
        gate = Gate(positions={"ETHUSDT"})
        w, sink, store, clock = _writer(gate)
        for i, (symbol, halted, btc_open, flush) in enumerate(steps, start=1):
            gate.halted_now = halted
            gate.positions ^= {"BTCUSDT"} if btc_open != ("BTCUSDT" in gate.positions) else set()
            await w.on_trade(trade(i, symbol))
            if flush:
                await w.flush_gaps()
        await _drain(w, clock)
        return store, sink.rows("trades")

    store, rows = asyncio.run(run())
    kept = [
        f"t{i}"
        for i, (symbol, halted, btc_open, _) in enumerate(steps, start=1)
        if not halted or symbol == "ETHUSDT" or btc_open
    ]
    assert [r["trade_id"] for r in rows] == kept  # dropped only when halted and no position
    assert all(g["symbol"] != "ETHUSDT" for g in store.gaps)
    for gap in store.gaps:
        written = [_at(int(str(r["ts"]))) for r in rows if r["symbol"] == gap["symbol"]]
        assert not any(gap["start"] <= at < gap["end"] for at in written), (gap, written)


async def test_an_admitted_row_seals_the_gate_window() -> None:
    gate = Gate()
    w, sink, store, clock = _writer(gate)
    await w.on_trade(trade(1))
    gate.halted_now = False
    await w.on_trade(trade(2))  # sealed here: the next drop opens a new window
    gate.halted_now = True
    await w.on_trade(trade(3))
    await _drain(w, clock)
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t2"]
    spans = [(g["start"], g["end"]) for g in store.gaps]
    assert spans == [(_at(T0 + 1), _at(T0 + 2)), (_at(T0 + 3), _at(T0 + 4))]


async def test_a_failing_gate_check_keeps_writing_and_logs_once() -> None:
    w, sink, store, clock = _writer(Gate(broken=True))
    with capture_logs() as logs:
        await w.on_trade(trade(1))
        await w.on_trade(trade(2))
    await _drain(w, clock)
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1", "t2"] and store.gaps == []
    assert [e["event"] for e in logs].count("recorder_disk_gate_failed") == 1


async def test_disk_pressure_refuses_new_chart_recording_only(
    bus: FakeBus, audit: FakeAudit
) -> None:
    clock, pressure = PolicyClock(), [True]
    p = RecordingPolicy(
        bus=bus,
        audit=audit,
        env="demo",
        now=clock,
        config=PolicyConfig(),
        disk_refuses=lambda: pressure[0],
    )
    p.positions_reloaded()
    try:
        await p.add_manual("BTCUSDT", user_actor("owner-1"))  # the explicit list keeps going
        await p.on_position_opened("ETHUSDT", "pos-1")  # money at risk: never refused
        await p.on_chart_opened("SOLUSDT", "c1")
        clock.advance(60)
        await p.tick()
        await p.tick()  # the refusal engages once
        assert set(p.effective_set()) == {"BTCUSDT", "ETHUSDT"}
        refused = [e for key, e in bus.events if key == "demo.recorder.cap_refused"]
        assert [(e.symbol, e.cause) for e in refused] == [("SOLUSDT", "disk_pressure")]
        denied = [kw["reason"] for a, kw in audit.records if kw.get("outcome") == "denied"]
        assert denied == ["disk_pressure"]
        pressure[0] = False  # below the level-2 release
        await p.tick()
        assert "SOLUSDT" in p.effective_set()
    finally:
        await p.stop()


async def test_position_open_assumes_open_until_positions_reload(
    bus: FakeBus, audit: FakeAudit
) -> None:
    p = RecordingPolicy(disk_refuses=bool, bus=bus, audit=audit, env="demo", now=PolicyClock())
    try:
        assert p.position_open("BTCUSDT")  # warm-up: the position cache is not authoritative
        p.positions_reloaded()
        assert not p.position_open("BTCUSDT")
        await p.on_position_opened("BTCUSDT", "pos-1")
        assert p.position_open("BTCUSDT")
        await p.on_position_closed("BTCUSDT", "pos-1")
        assert not p.position_open("BTCUSDT")
    finally:
        await p.stop()


async def test_budget_bools_and_metrics_follow_the_ladder_and_a_refused_volume() -> None:
    meter, clock = FakeMeter(), Clock()
    budget, _, _ = make_budget(meter, clock=clock)
    seen = []
    for pct in (91, 96, 91, 89, 84):
        meter.used, clock.t = CAP * pct // 100, clock.t + 60 * US_PER_S
        await budget.sample_once()
        seen.append((budget.refuses_auto_record, budget.halted))
    assert seen == [(True, False), (True, True), (True, True), (True, False), (False, False)]
    assert (_gauge(disk_used_ratio), _gauge(recorder_disk_pressure_level)) == (0.84, 1.0)
    assert (_gauge(disk_free_bytes), _gauge(recorder_projected_full_timestamp)) == (TOTAL // 2, 0)
    budget.recording_refused = True  # SR-096: a shared volume keeps the gate closed
    assert (budget.refuses_auto_record, budget.halted) == (True, True)
    await budget.sample_once()
    assert _gauge(recorder_disk_pressure_level) == 3.0  # so the halt pages


def _gauge(metric: Gauge) -> float | None:
    found = [x.value for f in metric.collect() for x in f.samples if not x.labels]
    return found[0] if found else None


def test_order_paths_never_import_the_recorder_or_its_budget() -> None:
    """SR-096 / AC4 'placing an order still succeeds': no OMS or exchange module can read the
    disk budget, the gate or the recorder, so recording pressure cannot reach order placement."""
    root = Path(candleviewer.__file__).parent
    for path in [*(root / "oms").rglob("*.py"), *(root / "exchange").rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom | ast.Import):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                names += [a.name for a in node.names]
                assert not any(
                    n.startswith(("candleviewer.recorder", "candleviewer.budget_wiring"))
                    for n in names
                ), path


async def test_a_hung_breakdown_never_freezes_the_free_space_ladder() -> None:
    class HungMeter(FakeMeter):
        async def breakdown(self) -> Breakdown:  # QuestDB / the walk never answers
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    meter = HungMeter(free=TOTAL * 4 // 100)
    config = BudgetConfig(cap_bytes=CAP, breakdown_timeout_s=0.01)
    budget, events, _ = make_budget(meter, config=config)
    await budget.sample_once()
    assert budget.level is L.HALT and events.events[0][1] == "recorder.disk_halt"
    await budget.stop()
    assert meter.closed  # stop() also closes the meter


async def test_rate_labels_follow_the_reported_symbols_and_future_points_are_ignored() -> None:
    clock, used = Clock(), 10 * GB
    history = [
        Point(t, used - (NOW - t) // 1_000, (("ETHUSDT", 10 * GB - (NOW - t) // US_PER_S),))
        for t in range(NOW - 2 * HOUR, NOW, 600 * US_PER_S)
    ]
    store = SeriesStoreFake([*history, Point(NOW + US_PER_DAY, 0, ())])  # a future point: ignored
    meter = FakeMeter(used=used, symbols={"ETHUSDT": 10 * GB})
    budget, _, _ = make_budget(meter, clock=clock, store=store)
    await budget.load_series()
    await budget.sample_once()
    assert [p.ts_us for p in store.appended] == [NOW]
    assert _labelled(recorder_bytes_per_day, symbol="ETHUSDT") == 86_400.0
    clock.t += 25 * HOUR  # the history leaves the 24 h window
    meter.symbols = {}
    await budget.sample_once()
    assert _labelled(recorder_bytes_per_day, symbol="ETHUSDT") is None


def _labelled(metric: Gauge, **labels: str) -> float | None:
    found = [x.value for f in metric.collect() for x in f.samples if x.labels == labels]
    return found[0] if found else None


async def test_a_stale_breakdown_never_commits_and_its_age_is_exported() -> None:
    meter, clock, store = FakeMeter(used=GB, symbols={"BTCUSDT": GB}), Clock(), SeriesStoreFake()
    budget, _, _ = make_budget(meter, clock=clock, store=store)
    await budget.sample_once()  # fresh: committed
    meter.breakdown_fail, clock.t = True, clock.t + 600 * US_PER_S
    await budget.sample_once()  # stale: no point, no refit, the ladder still runs
    assert [p.ts_us for p in store.appended] == [NOW]
    assert _gauge(recorder_disk_budget_breakdown_age_seconds) == 600.0
    assert _gauge(recorder_disk_budget_last_sample_timestamp_seconds) == (NOW // US_PER_S) + 600
