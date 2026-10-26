"""#913 slice 3 L1 (E29-T04, 29 CV-C13): the order lane, `oms_lane.OrderLane`, one daemon thread
running its own event loop; the hops back to the serving loop, `oms_lane.Serving`, this test's
loop; and the OMS runtime composed on the lane (20 Sec.6.2). No timing is asserted: each wait on
the lane's thread is a bound on the test, and a stalled serving loop is one blocked on an event."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_lane, oms_wiring
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.exits import AmendTerms, ExitCaller
from candleviewer.oms.fakes import InMemorySubmissionStore
from candleviewer.oms.order_machine import OrderMachines
from candleviewer.oms.ports import SubmitActor
from candleviewer.oms_lane import LANE_JOIN_S, LaneStopped, OrderLane, Serving
from candleviewer.oms_wiring import LANE_STALE_S
from candleviewer.settings import OMS_STOP_RESERVE_S, TEARDOWN_BUDGET_S, Settings
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.gateway import Gateway, LoopAffinityError
from candleviewer.statechart.persistence import ChainTripLatch
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import NewOrder, ScopedOrder
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms import order_rig
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.test_oms_runtime import (
    KEY,
    SENDING,
    STARTED,
    STOPPED,
    Beats,
    Port,
    Sink,
    World,
    crashed,
    failed_closed,
    failed_phases,
    started,
)

#: A bound on each test's waits for the lane's thread, never a time the test expects.
BOUND_S = 10.0


@pytest.fixture(autouse=True, params=["asyncio", "uvloop"])
def lane_loop(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-S3L1A-06 (C-13.7): each test with its lanes on asyncio's loop, then on uvloop, as
    `test_request_header_deadline_real_socket` runs its loops; skipped where uvloop is missing."""
    if request.param == "uvloop":
        new_loop = pytest.importorskip("uvloop").new_event_loop
        monkeypatch.setattr(OrderLane, "loop_factory", staticmethod(new_loop))


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


async def _awaited(future: Awaitable[Any]) -> Any:
    return await future


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
    """C-2.18: this loop is blocked, so the hop cannot begin here: it times out on the lane, and it
    does not run once this loop turns again."""
    serving = Serving(asyncio.get_running_loop(), Metrics("demo"))
    ran, done = list[str](), threading.Event()

    async def note() -> None:
        ran.append("call")

    async def hops() -> list[str]:
        failures = []
        try:
            await serving.call(note(), timeout_s=0)
        except TimeoutError:
            failures.append("call")
        done.set()
        return failures

    async with running() as lane:
        answered = lane.call(hops())
        assert done.wait(BOUND_S)  # this loop blocks meanwhile: the stall
        assert await answered == ["call"]
        for _ in range(8):  # this loop turns again: the hop does not run
            await asyncio.sleep(0)
    assert ran == []


def _failing(value: str) -> None:
    raise ValueError(value)


async def test_hops_from_the_lane_land_in_order_and_a_failing_notice_is_logged() -> None:
    """A notice sent before an awaited hop lands before it (a rejected credential, then a profile
    read); one that raises on the serving loop is logged by its type, never raised on the lane, and
    one the closed serving loop cannot take is logged as lost; each is counted (CR-S3L1A-01)."""
    metrics, closed = Metrics("demo"), asyncio.new_event_loop()
    serving = Serving(asyncio.get_running_loop(), metrics)

    async def ordered() -> list[str]:
        seen: list[str] = []
        serving.notify(seen.append, "notified")
        serving.notify(_failing, "a value never logged")
        seen.append(await serving.call(asyncio.sleep(0, result="awaited")))
        return seen

    closed.close()
    with capture_logs() as logs:
        async with running() as lane:
            assert await lane.call(ordered()) == ["notified", "awaited"]
        Serving(closed, metrics).notify(_failing, "a value never logged")
    failed = [(e["call"], e["error"]) for e in logs if e["event"] == "oms_lane_notice_failed"]
    assert failed == [("_failing", "ValueError")] and "a value never logged" not in str(logs)
    assert [e["call"] for e in logs if e["event"] == "oms_lane_notice_lost"] == ["_failing"]
    assert (_counted(metrics, "failed"), _counted(metrics, "lost")) == (1, 1)


def _counted(metrics: Metrics, reason: str) -> float | None:
    labels = {"env": "demo", "reason": reason}
    return metrics.registry.get_sample_value("oms_lane_notices_failed_total", labels)


