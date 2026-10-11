"""E16-T04 recording sessions + gap detection (Gherkin "Disconnect", "Crash", writer flush).

Chaos scenarios: C-13.6 #2 (WS drop) and #12 (process kill) are exercised at unit level here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest

from candleviewer.exchange.bybit.public_ws import stream_for_topic
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.sessions import (
    DEFAULT_STREAMS,
    SessionConfig,
    SessionManager,
    startup_reconcile,
    to_dt,
    to_us,
)
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

T0 = to_us(datetime(2026, 9, 14, 10, 0, tzinfo=UTC))


def _added(
    symbol: str = "BTCUSDT", change: Literal["added", "removed", "reason_changed"] = "added"
) -> RecorderSetChanged:
    return RecorderSetChanged(
        symbol=symbol, change=change, reason="manual", reasons=("manual",),
        priority=300, auto_evictable=False, ts_event=T0,
    )  # fmt: skip


async def _mgr() -> tuple[SessionManager, MemRecorderStore, UsClock, list[str]]:
    store, clock, inval = MemRecorderStore(), UsClock(T0), []
    mgr = SessionManager(store, now_us=clock, config=SessionConfig(), invalidate=inval.append,
                         topics=stream_for_topic)  # fmt: skip
    await mgr.on_set_changed(_added())
    return mgr, store, clock, inval


async def test_set_changed_added_opens_one_session_and_removed_closes_it() -> None:
    mgr, store, clock, inval = await _mgr()
    await mgr.on_set_changed(_added())  # idempotent: still one
    assert len(store.sessions) == 1 and mgr.live_session("BTCUSDT") is not None
    clock.advance_s(60)
    await mgr.on_set_changed(_added(change="removed"))
    (s,) = store.sessions.values()
    assert s["end_reason"] == "stopped" and s["state"] == "stopped"
    assert to_us(s["ended_at"]) == T0 + 60_000_000
    assert mgr.live_session("BTCUSDT") is None and "BTCUSDT" in inval


async def test_ws_drop_12_min_closes_session_one_gap_exact_new_session() -> None:
    """Gherkin: Disconnect produces one explicit gap (chaos #2)."""
    mgr, store, clock, _ = await _mgr()
    first = mgr.live_session("BTCUSDT")
    clock.advance_s(300)
    down_at = clock.t
    await mgr.on_feed_health("publicTrade.BTCUSDT", "degraded")
    clock.advance_s(5)
    await mgr.on_feed_health("publicTrade.BTCUSDT", "resubscribing")  # still the same outage
    clock.advance_s(12 * 60 - 5)
    up_at = clock.t
    await mgr.on_feed_health("publicTrade.BTCUSDT", "healthy")
    assert store.gap_windows() == [("trades", down_at, up_at, "ws_disconnect")]
    assert first is not None
    old = store.sessions[first]
    assert old["end_reason"] == "ws_disconnect" and to_us(old["ended_at"]) == up_at
    new = mgr.live_session("BTCUSDT")
    assert new is not None and new != first
    assert to_us(store.sessions[new]["started_at"]) == up_at


async def test_healthy_without_outage_and_stale_are_no_ops() -> None:
    mgr, store, _clock, _ = await _mgr()
    await mgr.on_feed_health("publicTrade.BTCUSDT", "stale")
    await mgr.on_feed_health("publicTrade.BTCUSDT", "healthy")
    await mgr.on_feed_health("publicTrade.ETHUSDT", "degraded")  # not recorded
    assert store.gaps == [] and len(store.sessions) == 1


async def test_global_drop_gaps_every_stream_of_every_live_symbol() -> None:
    mgr, store, clock, _ = await _mgr()
    await mgr.on_feed_health("*", "degraded")
    clock.advance_s(10)
    await mgr.on_feed_health("*", "healthy")
    assert sorted(w[0] for w in store.gap_windows("ws_disconnect")) == sorted(DEFAULT_STREAMS)
    assert len(store.sessions) == 2


async def test_partial_recovery_keeps_session_until_last_stream_recovers() -> None:
    mgr, store, clock, _ = await _mgr()
    sid = mgr.live_session("BTCUSDT")
    await mgr.on_feed_health("publicTrade.BTCUSDT", "degraded")
    await mgr.on_feed_health("orderbook.200.BTCUSDT", "degraded")
    clock.advance_s(3)
    await mgr.on_feed_health("publicTrade.BTCUSDT", "healthy")
    assert mgr.live_session("BTCUSDT") == sid and len(store.gaps) == 1
    clock.advance_s(3)
    await mgr.on_feed_health("orderbook.200.BTCUSDT", "healthy")
    assert mgr.live_session("BTCUSDT") != sid
    assert {w[0] for w in store.gap_windows()} == {
        "trades", "orderbook_delta", "orderbook_snapshot"
    }  # fmt: skip


async def test_exchange_outage_writes_gap_per_stream_clamped_to_session() -> None:
    mgr, store, _clock, _ = await _mgr()
    await mgr.on_exchange_outage("BTCUSDT", T0 - 10_000_000, T0 + 20_000_000)
    wins = store.gap_windows("exchange_outage")
    assert len(wins) == len(DEFAULT_STREAMS)
    assert all(lo == T0 and hi == T0 + 20_000_000 for _, lo, hi, _ in wins)
    await mgr.on_exchange_outage(None, T0, T0)  # zero-length: never a gap
    assert len(store.gaps) == len(DEFAULT_STREAMS)


async def test_b11_state_entries_are_mirrored_and_error_closes() -> None:
    mgr, store, _clock, _ = await _mgr()
    sid = mgr.live_session("BTCUSDT")
    assert sid is not None
    await mgr.on_b11_state("BTCUSDT", "recording", {})
    assert store.sessions[sid]["state"] == "recording"
    await mgr.on_b11_state("BTCUSDT", "degraded", {})
    assert store.sessions[sid]["state"] == "degraded"
    await mgr.on_b11_state("BTCUSDT", "gap", {})  # not a state entry
    assert store.sessions[sid]["state"] == "degraded"
    await mgr.on_b11_state("BTCUSDT", "error", {})
    assert store.sessions[sid]["state"] == "error" and store.sessions[sid]["end_reason"] == "error"
    await mgr.on_b11_state("BTCUSDT", "recording", {})  # nothing live: ignored


class _Writer:
    def __init__(self) -> None:
        self.jumps = [("BTCUSDT", T0 + 1_000, T0 + 9_000), ("ETHUSDT", 1, 2)]
        self.bounds = {"BTCUSDT": (T0 + 5, T0 + 50), "ETHUSDT": (1, 2)}

    def take_seq_jump_windows(self) -> list[tuple[str, int, int]]:
        out, self.jumps = self.jumps, []
        return out

    def take_event_bounds(self) -> dict[str, tuple[int, int]]:
        out, self.bounds = self.bounds, {}
        return out


async def test_writer_seq_jumps_become_seq_jump_gaps_and_bounds_touch_session() -> None:
    mgr, store, _clock, _ = await _mgr()
    await mgr.poll_writer(_Writer())
    assert store.gap_windows() == [("orderbook_delta", T0 + 1_000, T0 + 9_000, "seq_jump")]
    (s,) = store.sessions.values()
    assert to_us(s["first_event_ts"]) == T0 + 5 and to_us(s["last_event_ts"]) == T0 + 50


async def test_crash_recovery_closes_process_restart_with_gap_from_last_event() -> None:
    """Gherkin: Crash leaves no open session (chaos #12)."""
    store = MemRecorderStore()
    dead = SessionManager(store, now_us=UsClock(T0))
    await dead.on_set_changed(_added())
    sid = dead.live_session("BTCUSDT")
    assert sid is not None
    await store.set_session_state(sid, "recording")
    await store.touch_session_events(sid, first=to_dt(T0 + 1), last=to_dt(T0 + 7_000_000))
    # process killed (no stop()); a new process starts 2 minutes later
    start = T0 + 120_000_000
    fresh = SessionManager(store, now_us=UsClock(start))
    assert await fresh.recover_on_startup(start) == 1
    s = store.sessions[sid]
    assert s["end_reason"] == "process_restart" and to_us(s["ended_at"]) == start
    wins = store.gap_windows("process_restart")
    assert {w[0] for w in wins} == set(DEFAULT_STREAMS)
    assert all(lo == T0 + 7_000_000 and hi == start for _, lo, hi, _ in wins)
    assert await store.list_live_sessions() == []


async def test_crash_recovery_without_events_gaps_from_started_at() -> None:
    store = MemRecorderStore()
    dead = SessionManager(store, now_us=UsClock(T0))
    await dead.on_set_changed(_added())
    fresh = SessionManager(store, now_us=UsClock(T0 + 5))
    await fresh.recover_on_startup(T0 + 5)
    assert all(lo == T0 for _, lo, _, _ in store.gap_windows("process_restart"))


class _Gate:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def positions_reloaded(self) -> None:
        self.log.append("gate")


async def test_startup_reconcile_opens_gate_last_and_not_on_failure() -> None:
    """#2188 order: crash-close -> B11 restore -> positions reload -> gate."""
    store, log = MemRecorderStore(), []
    mgr = SessionManager(store, now_us=UsClock(T0))

    async def restore() -> None:
        log.append("restore")

    async def reload() -> None:
        log.append("positions")

    await startup_reconcile(mgr, _Gate(log), process_start_us=T0, restore_b11=restore,
                            reload_positions=reload)  # fmt: skip
    assert log == ["restore", "positions", "gate"]

    async def boom() -> None:
        raise OSError("oms down")

    log.clear()
    with pytest.raises(OSError):
        await startup_reconcile(mgr, _Gate(log), process_start_us=T0, reload_positions=boom)
    assert "gate" not in log


async def test_stop_closes_all_live_sessions_as_shutdown() -> None:
    mgr, store, _clock, _ = await _mgr()
    await mgr.stop()
    assert [s["end_reason"] for s in store.sessions.values()] == ["shutdown"]


async def test_writer_buffered_gaps_flush_once_session_opens(tmp_path: Path) -> None:
    """#2203 pending-gap path: the writer's backpressure gap waits for a live session, then
    lands on the session this module opened."""
    from candleviewer.recorder.writer import StreamWriter, WriterConfig
    from tests.unit.recorder._writer_helpers import FakeEvents, FakeSink, FsyncCounter

    store = MemRecorderStore()
    w = StreamWriter(
        lambda _s: FakeSink(), store, FakeEvents(), WriterConfig(wal_dir=tmp_path / "wal"),
        clock=lambda: 0.0, wall_clock_us=lambda: T0, fsync=FsyncCounter(),
    )  # fmt: skip
    await w.open()
    w._gaps[("BTCUSDT", "trades")] = [T0, T0 + 1_000]  # a dropped window (see writer tests)
    await w.flush_gaps()
    assert store.gaps == [] and w.pending_gaps()
    mgr = SessionManager(store, now_us=UsClock(T0))
    await mgr.on_set_changed(_added())
    await w.flush_gaps()
    assert store.gap_windows() == [("trades", T0, T0 + 1_000, "backpressure_drop")]
    assert store.gaps[0]["session_id"] == mgr.live_session("BTCUSDT")
    assert not w.pending_gaps()


def test_adapter_stream_for_topic_normalises_venue_topics() -> None:
    assert stream_for_topic("publicTrade.BTCUSDT") == ("BTCUSDT", ("trades",))
    assert stream_for_topic("orderbook.200.ETHUSDT") == (
        "ETHUSDT", ("orderbook_delta", "orderbook_snapshot")
    )  # fmt: skip
    assert stream_for_topic("*") == (None, DEFAULT_STREAMS)
    assert stream_for_topic("kline.1.BTCUSDT") == ("BTCUSDT", ())


async def test_without_resolver_every_health_event_is_socket_wide() -> None:
    store, clock = MemRecorderStore(), UsClock(T0)
    mgr = SessionManager(store, now_us=clock)
    await mgr.on_set_changed(_added())
    await mgr.on_feed_health("anything", "degraded")
    clock.advance_s(2)
    await mgr.on_feed_health("anything", "healthy")
    assert {w[0] for w in store.gap_windows()} == set(DEFAULT_STREAMS)


async def test_stale_topic_writes_its_silent_window_and_keeps_session() -> None:
    """Review LOW #4: a per-topic stale resubscribe recovers with no `healthy` event, so the
    observed silent window (age_s) is written as a `ws_disconnect` gap immediately."""
    mgr, store, clock, _ = await _mgr()
    sid = mgr.live_session("BTCUSDT")
    clock.advance_s(120)
    await mgr.on_feed_health("publicTrade.BTCUSDT", "stale", 30.0)
    assert store.gap_windows() == [("trades", clock.t - 30_000_000, clock.t, "ws_disconnect")]
    assert mgr.live_session("BTCUSDT") == sid
    await mgr.on_feed_health("publicTrade.BTCUSDT", "stale", 0.0)  # no age: nothing to write
    assert len(store.gaps) == 1


class _Audit:
    def __init__(self, log: list[str], fail: bool = False) -> None:
        self.log, self.fail = log, fail
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail:
            raise OSError("audit down")
        self.log.append("audit")
        self.records.append((action, kw))


class _LoggingStore(MemRecorderStore):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    async def record_gap(self, **kw: Any) -> int:
        self.log.append("gap")
        return await super().record_gap(**kw)


async def test_crash_recovery_is_audited_write_ahead_as_system_recorder() -> None:
    """Security MEDIUM: one `recorder.stop reason=process_restart` per closed session, actor
    `system:recorder`, written BEFORE the gap rows."""
    log: list[str] = []
    store = _LoggingStore(log)
    await SessionManager(store, now_us=UsClock(T0)).on_set_changed(_added())
    audit = _Audit(log)
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), audit=audit)
    assert await fresh.recover_on_startup(T0 + 9) == 1
    assert log[0] == "audit" and log.count("audit") == 1 and "gap" in log[1:]
    ((action, kw),) = audit.records
    assert action == "recorder.stop" and kw["reason"] == "process_restart"
    assert kw["actor_label"] == "system:recorder" and kw["actor_user_id"] is None
    assert kw["object_id"] == "BTCUSDT" and kw["after_state"]["reason"] == "process_restart"


async def test_crash_recovery_audit_failure_leaves_session_open() -> None:
    store = MemRecorderStore()
    await SessionManager(store, now_us=UsClock(T0)).on_set_changed(_added())
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), audit=_Audit([], fail=True))
    with pytest.raises(OSError):
        await fresh.recover_on_startup(T0 + 9)
    assert store.gaps == [] and len(await store.list_live_sessions()) == 1
