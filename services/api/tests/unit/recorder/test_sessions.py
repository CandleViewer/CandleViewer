"""E16-T04 recording sessions + gap detection (Gherkin "Disconnect", "Crash", writer flush).

Chaos scenarios: C-13.6 #2 (WS drop) and #12 (process kill) are exercised at unit level here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import reduce
from pathlib import Path
from typing import Any, Literal, cast
from unittest.mock import DEFAULT, AsyncMock, Mock

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.writer import AuditWriter
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
from tests.unit.recorder._fakes import FakeAudit
from tests.unit.recorder._session_fakes import DEMO, LIVE, MemRecorderStore, UsClock

T0 = to_us(datetime(2026, 9, 14, 10, 0, tzinfo=UTC))


def _added(
    symbol: str = "BTCUSDT", change: Literal["added", "removed", "reason_changed"] = "added"
) -> RecorderSetChanged:
    return RecorderSetChanged(
        symbol=symbol, change=change, reason="manual", reasons=("manual",),
        priority=300, auto_evictable=False, ts_event=T0,
    )  # fmt: skip


async def _crashed(store: MemRecorderStore, cfg: SessionConfig) -> None:
    """BTCUSDT's session, opened in `cfg`'s env by a process that was then killed."""
    mgr = SessionManager(store, now_us=UsClock(T0), audit=FakeAudit(), config=cfg)
    await mgr.on_set_changed(_added())


async def _mgr() -> tuple[SessionManager, MemRecorderStore, UsClock, list[str]]:
    store, clock, inval = MemRecorderStore(), UsClock(T0), []
    mgr = SessionManager(store, now_us=clock, config=LIVE, invalidate=inval.append,
                         topics=stream_for_topic, audit=FakeAudit())  # fmt: skip
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
    dead = SessionManager(store, now_us=UsClock(T0), audit=FakeAudit(), config=LIVE)
    await dead.on_set_changed(_added())
    sid = dead.live_session("BTCUSDT")
    assert sid is not None
    await store.set_session_state(sid, "recording")
    await store.touch_session_events(sid, first=to_dt(T0 + 1), last=to_dt(T0 + 7_000_000))
    # process killed (no stop()); a new process starts 2 minutes later
    start = T0 + 120_000_000
    fresh = SessionManager(store, now_us=UsClock(start), audit=FakeAudit(), config=LIVE)
    assert await fresh.recover_on_startup(start) == 1
    s = store.sessions[sid]
    assert s["end_reason"] == "process_restart" and to_us(s["ended_at"]) == start
    wins = store.gap_windows("process_restart")
    assert {w[0] for w in wins} == set(DEFAULT_STREAMS)
    assert all(lo == T0 + 7_000_000 and hi == start for _, lo, hi, _ in wins)
    assert await store.list_live_sessions("live") == []


async def test_crash_recovery_without_events_gaps_from_started_at() -> None:
    store = MemRecorderStore()
    dead = SessionManager(store, now_us=UsClock(T0), audit=FakeAudit(), config=LIVE)
    await dead.on_set_changed(_added())
    fresh = SessionManager(store, now_us=UsClock(T0 + 5), audit=FakeAudit(), config=LIVE)
    await fresh.recover_on_startup(T0 + 5)
    assert all(lo == T0 for _, lo, _, _ in store.gap_windows("process_restart"))


_ORDER = [
    "sessions.recover_on_startup", "restore", "policy.load_recorded", "policy.adopt_recorded",
    "seed.open_positions", "policy.adopt_positions", "policy.reconcile_all",
    "policy.positions_reloaded",
]  # fmt: skip


async def _startup(failing: str | None = None, positions: list[Any] | None = None) -> list[str]:
    """`startup_reconcile` over mocks that record every call in order; `failing` names the one
    that raises. Returns the calls made, by name."""
    m = AsyncMock()
    m.policy.positions_reloaded = Mock()  # the one sync step
    m.policy.load_recorded.return_value = []
    m.seed.open_positions.return_value = positions
    if failing is not None:
        reduce(getattr, failing.split("."), m).side_effect = OSError(f"{failing} down")
    try:
        await startup_reconcile(m.sessions, m.policy, process_start_us=T0, restore_b11=m.restore,
                                seed=m.seed)  # fmt: skip
    except OSError:
        assert failing is not None
    return [name for name, _, _ in m.mock_calls]


async def test_startup_reconcile_runs_every_step_in_order_and_opens_the_gate_last() -> None:
    assert await _startup(positions=[("ETHUSDT", "p1")]) == _ORDER


@pytest.mark.parametrize("failing", _ORDER[:-1])
async def test_a_failing_startup_step_stops_the_rest_and_leaves_the_gate_closed(
    failing: str,
) -> None:
    assert await _startup(failing, positions=[]) == _ORDER[: _ORDER.index(failing) + 1]


async def test_a_position_source_that_is_not_deployed_is_logged_and_the_gate_still_opens() -> None:
    with capture_logs() as logs:
        calls = await _startup(positions=None)
    assert calls == [name for name in _ORDER if name != "policy.adopt_positions"]
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("recorder_positions_source_not_deployed", "warning")
    ]


async def test_stop_closes_all_live_sessions_as_shutdown() -> None:
    mgr, store, _clock, _ = await _mgr()
    await mgr.stop()
    assert [s["end_reason"] for s in store.sessions.values()] == ["shutdown"]


async def test_writer_buffered_gaps_flush_once_session_opens(tmp_path: Path) -> None:
    """#2203 pending-gap path: the writer's backpressure gap waits for a live session, then
    lands on the session this module opened."""
    from candleviewer.recorder.writer import StreamWriter, WriterConfig
    from tests.unit.recorder._writer_helpers import OPEN_GATE, FakeEvents, FakeSink, FsyncCounter

    store = MemRecorderStore()
    w = StreamWriter(
        lambda _s: FakeSink(), store, FakeEvents(),
        WriterConfig(wal_dir=tmp_path / "wal", env="live"),
        clock=lambda: 0.0, wall_clock_us=lambda: T0, fsync=FsyncCounter(), disk_gate=OPEN_GATE,
    )  # fmt: skip
    await w.open()
    w._gaps[("BTCUSDT", "trades")] = [T0, T0 + 1_000]  # a dropped window (see writer tests)
    await w.flush_gaps()
    assert store.gaps == [] and w.pending_gaps()
    mgr = SessionManager(store, now_us=UsClock(T0), audit=FakeAudit(), config=LIVE)
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
    mgr = SessionManager(store, now_us=clock, audit=FakeAudit(), config=LIVE)
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
        self.log.append(f"audit:{kw['object_id']}")
        self.records.append((action, kw))


class _LoggingStore(MemRecorderStore):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    async def record_gap(self, **kw: Any) -> int:
        self.log.append(f"gap:{kw['symbol']}")
        return await super().record_gap(**kw)


async def test_crash_recovery_is_audited_write_ahead_as_system_recorder() -> None:
    """Security MEDIUM: one `recorder.stop reason=process_restart` per closed session, actor
    `system:recorder`, each written BEFORE its own session's gap rows."""
    log: list[str] = []
    store, symbols = _LoggingStore(log), ("BTCUSDT", "ETHUSDT")
    dead = SessionManager(store, now_us=UsClock(T0), audit=FakeAudit(), config=LIVE)
    for symbol in symbols:
        await dead.on_set_changed(_added(symbol))
    audit = _Audit(log)
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), audit=audit, config=LIVE)
    assert await fresh.recover_on_startup(T0 + 9) == 2
    gaps = len(DEFAULT_STREAMS)
    assert log == [f"{kind}:{s}" for s in symbols for kind in ["audit"] + ["gap"] * gaps]
    for symbol, (action, kw) in zip(symbols, audit.records, strict=True):
        assert action == "recorder.stop" and kw["reason"] == "process_restart"
        assert kw["actor_label"] == "system:recorder" and kw["actor_user_id"] is None
        assert kw["object_id"] == symbol and kw["after_state"]["reason"] == "process_restart"
        assert kw["after_state"]["recording_session_id"] == dead.live_session(symbol)