async def test_idle_waits_until_every_call_the_lane_began_has_ended() -> None:
    """CR-S3L1A-06: what the stop's wait on the lane rests on (`oms_wiring._closed`)."""
    async with running() as lane:
        began, release = threading.Event(), asyncio.Event()
        held = lane.call(_held(began, [], release))
        await _began(began)
        idle = asyncio.ensure_future(lane.idle())
        await asyncio.sleep(0)  # its first step: its call reaches the lane before the next
        await lane.call(asyncio.sleep(0))  # a round trip: the lane began the wait before it
        assert not idle.done()
        await lane.call(_set(release))
        await idle
        assert held.result() == "kept"


async def test_a_wedged_lane_times_a_bounded_call_out_and_its_stop_logs_it_unjoined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3L1A-02/-06: with the lane's thread blocked, a call with `timeout_s` is a `TimeoutError`
    here and closed unrun there once the lane turns again; the stop cannot join it and logs so."""
    monkeypatch.setattr(oms_lane, "LANE_JOIN_S", 0.0)
    began, release, ran = threading.Event(), threading.Event(), asyncio.Event()

    async def wedge() -> None:
        began.set()
        release.wait(BOUND_S)

    lane, unrun = OrderLane(), _set(ran)
    await lane.start()
    _, thread = await lane.call(_where())
    lane.call(wedge())
    await _began(began)
    with pytest.raises(TimeoutError):
        await lane.call(unrun, timeout_s=0)
    with capture_logs() as logs:
        await lane.stop()
    release.set()
    await asyncio.to_thread(thread.join, BOUND_S)
    assert [e["join_s"] for e in logs if e["event"] == "oms_lane_not_joined"] == [0.0]
    assert not (thread.is_alive() or ran.is_set())
    assert inspect.getcoroutinestate(unrun) == inspect.CORO_CLOSED


async def test_a_lane_whose_loop_dies_is_marked_dead_and_answers_its_callers() -> None:
    """CR-S3L1A-02/-03: an error out of the lane's loop (`SystemExit` from its task) is logged and
    marks the lane dead; the call it abandoned is cancelled, so no caller waits for ever; a later
    call is `LaneStopped`, closed unrun. Its cleanup ends inside the join's bound."""

    async def exits() -> None:
        raise SystemExit

    lane, late = OrderLane(), asyncio.sleep(0)
    await lane.start()
    _, thread = await lane.call(_where())
    with capture_logs() as logs:
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(BOUND_S):
                await lane.call(exits())
        await asyncio.to_thread(thread.join, BOUND_S)  # its thread has ended: the lane has died
    with pytest.raises(LaneStopped):
        lane.call(late)
    await lane.stop()
    assert lane.dead and [e["error"] for e in logs if e["event"] == "oms_lane_died"] == [
        "SystemExit"
    ]
    assert inspect.getcoroutinestate(late) == inspect.CORO_CLOSED
    assert 5 * oms_lane._CLEANUP_S < oms_lane.LANE_JOIN_S


async def test_a_lane_whose_loop_is_stopped_from_within_has_died_and_refuses_calls_at_once() -> (
    None
):
    """CR-S3L1C-01: a loop stopped by anything but `OrderLane.stop()`, here by a call on the lane,
    has died as one an error ends has: `dead`, logged once, and paged once however often the
    runtime reads its state. A call made while its cleanup runs is refused at once, `LaneStopped`,
    never queued there, as one made after it is, each closed unrun."""
    held, release, calls = threading.Event(), threading.Event(), [asyncio.sleep(0) for _ in "ab"]

    async def stops() -> None:
        asyncio.get_running_loop().stop()
        try:
            await asyncio.Event().wait()
        finally:  # the cleanup's cancel: the lane's thread is held while this test calls
            held.set()
            release.wait(BOUND_S)

    lane, world = OrderLane(), World()
    await lane.start()
    _, thread = await lane.call(_where())
    with capture_logs() as logs:
        stopped = lane.call(stops())
        await _began(held)
        with pytest.raises(LaneStopped):
            lane.call(calls[0])
        release.set()
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(BOUND_S):
                await stopped
        await asyncio.to_thread(thread.join, BOUND_S)
    with pytest.raises(LaneStopped):
        lane.call(calls[1])
    runtime, parts = world.runtime(), SimpleNamespace(lane=lane)
    runtime._parts = cast(Any, parts)  # the runtime's reads of its lane's state, nothing composed
    assert [runtime.state for _ in range(3)] == ["degraded"] * 3
    await lane.stop()
    assert lane.dead and world.pager.calls == ["oms_lane_died"]
    assert [e["error"] for e in logs if e["event"] == "oms_lane_died"] == [None]
    assert {inspect.getcoroutinestate(c) for c in calls} == {inspect.CORO_CLOSED}


