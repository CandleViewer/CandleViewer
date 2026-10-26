"""Unit: `RollOffJob` (E16-T05) — verified drop, retention on failure, backoff,
watermark monotonicity/attribution, oldest-first, lock contention, downsample.

All ports are in-memory fakes; time is an injected clock, backoff an injected
sleep (no real waits, no I/O).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.recorder.coverage import attribute_tiers
from candleviewer.recorder.intervals import Span
from candleviewer.recorder.rolloff import (
    US_PER_DAY,
    RollOffConfig,
    RollOffJob,
    RollOffReport,
    RollOffTask,
    recorder_rolloff_failures_total,
    recorder_rolloff_streams_unlisted_total,
)
from candleviewer.storage.cold.watermarks import ArchiveOutcome, RollOffWatermark
from candleviewer.storage.errors import DropNotAppliedReason, StoragePartitionDropNotApplied
from candleviewer.storage.models import StreamKind, TimeRange

NOW = datetime(2026, 10, 20, 2, 15, tzinfo=UTC)
NOW_US = int(NOW.timestamp() * 1_000_000)
TODAY = NOW_US - NOW_US % US_PER_DAY
T = StreamKind.TRADES


def day(n_ago: int) -> int:
    return TODAY - n_ago * US_PER_DAY


@dataclass
class FakeHot:
    days: dict[StreamKind, dict[int, list[str]]]
    dropped: list[tuple[StreamKind, int]] = field(default_factory=list)
    aged: dict[StreamKind, int] = field(default_factory=dict)  # partitions closed_days misses
    aged_before: list[int] = field(default_factory=list)

    async def closed_days(self, stream: StreamKind, before_us: int) -> list[int]:
        return [d for d in self.days.get(stream, {}) if d + US_PER_DAY <= before_us]

    async def aged_partitions(self, stream: StreamKind, before_us: int) -> int:
        self.aged_before.append(before_us)
        return self.aged.get(stream, 0)

    async def symbols_in(self, stream: StreamKind, rng: TimeRange) -> list[str]:
        return list(self.days[stream][rng.start_us])

    async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
        return dict.fromkeys(self.days[stream][rng.start_us], 10)

    def value_tag(self, rng: TimeRange) -> str:
        return "v0"

    async def snapshot(self, stream: StreamKind, rng: TimeRange) -> dict[str, tuple[int, str]]:
        counts = await self.row_counts(stream, rng)
        return {sym: (n, self.value_tag(rng)) for sym, n in counts.items()}

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
        self.dropped.append((stream, day_start_us))
        del self.days[stream][day_start_us]


@dataclass
class FakeArchiver:
    """`fail` maps (symbol, day) -> remaining failures (reason code)."""

    fail: dict[tuple[str, int], list[str]] = field(default_factory=dict)
    verified: set[tuple[str, StreamKind, int]] = field(default_factory=set)
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def archive_day(self, symbol: str, stream: StreamKind, d: TimeRange) -> ArchiveOutcome:
        self.calls.append((symbol, d.start_us))
        pending = self.fail.get((symbol, d.start_us), [])
        if pending:
            return ArchiveOutcome(
                symbol, stream, d.start_us, d.end_us, False, reason=pending.pop(0)
            )
        self.verified.add((symbol, stream, d.start_us))
        return ArchiveOutcome(symbol, stream, d.start_us, d.end_us, True, rows=10, bytes=100)


class FakeMarks:
    def __init__(self) -> None:
        self.m: dict[tuple[str, StreamKind], RollOffWatermark] = {}

    async def get(self, symbol: str, stream: StreamKind) -> RollOffWatermark:
        return self.m.get((symbol, stream), RollOffWatermark(symbol, stream))

    async def advance(
        self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
    ) -> RollOffWatermark:
        cur = await self.get(symbol, stream)
        if through_us > cur.archived_through_us:
            cur = RollOffWatermark(symbol, stream, through_us, cur.downsampled_through_us, now_us)
            self.m[(symbol, stream)] = cur
        return cur

    async def mark_downsampled(
        self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
    ) -> RollOffWatermark:
        cur = await self.get(symbol, stream)
        cur = RollOffWatermark(symbol, stream, cur.archived_through_us, through_us, now_us)
        self.m[(symbol, stream)] = cur
        return cur


class Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, str | int]]] = []

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        self.rows.append((action, detail))


class Events:
    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        return None


class Lock:
    def __init__(self, held: set[str] | None = None) -> None:
        self.held = held or set()

    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        yield volume not in self.held


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


def _job(hot: FakeHot, arch: FakeArchiver, marks: FakeMarks, **kw: object) -> RollOffJob:
    async def hot_days(symbol: str, stream: StreamKind) -> int | None:
        return 7

    params: dict[str, object] = {
        "hot": hot,
        "archiver": arch,
        "watermarks": marks,
        "hot_days": hot_days,
        "audit": kw.pop("audit", Audit()),
        "events": Events(),
        "lock": kw.pop("lock", Lock()),
        "config": RollOffConfig(streams=(T,), backoff_base_s=1.0, backoff_max_s=4.0),
        "clock": lambda: NOW,
        "sleep": kw.pop("sleep", Sleeps()),
    }
    params.update(kw)
    return RollOffJob(**params)  # type: ignore[arg-type]  # test kwargs assembled dynamically


async def test_rolloff_old_partition_verified_is_dropped_audited_and_watermark_advances() -> None:
    hot = FakeHot({T: {day(10): ["BTCUSDT"], day(2): ["BTCUSDT"]}})
    arch, marks, audit = FakeArchiver(), FakeMarks(), Audit()
    report = await _job(hot, arch, marks, audit=audit).run()
    assert hot.dropped == [(T, day(10))]  # day(2) is inside the 7-day hot window
    assert report.dropped == [(T, day(10))]
    mark = await marks.get("BTCUSDT", T)
    assert mark.archived_through_us == day(10) + US_PER_DAY
    assert mark.updated_at_us == NOW_US
    action, detail = audit.rows[0]
    assert action == "retention.purge"
    assert detail["stream"] == "trades" and detail["rows"] == 10
    assert detail["range_start_us"] == day(10)


@pytest.mark.parametrize("reason", ["archive_verification_failed", "archive_write_failed"])
async def test_rolloff_failure_retains_hot_retries_with_backoff_and_freezes_watermark(
    reason: str,
) -> None:
    hot = FakeHot({T: {day(10): ["BTCUSDT"]}})
    arch = FakeArchiver(fail={("BTCUSDT", day(10)): [reason] * 5})
    marks, sleeps, audit = FakeMarks(), Sleeps(), Audit()
    report = await _job(hot, arch, marks, sleep=sleeps, audit=audit).run()
    assert hot.dropped == []
    assert report.retained == [(T, day(10), reason)]
    assert len(arch.calls) == 3  # bounded attempts
    assert sleeps.calls == [1.0, 2.0]  # exponential backoff
    assert (await marks.get("BTCUSDT", T)).archived_through_us == 0
    assert audit.rows == []


async def test_rolloff_transient_failure_recovers_on_retry() -> None:
    hot = FakeHot({T: {day(10): ["BTCUSDT"]}})
    arch = FakeArchiver(fail={("BTCUSDT", day(10)): ["archive_verification_failed"]})
    await _job(hot, arch, FakeMarks()).run()
    assert hot.dropped == [(T, day(10))]


async def test_rolloff_day_with_one_failing_symbol_is_not_dropped() -> None:
    hot = FakeHot({T: {day(9): ["BTCUSDT", "ETHUSDT"]}})
    arch = FakeArchiver(fail={("ETHUSDT", day(9)): ["archive_verification_failed"] * 3})
    marks = FakeMarks()
    await _job(hot, arch, marks).run()
    assert hot.dropped == []
    assert (await marks.get("BTCUSDT", T)).archived_through_us == 0


async def test_rolloff_older_failing_day_stops_newer_drops_and_caps_the_watermark() -> None:
    """#2347: oldest-first, and a day that stays hot stops the stream, so no newer day is
    dropped above it and the watermark is a contiguous prefix."""
    hot = FakeHot({T: {day(12): ["BTCUSDT"], day(11): ["BTCUSDT"], day(10): ["BTCUSDT"]}})
    arch = FakeArchiver(fail={("BTCUSDT", day(11)): ["archive_verification_failed"] * 3})
    marks = FakeMarks()
    with capture_logs() as logs:
        report = await _job(hot, arch, marks).run()
    assert [e for e in logs if e["event"] == "rolloff_stream_stopped"] == [
        {
            "event": "rolloff_stream_stopped",
            "log_level": "warning",
            "stream": "trades",
            "day_start_us": day(11),
            "reason": "archive_verification_failed",
        }
    ]
    assert [d for _, d in arch.calls] == [day(12)] + [day(11)] * 3  # oldest first; day(10) waits
    assert hot.dropped == report.dropped == [(T, day(12))]
    assert report.retained == [(T, day(11), "archive_verification_failed")]
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(12) + US_PER_DAY


class _WatermarkCheckingHot(FakeHot):
    """At every `drop_day`, each symbol of the day must already be below its watermark."""

    def __init__(self, days: dict[StreamKind, dict[int, list[str]]], marks: FakeMarks) -> None:
        super().__init__(days)
        self.marks = marks
        self.trailing: list[tuple[str, int]] = []

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
        for symbol in self.days[stream][day_start_us]:
            mark = await self.marks.get(symbol, stream)
            if mark.archived_through_us < day_start_us + US_PER_DAY:
                self.trailing.append((symbol, day_start_us))
        await super().drop_day(stream, day_start_us)


async def test_rolloff_watermark_covers_each_day_before_its_drop() -> None:
    marks = FakeMarks()
    hot = _WatermarkCheckingHot(
        {T: {day(12): ["BTCUSDT", "ETHUSDT"], day(11): ["BTCUSDT"], day(10): ["ETHUSDT"]}}, marks
    )
    await _job(hot, FakeArchiver(), marks).run()
    assert hot.dropped == [(T, day(12)), (T, day(11)), (T, day(10))]
    assert hot.trailing == []  # no day was ever gone from QuestDB while still labelled hot
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(11) + US_PER_DAY
    assert (await marks.get("ETHUSDT", T)).archived_through_us == day(10) + US_PER_DAY


async def test_rolloff_crash_after_watermark_before_drop_reads_cold_and_rerun_redrops() -> None:
    """Killed between the watermark write and the DROP: the day is in both tiers, coverage
    attributes it to Parquet (verified there), and the next run drops it idempotently."""

    class KillAtDrop(FakeHot):
        armed = True

        async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
            if self.armed:
                self.armed = False
                raise Kill
            await super().drop_day(stream, day_start_us)

    hot, arch, marks, audit = (
        KillAtDrop({T: {day(10): ["BTCUSDT"]}}),
        FakeArchiver(),
        FakeMarks(),
        Audit(),
    )
    with pytest.raises(Kill):
        await _job(hot, arch, marks, audit=audit).run()
    mark = (await marks.get("BTCUSDT", T)).archived_through_us
    assert mark == day(10) + US_PER_DAY and day(10) in hot.days[T]  # both tiers: safe
    assert ("BTCUSDT", T, day(10)) in arch.verified
    tiers = attribute_tiers([Span(day(10), day(10) + US_PER_DAY)], mark)
    assert [(i.lo, i.hi, i.tier) for i in tiers] == [(day(10), day(10) + US_PER_DAY, "parquet")]

    report = await _job(hot, arch, marks, audit=audit).run()
    assert hot.dropped == report.dropped == [(T, day(10))] and hot.days[T] == {}
    after = await marks.get("BTCUSDT", T)
    assert after.archived_through_us == mark and after.updated_at_us == NOW_US  # max(): no move
    assert [a for a, _ in audit.rows] == ["retention.purge", "retention.purge"]
    assert await _job(hot, arch, marks, audit=audit).run() == RollOffReport()  # nothing left


async def test_rolloff_day_kept_by_another_symbols_window_blocks_newer_days_of_its_symbols() -> (
    None
):
    """A day outside the window for one symbol (pinned) stays hot for all of its symbols, so a
    newer day holding one of them may not drop past it; a newer day without them still drops."""

    async def pinned_sol(symbol: str, stream: StreamKind) -> int | None:
        return None if symbol == "SOLUSDT" else 7

    marks = FakeMarks()
    hot = FakeHot(
        {T: {day(13): ["SOLUSDT"], day(12): ["BTCUSDT", "SOLUSDT"], day(11): ["BTCUSDT"],
             day(10): ["ETHUSDT"]}}
    )  # fmt: skip
    await _job(hot, FakeArchiver(), marks, hot_days=pinned_sol).run()
    assert hot.dropped == [(T, day(10))]
    assert (await marks.get("BTCUSDT", T)).archived_through_us == 0
    assert (await marks.get("ETHUSDT", T)).archived_through_us == day(10) + US_PER_DAY


async def test_rolloff_pinned_symbol_is_never_rolled_off() -> None:
    hot = FakeHot({T: {day(30): ["BTCUSDT"]}})

    async def pinned(symbol: str, stream: StreamKind) -> int | None:
        return None

    await _job(hot, FakeArchiver(), FakeMarks(), hot_days=pinned).run()
    assert hot.dropped == []


async def test_rolloff_advisory_lock_contention_skips_stream() -> None:
    hot = FakeHot({T: {day(10): ["BTCUSDT"]}})
    report = await _job(hot, FakeArchiver(), FakeMarks(), lock=Lock({"rolloff:trades"})).run()
    assert report.skipped_locked == [T] and hot.dropped == []


async def test_rolloff_rejects_naive_clock() -> None:
    job = _job(FakeHot({T: {}}), FakeArchiver(), FakeMarks(), clock=lambda: datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="tz-aware"):
        await job.run()


class FakeDown:
    def __init__(self) -> None:
        self.calls: list[tuple[str, StreamKind, int]] = []

    async def downsample_before(self, symbol: str, stream: StreamKind, before_us: int) -> int:
        self.calls.append((symbol, stream, before_us))
        return before_us - US_PER_DAY


class ColdSyms:
    async def symbols(self, stream: StreamKind) -> list[str]:
        return ["BTCUSDT"]


async def test_rolloff_downsamples_only_book_streams_past_180_days_and_labels_range() -> None:
    down, marks = FakeDown(), FakeMarks()
    job = _job(FakeHot({T: {}}), FakeArchiver(), marks, downsampler=down, cold_symbols=ColdSyms())
    report = await job.run()
    assert {s for _, s, _ in down.calls} == {
        StreamKind.ORDERBOOK_DELTA,
        StreamKind.HEATMAP_CELLS,
    }
    assert all(b == NOW_US - 180 * US_PER_DAY for _, _, b in down.calls)
    mark = await marks.get("BTCUSDT", StreamKind.ORDERBOOK_DELTA)
    assert mark.downsampled_through_us == NOW_US - 181 * US_PER_DAY
    assert len(report.downsampled) == 2


async def test_rolloff_task_runs_job_survives_failure_and_stops() -> None:
    runs: list[int] = []
    slept = asyncio.Event()
    never = asyncio.Event()

    class Boom:
        async def run(self) -> None:
            runs.append(1)
            raise RuntimeError("x")

    async def sleep(s: float) -> None:
        slept.set()
        await never.wait()  # parked until cancelled

    task = RollOffTask(Boom(), interval_s=5.0, sleep=sleep)  # type: ignore[arg-type]  # duck-typed job
    task.start()
    await asyncio.wait_for(slept.wait(), 5)
    assert task.running and runs == [1]  # the failed run did not kill the loop
    await task.stop()
    assert not task.running


class _UnwindFails:
    """A job whose run, once cancelled, fails while unwinding (a lock release that raises)."""

    def __init__(self) -> None:
        self.parked = asyncio.Event()

    async def run(self) -> None:
        try:
            self.parked.set()
            await asyncio.Event().wait()
        finally:
            raise ConnectionError("release failed")


class _CancelResistant:
    """A job that absorbs every cancel and hangs until released."""

    def __init__(self) -> None:
        self.parked = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self) -> None:
        self.parked.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                continue


async def test_rolloff_stop_returns_when_the_run_fails_while_unwinding_the_cancel() -> None:
    job = _UnwindFails()
    sleeps: list[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)
        await asyncio.Event().wait()

    task = RollOffTask(job, interval_s=86400.0, sleep=sleep)  # type: ignore[arg-type]  # duck-typed job
    task.start()
    await asyncio.wait_for(job.parked.wait(), 5)
    await asyncio.wait_for(task.stop(), 5)  # returns: no 24 h sleep after the failed release
    assert sleeps == [] and not task.running


async def test_rolloff_stop_is_bounded_when_the_run_will_not_unwind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("candleviewer.recorder.rolloff.ROLLOFF_STOP_TIMEOUT_S", 0.05)
    job = _CancelResistant()
    slept = asyncio.Event()

    async def park(_: float) -> None:  # the released run's next night never comes
        slept.set()
        await asyncio.Event().wait()

    task = RollOffTask(job, interval_s=1.0, sleep=park)  # type: ignore[arg-type]  # duck-typed job
    task.start()
    await asyncio.wait_for(job.parked.wait(), 5)
    try:
        with capture_logs() as logs:
            await asyncio.wait_for(task.stop(), 5)  # the bound, not the 5 s guard, ends the wait
        assert [e["event"] for e in logs] == ["rolloff_stop_timed_out"]
        stuck = task._stuck  # the run left behind stays referenced
        assert stuck is not None and not stuck.done()
    finally:
        job.release.set()
    await asyncio.wait_for(slept.wait(), 5)
    stuck.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stuck, 5)


async def test_an_outer_cancel_of_rolloff_stop_propagates() -> None:
    class Parked:
        parked = asyncio.Event()

        async def run(self) -> None:
            self.parked.set()
            await asyncio.Event().wait()

    job = Parked()
    task = RollOffTask(job, interval_s=1.0)  # type: ignore[arg-type]  # duck-typed job
    task.start()
    await asyncio.wait_for(job.parked.wait(), 5)
    stopper = asyncio.ensure_future(task.stop())
    await asyncio.sleep(0)  # stop() has cancelled the run and waits for it
    stopper.cancel()  # the caller's own cancel, while stop() waits
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stopper, 5)


async def test_a_run_left_by_a_cancelled_stop_stays_referenced() -> None:
    job = _CancelResistant()
    slept = asyncio.Event()

    async def park(_: float) -> None:  # the released run's next night never comes
        slept.set()
        await asyncio.Event().wait()

    task = RollOffTask(job, interval_s=1.0, sleep=park)  # type: ignore[arg-type]  # duck-typed job
    task.start()
    await asyncio.wait_for(job.parked.wait(), 5)
    stopper = asyncio.ensure_future(task.stop())
    await asyncio.sleep(0)  # stop() has cancelled the run and waits for it
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stopper, 5)
    stuck = task._stuck  # the run, still pending, is not dropped with the caller's wait
    assert stuck is not None and not stuck.done()
    job.release.set()
    await asyncio.wait_for(slept.wait(), 5)
    stuck.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stuck, 5)


async def test_rolloff_stop_logs_a_run_that_ended_on_an_error() -> None:
    class Done:
        async def run(self) -> None:
            return None

    slept = asyncio.Event()

    async def fails_on_cancel(_: float) -> None:
        slept.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("boom") from None

    task = RollOffTask(Done(), interval_s=1.0, sleep=fails_on_cancel)  # type: ignore[arg-type]  # duck-typed job
    task.start()
    await asyncio.wait_for(slept.wait(), 5)
    with capture_logs() as logs:
        await asyncio.wait_for(task.stop(), 5)
    assert [(e["event"], e.get("error")) for e in logs] == [("rolloff_stop_failed", "RuntimeError")]
    assert task._stuck is None


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    nights=st.lists(
        st.lists(st.booleans(), min_size=6, max_size=6),  # per-day failure flags
        min_size=1,
        max_size=5,
    )
)
async def test_property_no_drop_without_verified_copy_and_watermark_monotone(
    nights: list[list[bool]],
) -> None:
    days = [day(8 + i) for i in range(6)]
    hot = FakeHot({T: {d: ["BTCUSDT"] for d in days}})
    marks = FakeMarks()
    arch = FakeArchiver()
    last = 0
    for flags in nights:
        arch.fail = {
            ("BTCUSDT", d): ["archive_verification_failed"] * 3
            for d, f in zip(days, flags, strict=True)
            if f
        }
        await _job(hot, arch, marks).run()
        for stream, d in hot.dropped:
            assert ("BTCUSDT", stream, d) in arch.verified
        mark = (await marks.get("BTCUSDT", T)).archived_through_us
        assert mark >= last
        # watermark never covers a day that is still hot
        assert all(mark <= d for d in hot.days[T])
        last = mark


class Kill(BaseException):
    """Simulated SIGKILL: not an `Exception`, so nothing in the job swallows it."""


async def test_chaos_kill_between_write_and_verify_loses_nothing_and_rerun_converges() -> None:
    hot = FakeHot({T: {day(10): ["BTCUSDT"]}})

    class KillingArchiver(FakeArchiver):
        killed = False

        async def archive_day(
            self, symbol: str, stream: StreamKind, d: TimeRange
        ) -> ArchiveOutcome:
            if not self.killed:
                self.killed = True
                raise Kill
            return await super().archive_day(symbol, stream, d)

    arch, marks = KillingArchiver(), FakeMarks()
    with pytest.raises(Kill):
        await _job(hot, arch, marks).run()
    assert day(10) in hot.days[T] and (await marks.get("BTCUSDT", T)).archived_through_us == 0
    await _job(hot, arch, marks).run()
    assert hot.dropped == [(T, day(10))]


async def test_chaos_kill_between_verify_and_drop_loses_nothing_and_rerun_converges() -> None:
    hot = FakeHot({T: {day(10): ["BTCUSDT"]}})

    class KillingAudit(Audit):
        armed = True

        async def write(self, action: str, detail: dict[str, str | int]) -> None:
            if self.armed:
                self.armed = False
                raise Kill
            await super().write(action, detail)

    audit, marks = KillingAudit(), FakeMarks()
    with pytest.raises(Kill):
        await _job(hot, FakeArchiver(), marks, audit=audit).run()
    assert day(10) in hot.days[T]  # verified cold copy exists, hot still present (duplicate ok)
    await _job(hot, FakeArchiver(), marks, audit=audit).run()
    assert hot.dropped == [(T, day(10))]
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(10) + US_PER_DAY


class LateRowHot(FakeHot):
    """A row (or a new symbol) lands after the verified export, before the drop."""

    def __init__(self, days: dict[StreamKind, dict[int, list[str]]], *, new_symbol: bool) -> None:
        super().__init__(days)
        self.calls = 0
        self.new_symbol = new_symbol

    async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
        self.calls += 1
        counts = await super().row_counts(stream, rng)
        if self.calls > 1:
            if self.new_symbol:
                counts["SOLUSDT"] = 1
            else:
                counts["BTCUSDT"] += 1
        return counts


@pytest.mark.parametrize("new_symbol", [False, True])
async def test_rolloff_late_row_between_export_and_drop_aborts_drop(new_symbol: bool) -> None:
    hot = LateRowHot({T: {day(10): ["BTCUSDT"]}}, new_symbol=new_symbol)
    emitted: list[str] = []

    class Ev:
        async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
            emitted.append(code)

    marks, audit = FakeMarks(), Audit()
    report = await _job(hot, FakeArchiver(), marks, audit=audit, events=Ev()).run()
    assert hot.dropped == []
    assert [a for a, _ in audit.rows] == ["retention.purge", "rolloff.drop_aborted"]
    assert audit.rows[1][1]["reason"] == "count_changed"
    assert report.retained == [(T, day(10), "archive_verification_failed")]
    assert "archive.verification_failed" in emitted
    # the watermark moved before the re-check: the day keeps its hot rows (both tiers) and the
    # next run re-archives it
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(10) + US_PER_DAY


async def test_rolloff_late_rows_on_an_older_day_stop_newer_drops() -> None:
    """The older day's late rows exist in QuestDB only: no newer day may drop above it."""

    class LateOnOldest(FakeHot):
        reads = 0

        async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
            counts = await super().row_counts(stream, rng)
            if rng.start_us == day(11):
                self.reads += 1
                if self.reads > 1:
                    counts["BTCUSDT"] += 1
            return counts

    hot, marks = LateOnOldest({T: {day(11): ["BTCUSDT"], day(10): ["BTCUSDT"]}}), FakeMarks()
    report = await _job(hot, FakeArchiver(), marks).run()
    assert hot.dropped == report.dropped == []
    assert report.retained == [(T, day(11), "archive_verification_failed")]
    # covers the late-row day (its rows stay hot), never the newer day above it
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(11) + US_PER_DAY


