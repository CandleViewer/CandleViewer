"""E16-T04 x E16-T02 (#2188): crash recovery opens the policy warm-up gate afterwards, and
the B11 state-entry hooks are mirrored onto the session row through the policy."""

from __future__ import annotations

from datetime import UTC, datetime

from candleviewer.recorder.policy import RecordingPolicy
from candleviewer.recorder.sessions import SessionManager, startup_reconcile, to_dt, to_us
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock
from tests.unit.recorder.conftest import FakeAudit, FakeBus, FakeClock

T0 = to_us(datetime(2026, 9, 14, tzinfo=UTC))


async def test_crash_recovery_then_warmup_gate_opens_and_only_then_stops(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    """Gherkin "Crash leaves no open session" + policy gate (C-13.6 #12)."""
    store = MemRecorderStore()
    dead = SessionManager(store, now_us=UsClock(T0))
    sid = await store.open_session_at(recorded_symbol_id="r", symbol="ETHUSDT",
                                      streams=["trades"], orderbook_depth=1, ws_endpoint="x",
                                      started_at=to_dt(T0))  # fmt: skip
    await store.touch_session_events(sid, first=to_dt(T0), last=to_dt(T0 + 5_000_000))
    del dead  # process killed
    p = RecordingPolicy(bus=bus, audit=audit, env="demo", now=clock)
    try:
        await p.on_position_opened("ETHUSDT", "p1")
        await p.on_position_closed("ETHUSDT", "p1")
        clock.advance(10_000)
        await p.tick()
        assert p.leaf("ETHUSDT") == "lingering"  # gate closed before the reconcile
        start = T0 + 60_000_000
        order: list[str] = []

        async def reload_positions() -> None:
            await p.tick()
            order.append(f"positions:{p.leaf('ETHUSDT')}")  # still gated while reloading

        mgr = SessionManager(store, now_us=UsClock(start))
        await startup_reconcile(mgr, p, process_start_us=start,
                                reload_positions=reload_positions)  # fmt: skip
        s = store.sessions[sid]
        assert s["end_reason"] == "process_restart" and to_us(s["ended_at"]) == start
        assert store.gap_windows("process_restart") == [
            ("trades", T0 + 5_000_000, start, "process_restart")
        ]
        assert order == ["positions:lingering"]
        await p.tick()
        assert p.effective_set() == {}  # gate open: the expired grace now stops
    finally:
        await p.stop()


async def test_policy_forwards_b11_state_entries_to_the_session_mirror(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    store = MemRecorderStore()
    mgr = SessionManager(store, now_us=UsClock(T0))
    p = RecordingPolicy(bus=bus, audit=audit, env="demo", now=clock)
    p.positions_reloaded()
    p.observe_states(mgr.on_b11_state)
    try:
        await p.on_position_opened("BTCUSDT", "p1")
        for _topic, ev in bus.events:
            await mgr.on_set_changed(ev)
        sid = mgr.live_session("BTCUSDT")
        assert sid is not None
        assert p.leaf("BTCUSDT") == "recording"
        # the `recording` entry hook ran before the session existed; re-entering mirrors it
        await mgr.on_b11_state("BTCUSDT", "recording", {})
        assert store.sessions[sid]["state"] == "recording"
    finally:
        await p.stop()


async def test_mirror_failure_never_fails_the_chart(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    async def broken(symbol: str, hook: str, ctx: object) -> None:
        raise OSError("pg down")

    p = RecordingPolicy(bus=bus, audit=audit, env="demo", now=clock)
    p.positions_reloaded()
    p.observe_states(broken)  # type: ignore[arg-type]
    try:
        await p.on_position_opened("BTCUSDT", "p1")
        assert p.leaf("BTCUSDT") == "recording"
    finally:
        await p.stop()