async def test_a_call_racing_the_lanes_death_never_begins_and_is_refused_as_stopped() -> None:
    """SEC-S3L1A-01, SEC-S3L1CD-01 (C-2.18): a call made as the lane's loop dies, past the death's
    check, never runs: the cleanup refuses it as `call` refuses one made after it (uvloop takes it
    in one more turn of its loop, and the cleanup's cancel round refuses it), `LaneStopped`, never
    a cancellation, so the route's read and its submit are `oms_not_ready` (503), and the coroutine
    is closed unrun. The call the death abandoned is cancelled."""
    began, go, ran = threading.Event(), threading.Event(), list[str]()

    async def exits() -> None:
        began.set()
        go.wait(BOUND_S)  # the lane's thread is held: the racing calls are queued meanwhile
        raise SystemExit

    async def racing() -> None:
        ran.append("a step")

    lane, raced = OrderLane(), [racing() for _ in range(3)]
    await lane.start()
    _, thread = await lane.call(_where())
    abandoned = lane.call(exits())
    await _began(began)
    parts: Any = SimpleNamespace(lane=lane)
    refused: list[Awaitable[Any]] = [
        lane.call(raced[0]),
        asyncio.ensure_future(oms_wiring._on_lane(parts, raced[1])),  # a read, bounded
        asyncio.ensure_future(oms_wiring._on_lane(parts, raced[2], None)),  # the submit
    ]
    await asyncio.sleep(0)  # the route's first steps: their calls are queued on the lane
    go.set()
    for answer, error in zip(refused, (LaneStopped, OmsNotReady, OmsNotReady), strict=True):
        with pytest.raises(error):
            async with asyncio.timeout(BOUND_S):
                await answer
    with pytest.raises(asyncio.CancelledError):  # an exit never reaches this loop
        async with asyncio.timeout(BOUND_S):
            await abandoned
    await asyncio.to_thread(thread.join, BOUND_S)
    await lane.stop()
    assert lane.dead and ran == []
    assert {inspect.getcoroutinestate(c) for c in raced} == {inspect.CORO_CLOSED}


async def test_a_call_racing_the_lanes_stop_never_begins_and_is_refused_as_stopped() -> None:
    """SEC-S3L1CD-01: a call taken just before the stop began, which the lane reaches only after,
    is refused as `LaneStopped`, never begun nor cancelled; the call it had begun ends as it would
    have."""
    began, go, ran = threading.Event(), threading.Event(), list[str]()

    async def held() -> str:
        began.set()
        go.wait(BOUND_S)  # the lane's thread is held: the call and the stop are queued meanwhile
        return "kept"

    async def racing() -> None:
        ran.append("a step")

    lane, raced = OrderLane(), racing()
    await lane.start()
    kept = lane.call(held())
    await _began(began)
    refused = lane.call(raced)
    stop = asyncio.ensure_future(lane.stop())
    await asyncio.sleep(0)  # its first step: the stop has begun, the lane's loop told to stop
    go.set()
    async with asyncio.timeout(BOUND_S):
        await stop
        assert await kept == "kept"
        with pytest.raises(LaneStopped):
            await refused
    assert not lane.dead and ran == [] and inspect.getcoroutinestate(raced) == inspect.CORO_CLOSED


async def test_a_task_the_cleanup_begins_after_its_last_round_is_cancelled_before_the_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S3L1A-01: a task begun on the lane after its cleanup's last cancel round (here, by its
    executor's shutdown) is cancelled, and given a turn, before the loop closes."""
    factory, outcome = OrderLane.loop_factory, list[str]()

    async def lingers() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            outcome.append("cancelled")
            raise

    def made() -> asyncio.AbstractEventLoop:
        loop, late = factory(), list[asyncio.Future[None]]()
        shutdown = loop.shutdown_default_executor

        async def begins(*args: Any) -> None:
            late.append(asyncio.ensure_future(lingers()))
            await asyncio.sleep(0)  # it has begun: it waits, past every round
            await shutdown(*args)

        monkeypatch.setattr(loop, "shutdown_default_executor", begins)
        return loop

    monkeypatch.setattr(OrderLane, "loop_factory", staticmethod(made))
    async with running():
        pass
    assert outcome == ["cancelled"]


