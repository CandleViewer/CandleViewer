"""Unit: `RollOffJob` (E16-T05) — verified drop, retention on failure, backoff,
watermark monotonicity/attribution, newest-first, lock contention, downsample.

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

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.recorder.rolloff import (
    US_PER_DAY,
    RollOffConfig,
    RollOffJob,
    RollOffTask,
    recorder_rolloff_failures_total,
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

    async def closed_days(self, stream: StreamKind, before_us: int) -> list[int]:
        return [d for d in self.days.get(stream, {}) if d + US_PER_DAY <= before_us]

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


async def test_rolloff_processes_newest_first_and_watermark_stops_below_failed_day() -> None:
    hot = FakeHot({T: {day(12): ["BTCUSDT"], day(11): ["BTCUSDT"], day(10): ["BTCUSDT"]}})
    arch = FakeArchiver(fail={("BTCUSDT", day(11)): ["archive_verification_failed"] * 3})
    marks = FakeMarks()
    await _job(hot, arch, marks).run()
    assert [d for _, d in arch.calls[:1]] == [day(10)]  # newest first
    assert sorted(d for _, d in hot.dropped) == [day(12), day(10)]
    # day(10) was dropped but day(11) is still hot: the watermark may not pass day(11)
    assert (await marks.get("BTCUSDT", T)).archived_through_us == day(12) + US_PER_DAY


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
    assert (await marks.get("BTCUSDT", T)).archived_through_us == 0


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
        assert all(mark <= d for d in h.days[T])  # never covers still-hot data
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

    await _job(H({T: {day(10): ["BTCUSDT"]}}), FakeArchiver(), FakeMarks(), audit=A()).run()
    assert order == ["snapshot", "retention.purge", "snapshot", "drop"]


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
    [("timeout", "WARNING"), ("suspended", "CRITICAL"), ("unexpected_shape", "CRITICAL")],
)
async def test_rolloff_unconfirmed_drop_is_audited_retained_and_stops_the_stream(
    reason: DropNotAppliedReason, severity: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, third = day(10), day(11), day(12)  # newest-first: the second is unconfirmed
    hot = UnconfirmedHot({T: {d: ["BTCUSDT"] for d in (first, second, third)}}, {second: reason})
    arch, marks, audit = FakeArchiver(), FakeMarks(), Audit()
    emitted: list[tuple[str, str, dict[str, str | int]]] = []
    advanced: list[tuple[dict[str, list[int]], dict[str, list[int]]]] = []
    real_advance = RollOffJob._advance

    class Ev:
        async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
            emitted.append((severity, code, detail))

    async def spy(
        self: RollOffJob,
        stream: StreamKind,
        dropped: dict[str, list[int]],
        retained: dict[str, list[int]],
    ) -> None:
        advanced.append(
            ({k: [*v] for k, v in dropped.items()}, {k: [*v] for k, v in retained.items()})
        )
        await real_advance(self, stream, dropped, retained)

    monkeypatch.setattr(RollOffJob, "_advance", spy)
    label = f"drop_not_applied_{reason}"
    before = _failures(label)

    report = await _job(hot, arch, marks, audit=audit, events=Ev()).run()

    # No false "dropped": only the day confirmed earlier in the pass; the third day is untouched.
    assert hot.dropped == report.dropped == [(T, first)]
    assert sorted(hot.days[T]) == [third, second]
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
    # `_advance` still ran with the confirmed day, but the watermark may not pass a day that is
    # still hot: newest-first, the unconfirmed day (and the untouched older one) cap it.
    assert advanced == [({"BTCUSDT": [first]}, {"BTCUSDT": [second]})]
    assert (await marks.get("BTCUSDT", T)).archived_through_us == 0
