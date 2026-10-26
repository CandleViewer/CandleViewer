"""Unit: E16-T07's write gate fails closed on a stale sample (#4581).

`DiskBudget` ages its last completed pass at every read, on an injected monotonic clock. Once
that pass is older than three sample intervals, `halted`, `refuses_auto_record` and
`effective_level` read as at level 3, and so do the report and the level gauge; two completed
passes in a row re-open the gate, and every failed pass is counted. A fake meter, injected clocks
and an injected sleep that the test steps: no disk and no real sleep."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from structlog.testing import capture_logs

from candleviewer.observability.metrics import Counter, Gauge
from candleviewer.recorder.budget import BudgetConfig, DiskBudget
from candleviewer.recorder.metrics import (
    disk_budget_sample_failed_total,
    recorder_disk_pressure_level,
)
from candleviewer.recorder.models import DiskPressureLevel as L
from candleviewer.recorder.writer import DiskGate, StreamWriter, WriterConfig
from tests.unit.recorder._budget_fakes import CAP, NOW, FakeEvents, FakeMeter
from tests.unit.recorder._fakes import FakeBus, FakeClock
from tests.unit.recorder._session_fakes import UsClock
from tests.unit.recorder._writer_helpers import T0, FakeSink, FakeStore, FsyncCounter, trade
from tests.unit.recorder._writer_helpers import FakeEvents as WriterEvents

#: The monotonic time the budget is built at and its first pass runs at.
T = 1_000.0
#: Three sample intervals of 60 s (`BudgetConfig.sample_interval_s`).
BOUND = 180.0
#: `(halted, refuses_auto_record, effective_level)`.
OPEN, CLOSED, WARN = (False, False, L.NORMAL), (True, True, L.HALT), (False, False, L.WARN)
#: The gate's two transition logs.
MOVES = frozenset({"disk_budget_samples_stale", "disk_budget_samples_fresh"})


class Loop:
    """The budget's injected sleep. The task parks here after each pass; `release()` lets the
    next pass run at the clocks' current time, and `step()` also waits until it is over."""

    def __init__(self) -> None:
        self._go, self._idle = asyncio.Event(), asyncio.Event()

    async def sleep(self, _seconds: float) -> None:
        self._idle.set()
        await self._go.wait()
        self._go.clear()

    async def idle(self) -> None:
        await asyncio.wait_for(self._idle.wait(), timeout=5)

    def release(self) -> None:
        self._idle.clear()
        self._go.set()

    async def step(self, mono: FakeClock, at: float) -> None:
        """One more pass, at monotonic time `at`."""
        mono.t = at
        self.release()
        await self.idle()


@dataclass
class StuckMeter(FakeMeter):
    """Once `stuck`, `volume()` never answers, so its pass never returns."""

    stuck: bool = False
    entered: asyncio.Event = field(default_factory=asyncio.Event)

    async def volume(self) -> tuple[int, int]:
        if self.stuck:
            self.entered.set()
            await asyncio.Event().wait()
        return await super().volume()


def _budget(
    meter: FakeMeter, mono: FakeClock, loop: Loop, config: BudgetConfig | None = None
) -> DiskBudget:
    return DiskBudget(
        meter=meter,
        events=FakeEvents(),
        bus=FakeBus(),
        env="demo",
        config=config or BudgetConfig(cap_bytes=CAP),
        now_us=UsClock(NOW),
        sleep=loop.sleep,
        monotonic=mono,
    )


def _gate(budget: DiskBudget) -> tuple[bool, bool, L]:
    return budget.halted, budget.refuses_auto_record, budget.effective_level


def _read(metric: Counter | Gauge) -> float:
    """An unlabelled series' value (a counter's `_total` sample, not its `_created`)."""
    samples = [s for m in metric.collect() for s in m.samples]
    (value,) = [s.value for s in samples if not s.name.endswith("_created")]
    return value


def _at(us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us)