async def test_a_stop_landing_in_the_dying_lanes_cleanup_never_cuts_it_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S3L1CD-01: a failed start or a stop that races the lane's death stops its loop while the
    death's cleanup runs it, as here from within that cleanup; the cleanup runs each of its steps
    to the end all the same, and nothing escapes the lane's thread."""
    factory, steps = OrderLane.loop_factory, list[str]()

    def made() -> asyncio.AbstractEventLoop:
        loop = factory()
        asyncgens, executor = loop.shutdown_asyncgens, loop.shutdown_default_executor

        async def stopped() -> None:
            loop.stop()  # the stop that raced the death, taken by its cleanup
            for _ in range(2):  # past the turn that stop ends
                await asyncio.sleep(0)
            await asyncgens()
            steps.append("asyncgens")

        async def shut(*args: Any) -> None:
            await executor(*args)
            steps.append("executor")

        monkeypatch.setattr(loop, "shutdown_asyncgens", stopped)
        monkeypatch.setattr(loop, "shutdown_default_executor", shut)
        return loop

    async def exits() -> None:
        raise SystemExit

    monkeypatch.setattr(OrderLane, "loop_factory", staticmethod(made))
    monkeypatch.setattr(oms_lane, "_CLEANUP_S", BOUND_S)  # no step runs out under load
    lane = OrderLane()
    await lane.start()
    _, thread = await lane.call(_where())
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(BOUND_S):
            await lane.call(exits())
    await asyncio.to_thread(thread.join, BOUND_S)
    await lane.stop()
    assert lane.dead and not thread.is_alive() and steps == ["asyncgens", "executor"]