async def test_a_retried_recovery_audits_a_stale_session_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-A5: the runtime retries a failed startup, and recovery meets the same stale session
    again when its close keeps failing after its audit: the append-only record is written once.
    An audit that failed is still retried (never an unaudited close)."""
    store, audit = MemRecorderStore(), FakeAudit()
    await SessionManager(store, now_us=UsClock(T0), audit=FakeAudit()).on_set_changed(_added())
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), audit=audit)
    emit = AsyncMock(side_effect=[OSError("audit down"), DEFAULT], wraps=audit.emit)
    close = AsyncMock(
        side_effect=[OSError("pg down")] * 2 + [DEFAULT], wraps=store.close_session_at
    )
    monkeypatch.setattr(audit, "emit", emit)
    monkeypatch.setattr(store, "close_session_at", close)
    for _ in range(3):  # the audit fails, then the close fails twice
        with pytest.raises(OSError):
            await fresh.recover_on_startup(T0 + 9)
    assert await fresh.recover_on_startup(T0 + 9) == 1  # the fourth attempt closes it
    assert audit.actions() == ["recorder.stop"]  # one record for four attempts


async def test_crash_recovery_audit_failure_leaves_session_open() -> None:
    store = MemRecorderStore()
    await _crashed(store, LIVE)
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), audit=_Audit([], fail=True), config=LIVE)
    with pytest.raises(OSError):
        await fresh.recover_on_startup(T0 + 9)
    assert store.gaps == [] and len(await store.list_live_sessions("live")) == 1


class _StalledAudit:
    """Audit sink whose `emit` parks until released, like an `AuditWriter` append in flight."""

    def __init__(self, fail: bool = False) -> None:
        self.entered, self.release, self.finished = (asyncio.Event() for _ in range(3))
        self.cancelled, self.fail = False, fail
        self.records: list[str] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished.set()
        if self.fail:
            raise OSError("audit down")
        self.records.append(action)


async def _stalled_recovery(audit: _StalledAudit) -> MemRecorderStore:
    """Crash recovery whose `recorder.stop` audit outlives `store_timeout_s` (0 s: the
    in-memory store never suspends, so only the stalled audit reaches the deadline)."""
    store = MemRecorderStore()
    await _crashed(store, LIVE)
    cfg = SessionConfig(env="live", store_timeout_s=0.0)
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), config=cfg, audit=audit)
    with pytest.raises(TimeoutError):
        await fresh.recover_on_startup(T0 + 9)
    return store


async def test_crash_recovery_audit_timeout_fails_recovery_and_leaves_session_open() -> None:
    """#2250 review: the `store_timeout_s` bound fails recovery (session left open, retried
    on the next start, never an unaudited close). Cancellation safety of an append already
    in flight is the sink's job (`AuditWriter`), so the recorder just cancels its await:
    nothing is left running here."""
    audit = _StalledAudit()
    store = await _stalled_recovery(audit)
    assert audit.entered.is_set() and audit.cancelled
    assert store.gaps == [] and len(await store.list_live_sessions("live")) == 1
    assert audit.records == []


# -- the audit writer is required: no unaudited crash recovery can exist (C-2.9, #2188) ----------


def test_session_manager_built_without_audit_raises_type_error() -> None:
    store, clock = MemRecorderStore(), UsClock(T0)
    with pytest.raises(TypeError, match="audit"):
        SessionManager(store, now_us=clock, config=LIVE)  # type: ignore[call-arg]  # the default is gone


def test_session_manager_built_with_audit_none_raises_value_error_naming_the_reason() -> None:
    store, clock = MemRecorderStore(), UsClock(T0)
    with pytest.raises(ValueError, match=r"crash-recovery `recorder\.stop` audit.*C-2\.9"):
        SessionManager(store, now_us=clock, audit=None, config=LIVE)  # type: ignore[arg-type]  # a runtime None


async def test_crash_recovery_writes_the_stop_audit_record_for_the_session_it_closes() -> None:
    """The path that used to skip its audit silently when none was wired (#2188): the closed
    session now always has its `recorder.stop` record, with the exact gap window."""
    store, audit = MemRecorderStore(), FakeAudit()
    await _crashed(store, LIVE)
    (sid,) = store.sessions
    start = T0 + 120_000_000
    fresh = SessionManager(store, now_us=UsClock(start), audit=audit, config=LIVE)
    assert await fresh.recover_on_startup(start) == 1
    after_state = {
        "symbol": "BTCUSDT", "recording_session_id": sid, "reason": "process_restart",
        "gap_start_us": str(T0), "gap_end_us": str(start),
    }  # fmt: skip
    assert audit.records == [
        ("recorder.stop", {
            "actor_label": "system:recorder", "actor_user_id": None,
            "object_kind": "recorded_symbol", "object_id": "BTCUSDT",
            "reason": "process_restart", "after_state": after_state, "env": "live",
        })
    ]  # fmt: skip


async def test_the_stop_record_carries_the_managers_env() -> None:
    store, audit = MemRecorderStore(), FakeAudit()
    await _crashed(store, DEMO)
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), config=DEMO, audit=audit)
    await fresh.recover_on_startup(T0 + 9)
    assert audit.envs() == [("recorder.stop", "demo")]


async def test_the_stop_record_keeps_its_after_state_through_the_audit_writers_build(
    tmp_path: Path,
) -> None:
    """M19's redactor blanks a `session_id` key as a credential name; this record must survive."""
    store, audit = MemRecorderStore(), FakeAudit()
    await _crashed(store, LIVE)
    fresh = SessionManager(store, now_us=UsClock(T0 + 9), audit=audit, config=LIVE)
    await fresh.recover_on_startup(T0 + 9)
    ((action, kw),) = audit.records
    built = AuditWriter(cast(Any, object()), str(tmp_path / "audit.wal")).build(action, **kw)
    assert built.after_state == kw["after_state"]
