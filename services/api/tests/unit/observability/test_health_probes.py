"""E04-T04 unit tests: aggregation, timeout isolation, edge-triggered events."""

from __future__ import annotations

import asyncio
import contextlib
import itertools

import pytest

from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    NotDeployedProbe,
    ProbeResult,
    SystemEvent,
    worst_of,
)

S = ComponentState


class _Sink:
    def __init__(self) -> None:
        self.events: list[SystemEvent] = []

    async def write(self, event: SystemEvent) -> None:
        self.events.append(event)


def test_rank_order_is_down_warning_degraded_healthy() -> None:
    assert S.DOWN.rank > S.WARNING.rank > S.DEGRADED.rank > S.HEALTHY.rank


@pytest.mark.parametrize("combo", list(itertools.product(list(S), repeat=2)))
def test_worst_of_pairs_is_max_rank(combo: tuple[S, S]) -> None:
    got = worst_of(list(combo))
    assert got.rank == max(c.rank for c in combo)


def test_worst_of_empty_and_not_deployed_is_healthy() -> None:
    assert worst_of([]) is S.HEALTHY
    assert worst_of([S.NOT_DEPLOYED, S.NOT_DEPLOYED]) is S.HEALTHY


async def test_slow_probe_times_out_degraded_others_normal() -> None:
    async def hang() -> ProbeResult:
        await asyncio.sleep(30)
        return ProbeResult(S.HEALTHY)

    async def ok() -> ProbeResult:
        return ProbeResult(S.HEALTHY, "fine")

    reg = HealthRegistry(probe_deadline_s=0.05)
    reg.register(CallableProbe("parquet_store", hang, timeout=10))
    reg.register(CallableProbe("postgres", ok))
    snap = await asyncio.wait_for(reg.refresh(), timeout=2)
    by = {c.name: c for c in snap.components}
    assert by["parquet_store"].state is S.DEGRADED
    assert by["parquet_store"].detail == "probe timeout"
    assert by["postgres"].state is S.HEALTHY
    assert snap.overall is S.DEGRADED


async def test_probe_exception_is_isolated_and_not_leaked() -> None:
    async def boom() -> ProbeResult:
        raise RuntimeError("postgres://user:secret@host/db")

    reg = HealthRegistry()
    reg.register(CallableProbe("postgres", boom))
    reg.register(NotDeployedProbe("oms"))
    snap = await reg.refresh()
    by = {c.name: c for c in snap.components}
    assert by["postgres"].state is S.DOWN
    assert "secret" not in by["postgres"].detail
    assert by["oms"].state is S.NOT_DEPLOYED
    assert snap.overall is S.DOWN


async def test_last_good_at_kept_after_failure() -> None:
    state = {"ok": True}

    async def fn() -> ProbeResult:
        return ProbeResult(S.HEALTHY if state["ok"] else S.DOWN)

    reg = HealthRegistry()
    reg.register(CallableProbe("postgres", fn))
    first = (await reg.refresh()).components[0]
    state["ok"] = False
    second = (await reg.refresh()).components[0]
    assert second.state is S.DOWN
    assert second.last_good_at == first.last_good_at is not None


async def test_transitions_are_edge_triggered() -> None:
    seq = iter([S.HEALTHY, S.HEALTHY, S.DOWN, S.DOWN, S.DOWN, S.HEALTHY])

    async def fn() -> ProbeResult:
        return ProbeResult(next(seq))

    sink = _Sink()
    reg = HealthRegistry(events=sink)
    reg.register(CallableProbe("bybit_public_ws", fn))
    for _ in range(6):
        await reg.refresh()
    assert [e.severity for e in sink.events] == ["error", "info"]
    assert all(e.component == "exchange" for e in sink.events)
    assert "healthy -> down" in sink.events[0].message
    assert sink.events[1].kind == "health_recovered"


async def test_sink_and_publisher_failures_do_not_break_refresh() -> None:
    class Bad:
        async def write(self, event: SystemEvent) -> None:
            raise RuntimeError("x")

    seq = iter([S.HEALTHY, S.DOWN])

    async def fn() -> ProbeResult:
        return ProbeResult(next(seq))

    async def pub(_: object) -> None:
        raise RuntimeError("x")

    reg = HealthRegistry(events=Bad(), on_snapshot=pub)
    reg.register(CallableProbe("postgres", fn))
    await reg.refresh()
    assert (await reg.refresh()).overall is S.DOWN