async def test_start_refuses_a_started_lane_and_fails_closed_on_a_loop_that_never_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3L1A-04/-06: a started lane refuses a second start. Past `LANE_START_S` with its loop
    not running, the lane is stopped again, its loop closed, and takes nothing; a thread that
    cannot start leaves its loop closed."""
    serve, loops = oms_lane._serve, list[asyncio.AbstractEventLoop]()

    def mute(loop: asyncio.AbstractEventLoop, _running: threading.Event, *rest: Any) -> None:
        loops.append(loop)  # it runs its loop and never says so
        serve(loop, threading.Event(), *rest)

    class Unstartable(threading.Thread):
        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    async with running() as lane:
        with pytest.raises(RuntimeError, match="already started"):
            await lane.start()
        assert await lane.call(asyncio.sleep(0, result="kept")) == "kept"
    monkeypatch.setattr(oms_lane, "_serve", mute)
    monkeypatch.setattr(oms_lane, "LANE_START_S", 0.0)
    lane, late = OrderLane(), asyncio.sleep(0)
    with pytest.raises(LaneStopped, match="did not start"):
        await lane.start()
    with pytest.raises(LaneStopped):
        lane.call(late)
    loops.append(asyncio.new_event_loop())
    monkeypatch.setattr(OrderLane, "loop_factory", staticmethod(lambda: loops[-1]))
    threads = SimpleNamespace(Event=threading.Event, Lock=threading.Lock, Thread=Unstartable)
    monkeypatch.setattr(oms_lane, "threading", threads)
    with pytest.raises(RuntimeError, match="new thread"):
        await OrderLane().start()
    assert [loop.is_closed() for loop in loops] == [True, True]
    assert inspect.getcoroutinestate(late) == inspect.CORO_CLOSED


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


def _noting(real: Any, threads: list[threading.Thread]) -> Any:
    async def noted(self: Port, req: Any) -> Any:
        threads.append(threading.current_thread())
        return await real(self, req)

    return noted


def _logged(real: Any, entry: str, log: list[str]) -> Any:
    async def logged(self: Any) -> Any:
        log.append(entry)
        return await real(self)

    return logged


async def test_the_oms_runs_on_the_lane_and_its_stop_drains_cancels_closes_and_joins_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 Sec.6.2 on `OrderLane`: the sweep resumes a create left at the venue's door, whose venue
    call runs on the lane, through its own port (#913 L1d-1); the facade's machine refuses a send
    from this loop; the route's reads answer from the lane. The stop drains (its bound spent at once
    here), cancels a submit still on the lane and waits there for its unwinding, which ends only
    once that wait has begun, before the machines and the commands close (CR-S3L1B-06), then stops
    the lane: its closers' deadline leaves `LANE_JOIN_S` of the reserve for the join."""
    drains, reserves, threads = list[float](), list[float](), list[threading.Thread]()
    drained, closed, idle = oms_wiring._drained, oms_wiring._closed, OrderLane._idle
    idling = asyncio.Event()  # the stop's wait on the lane has begun

    async def spent(tasks: set[asyncio.Task[Any]], timeout_s: float) -> set[asyncio.Task[Any]]:
        drains.append(timeout_s)
        return await drained(tasks, 0)

    async def timed(closers: Any, deadline: float) -> None:
        reserves.append(deadline - asyncio.get_running_loop().time())
        await closed(closers, deadline)

    async def waits(self: OrderLane) -> None:
        idling.set()
        await idle(self)

    async def unwinds(began: threading.Event) -> None:
        began.set()
        try:
            await asyncio.Event().wait()
        finally:  # a slow unwind: it ends once the stop waits on the lane
            await idling.wait()
            world.log.append("unwound")

    monkeypatch.setattr(oms_wiring, "_drained", spent)
    monkeypatch.setattr(oms_wiring, "_closed", timed)
    monkeypatch.setattr(OrderLane, "_idle", waits)
    monkeypatch.setattr(Port, "place_order", _noting(Port.place_order, threads))
    world = World()
    await crashed(world)
    spied = {(OrderMachines, "stop"): "machines", (OmsCommandPort, "aclose"): "commands"}
    for (owner, name), entry in spied.items():  # after the crash: its own facade stops unlogged
        monkeypatch.setattr(owner, name, _logged(getattr(owner, name), entry, world.log))
    for flag in world.flags:
        flag.read()
    async with asyncio.timeout(BOUND_S), started(world.runtime(lane=OrderLane)) as runtime:
        await runtime.wait_ready()
        parts = runtime._composed()
        loop, thread = await parts.lane.call(_where())
        resumed = parts.machines.settled(
            cr.ACCOUNT, SENDING.id, leaving="submitting", timeout_s=BOUND_S
        )
        assert await parts.lane.call(resumed) == "submitted"
        assert threads == [thread]  # R1: the create went out on the lane (#913 L1d-1)
        with pytest.raises(LoopAffinityError):
            await parts.machines._gateway.send(str(SENDING.id), "KILL")
        assert await runtime.route.accounts.environment_of(cr.ACCOUNT) == "demo"
        began = threading.Event()
        answered = runtime.run(_awaited(parts.lane.call(asyncio.sleep(0, result="202"))))
        hung = runtime.run(_awaited(parts.lane.call(unwinds(began))))
        assert await answered == "202"
        await _began(began)
    assert drains == [Settings().oms_drain_s] and hung.cancelled()
    reserve = OMS_STOP_RESERVE_S - LANE_JOIN_S
    assert reserve - 1 < reserves[-1] <= reserve  # the join's share is the reserve's last
    assert Settings().oms_drain_s + OMS_STOP_RESERVE_S <= TEARDOWN_BUDGET_S  # the 15 s grace
    assert not thread.is_alive() and loop.is_closed() and not b01.ports_wired()
    unwound = [*STARTED, "unwound", "machines", "commands", *STOPPED]
    assert world.log == unwound and world.venue.ports[0].closed


