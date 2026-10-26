"""#2188 S4b: `build_recorder` over in-memory stores. One env feeds the policy, the sessions and
the writer; the gate's arguments; a set change reaches the sessions (with its streams), then the
writer, then the bus; a restored chart gets its session at the startup's end; the audit emitter
raises when unresolved; the store is bounded; the runtime is built, not started."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.datastructures import State

import candleviewer.recorder_wiring as rw
from candleviewer.app import _LazyAuditEmitter, recording_writer
from candleviewer.health_wiring import register_recorder_probe
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.health_probes import ComponentState, HealthRegistry
from candleviewer.recorder.budget import DiskBudget
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from candleviewer.recorder.sessions import SessionConfig
from candleviewer.recorder.snapshot_anchors import NoAnchor
from candleviewer.recorder.writer import WriterConfig
from candleviewer.settings import Environment, Settings
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem
from tests.unit.recorder._session_fakes import MemRecorderStore
from tests.unit.recorder._writer_helpers import FakeEvents, FakeSink, FakeStore

USER = user_actor("u-1")


class Budget:
    halted = False
    refuses_auto_record = False


class Rig:
    def __init__(self, tmp_path: Path, env: Environment, audit: Any, budget: Budget | None) -> None:
        self.settings = Settings(
            parquet_root=str(tmp_path / "parquet"), environment=env, recorder_max_symbols=5
        )
        self.config, self.clock = rw.policy_config(self.settings), FakeClock(1_000.0)
        self.bus, self.store, self.sess = FakeBus(), Mem(), MemRecorderStore()
        self.budget, self.trace = budget, list[str]()
        self.rec = rw.build_recorder(
            self.settings, self.config, recorded=self.store, sessions=self.sess,
            counters=FakeStore(), rows=cast(Any, object()), audit=audit, bus=self.bus,
            budget=cast("DiskBudget | None", budget), invalidate=self.trace.append,
            topics=lambda t: (t, ()), sinks=lambda _s: FakeSink(), events=FakeEvents(),
            clocks=rw.Clocks(wall_s=self.clock, process_start_us=0),
        )  # fmt: skip


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Rig]:
    r = Rig(tmp_path, Environment.DEMO, FakeAudit(), Budget())
    r.rec.policy.positions_reloaded()
    yield r
    await r.rec.policy.stop()


def _manual(rig: Rig) -> Any:
    return rig.rec.policy.add_manual("ETHUSDT", USER, ("trades", "tickers"))


async def test_policy_sessions_and_writer_take_the_one_settings_env(tmp_path: Path) -> None:
    r = Rig(tmp_path, Environment.TESTNET, FakeAudit(), None)
    pol = cast(Any, r.rec.policy)
    assert (r.rec.env, pol._env) == ("testnet", "testnet")
    assert cast(Any, r.rec.sessions)._cfg.env == cast(Any, r.rec.writer)._cfg.env == "testnet"
    assert r.rec.runtime._env == "testnet"


def test_no_recorder_part_defaults_its_env() -> None:
    for cls in (SessionConfig, WriterConfig):
        assert inspect.signature(cls).parameters["env"].default is inspect.Parameter.empty
    assert inspect.signature(RecordingPolicy).parameters["env"].default is inspect.Parameter.empty
    assert (
        inspect.signature(rw.NoPositionSource).parameters["env"].default is inspect.Parameter.empty
    )


async def test_no_position_source_answers_none_for_its_env() -> None:
    src = rw.NoPositionSource("demo")
    answer = cast(Any, src).open_positions()
    assert await answer is None and src.env == "demo"


async def test_the_policy_runs_with_the_one_config_and_the_settings_retention(
    rig: Rig,
) -> None:
    assert cast(Any, rig.rec.policy)._cfg is rig.config
    assert rig.config.default_retention_days == rig.settings.recorder_retention_days
    assert rig.config.max_symbols == 5 and rig.config.autostart_delay_s == 60.0
    assert PolicyConfig().autostop_grace_s == rig.config.autostop_grace_s


async def test_the_policy_reads_the_injected_wall_clock(rig: Rig) -> None:
    assert cast(Any, rig.rec.policy)._now is rig.clock  # linger_until is wall-clock (Q4)


async def test_gate_arguments_read_the_budget_and_the_policy(tmp_path: Path) -> None:
    b = Budget()
    r = Rig(tmp_path, Environment.DEMO, FakeAudit(), b)
    gate = cast(Any, r.rec.writer)._gate
    assert gate.position_open == r.rec.policy.position_open
    b.halted, b.refuses_auto_record = True, True
    assert gate.halted() and cast(Any, r.rec.policy)._disk_refuses()
    b.halted = b.refuses_auto_record = False  # read per call, never captured
    assert not gate.halted() and not cast(Any, r.rec.policy)._disk_refuses()


async def test_without_a_budget_the_gate_and_the_refusal_read_false(tmp_path: Path) -> None:
    r = Rig(tmp_path, Environment.DEMO, FakeAudit(), None)
    assert not cast(Any, r.rec.writer)._gate.halted()
    assert not cast(Any, r.rec.policy)._disk_refuses()


async def test_a_set_change_reaches_sessions_then_writer_then_bus(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    mgr, wr, bus = cast(Any, rig.rec.sessions), cast(Any, rig.rec.writer), rig.bus
    on_sessions, on_writer, on_bus = mgr.on_set_changed, wr.on_set_changed, bus.publish

    async def s(*a: Any) -> None:
        order.append("sessions")
        await on_sessions(*a)

    def w(*a: Any) -> None:
        order.append("writer")
        on_writer(*a)

    async def b(*a: Any) -> None:
        order.append("bus")
        await on_bus(*a)

    monkeypatch.setattr(mgr, "on_set_changed", s)
    monkeypatch.setattr(wr, "on_set_changed", w)
    monkeypatch.setattr(bus, "publish", b)
    await _manual(rig)
    assert order == ["sessions", "writer", "bus"]
    assert wr.is_recording("ETHUSDT") and mgr.live_session("ETHUSDT") is not None


async def test_the_sessions_get_the_entrys_streams(rig: Rig) -> None:
    await _manual(rig)
    [session] = rig.sess.sessions.values()
    assert session["streams"] == ["trades", "tickers"]


async def test_a_restored_chart_gets_its_session_and_writer_lane_at_the_startup_end(
    rig: Rig,
) -> None:
    await _manual(rig)  # adopted without a publish: nothing opened it
    await rig.rec.sessions.stop()
    cast(Any, rig.rec.writer).seed([])
    assert rig.rec.sessions.live_session("ETHUSDT") is None
    await rig.rec.on_ready()
    assert rig.rec.sessions.live_session("ETHUSDT") is not None
    assert rig.rec.writer.is_recording("ETHUSDT")
    assert [s["streams"] for s in rig.sess.sessions.values()][-1] == ["trades", "tickers"]


async def test_an_on_ready_that_fails_for_one_symbol_does_not_starve_the_rest(rig: Rig) -> None:
    await rig.rec.policy.add_manual("BTCUSDT", USER)
    await _manual(rig)
    await rig.rec.sessions.stop()
    rig.sess.fail = True
    await rig.rec.on_ready()  # every open fails and is logged, none raises
    rig.sess.fail = False
    await rig.rec.on_ready()
    assert {"BTCUSDT", "ETHUSDT"} <= {s["symbol"] for s in rig.sess.sessions.values()}


class _Unresolved:
    @property
    def writer(self) -> Any:
        raise RuntimeError("AuditService.start() has not wired a real backend")


async def test_the_lazy_audit_emitter_raises_when_unresolved() -> None:
    with pytest.raises(RuntimeError):
        await _LazyAuditEmitter(cast(Any, _Unresolved())).emit("recorder.add", env="demo")


async def test_a_write_with_an_unresolved_audit_raises_and_records_nothing(
    tmp_path: Path,
) -> None:
    r = Rig(tmp_path, Environment.DEMO, _LazyAuditEmitter(cast(Any, _Unresolved())), None)
    r.rec.policy.positions_reloaded()
    try:
        with pytest.raises(RuntimeError):
            await _manual(r)
        assert not r.rec.writer.is_recording("ETHUSDT") and not r.sess.sessions
    finally:
        await r.rec.policy.stop()


async def test_build_recorder_bounds_the_policys_store_and_cuts_a_held_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert rw.STORE_TIMEOUT_S == 5.0
    monkeypatch.setattr(rw, "STORE_TIMEOUT_S", 0.01)  # `build_recorder` reads it at build
    r = Rig(tmp_path, Environment.DEMO, FakeAudit(), None)
    bounded = cast(Any, r.rec.policy)._recorded
    assert isinstance(bounded, rw.BoundedStore) and bounded._timeout_s == 0.01
    r.rec.policy.positions_reloaded()
    r.store.hold["upsert_manual"] = asyncio.Event()  # never set: only the bound ends it
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_manual(r), 1)  # an unbounded store fails here, not hangs
        assert not r.rec.writer.is_recording("ETHUSDT")
    finally:
        await r.rec.policy.stop()


async def test_a_sessions_failure_in_the_fan_out_still_records_and_publishes_then_the_tick_heals(
    rig: Rig,
) -> None:
    rig.sess.fail = True
    await asyncio.wait_for(_manual(rig), 1)  # the add happened: no 5xx for it
    assert rig.rec.writer.is_recording("ETHUSDT") and len(rig.bus.events) == 1
    assert rig.rec.sessions.live_session("ETHUSDT") is None
    rig.sess.fail = False
    await asyncio.wait_for(rig.rec.runtime._tick(), 1)
    assert rig.rec.sessions.live_session("ETHUSDT") is not None
    assert [s["streams"] for s in rig.sess.sessions.values()] == [["trades", "tickers"]]


async def test_the_heal_of_one_symbol_failing_starves_no_other(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.sess.fail = True
    await rig.rec.policy.add_manual("BTCUSDT", USER)
    await _manual(rig)
    rig.sess.fail = False
    mgr, real = cast(Any, rig.rec.sessions), rig.rec.sessions.on_set_changed

    async def flaky(event: Any, streams: Any = ()) -> None:
        if event.symbol == "BTCUSDT":
            raise OSError("pg down")
        await real(event, streams)

    monkeypatch.setattr(mgr, "on_set_changed", flaky)
    await rig.rec.runtime._tick()
    assert rig.rec.sessions.live_session("ETHUSDT") is not None
    assert rig.rec.sessions.live_session("BTCUSDT") is None


async def test_a_cancel_in_the_fan_out_sessions_step_is_not_swallowed(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def cancelled(*_a: Any) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(cast(Any, rig.rec.sessions), "on_set_changed", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await _manual(rig)


async def test_the_runtime_is_built_not_started(rig: Rig) -> None:
    assert rig.rec.runtime.health().status is HealthStatus.STOPPED  # only the lifespan starts it
    assert not rig.rec.runtime.startup_complete


def test_the_four_policy_keys_default_as_documented() -> None:
    s = Settings()
    assert (s.recorder_autostart_delay_s, s.recorder_autostop_grace_s) == (60, 1800)
    assert (s.recorder_autorecord_enabled, s.recorder_max_symbols) == (True, 20)


async def test_user_writes_are_refused_until_the_startup_completes() -> None:
    control = SimpleNamespace()
    ready = False
    state = State()
    state.recording_writer, state.recording_ready = control, lambda: ready
    assert recording_writer(state) is None  # warm-up: 503, nothing changes
    ready = True
    assert recording_writer(state) is control  # read per request, never captured
    state.recording_ready = lambda: False
    assert recording_writer(state) is None


class _Events:
    def __init__(self) -> None:
        self.written: list[Any] = []

    async def write(self, event: Any) -> None:
        self.written.append(event)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (HealthStatus.DEGRADED, ComponentState.DEGRADED),
        (HealthStatus.STOPPED, ComponentState.NOT_DEPLOYED),
    ],
)
async def test_the_probe_maps_the_runtime_status_and_no_detail_reaches_the_registry(
    status: HealthStatus, expected: ComponentState
) -> None:
    marker, now = "MARKER-env-live-OSError-attempts-5", [HealthStatus.OK]
    events = _Events()
    registry = HealthRegistry(events=cast(Any, events))
    register_recorder_probe(
        registry, lambda: HealthReport(module="recorder", status=now[0], detail=marker)
    )
    await registry.refresh()  # healthy first: the next state is an edge
    now[0] = status
    snap = await registry.refresh()
    [health] = [c for c in snap.components if c.name == "recorder"]
    assert health.state is expected
    assert "MARKER" not in repr(snap) and "MARKER" not in repr(events.written)
    assert events.written  # the edge was written, without the detail


class _Books:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def anchor(self, symbol: str) -> NoAnchor:
        self.asked.append(symbol)
        return "not_live"


def test_lazy_anchor_books_read_the_stream_per_call_and_name_a_missing_one() -> None:
    """#2223: the ingestion book stream is attached after the recorder is composed."""
    books: list[_Books] = []
    lazy = rw.LazyAnchorBooks(lambda: books[0] if books else None)
    assert lazy.anchor("BTCUSDT") == "no_book"
    books.append(_Books())
    assert lazy.anchor("BTCUSDT") == "not_live" and books[0].asked == ["BTCUSDT"]


async def test_build_recorder_with_books_anchors_on_the_settings_interval(tmp_path: Path) -> None:
    settings = Settings(parquet_root=str(tmp_path / "parquet"), recorder_snapshot_interval_s=7)
    mono, books = FakeClock(50.0), _Books()
    rec = rw.build_recorder(
        settings, rw.policy_config(settings), recorded=Mem(), sessions=MemRecorderStore(),
        counters=FakeStore(), rows=cast(Any, object()), audit=FakeAudit(), bus=FakeBus(),
        budget=None, invalidate=lambda _s: None, topics=lambda t: (t, ()),
        sinks=lambda _s: FakeSink(), events=FakeEvents(),
        clocks=rw.Clocks(mono_s=mono, process_start_us=0), books=books,
    )  # fmt: skip
    assert rec.anchors is not None
    rec.writer.seed(["BTCUSDT"])
    await rec.anchors.tick()
    mono.advance(6)
    await rec.anchors.tick()
    assert books.asked == []
    mono.advance(1)
    await rec.anchors.tick()
    assert books.asked == ["BTCUSDT"]