async def test_rolloff_day_just_past_window_waits_for_safety_margin() -> None:
    hot = FakeHot({T: {day(8): ["BTCUSDT"]}})  # ends 7 d ago: past 7 d, inside 7+1 d margin
    await _job(hot, FakeArchiver(), FakeMarks()).run()
    assert hot.dropped == []


async def test_system_audit_adapter_writes_as_system_rolloff() -> None:
    from candleviewer.recorder.rolloff import ROLLOFF_ACTOR, SystemAuditAdapter

    seen: list[tuple[str, dict[str, object]]] = []

    class Em:
        async def emit(self, action: str, **kw: object) -> None:
            seen.append((action, kw))

    await SystemAuditAdapter(Em()).write("retention.purge", {"stream": "trades", "rows": 3})
    action, kw = seen[0]
    assert action == "retention.purge" and kw["actor_label"] == ROLLOFF_ACTOR == "system:rolloff"
    assert kw["after_state"] == {"stream": "trades", "rows": 3}


async def test_rolloff_day_with_no_symbols_is_never_dropped() -> None:
    hot = FakeHot({T: {day(20): []}})
    await _job(hot, FakeArchiver(), FakeMarks()).run()
    assert hot.dropped == []


async def test_downsample_holds_stream_lock_and_audits_before_rewrite() -> None:
    order: list[str] = []

    class A(Audit):
        async def write(self, action: str, detail: dict[str, str | int]) -> None:
            order.append(action)

    class D(FakeDown):
        async def downsample_before(self, symbol: str, stream: StreamKind, before_us: int) -> int:
            order.append("downsample")
            return await super().downsample_before(symbol, stream, before_us)

    job = _job(
        FakeHot({T: {}}),
        FakeArchiver(),
        FakeMarks(),
        audit=A(),
        downsampler=D(),
        cold_symbols=ColdSyms(),
        lock=Lock({"rolloff:heatmap_cells"}),
    )
    report = await job.run()
    assert order == ["retention.downsample", "downsample"]  # orderbook only; heatmap locked
    assert StreamKind.HEATMAP_CELLS in report.skipped_locked


