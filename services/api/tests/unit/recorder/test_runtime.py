"""#2188 S4a: `RecorderRuntime` over mock collaborators, an injected clock and sleep: the startup
retries with the gate closed, the tick, the ordered stop and the health. The real startup runs
against the mocks (the real policy and sessions are S3a's tests). No test sleeps: the runtime
parks in `Sleep` until the test lets it go."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, cast
from unittest.mock import DEFAULT, AsyncMock, Mock

import pytest
from structlog.testing import capture_logs

from candleviewer.observability.health import HealthStatus
from candleviewer.recorder.runtime import TICK_S, RecorderRuntime, RuntimeBounds
from tests.unit.recorder._fakes import FakeClock

BOUNDS = RuntimeBounds(
    start_timeout_s=30, startup_timeout_s=5, tick_timeout_s=5, retry_base_s=1, retry_cap_s=8,
    max_attempts=4,
)  # fmt: skip
GATE = "policy.positions_reloaded"
TICK = ["policy.tick", "sessions.poll_writer"]
STOP = ["writer.stop", "sessions.stop", "policy.stop"]


class Sleep:
    """The injected `sleep`: the runtime parks in it until the test lets it go."""

    def __init__(self) -> None:
        self._parked: asyncio.Queue[tuple[float, asyncio.Future[None]]] = asyncio.Queue()
        self._gate: asyncio.Future[None] | None = None

    async def __call__(self, delay: float) -> None:
        gate = asyncio.get_running_loop().create_future()
        self._parked.put_nowait((delay, gate))
        await gate

    async def parked(self) -> float:
        """Wait until the runtime is in a sleep (all it had to do before has run): its delay."""
        delay, self._gate = await asyncio.wait_for(self._parked.get(), 5)
        return delay

    def go(self) -> None:
        cast(asyncio.Future[None], self._gate).set_result(None)


class Rig:
    """The runtime over mocks that record every call in order; `names` lists the ones in play."""

    def __init__(self, bounds: RuntimeBounds, rng: Any) -> None:
        self.clock, self.sleep, self.m = FakeClock(), Sleep(), AsyncMock()
        self.m.policy.positions_reloaded = Mock()  # the one sync step
        self.m.policy.load_recorded.return_value = []
        self.m.seed.open_positions.return_value = []
        self.rt = RecorderRuntime(
            policy=self.m.policy, sessions=self.m.sessions, writer=self.m.writer, seed=self.m.seed,
            restore_b11=self.m.restore, process_start_us=0, clock=self.clock,
            sleep=self.sleep, rng=rng, bounds=bounds,
        )  # fmt: skip

    @property
    def names(self) -> list[str]:
        watched = {"writer.start", "restore", GATE, *TICK, *STOP}
        return [n for n, _, _ in self.m.mock_calls if n in watched]


@pytest.fixture
async def rig(request: pytest.FixtureRequest) -> AsyncIterator[Rig]:
    """`parametrize("rig", [overrides], indirect=True)` replaces bounds, and `rng` (default 1.0)."""
    over = dict(getattr(request, "param", {}))
    rng = over.pop("rng", lambda: 1.0)
    r = Rig(replace(BOUNDS, **over), rng)
    yield r
    await r.rt.stop(0.4)  # a task the test left running


async def _hang(*_: object) -> None:
    await asyncio.Event().wait()  # never returns: only a timeout ends it


async def test_start_returns_before_the_startup_finishes_while_a_slow_wal_replay_runs(
    rig: Rig,
) -> None:
    replay = asyncio.Event()
    rig.m.writer.start.side_effect = replay.wait  # the writer's start parks: the WAL replay
    await asyncio.wait_for(rig.rt.start(), 1)  # `start_all` is not blocked
    for _ in range(20):
        await asyncio.sleep(0)  # the loop runs meanwhile
    h = rig.rt.health()
    assert (rig.names, rig.rt.startup_complete, h.status, h.detail) == (
        ["writer.start"], False, HealthStatus.OK, "startup=pending")  # fmt: skip
    replay.set()
    assert await rig.sleep.parked() == TICK_S  # the first tick has run
    assert rig.names == ["writer.start", "restore", GATE, *TICK] and rig.rt.startup_complete


@pytest.mark.parametrize(
    ("rig", "scale"),
    [({"rng": lambda: 1.0}, 1.0), ({"rng": lambda: 0.0}, 0.5)],
    indirect=["rig"],
)
async def test_a_failing_startup_keeps_the_gate_closed_and_retries_with_growing_capped_delays(
    rig: Rig, scale: float
) -> None:
    rig.m.restore.side_effect = [OSError("pg down")] * 6 + [None]
    await rig.rt.start()
    seen = []
    for _ in range(6):
        delay = await rig.sleep.parked()  # in its backoff
        h = rig.rt.health()
        seen.append((delay, h.status.value, h.detail, rig.rt.startup_complete, GATE in rig.names))
        rig.sleep.go()
    assert [s[0] for s in seen] == [d * scale for d in (1, 2, 4, 8, 8, 8)]  # doubling, capped
    states = [("ok", f"startup=retrying attempts={n} last_error=OSError") for n in (1, 2, 3)]
    states += [("degraded", f"startup=degraded attempts={n} last_error=OSError") for n in (4, 5, 6)]
    assert [s[1:3] for s in seen] == states  # degraded past the bound, the retries go on at the cap
    assert [s[3:] for s in seen] == [(False, False)] * 6  # never complete, the gate never opened
    assert await rig.sleep.parked() == TICK_S  # the seventh startup passed
    assert (rig.rt.health().detail, rig.rt.startup_complete) == ("startup=done", True)
    assert rig.names == ["writer.start", *["restore"] * 7, GATE, *TICK]  # the writer started once


@pytest.mark.parametrize("rig", [{"startup_timeout_s": 0.01}], indirect=True)
async def test_a_hung_restore_fails_the_whole_attempt_at_its_timeout_and_is_retried(
    rig: Rig,
) -> None:
    async def hang_once() -> None:
        rig.m.restore.side_effect = None  # the retry's restore returns
        await _hang()

    rig.m.restore.side_effect = hang_once
    await rig.rt.start()
    await rig.sleep.parked()  # the attempt timed out and the runtime is in its backoff
    assert rig.rt.health().detail == "startup=retrying attempts=1 last_error=TimeoutError"
    assert GATE not in rig.names and not rig.rt.startup_complete
    rig.sleep.go()
    await rig.sleep.parked()
    assert GATE in rig.names and rig.rt.startup_complete


@pytest.mark.parametrize("kind", ["raises", "hangs"])
@pytest.mark.parametrize("rig", [{"tick_timeout_s": 0.01}], indirect=True)
async def test_a_tick_that_raises_or_hangs_is_logged_and_the_next_tick_runs(
    rig: Rig, kind: str
) -> None:
    first = [True]

    async def effect() -> object:
        if first:
            first.clear()
            if kind == "raises":
                raise OSError("tick down")
            await _hang()
        return DEFAULT  # the later ticks work

    rig.m.policy.tick.side_effect = effect
    with capture_logs() as logs:
        await rig.rt.start()
        await rig.sleep.parked()  # tick 1 failed, and the loop is in its sleep
    error = "OSError" if kind == "raises" else "TimeoutError"
    assert [(e["event"], e["step"], e["error"]) for e in logs if "error" in e] == [
        ("recorder_tick_failed", "policy", error)]  # fmt: skip
    rig.sleep.go()
    await rig.sleep.parked()  # tick 2 ran
    assert rig.names[-4:] == TICK * 2 and rig.rt.health().status is HealthStatus.OK


async def test_stop_cancels_the_task_then_stops_the_writer_the_sessions_and_the_policy(
    rig: Rig,
) -> None:
    assert rig.rt.health().status is HealthStatus.STOPPED  # not started
    await rig.rt.start()
    await rig.sleep.parked()  # up, and ticking
    rig.m.writer.stop.side_effect = _hang  # a writer that never stops...
    rig.m.sessions.stop.side_effect = OSError("pg down")  # ...and sessions that cannot close
    with capture_logs() as logs:
        await asyncio.wait_for(rig.rt.stop(0.04), 2)  # each step within 10 ms, each one run
    assert rig.names[-3:] == STOP and rig.m.writer.stop.call_args.args == (0.005,)
    assert [(e["step"], e["error"]) for e in logs] == [
        ("writer", "TimeoutError"), ("sessions", "OSError")]  # fmt: skip
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "recorder-runtime"]
    assert rig.rt.health().status is HealthStatus.STOPPED
