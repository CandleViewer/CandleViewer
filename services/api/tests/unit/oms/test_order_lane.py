"""#913 slice 3 L1 (E29-T04, 29 CV-C13): the order lane, `oms_lane.OrderLane`, one daemon thread
running its own event loop; and the hops back to the serving loop, `oms_lane.Serving`, this
test's loop. No timing is asserted: each wait on the lane's thread is a bound on the test, and a
stalled serving loop is one blocked on an event."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager

import pytest
from structlog.testing import capture_logs

from candleviewer.oms_lane import LaneStopped, OrderLane, Serving
from candleviewer.statechart.gateway import Gateway, LoopAffinityError

#: A bound on each test's waits for the lane's thread, never a time the test expects.
BOUND_S = 10.0


@asynccontextmanager
async def running() -> AsyncIterator[OrderLane]:
    """A started lane, stopped after the test's body, which `BOUND_S` bounds."""
    lane = OrderLane()
    await lane.start()
    try:
        async with asyncio.timeout(BOUND_S):
            yield lane
    finally:
        await lane.stop()


async def _where() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    return asyncio.get_running_loop(), threading.current_thread()


async def _raises(error: Exception) -> None:
    raise error


async def _held(began: threading.Event, outcome: list[str], release: asyncio.Event) -> str:
    """Lane work that waits for `release`, noting a cancellation."""
    began.set()
    try:
        await release.wait()
    except asyncio.CancelledError:
        outcome.append("cancelled")
        raise
    return "kept"


async def _set(event: asyncio.Event) -> None:
    event.set()


async def _began(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, BOUND_S)


async def test_the_lane_runs_its_own_loop_on_a_daemon_thread_and_stops_it_joined_and_closed() -> (
    None
):
    refused, late = asyncio.sleep(0), asyncio.sleep(0)
    with pytest.raises(LaneStopped):
        OrderLane().call(refused)  # not started: refused, the coroutine closed
    async with running() as lane:
        loop, thread = await lane.call(_where())
        assert thread is not threading.current_thread() and thread.daemon
        assert loop is not asyncio.get_running_loop() and loop.is_running()
        began, outcome = threading.Event(), list[str]()
        left = lane.call(_held(began, outcome, asyncio.Event()))
        await _began(began)
    assert not thread.is_alive() and loop.is_closed() and outcome == ["cancelled"]  # the stop's
    with pytest.raises(asyncio.CancelledError):
        await left
    with pytest.raises(LaneStopped):
        lane.call(late)
    assert {inspect.getcoroutinestate(c) for c in (refused, late)} == {inspect.CORO_CLOSED}


async def test_call_answers_the_lanes_result_and_raises_its_error() -> None:
    async with running() as lane:
        assert await lane.call(asyncio.sleep(0, result="202")) == "202"
        with pytest.raises(ValueError, match="refused on the lane"):
            await lane.call(_raises(ValueError("refused on the lane")))


async def test_a_cancelled_caller_cancels_the_lanes_task_and_a_shielded_one_leaves_it_to_end() -> (
    None
):
    """24 Sec.8.4 step 12: the stop's cancel reaches the submit on the lane; the route's shield
    keeps it running through the client's disconnect."""
    async with running() as lane:
        began, outcome = threading.Event(), list[str]()
        cancelled = lane.call(_held(began, outcome, asyncio.Event()))
        await _began(began)
        cancelled.cancel()
        await lane.idle()  # until the lane's task has ended
        assert outcome == ["cancelled"]
        began, release = threading.Event(), asyncio.Event()
        kept = lane.call(_held(began, outcome, release))
        handler = asyncio.ensure_future(asyncio.shield(kept))
        await _began(began)
        handler.cancel()  # the client went away
        with pytest.raises(asyncio.CancelledError):
            await handler
        await lane.call(_set(release))
        assert await kept == "kept" and outcome == ["cancelled"]


async def test_a_hop_to_a_stalled_serving_loop_is_bounded_and_its_timeout_surfaces() -> None:
    """C-2.18: this loop is blocked, so neither hop can begin here: each times out on the lane, and
    neither runs once this loop turns again."""
    serving, ran, done = Serving(asyncio.get_running_loop()), list[str](), threading.Event()

    async def note() -> None:
        ran.append("call")

    async def hops() -> list[str]:
        failures = []
        try:
            await serving.call(note(), timeout_s=0)
        except TimeoutError:
            failures.append("call")
        try:
            serving.block(lambda: ran.append("block"), timeout_s=0)
        except TimeoutError:
            failures.append("block")
        done.set()
        return failures

    async with running() as lane:
        answered = lane.call(hops())
        assert done.wait(BOUND_S)  # this loop blocks meanwhile: the stall
        assert await answered == ["call", "block"]
        for _ in range(8):  # this loop turns again: neither hop runs
            await asyncio.sleep(0)
    assert ran == []


def _failing(value: str) -> None:
    raise ValueError(value)


async def test_hops_from_the_lane_land_in_order_and_a_failing_notice_is_logged() -> None:
    """A notice sent before a read lands before it (a rejected credential, then the gate); one that
    raises on the serving loop is logged by its type, never raised on the lane."""
    serving = Serving(asyncio.get_running_loop())

    async def ordered() -> list[str]:
        seen: list[str] = []
        serving.notify(seen.append, "notified")
        serving.notify(_failing, "a value never logged")
        serving.block(lambda: seen.append("read"))
        seen.append(await serving.call(asyncio.sleep(0, result="awaited")))
        return seen

    with capture_logs() as logs:
        async with running() as lane:
            assert await lane.call(ordered()) == ["notified", "read", "awaited"]
    failed = [(e["call"], e["error"]) for e in logs if e["event"] == "oms_lane_notice_failed"]
    assert failed == [("_failing", "ValueError")] and "a value never logged" not in str(logs)


class Interpreter:
    """A machine's interpreter as the gateway sends to it."""

    def __init__(self) -> None:
        self.sent: list[object] = []

    def send(self, event: object, *, wait: bool) -> Awaitable[None]:
        self.sent.append(event)
        return asyncio.sleep(0)


class Refusals:
    def record_send_refused(self, reason: str) -> None:
        raise AssertionError(reason)


async def test_a_machine_on_the_lane_takes_a_send_there_and_refuses_one_from_this_loop() -> None:
    """The gateway's loop affinity (CV-C14): a machine registered on the lane is that loop's."""
    gateway, interpreter = Gateway(), Interpreter()

    async def registered() -> None:
        gateway.register("order:1", interpreter, kind="order", lane="order", metrics=Refusals())

    async with running() as lane:
        await lane.call(registered())
        with pytest.raises(LoopAffinityError):
            await gateway.send("order:1", "EXEC")
        await lane.call(gateway.send("order:1", "EXEC"))
    assert interpreter.sent == ["EXEC"]