class PhaseCrash(BaseException):
    """Simulated crash at a phase boundary (not swallowed by the job)."""


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    nights=st.lists(
        st.lists(
            st.sampled_from(
                [
                    "ok",
                    "verify_fail",
                    "write_fail",
                    "late_row",
                    "crash_archive",
                    "crash_audit",
                    "crash_drop",
                    "drop_unconfirmed",
                    "crash_advance",
                ]
            ),
            min_size=4,
            max_size=4,
        ),
        min_size=1,
        max_size=5,
    )
)
async def test_property_phase_crashes_write_failures_late_rows_never_lose_data(
    nights: list[list[str]],
) -> None:
    days = [day(9 + i) for i in range(4)]
    hot = FakeHot({T: {d: ["BTCUSDT"] for d in days}})
    verified: set[int] = set()
    plan: dict[int, str] = {}

    class Arch:
        async def archive_day(
            self, symbol: str, stream: StreamKind, d: TimeRange
        ) -> ArchiveOutcome:
            mode = plan.get(d.start_us, "ok")
            if mode == "crash_archive":
                raise PhaseCrash
            if mode in ("verify_fail", "write_fail"):
                code = (
                    "archive_verification_failed"
                    if mode == "verify_fail"
                    else "archive_write_failed"
                )
                return ArchiveOutcome(symbol, stream, d.start_us, d.end_us, False, reason=code)
            verified.add(d.start_us)
            return ArchiveOutcome(symbol, stream, d.start_us, d.end_us, True, rows=10, bytes=1)

    class Hot(FakeHot):
        seen: ClassVar[dict[int, int]] = {}

        async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
            n = self.seen.get(rng.start_us, 0)
            self.seen[rng.start_us] = n + 1
            late = plan.get(rng.start_us) == "late_row" and n % 2 == 1
            return {"BTCUSDT": 11 if late else 10}

        async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
            if plan.get(day_start_us) == "crash_drop":
                raise PhaseCrash
            if plan.get(day_start_us) == "drop_unconfirmed":
                raise StoragePartitionDropNotApplied("not confirmed", reason="timeout")
            assert day_start_us in verified, "dropped without a verified cold copy"
            await super().drop_day(stream, day_start_us)

    class Aud(Audit):
        async def write(self, action: str, detail: dict[str, str | int]) -> None:
            if plan.get(int(detail.get("range_start_us", -1))) == "crash_audit":
                raise PhaseCrash

    class Marks(FakeMarks):
        async def advance(
            self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
        ) -> RollOffWatermark:
            if any(v == "crash_advance" for v in plan.values()):
                raise PhaseCrash
            return await super().advance(symbol, stream, through_us, now_us=now_us)

    h = Hot(hot.days)
    h.seen.clear()
    marks = Marks()
    last = 0
    for modes in nights:
        plan.clear()
        plan.update(dict(zip(days, modes, strict=True)))
        try:
            await _job(h, Arch(), marks, audit=Aud()).run()  # type: ignore[arg-type]
        except PhaseCrash:
            pass
        mark = (await marks.get("BTCUSDT", T)).archived_through_us
        assert mark >= last
        # covers a still-hot day only when it is in both tiers (verified cold, #2347)
        assert all(mark <= d or d in verified for d in h.days[T])
        last = mark
    # convergence: a clean night drops everything left
    plan.clear()
    await _job(h, Arch(), marks).run()  # type: ignore[arg-type]
    assert h.days[T] == {}