async def test_an_amend_runs_on_the_lane_while_this_loop_is_blocked_and_reads_its_profile_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#913 slice 4 on the lane (the orchestrator's ruling of 2026-10-25 02:50Z): the route's call
    hands the amend to the lane, which reads the order's instrument there while this loop is
    blocked. A price move is risk-increasing, so the amend reads its profile through the
    pipeline's `ServedProfiles`, on this loop (OM-D10's named residual), and its venue call runs on
    the lane, through the lane's own port (#913 L1d-1); it answers once this loop turns again:
    accepted, the order `submitted`."""
    reads, sent = list[tuple[str, threading.Thread]](), list[threading.Thread]()
    listed, read_profile = threading.Event(), sr.Profiles.get_effective_profile

    async def profile(
        self: sr.Profiles, account_id: UUID, profile_id: UUID | None = None
    ) -> AccountProfile:
        reads.append(("profile", threading.current_thread()))
        return await read_profile(self, account_id, profile_id)

    def snapshot() -> dict[str, Instrument]:
        reads.append(("instrument", threading.current_thread()))
        listed.set()
        return {cr.SYMBOL: sr.instrument()}

    monkeypatch.setattr(sr.Profiles, "get_effective_profile", profile)
    monkeypatch.setattr(Port, "amend_order", _noting(Port.amend_order, sent))
    world, owner = World(), UUID(int=0x0E)
    world.ingestion.instruments = SimpleNamespace(snapshot=snapshot)
    await crashed(world)
    world.store.seed_owner(owner)
    for flag in world.flags:
        flag.read()
    caller = ExitCaller(OwnerScope(owner), SubmitActor(user_id=owner, role="owner"))
    async with asyncio.timeout(BOUND_S), started(world.runtime(lane=OrderLane)) as runtime:
        await runtime.wait_ready()
        parts = runtime._composed()
        _, on_lane = await parts.lane.call(_where())
        resumed = parts.machines.settled(
            cr.ACCOUNT, SENDING.id, leaving="submitting", timeout_s=BOUND_S
        )
        assert await parts.lane.call(resumed) == "submitted"
        scoped = await runtime.exits.scope(caller, SENDING.id)
        assert isinstance(scoped, ScopedOrder)
        moved = AmendTerms(price=Decimal("61000"))
        amend = runtime.exits.amend(scoped, moved, caller=caller, expected_seq=None)
        amended = asyncio.ensure_future(amend)
        await asyncio.sleep(0)  # the route's task hands the amend to the lane
        assert listed.wait(BOUND_S)  # this loop blocks meanwhile: the lane reads the instrument
        got = await amended
    here = threading.current_thread()
    assert (got.kind, got.status, got.lifecycle_state) == ("accepted", 202, "submitted")
    assert reads == [("instrument", on_lane), ("profile", here)] and sent == [on_lane]  # R2


async def test_a_cancelled_start_lets_the_compose_close_on_the_lane_before_the_lane_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3L1B-03: the start is cancelled while the sink starts on the lane; the compose closes the
    lane's audit writer (#913 L2), the port and the pool and unwires B1's ports there, and only then
    is the lane stopped."""
    world, began, stop = World(), threading.Event(), OrderLane.stop

    async def hangs(self: Sink) -> None:
        began.set()
        await asyncio.Event().wait()

    async def stops(self: OrderLane) -> None:
        world.log.append("lane.stop")
        await stop(self)

    monkeypatch.setattr(Sink, "start", hangs)
    monkeypatch.setattr(OrderLane, "stop", stops)
    start = asyncio.ensure_future(world.runtime(lane=OrderLane).start())
    await _began(began)
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    unwound = ["audit.stop", "pool.release", "lock.release", "lane.stop"]
    assert world.log == ["lock.acquire", "audit.start", *unwound] and world.venue.ports[0].closed
    assert not b01.ports_wired()


async def test_a_start_cancelled_again_while_the_compose_closes_still_stops_its_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S3L1C-01: the start, cancelled while the sink starts on the lane, is cancelled again
    while it waits there for the compose to close the trading port; the lane is still stopped."""
    world, began, closing = World(), threading.Event(), threading.Event()

    async def hangs(self: Any) -> None:
        (closing if isinstance(self, Port) else began).set()
        await asyncio.Event().wait()

    monkeypatch.setattr(Sink, "start", hangs)
    monkeypatch.setattr(Port, "aclose", hangs)  # the compose's unwind, held on this loop
    monkeypatch.setattr(OrderLane, "stop", _logged(OrderLane.stop, "lane.stop", world.log))
    monkeypatch.setattr(oms_wiring, "OMS_STOP_RESERVE_S", 10 * BOUND_S)  # no share runs out
    start = asyncio.ensure_future(world.runtime(lane=OrderLane).start())
    for event in (began, closing):
        await _began(event)
        start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    # the lane's writer, the pool and the lock close after the port and its signing (#913 L1d), so
    # the hung port's close holds them; the lane's stop ends its tasks
    assert world.log == ["lock.acquire", "audit.start", "lane.stop"] and not b01.ports_wired()


def _dying_at(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """SEC-S3L1CD-01: `OrderLane.call`, but the lane's loop dies as it takes the call to `name`, a
    coroutine's qualified name: its thread is held while the call passes the death's check and is
    queued, then the loop dies before it begins the call."""
    call = OrderLane.call

    def dies(go: threading.Event) -> None:
        go.wait(BOUND_S)
        raise SystemExit

    def racing(
        self: OrderLane, coro: Coroutine[Any, Any, Any], *, timeout_s: float | None = None
    ) -> asyncio.Future[Any]:
        if getattr(coro, "__qualname__", None) != name:
            return call(self, coro, timeout_s=timeout_s)
        go, loop = threading.Event(), self._loop
        assert loop is not None
        loop.call_soon_threadsafe(dies, go)
        try:
            return call(self, coro, timeout_s=timeout_s)
        finally:
            go.set()

    monkeypatch.setattr(OrderLane, "call", racing)


async def test_a_closer_the_dying_lane_refuses_leaves_the_closers_after_it_to_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S3L1CD-01: the lane dies as the stop calls the sink's close there, once the machines and
    the commands have closed. That closer is refused, `LaneStopped`, logged, and the ones after it
    still run: the lane's audit writer's is refused in turn (#913 L2), the trading port closes on
    this loop, the pool's, the heartbeat's and the environment lock's are refused too, and the stop
    ends, not cancelled."""
    _dying_at(monkeypatch, "Sink.stop")
    world = World()
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND_S), started(world.runtime(lane=OrderLane)):
            pass
    steps = [(e["step"], e["error"]) for e in logs if e["event"] == "oms_stop_step_failed"]
    refused = ["sink", "audit", "pool", "heartbeat", "environment_lock"]
    assert steps == [(step, "LaneStopped") for step in refused]
    assert world.venue.ports[0].closed and not b01.ports_wired()
    assert world.log == [*STARTED, "heartbeat.end"]  # the death's cleanup ended the heartbeat
    assert [e["error"] for e in logs if e["event"] == "oms_lane_died"] == ["SystemExit"]