async def test_a_raising_meter_closes_the_gate_three_intervals_after_its_last_pass() -> None:
    mono, meter, loop = FakeClock(T), FakeMeter(used=CAP * 84 // 100), Loop()  # level 1 (WARN)
    budget = _budget(meter, mono, loop)
    budget.start()
    try:
        await loop.idle()  # the first pass, at T, completes
        failed = _read(disk_budget_sample_failed_total)
        meter.fail = True
        for at in (T + 60, T + 120, T + BOUND):  # failed passes: the last level holds
            await loop.step(mono, at)
            assert (_gate(budget), _read(recorder_disk_pressure_level)) == (WARN, 1.0), at
        mono.t = T + BOUND + 0.001  # no pass since: the readers age the last one themselves
        assert _gate(budget) == CLOSED
        assert (budget.level, budget.accelerate_retention) == (L.WARN, False)  # the ladder's own
        await loop.step(mono, T + 240)
        assert (_gate(budget), _read(recorder_disk_pressure_level)) == (CLOSED, 3.0)
        assert _read(disk_budget_sample_failed_total) - failed == 4
        report = budget.report()
        assert report is not None
        gate = report.level, report.write_gate, report.write_gate_reason
        assert gate == (L.HALT, "closed", "disk_halt")
    finally:
        await budget.stop()


async def test_a_meter_that_never_answers_ages_the_gate_from_construction() -> None:
    mono, meter, loop = FakeClock(T), FakeMeter(fail=True), Loop()
    failed = _read(disk_budget_sample_failed_total)
    budget = _budget(meter, mono, loop)  # built at T: with no completed pass, the age starts here
    budget.start()
    try:
        await loop.idle()  # the first pass, at T, fails
        assert (_gate(budget), _read(recorder_disk_pressure_level)) == (OPEN, 0.0)
        for at in (T + 60, T + 120, T + BOUND):  # more failed passes: open up to exactly 180 s
            await loop.step(mono, at)
            assert (_gate(budget), _read(recorder_disk_pressure_level)) == (OPEN, 0.0), at
        mono.t = T + BOUND + 0.001
        assert _gate(budget) == CLOSED
        await loop.step(mono, T + 240)
        assert (_gate(budget), _read(recorder_disk_pressure_level)) == (CLOSED, 3.0)
        await loop.step(mono, T + 300)  # a failed pass while already closed still counts
        assert _read(disk_budget_sample_failed_total) - failed == 6
    finally:
        await budget.stop()


async def test_a_pass_that_never_returns_still_closes_the_gate_at_read_time() -> None:
    mono, meter, loop = FakeClock(T), StuckMeter(), Loop()
    config = BudgetConfig(cap_bytes=CAP, io_timeout_s=3_600.0)  # nothing ends the stuck read
    budget = _budget(meter, mono, loop, config)
    budget.start()
    try:
        await loop.idle()  # the first pass, at T, completes
        meter.stuck, mono.t = True, T + 60
        loop.release()
        await asyncio.wait_for(meter.entered.wait(), timeout=5)  # the second never returns
        mono.t = T + BOUND
        assert _gate(budget) == OPEN
        mono.t = T + BOUND + 0.001
        assert _gate(budget) == CLOSED
        report = budget.report()
        assert report is not None and (report.level, report.write_gate) == (L.HALT, "closed")
    finally:
        await budget.stop()


async def test_after_a_stale_spell_only_the_second_pass_in_a_row_reopens_the_gate() -> None:
    mono, meter, loop = FakeClock(T), FakeMeter(), Loop()
    budget = _budget(meter, mono, loop)
    with capture_logs() as logs:
        budget.start()
        try:
            await loop.idle()
            meter.fail = True
            for at in (T + 60, T + 120, T + 180, T + 240):
                await loop.step(mono, at)
            meter.fail = False
            await loop.step(mono, T + 300)  # one completed pass is not yet a recovery
            assert (_gate(budget), _read(recorder_disk_pressure_level)) == (CLOSED, 3.0)
            await loop.step(mono, T + 360)  # the second in a row re-opens the gate
            assert (_gate(budget), _read(recorder_disk_pressure_level)) == (OPEN, 0.0)
            report = budget.report()
            assert report is not None
            gate = report.level, report.write_gate, report.write_gate_reason
            assert gate == (L.NORMAL, "open", None)
            await loop.step(mono, T + 660)  # completed, but 300 s after the last one
            assert _gate(budget) == CLOSED
            await loop.step(mono, T + 720)
            assert _gate(budget) == OPEN
        finally:
            await budget.stop()
    moves = [e for e in logs if e["event"] in MOVES]
    assert [(e["event"], e["log_level"], e.get("error")) for e in moves] == [
        ("disk_budget_samples_stale", "error", "OSError"),
        ("disk_budget_samples_fresh", "info", None),
        ("disk_budget_samples_stale", "error", None),
        ("disk_budget_samples_fresh", "info", None),
    ]
    assert all(set(e) <= {"event", "log_level", "error"} for e in moves)  # the class only


async def test_a_meter_that_fails_between_its_successes_never_flaps_the_gate() -> None:
    mono, meter, loop = FakeClock(T), FakeMeter(), Loop()
    budget = _budget(meter, mono, loop)
    at = T

    async def passes(*fails: bool) -> list[bool]:
        """One pass per entry, 60 s apart (`True` fails it): `halted` after each."""
        nonlocal at
        seen = []
        for fail in fails:
            meter.fail, at = fail, at + 60
            await loop.step(mono, at)
            seen.append(budget.halted)
        return seen

    budget.start()
    try:
        await loop.idle()
        flaky, spell = (True, False) * 3, (True, True, True, True)
        assert await passes(*flaky) == [False] * 6  # a success every 120 s: never stale
        assert await passes(*spell) == [False, False, False, True]  # open at exactly 180 s
        assert await passes(*(False, True) * 3) == [True] * 6  # never two in a row
        assert await passes(*(False, True, True, True) * 2) == [True] * 8  # one in four
        assert await passes(False, False) == [True, False]  # two in a row
    finally:
        await budget.stop()


async def test_the_writer_drops_rows_while_stale_and_takes_them_after_recovery() -> None:
    mono = FakeClock(T)
    budget = _budget(FakeMeter(), mono, Loop())
    sink, store, clock = FakeSink(), FakeStore(), FakeClock(100.0)
    writer = StreamWriter(
        lambda _stream: sink,
        store,
        WriterEvents(),
        WriterConfig(wal_dir=Path("unused-wal"), env="live"),
        clock=clock,
        wall_clock_us=lambda: T0,
        fsync=FsyncCounter(),
        disk_gate=DiskGate(lambda: budget.halted, lambda _symbol: False),  # no open position
    )
    writer.seed(["BTCUSDT"])
    await budget.sample_once()  # a completed pass at T
    await writer.on_trade(trade(1))
    mono.t = T + BOUND + 1  # no pass since: stale
    await writer.on_trade(trade(2))
    await budget.sample_once()  # the first completed pass after it: still closed
    await writer.on_trade(trade(3))
    mono.t += 60
    await budget.sample_once()  # the second in a row: open
    await writer.on_trade(trade(4))
    clock.advance(1)
    await writer.pump("trades")
    await writer.flush_gaps()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1", "t4"]
    gaps = [(g["start"], g["end"], g["cause"]) for g in store.gaps]
    assert gaps == [(_at(T0 + 2), _at(T0 + 3), "backpressure_drop")]  # t2 to t3, both dropped


async def test_the_report_follows_a_refused_volume_set_after_its_sample() -> None:
    budget = _budget(FakeMeter(used=CAP), FakeClock(T), Loop())  # level 3 on the ladder
    await budget.sample_once()
    report = budget.report()
    assert report is not None and report.write_gate_reason == "disk_halt"
    budget.recording_refused = True  # the same level, a different reason
    report = budget.report()
    assert report is not None and report.write_gate_reason == "volume_refused"