async def test_rolloff_value_change_without_count_change_aborts_drop() -> None:
    """Dedup upsert rewrote values in place: same count, different fingerprint."""

    class Upserted(FakeHot):
        n = 0

        def value_tag(self, rng: TimeRange) -> str:
            self.n += 1
            return "v0" if self.n == 1 else "v1"

    hot, audit = Upserted({T: {day(10): ["BTCUSDT"]}}), Audit()
    await _job(hot, FakeArchiver(), FakeMarks(), audit=audit).run()
    assert hot.dropped == []
    assert audit.rows[-1] == (
        "rolloff.drop_aborted",
        audit.rows[0][1] | {"reason": "values_changed"},
    )


async def test_rolloff_purge_audit_precedes_final_recheck_and_drop() -> None:
    order: list[str] = []

    class H(FakeHot):
        async def snapshot(self, stream: StreamKind, rng: TimeRange) -> dict[str, tuple[int, str]]:
            order.append("snapshot")
            return await super().snapshot(stream, rng)

        async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
            order.append("drop")
            await super().drop_day(stream, day_start_us)

    class A(Audit):
        async def write(self, action: str, detail: dict[str, str | int]) -> None:
            order.append(action)

    class M(FakeMarks):
        async def advance(
            self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
        ) -> RollOffWatermark:
            order.append("advance")
            return await super().advance(symbol, stream, through_us, now_us=now_us)

    await _job(H({T: {day(10): ["BTCUSDT"]}}), FakeArchiver(), M(), audit=A()).run()
    # only the drop's own listing and DROP follow the last snapshot (#2347 review)
    assert order == ["snapshot", "retention.purge", "advance", "snapshot", "drop"]