async def test_a_lane_dying_as_the_start_calls_the_compose_fails_the_start_closed_and_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S3L1CD-01: the lane dies as the start calls the compose there, which is refused,
    `LaneStopped`, never begun: a failed start, logged by its phase, paged and `degraded`, nothing
    composed or wired; not a cancelled start, which would page nothing."""
    _dying_at(monkeypatch, "OmsRuntime._compose")
    world = World()
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND_S), started(world.runtime(lane=OrderLane)) as runtime:
            assert runtime.state == "degraded"
    assert (failed_closed(logs), failed_phases(logs)) == (["LaneStopped"], ["lane"])
    assert world.pager.calls == ["oms_runtime_failed_closed: lane"]
    assert world.venue.ports == [] and not b01.ports_wired()


# --- order turns on the lane, the serving loop blocked (#913 L2; the stall test's setup) ----------


def exit_order(seq: int) -> NewOrder:
    """A reduce-only limit sell: its fills start no stop (INV-B1-o), so an `EXEC` of it reads
    and sends nothing at the venue. A short id, so its ack's exchange id (`x<id>`, `placed`)
    passes the exchange-answer redactor that a 39-digit one does not."""
    return cr.new_order(
        seq=seq, id=UUID(int=seq), side="Sell", intent="scale_out", reduce_only=True,
        stop_loss=None, take_profit=None,
    )  # fmt: skip


async def hydrating(world: World, n: int) -> list[NewOrder]:
    """A first process that went down with `n` reduce-only orders `submitted`, each acked, as
    `crashed` leaves its two: the runtime's sweep hydrates them all."""
    store, saved = world.store, b01._ATTEMPTS
    InMemorySubmissionStore(store).seed_account(cr.ref())
    world.accounts.append(TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], False, KEY))
    b01._ATTEMPTS = OrderedDict()
    rig, orders = order_rig.build_rig(store), [exit_order(1000 + i) for i in range(n)]
    try:
        for order in orders:
            await rig.facade.start(order, environment="demo", gates=order_rig.GATES)
            await rig.facade.command(cr.ACCOUNT, order.id, "SEND", actor="user")
        await rig.quiet()
        assert {rig.facade.state(order.id)[0] for order in orders} == {"submitted"}
    finally:
        await rig.facade.stop()
        b01._ATTEMPTS = saved
    return orders


async def validated(machines: OrderMachines, n: int) -> list[NewOrder]:
    """`n` entries started and left `validated`, never sent: each takes an abandon."""
    entries = [cr.new_order(seq=2000 + i) for i in range(n)]
    for entry in entries:
        await machines.start(entry, environment="demo", gates=order_rig.GATES)
    return entries