async def test_observers_and_placeholders_and_ticker() -> None:
    seen: list[str] = []
    reg = HealthRegistry()
    reg.state_observer = lambda n, s: seen.append(n)
    reg.duration_observer = lambda n, d: None
    reg.register_placeholders()
    reg.start(0.01)
    reg.start(0.01)  # idempotent
    for _ in range(100):
        if reg.snapshot() is not None:
            break
        await asyncio.sleep(0.01)
    await reg.stop()
    await reg.stop()
    snap = reg.snapshot()
    assert snap is not None and len(snap.components) == 10
    assert all(c.state is S.NOT_DEPLOYED for c in snap.components)
    assert snap.overall is S.HEALTHY
    assert "disk" in seen


# F1 (E04-Q02): the ticker must outlive a failing refresh and never serve stale HEALTHY.
async def test_probe_ticker_survives_one_raising_refresh_and_shows_the_next_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yield_once = asyncio.sleep  # the loop's own sleep is replaced; this one stays real
    monkeypatch.setattr(asyncio, "sleep", lambda _s: yield_once(0))
    down = False
    calls = 0

    async def probe() -> ProbeResult:
        return ProbeResult(S.DOWN if down else S.HEALTHY, "")

    def observer(_name: str, _state: S) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:  # the second refresh raises, once
            raise RuntimeError("observer failed")

    reg = HealthRegistry()
    reg.register(CallableProbe("postgres", probe))
    reg.state_observer = observer
    reg.start(1.0)
    try:
        for _ in range(20):
            await yield_once(0)
        first = reg.snapshot()
        assert first is not None and first.overall is S.HEALTHY
        down = True
        for _ in range(200):  # many ticks of the fake clock; no wall time passes
            await yield_once(0)
        latest = reg.snapshot()
        assert latest is not None and latest.overall is S.DOWN
    finally:
        await reg.stop()


async def _spin(n: int) -> None:
    for _ in range(n):
        await _REAL_SLEEP(0)


_REAL_SLEEP = asyncio.sleep


async def test_ticker_survives_raising_refresh_and_marks_snapshot_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", lambda _s: _REAL_SLEEP(0))
    reg = HealthRegistry()

    async def ok() -> ProbeResult:
        return ProbeResult(S.HEALTHY)

    reg.register(CallableProbe("postgres", ok))
    await reg.refresh()
    fail = True
    real_refresh = reg.refresh
    calls = 0

    async def flaky() -> object:
        nonlocal calls
        calls += 1
        if fail:
            raise RuntimeError("boom")
        return await real_refresh()

    monkeypatch.setattr(reg, "refresh", flaky)
    reg.start(1.0)
    try:
        await _spin(20)
        assert calls > 2  # kept ticking after the first raise
        snap = reg.snapshot()
        assert snap is not None and snap.overall is S.DEGRADED  # not stale HEALTHY
        fail = False
        await _spin(20)
        snap = reg.snapshot()
        assert snap is not None and snap.overall is S.HEALTHY  # recovered
    finally:
        await reg.stop()


async def test_raising_observers_do_not_freeze_the_snapshot() -> None:
    def bad_state(_n: str, _s: S) -> None:
        raise RuntimeError("state hook")

    def bad_duration(_n: str, _d: float) -> None:
        raise RuntimeError("duration hook")

    async def ok() -> ProbeResult:
        return ProbeResult(S.DOWN)

    reg = HealthRegistry()
    reg.state_observer = bad_state
    reg.duration_observer = bad_duration
    reg.register(CallableProbe("postgres", ok))
    snap = await reg.refresh()
    assert snap.overall is S.DOWN
    assert reg.snapshot() is snap


async def test_stop_cancels_the_ticker_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = HealthRegistry()
    reg.register_placeholders(["postgres"])
    reg.start(30.0)
    await _spin(5)
    task = reg._task
    assert task is not None
    await reg.stop()
    assert task.cancelled() or task.done()
    assert reg._task is None
    with contextlib.suppress(asyncio.CancelledError):
        assert task.cancelled()