async def test_rolloff_late_row_during_the_watermark_advance_keeps_the_day_hot() -> None:
    """A backfilled row that lands while the watermark is written is caught by the final
    re-check: the day stays hot, and the next run archives the row and drops the day."""
    counts = {day(10): 10}
    archived: dict[int, int] = {}

    class Hot(FakeHot):
        async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
            return {"BTCUSDT": counts[rng.start_us]}

    class Arch(FakeArchiver):
        async def archive_day(
            self, symbol: str, stream: StreamKind, d: TimeRange
        ) -> ArchiveOutcome:
            archived[d.start_us] = counts[d.start_us]  # the export reads the hot day as it is
            self.verified.add((symbol, stream, d.start_us))
            n = counts[d.start_us]
            return ArchiveOutcome(symbol, stream, d.start_us, d.end_us, True, rows=n, bytes=1)

    class LateMarks(FakeMarks):
        armed = True

        async def advance(
            self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
        ) -> RollOffWatermark:
            if self.armed:
                self.armed = False
                counts[day(10)] += 1  # the late row
            return await super().advance(symbol, stream, through_us, now_us=now_us)

    hot, marks = Hot({T: {day(10): ["BTCUSDT"]}}), LateMarks()
    report = await _job(hot, Arch(), marks).run()
    assert hot.dropped == report.dropped == []
    assert report.retained == [(T, day(10), "archive_verification_failed")]
    # the watermark already covers the day: safe, its hot rows stay until a re-archive
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(10) + US_PER_DAY

    report = await _job(hot, Arch(), marks).run()
    assert hot.dropped == report.dropped == [(T, day(10))]
    assert archived[day(10)] == 11  # the late row reached Parquet before the drop