async def turns(
    machines: OrderMachines,
    exits: Sequence[NewOrder],
    entries: Sequence[NewOrder],
    clock: Callable[[], float],
) -> list[tuple[float, float]]:
    """The order turns, in turn: an `EXEC` of each exit, a partial fill, and an abandon of each
    entry from `validated`; neither calls the venue. Each is timed on `clock` from its send to its
    committed step, its event, sink rows and audit record included: (sent, committed)."""
    spans = list[tuple[float, float]]()
    for exit_, entry in zip(exits, entries, strict=True):
        fill = order_rig.fill_of(
            exit_, f"e{exit_.id.int % 10**6}", "0.004", account_id=str(cr.ACCOUNT), side="sell"
        )
        sent = clock()
        await machines.push(cr.ACCOUNT, exit_.id, "EXEC", fill)
        spans.append((sent, clock()))
        sent = clock()
        await machines.abandon(cr.ACCOUNT, entry.id, "lane_isolation")
        spans.append((sent, clock()))
    return spans


async def _when(began: threading.Event) -> None:
    assert await asyncio.to_thread(began.wait, BOUND_S)


@pytest.mark.parametrize("bundled", [False, True])
async def test_order_turns_on_the_lane_need_no_turn_of_the_blocked_serving_loop(
    bundled: bool,
) -> None:
    """#913 L2 (29 CV-C13; rulings Q12, Q13): with this loop blocked, the lane takes an `EXEC` of
    each hydrated order and abandons as many `validated` ones, each recorded by the lane's own
    audit writer and written ahead to its own sink, beside a bundle's or not: the lane releases
    this loop's block once every turn has committed. A turn that waited on this loop, an audit or
    sink hop among them, would leave the block to its bound. No timing is asserted (the stall
    test's numbers are `test_order_lane_isolation`'s)."""
    world, count = World(), 8
    exits = await hydrating(world, count)
    bundle = SimpleNamespace(sink=InMemoryMachineEventSink(), latch=ChainTripLatch())
    for flag in world.flags:
        flag.read()
    runtime = world.runtime(lane=OrderLane, bundle=bundle if bundled else None)
    async with asyncio.timeout(3 * BOUND_S), started(runtime):
        await runtime.wait_ready()
        parts = runtime._composed()
        entries = await parts.lane.call(validated(parts.machines, count))
        blocked, ended = threading.Event(), threading.Event()

        async def driven() -> list[tuple[float, float]]:
            await _when(blocked)
            try:
                return await turns(parts.machines, exits, entries, lambda: 0.0)
            finally:
                ended.set()

        taken = parts.lane.call(driven())
        blocked.set()
        released = ended.wait(BOUND_S)  # this loop blocks meanwhile
        assert released and len(await taken) == 2 * count
    states = {world.store._orders[order.id].lifecycle_state for order in (*exits, *entries)}
    assert states == {"partially_filled", "killed"}
    killed = ("orders.cancel", "kill_no_cancel_unsubmitted")
    assert world.writer.actions.count(killed) == count
    [sink] = world.sinks
    assert sink.rows and bundle.sink.rows == []


async def _ticked(beats: Beats) -> None:
    """One more tick of the lane's heartbeat, let go on the lane's loop, where it waits."""
    beats.tick()
    for _ in range(8):
        await asyncio.sleep(0)


async def test_a_wedged_lane_reads_degraded_and_pages_once_until_it_ticks_again() -> None:
    """Ruling 2 (OM-D12's wedged lane; CR-S3L1A-02), the lane heartbeat's stall test, on
    `OrderLane`: a call that holds the lane's own thread, as a begun `block` whose serving-loop call
    never returns does, stops the heartbeat; once its last tick is past `LANE_STALE_S` the runtime
    reads `degraded` and pages once, though `OrderLane.dead` stays false; once the lane turns and
    ticks again it reads `ok`. No timing: the heartbeat's clock is the test's."""
    world, wedged, freed = World(), threading.Event(), threading.Event()
    for flag in world.flags:
        flag.read()

    async def wedge() -> None:
        wedged.set()
        freed.wait(BOUND_S)  # holds the lane's thread: nothing else runs there meanwhile

    async with asyncio.timeout(3 * BOUND_S), started(world.runtime(lane=OrderLane)) as runtime:
        await runtime.wait_ready()
        parts = runtime._composed()
        stuck = parts.lane.call(wedge())
        await _began(wedged)
        world.beats.s += LANE_STALE_S + 0.001
        assert [runtime.state for _ in range(2)] == ["degraded"] * 2 and not parts.lane.dead
        freed.set()
        await stuck
        await parts.lane.call(_ticked(world.beats))
        assert runtime.state == "ok"
    assert world.pager.calls == ["oms_lane_stalled"]
