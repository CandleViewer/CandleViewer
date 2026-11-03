"""#5629: maintenance mode holds the recorder (`recorder.pause.RecorderPause`) through the
maintenance controller's `RecorderControl` port.

AC (ruled BQ 6): with `keep_recorder = false` the recorder pauses on enter; with `true` it keeps
running; leaving maintenance resumes it. The held interval is one `maintenance_pause` gap per
stream of every live session. Fake clocks, no sleeps, no I/O beyond `tmp_path`."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import (
    MAINTENANCE_KEEP_RECORDER,
    MAINTENANCE_MODE,
    FlagService,
    FlagWriter,
    MaintenanceController,
    MaintenanceGate,
    chain_hooks,
    default_registry,
)
from candleviewer.admin.flags.maintenance import RecorderControl
from candleviewer.audit.access import AuditPrincipal
from candleviewer.recorder import pause as pause_mod
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.pause import RecorderPause
from candleviewer.recorder.sessions import DEFAULT_STREAMS, SessionManager, to_us
from candleviewer.recorder.writer import StreamWriter
from tests.unit.admin.flag_fakes import Clock, FakeFlagStore, FakeStepUp, FakeUsers
from tests.unit.admin.flag_fakes import FakeAudit as FlagAudit
from tests.unit.recorder._fakes import FakeAudit
from tests.unit.recorder._session_fakes import LIVE, MemRecorderStore, UsClock
from tests.unit.recorder._writer_helpers import FakeSink, delta, make_writer, snapshot, trade

_OWNER = AuditPrincipal(user_id=UUID(int=1), username="owner", permissions=frozenset({"*"}))
T0 = 1_790_000_000_000_000  # session wall clock, epoch µs


def _set(symbol: str, change: str = "added") -> RecorderSetChanged:
    return RecorderSetChanged.model_validate(
        {
            "symbol": symbol,
            "change": change,
            "reason": "manual",
            "reasons": ("manual",) if change != "removed" else (),
            "priority": 300,
            "auto_evictable": False,
            "ts_event": T0,
        }
    )


class _BlockingSink(FakeSink):
    """A sink whose next write waits on `release` once `armed` (a flush cut mid-write)."""

    def __init__(self) -> None:
        super().__init__()
        self.armed = False
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        if self.armed:
            self.entered.set()
            await self.release.wait()
        await super().write_rows(table, rows, ts_us_key)


class _BlockingGaps(MemRecorderStore):
    """A gap store whose writes wait on `release` while `armed` (a resume cut mid-write)."""

    def __init__(self) -> None:
        super().__init__()
        self.armed = self.broken = False
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def record_gap(
        self,
        *,
        session_id: str,
        symbol: str,
        stream: str,
        gap_start: datetime,
        gap_end: datetime,
        cause: str,
    ) -> int | None:
        if self.broken:
            raise OSError("pg down")
        if self.armed:
            self.entered.set()
            await self.release.wait()
        return await super().record_gap(
            session_id=session_id, symbol=symbol, stream=stream,
            gap_start=gap_start, gap_end=gap_end, cause=cause,
        )  # fmt: skip


class _Rig:
    def __init__(
        self,
        writer: StreamWriter,
        sink: FakeSink,
        store: MemRecorderStore,
        effect_timeout_s: float = 5.0,
    ) -> None:
        self.writer, self.sink, self.store = writer, sink, store
        self.clock = UsClock(T0)
        self.sessions = SessionManager(store, now_us=self.clock, audit=FakeAudit(), config=LIVE)
        self.pause = RecorderPause(
            writer, self.sessions, now_us=self.clock, flush_timeout_s=5.0, gap_timeout_s=5.0
        )
        self.flags = FakeFlagStore()
        self.service = FlagService(default_registry(), self.flags, clock=Clock())
        self.controller = MaintenanceController(
            self.service,
            MaintenanceGate(),
            notify=lambda _on: None,
            audit=FlagAudit(),
            recorder=self.pause,
            effect_timeout_s=effect_timeout_s,
        )
        hook = chain_hooks(self.controller.gate_hook, self.controller.effects_hook)
        self.flag_writer = FlagWriter(
            self.service, FlagAudit(), FakeStepUp(), FakeUsers(), on_change=hook
        )

    async def start(self) -> _Rig:
        await self.flags.ensure(self.service.registry.values())
        await self.controller.refresh()
        await self.sessions.on_set_changed(_set("BTCUSDT"))
        return self

    async def toggle(self, key: str, value: bool) -> None:
        await self.flag_writer.set(
            key,
            _OWNER,
            value=value,
            reason="maintenance window",
            expected_updated_at=self.flags.rows[key].updated_at,
        )


async def _rig(
    tmp_path: Path,
    *,
    sink: FakeSink | None = None,
    store: MemRecorderStore | None = None,
    effect_timeout_s: float = 5.0,
) -> _Rig:
    writer, sink_, *_ = await make_writer(tmp_path, sink=sink)
    return await _Rig(writer, sink_, store or MemRecorderStore(), effect_timeout_s).start()


def test_recorder_pause_is_the_maintenance_recorder_port() -> None:
    """mypy proves the structural fit; `recorder` may not import `admin` (CONSTITUTION Sec.3)."""
    port: RecorderControl = RecorderPause(
        _NoWriter(), _NoSessions(), now_us=lambda: T0, flush_timeout_s=1.0, gap_timeout_s=1.0
    )
    assert callable(port.pause) and callable(port.resume)


class _NoWriter:
    def hold(self) -> bool:
        return True

    def release(self) -> bool:
        return True

    async def flush_queued(self) -> None:
        return None


class _NoSessions:
    def live_sessions(self) -> tuple[()]:
        return ()

    async def on_maintenance_pause(self, start_us: int, end_us: int, held: object = ()) -> None:
        return None


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf")])
def test_recorder_pause_refuses_an_unbounded_or_instant_timeout(bad: float) -> None:
    with pytest.raises(ValueError, match="flush_timeout_s"):
        RecorderPause(_NoWriter(), _NoSessions(), now_us=lambda: T0,
                      flush_timeout_s=bad, gap_timeout_s=1.0)  # fmt: skip
    with pytest.raises(ValueError, match="gap_timeout_s"):
        RecorderPause(_NoWriter(), _NoSessions(), now_us=lambda: T0,
                      flush_timeout_s=1.0, gap_timeout_s=bad)  # fmt: skip


async def test_maintenance_with_keep_recorder_false_pauses_the_recorder_on_enter(
    tmp_path: Path,
) -> None:
    rig = await _rig(tmp_path)
    await rig.toggle(MAINTENANCE_KEEP_RECORDER, False)
    await rig.toggle(MAINTENANCE_MODE, True)
    assert rig.writer.held and rig.pause.paused
    await rig.writer.on_trade(trade(1))
    await rig.writer.on_book_delta(delta(5))
    assert rig.writer.backlog_rows == 0 and rig.writer.take_event_bounds() == {}
    assert rig.store.gaps == []  # nothing is written until the hold ends


async def test_maintenance_with_keep_recorder_true_keeps_the_recorder_running(
    tmp_path: Path,
) -> None:
    rig = await _rig(tmp_path)
    await rig.toggle(MAINTENANCE_MODE, True)  # `keep_recorder` defaults to true
    assert not rig.writer.held and not rig.pause.paused
    await rig.writer.on_trade(trade(1))
    assert rig.writer.backlog_rows == 1


async def test_leaving_maintenance_resumes_and_writes_one_maintenance_pause_gap_per_stream(
    tmp_path: Path,
) -> None:
    rig = await _rig(tmp_path)
    await rig.toggle(MAINTENANCE_KEEP_RECORDER, False)
    rig.clock.advance_s(10)
    paused_at = rig.clock.t
    await rig.toggle(MAINTENANCE_MODE, True)
    rig.clock.advance_s(300)
    resumed_at = rig.clock.t
    await rig.toggle(MAINTENANCE_MODE, False)
    assert not rig.writer.held and not rig.pause.paused
    await rig.writer.on_trade(trade(2))
    assert rig.writer.backlog_rows == 1
    windows = rig.store.gap_windows()
    assert sorted(windows) == sorted(
        (s, paused_at, resumed_at, "maintenance_pause") for s in DEFAULT_STREAMS
    )
    assert {g["session_id"] for g in rig.store.gaps} == {rig.sessions.live_session("BTCUSDT")}


async def test_pause_flushes_what_was_queued_before_the_hold(tmp_path: Path) -> None:
    rig = await _rig(tmp_path)
    for i in range(3):
        await rig.writer.on_trade(trade(i))
    await rig.pause.pause("maintenance.enabled")
    assert len(rig.sink.rows("trades")) == 3 and rig.writer.backlog_rows == 0


async def test_pause_and_resume_are_idempotent(tmp_path: Path) -> None:
    rig = await _rig(tmp_path)
    paused_at = rig.clock.t
    await rig.pause.pause("maintenance.enabled")
    rig.clock.advance_s(5)
    with capture_logs() as logs:
        await rig.pause.pause("maintenance.enabled")  # the hold's start does not move
    assert [e["event"] for e in logs] == []
    rig.clock.advance_s(5)
    await rig.pause.resume("maintenance.disabled")
    rig.clock.advance_s(5)
    await rig.pause.resume("maintenance.disabled")  # nothing more is written
    assert {(lo, hi) for _, lo, hi, _ in rig.store.gap_windows()} == {
        (paused_at, paused_at + 10_000_000)
    }
    assert len(rig.store.gaps) == len(DEFAULT_STREAMS)


async def test_a_pause_cut_mid_flush_stays_held_keeps_its_rows_and_the_next_call_flushes(
    tmp_path: Path,
) -> None:
    sink = _BlockingSink()
    rig = await _rig(tmp_path, sink=sink)
    for i in range(3):
        await rig.writer.on_trade(trade(i))
    sink.armed = True
    task = asyncio.create_task(rig.pause.pause("maintenance.enabled"))
    await sink.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rig.writer.held and rig.pause.paused  # the hold is one synchronous step
    assert rig.writer.backlog_rows == 3 and sink.rows("trades") == []  # the batch is back
    sink.armed = False
    await rig.pause.pause("maintenance.enabled")  # the controller's next poll
    assert len(sink.rows("trades")) == 3 and rig.writer.backlog_rows == 0


async def test_a_resume_cut_mid_gap_write_keeps_the_interval_and_the_retry_writes_it_once(
    tmp_path: Path,
) -> None:
    store = _BlockingGaps()
    rig = await _rig(tmp_path, store=store)
    await rig.pause.pause("maintenance.enabled")
    rig.clock.advance_s(60)
    store.armed = True
    task = asyncio.create_task(rig.pause.resume("maintenance.disabled"))
    await store.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not rig.writer.held and not rig.pause.paused  # capture is back at once
    store.armed = False
    rig.clock.advance_s(5)  # the retry's clock has moved: the interval's end has not
    await rig.pause.resume("maintenance.disabled")
    await rig.pause.resume("maintenance.disabled")
    assert sorted(rig.store.gap_windows()) == sorted(
        (s, T0, T0 + 60_000_000, "maintenance_pause") for s in DEFAULT_STREAMS
    )


async def test_a_resume_cut_by_its_gap_budget_raises_and_keeps_the_interval(
    tmp_path: Path,
) -> None:
    store = _BlockingGaps()
    writer, *_ = await make_writer(tmp_path)
    clock = UsClock(T0)
    sessions = SessionManager(store, now_us=clock, audit=FakeAudit(), config=LIVE)
    await sessions.on_set_changed(_set("BTCUSDT"))
    pause = RecorderPause(writer, sessions, now_us=clock, flush_timeout_s=1.0, gap_timeout_s=0.01)
    await pause.pause("maintenance.enabled")
    clock.advance_s(1)
    store.armed = True
    with pytest.raises(TimeoutError):
        await pause.resume("maintenance.disabled")
    store.armed = False
    await pause.resume("maintenance.disabled")
    assert len(store.gap_windows("maintenance_pause")) == len(DEFAULT_STREAMS)


async def test_the_first_delta_after_a_hold_is_not_a_seq_jump(tmp_path: Path) -> None:
    rig = await _rig(tmp_path)
    await rig.writer.on_book_delta(delta(10))
    await rig.pause.pause("maintenance.enabled")
    await rig.writer.on_book_delta(delta(11))  # missed while held
    await rig.pause.resume("maintenance.disabled")
    await rig.writer.on_book_delta(delta(50, prev=49))
    assert rig.writer.take_seq_jump_windows() == []


async def test_a_session_closed_during_the_hold_still_gets_its_gap(tmp_path: Path) -> None:
    rig = await _rig(tmp_path)
    first = rig.sessions.live_session("BTCUSDT")
    await rig.pause.pause("maintenance.enabled")
    rig.clock.advance_s(30)
    await rig.sessions.on_set_changed(_set("BTCUSDT", "removed"))
    await rig.sessions.on_set_changed(_set("ETHUSDT"))  # opened while held
    rig.clock.advance_s(30)
    await rig.pause.resume("maintenance.disabled")
    by_session = {g["session_id"] for g in rig.store.gaps}
    eth = rig.sessions.live_session("ETHUSDT")
    assert by_session == {first, eth}
    first_hi = {to_us(g["gap_end"]) for g in rig.store.gaps if g["session_id"] == first}
    assert first_hi == {T0 + 30_000_000}  # clamped to its session's close
    eth_lo = {to_us(g["gap_start"]) for g in rig.store.gaps if g["session_id"] == eth}
    assert eth_lo == {T0 + 30_000_000}  # from its own start, not the hold's


async def test_held_intervals_past_the_bound_drop_the_oldest_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pause_mod, "MAX_PENDING", 1)
    store = _BlockingGaps()
    rig = await _rig(tmp_path, store=store)
    store.broken = True  # every gap write fails: the intervals stay pending
    for _ in range(2):
        await rig.pause.pause("maintenance.enabled")
        rig.clock.advance_s(1)
        with capture_logs() as logs, pytest.raises(OSError):
            await rig.pause.resume("maintenance.disabled")
    assert "recorder_pause_gap_unpersisted" in [e["event"] for e in logs]


async def test_a_flag_store_row_change_keeps_the_hold_until_maintenance_leaves(
    tmp_path: Path,
) -> None:
    """A poll that re-reads `maintenance.mode = true` does not pause twice."""
    rig = await _rig(tmp_path)
    await rig.toggle(MAINTENANCE_KEEP_RECORDER, False)
    await rig.toggle(MAINTENANCE_MODE, True)
    rig.flags.rows[MAINTENANCE_MODE] = replace(rig.flags.rows[MAINTENANCE_MODE], value=True)
    await rig.controller.refresh()
    assert rig.writer.held
    rig.clock.advance_s(5)  # a zero-length hold is no gap (`rg_window`)
    await rig.toggle(MAINTENANCE_MODE, False)
    assert not rig.writer.held
    assert len(rig.store.gaps) == len(DEFAULT_STREAMS)


async def test_a_held_writer_takes_nothing_on_any_path(tmp_path: Path) -> None:
    """Review B (Major): each hold guard is pinned. Held, a trade, a delta whose `prev` breaks
    the chain, a snapshot and an anchor change no counter, sequence, bound or backlog; removing
    any one guard fails this test (checked by mutation)."""
    rig = await _rig(tmp_path)
    await rig.writer.on_book_delta(delta(10))  # the chain a later delta could break
    await rig.pause.pause("maintenance.enabled")  # holds, then flushes the delta
    rig.writer.take_event_bounds()
    rig.writer.take_seq_jump_windows()
    ctr = rig.writer._ctr("BTCUSDT")
    before = (ctr.received, ctr.dropped, dict(rig.writer._last_update_id))

    await rig.writer.on_trade(trade(1))
    await rig.writer.on_book_delta(delta(50, prev=49))
    await rig.writer.on_book_snapshot(snapshot(60))
    assert await rig.writer.on_book_anchor(snapshot(70), at_us=T0) == "held"

    assert rig.writer.take_seq_jump_windows() == []
    assert (ctr.received, ctr.dropped, dict(rig.writer._last_update_id)) == before
    assert rig.writer.take_event_bounds() == {}
    assert rig.writer.backlog_rows == 0


async def test_pause_and_resume_log_their_event_level_and_reason(tmp_path: Path) -> None:
    rig = await _rig(tmp_path)
    with capture_logs() as logs:
        await rig.pause.pause("maintenance.enabled")
        rig.clock.advance_s(1)
        await rig.pause.resume("maintenance.disabled")
    mine = [
        (e["event"], e["log_level"], e["reason"])
        for e in logs
        if e["event"] in ("recorder_paused", "recorder_resumed")
    ]
    assert mine == [
        ("recorder_paused", "warning", "maintenance.enabled"),
        ("recorder_resumed", "info", "maintenance.disabled"),
    ]


async def test_a_pause_cut_by_its_flush_budget_then_exit_releases_and_writes_the_gaps(
    tmp_path: Path,
) -> None:
    """Review A (Major 1): the controller's flag is no longer what decides the exit's resume."""
    sink = _BlockingSink()
    rig = await _rig(tmp_path, sink=sink, effect_timeout_s=0.01)
    await rig.toggle(MAINTENANCE_KEEP_RECORDER, False)
    await rig.writer.on_trade(trade(1))
    sink.armed = True
    with capture_logs() as logs:
        await rig.toggle(MAINTENANCE_MODE, True)  # the flush is cut by the effect budget
    assert "feature_flag_hook_failed" in [e["event"] for e in logs]
    assert rig.writer.held
    sink.armed = False
    rig.clock.advance_s(30)
    await rig.toggle(MAINTENANCE_MODE, False)
    assert not rig.writer.held
    assert len(rig.store.gap_windows("maintenance_pause")) == len(DEFAULT_STREAMS)


async def test_a_resume_cut_by_its_budget_then_reentry_holds_again(tmp_path: Path) -> None:
    store = _BlockingGaps()
    rig = await _rig(tmp_path, store=store, effect_timeout_s=0.01)
    await rig.toggle(MAINTENANCE_KEEP_RECORDER, False)
    await rig.toggle(MAINTENANCE_MODE, True)
    rig.clock.advance_s(30)
    store.armed = True
    await rig.toggle(MAINTENANCE_MODE, False)  # released at once, the gap write cut
    assert not rig.writer.held
    store.armed = False
    await rig.toggle(MAINTENANCE_MODE, True)
    assert rig.writer.held


async def test_stop_writes_the_open_hold_as_gaps_and_keeps_the_writer_held(
    tmp_path: Path,
) -> None:
    """Review A (Major 2, C-2.14): a normal shutdown while held still records the hold."""
    rig = await _rig(tmp_path)
    await rig.pause.pause("maintenance.enabled")
    rig.clock.advance_s(45)
    await rig.pause.stop()
    assert rig.writer.held
    assert sorted(rig.store.gap_windows()) == sorted(
        (s, T0, T0 + 45_000_000, "maintenance_pause") for s in DEFAULT_STREAMS
    )
    await rig.pause.stop()  # nothing left: a second stop writes nothing
    assert len(rig.store.gaps) == len(DEFAULT_STREAMS)


async def test_stop_logs_every_interval_it_cannot_write_as_critical(tmp_path: Path) -> None:
    store = _BlockingGaps()
    rig = await _rig(tmp_path, store=store)
    await rig.pause.pause("maintenance.enabled")
    rig.clock.advance_s(5)
    store.broken = True
    with capture_logs() as logs, pytest.raises(OSError):
        await rig.pause.stop()
    lost = [e for e in logs if e["event"] == "recorder_pause_gap_unpersisted"]
    assert [(e["log_level"], e["start_us"], e["end_us"]) for e in lost] == [
        ("critical", T0, T0 + 5_000_000)
    ]