class UnconfirmedHot(FakeHot):
    """`drop_day` cannot confirm the drop for the days in `unconfirmed` (the day stays listed)."""

    def __init__(
        self,
        days: dict[StreamKind, dict[int, list[str]]],
        unconfirmed: dict[int, DropNotAppliedReason],
    ) -> None:
        super().__init__(days)
        self.unconfirmed = unconfirmed

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
        if (reason := self.unconfirmed.get(day_start_us)) is not None:
            raise StoragePartitionDropNotApplied("not confirmed applied", reason=reason)
        await super().drop_day(stream, day_start_us)


def _failures(reason: str) -> float:
    return float(recorder_rolloff_failures_total.labels(reason=reason)._value.get())


@pytest.mark.parametrize(
    ("reason", "severity"),
    [
        ("timeout", "WARNING"),
        ("suspended", "CRITICAL"),
        ("unexpected_shape", "CRITICAL"),
        ("missing", "WARNING"),  # no DROP was issued: the day left QuestDB another way
    ],
)
async def test_rolloff_unconfirmed_drop_is_audited_retained_and_stops_the_stream(
    reason: DropNotAppliedReason, severity: str
) -> None:
    first, second, third = day(12), day(11), day(10)  # oldest-first: the second is unconfirmed
    hot = UnconfirmedHot({T: {d: ["BTCUSDT"] for d in (first, second, third)}}, {second: reason})
    arch, marks, audit = FakeArchiver(), FakeMarks(), Audit()
    emitted: list[tuple[str, str, dict[str, str | int]]] = []

    class Ev:
        async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
            emitted.append((severity, code, detail))

    label = f"drop_not_applied_{reason}"
    before = _failures(label)

    report = await _job(hot, arch, marks, audit=audit, events=Ev()).run()

    # No false "dropped": only the day confirmed earlier in the pass; the third day is untouched.
    assert hot.dropped == report.dropped == [(T, first)]
    assert sorted(hot.days[T]) == [second, third]
    assert {d for _, d in arch.calls} == {first, second}
    assert report.retained == [(T, second, label)]
    # The write-ahead intent keeps its outcome: same stream + day, plus the reason.
    assert [a for a, _ in audit.rows] == ["retention.purge"] * 2 + ["rolloff.drop_unconfirmed"]
    (_, intent), (_, outcome) = audit.rows[1], audit.rows[2]
    assert intent["range_start_us"] == second
    assert outcome == intent | {"reason": reason}
    assert {a for a, _ in audit.rows} <= AUDIT_ACTIONS  # the real writer refuses unregistered ones
    assert emitted == [
        (
            severity,
            "rolloff.drop_unconfirmed",
            {"stream": "trades", "range_start_us": second, "reason": reason},
        )
    ]
    assert _failures(label) == before + 1
    # The watermark moved over the second day before its DROP (#2347): its verified cold copy
    # covers it, so a DROP that did not apply leaves it in both tiers, never in neither.
    assert (await marks.get("BTCUSDT", T)).archived_through_us == second + US_PER_DAY
    assert ("BTCUSDT", T, second) in arch.verified


_OUTCOMES = st.sampled_from(["ok", "verify_fail", "late_row", "crash_drop", "unconfirmed"])
_SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    nights=st.lists(st.lists(_OUTCOMES, min_size=5, max_size=5), min_size=1, max_size=4),
    layout=st.lists(st.sets(st.sampled_from(_SYMS), min_size=1), min_size=5, max_size=5),
    # SOLUSDT's hot window: the common 7 days, a longer one (11 or 12 days keeps the newer
    # days of the five inside it), or pinned (`None`, never rolled off)
    sol_days=st.sampled_from([7, 11, 12, None]),
)
async def test_property_watermark_never_trails_a_drop_and_stays_contiguous(
    nights: list[list[str]], layout: list[set[str]], sol_days: int | None
) -> None:
    """#2347 invariant over random per-day outcomes and retention policies: at every DROP each
    symbol of the day is already below its watermark; an older day of that symbol is still hot
    only if it reached its own DROP first (both tiers), never a day kept hot by a failure or
    another symbol's window; and the watermark covers a hot day only when it is verified cold."""
    days = [day(14 - i) for i in range(5)]  # oldest first
    plan: dict[int, str] = {}
    marks = FakeMarks()
    arch = FakeArchiver()

    async def hot_days(symbol: str, stream: StreamKind) -> int | None:
        return sol_days if symbol == "SOLUSDT" else 7

    def in_window(d: int, sym: str) -> bool:  # `_window_ok` for one symbol, safety margin 1
        w = sol_days if sym == "SOLUSDT" else 7
        return w is not None and d + US_PER_DAY <= NOW_US - (w + 1) * US_PER_DAY

    class Hot(FakeHot):
        reads: ClassVar[dict[int, int]] = {}
        attempted: ClassVar[set[int]] = set()  # days that reached `drop_day` (advanced first)

        async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
            n = self.reads.get(rng.start_us, 0)
            self.reads[rng.start_us] = n + 1
            counts = await super().row_counts(stream, rng)
            if plan.get(rng.start_us) == "late_row" and n % 2 == 1:
                counts = {k: v + 1 for k, v in counts.items()}
            return counts

        async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
            for sym in self.days[stream][day_start_us]:
                assert (sym, stream, day_start_us) in arch.verified
                assert in_window(day_start_us, sym)
                mark = (await marks.get(sym, stream)).archived_through_us
                assert mark >= day_start_us + US_PER_DAY, "watermark trails the drop"
                # contiguous: an older day of `sym` still hot must have reached its own DROP
                # (so it is in both tiers); a failed, late-row or window-kept day must not
                for d, syms in self.days[stream].items():
                    if d < day_start_us and sym in syms:
                        assert d in self.attempted, "dropped above an older day still hot"
                        assert (sym, stream, d) in arch.verified
            self.attempted.add(day_start_us)
            mode = plan.get(day_start_us)
            if mode == "crash_drop":
                raise Kill
            if mode == "unconfirmed":
                raise StoragePartitionDropNotApplied("not confirmed", reason="timeout")
            await super().drop_day(stream, day_start_us)

    hot = Hot({T: {d: sorted(syms) for d, syms in zip(days, layout, strict=True)}})
    hot.reads.clear()
    hot.attempted.clear()
    for modes in [*nights, ["ok"] * 5]:  # a clean night last: everything droppable drops
        plan.clear()
        plan.update(zip(days, modes, strict=True))
        arch.fail = {
            (sym, d): ["archive_verification_failed"] * 3
            for d, mode in plan.items()
            if mode == "verify_fail"
            for sym in _SYMS
        }
        try:
            await _job(hot, arch, marks, hot_days=hot_days).run()
        except Kill:
            pass
        for sym in _SYMS:
            mark = (await marks.get(sym, T)).archived_through_us
            # every dropped day of `sym` is below its watermark; every hot one above it is
            # hot only, and one below it is in both tiers
            for d, syms in zip(days, layout, strict=True):
                if sym not in syms:
                    continue
                if d not in hot.days[T]:
                    assert d + US_PER_DAY <= mark
                elif d + US_PER_DAY <= mark:
                    assert (sym, T, d) in arch.verified
    # after the clean night a day is still hot only when a symbol of it is inside its window or
    # waits behind an older day still hot (pinned / longer-window symbols, bounded by them)
    left = sorted(hot.days[T])
    for i, d in enumerate(left):
        syms = set(hot.days[T][d])
        older = {s for e in left[:i] for s in hot.days[T][e]}
        assert not all(in_window(d, s) for s in syms) or syms & older


# #3794: a stream whose aged partitions roll-off cannot list is counted and logged, never silent.

D = StreamKind.ORDERBOOK_DELTA


def _unlisted(stream: StreamKind) -> float:
    return float(recorder_rolloff_streams_unlisted_total.labels(stream=stream.value)._value.get())


@pytest.mark.parametrize("aged", [1, 24], ids=["one-partition", "a-day-of-hours"])
async def test_rolloff_counts_and_logs_once_a_stream_whose_aged_partitions_list_no_day(
    aged: int,
) -> None:
    """Deltas sat in QuestDB with no error at all: `closed_days` could not read hour names."""
    before = _unlisted(D)
    hot = FakeHot({D: {}}, aged={D: aged})
    job = _job(hot, FakeArchiver(), FakeMarks(), config=RollOffConfig(streams=(D,)))

    with capture_logs() as logs:
        report = await job.run()

    assert _unlisted(D) == before + 1 and report.dropped == []
    assert [e for e in logs if e["event"] == "rolloff_stream_unlisted"] == [
        {
            "event": "rolloff_stream_unlisted",
            "log_level": "warning",
            "stream": D.value,
            "partitions": aged,
        }
    ]
    assert hot.aged_before == [NOW_US - 2 * US_PER_DAY]  # two days: whatever the partitioning


async def test_a_failing_guard_query_never_stops_the_runs_other_streams() -> None:
    """The guard is a signal: if its query fails, the next stream still rolls off."""

    class BrokenGuardHot(FakeHot):
        async def aged_partitions(self, stream: StreamKind, before_us: int) -> int:
            if stream is D:
                raise ConnectionResetError("questdb went away")
            return 0

    before = _failures("unlisted_check_failed")
    hot = BrokenGuardHot({D: {}, T: {day(10): ["BTCUSDT"]}})
    job = _job(hot, FakeArchiver(), FakeMarks(), config=RollOffConfig(streams=(D, T)))

    with capture_logs() as logs:
        report = await job.run()

    assert report.dropped == [(T, day(10))]
    assert _failures("unlisted_check_failed") == before + 1
    assert {
        "event": "rolloff_unlisted_check_failed",
        "log_level": "warning",
        "stream": D.value,
        "error": "ConnectionResetError",
    } in logs


def test_the_unlisted_counter_starts_at_zero_for_every_rolloff_stream() -> None:
    """The alert reads `increase()`: a series created by its first increment shows no increase."""
    from prometheus_client import REGISTRY

    from candleviewer.recorder.rolloff import ROLLOFF_STREAMS

    name = "recorder_rolloff_streams_unlisted_total"
    for stream in ROLLOFF_STREAMS:
        assert REGISTRY.get_sample_value(name, {"stream": stream.value}) is not None, stream
    failed = {"reason": "unlisted_check_failed"}  # 07's first diagnostic query reads it
    assert REGISTRY.get_sample_value("recorder_rolloff_failures_total", failed) is not None


@pytest.mark.parametrize(
    ("days", "aged"),
    [({}, 0), ({day(10): ["BTCUSDT"]}, 5)],
    ids=["nothing-aged", "days-listed"],
)
async def test_rolloff_does_not_count_a_stream_with_nothing_aged_or_with_days_listed(
    days: dict[int, list[str]], aged: int
) -> None:
    before = _unlisted(D)
    hot = FakeHot({D: dict(days)}, aged={D: aged})

    await _job(hot, FakeArchiver(), FakeMarks(), config=RollOffConfig(streams=(D,))).run()

    assert _unlisted(D) == before
    assert hot.aged_before == ([] if days else [NOW_US - 2 * US_PER_DAY])  # read only if none


def test_rolloff_wiring_takes_the_cross_process_advisory_lock() -> None:
    """E16-F01 S4c (#2214 item 6): one roll-off per database, not per process."""
    from types import SimpleNamespace
    from typing import Any, cast

    from candleviewer.rolloff_wiring import build_rolloff_job
    from candleviewer.settings import Settings
    from candleviewer.storage.retention.locks import PgAdvisoryRunLock

    engine = object()
    relational = cast(Any, SimpleNamespace(engine=engine))
    audit = cast(Any, object())
    job = build_rolloff_job(Settings(storage_backend="real"), audit, relational)
    assert job is not None and isinstance(job._lock, PgAdvisoryRunLock)
    assert job._lock._engine is engine
    assert build_rolloff_job(Settings(), audit, relational) is None  # fake backend: no job
    assert build_rolloff_job(Settings(storage_backend="real"), audit, None) is None
