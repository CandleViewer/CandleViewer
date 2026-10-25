"""The order lane (29-statechart-adoption-plan.md CV-C13; 20-architecture.md Sec.4.1 rule 1 and
Sec.6.2; E29-T04 #913 slice 3 L1): one daemon thread running its own event loop, so the OMS never
shares a loop with the platform lane. Composition root, not a module.

`OrderLane` is the thread and its loop. `OmsRuntime.start()` starts it and composes the OMS there,
and `stop()` stops it last. `call(coro)` runs a coroutine on the lane from any other loop, as
`run_coroutine_threadsafe` does, and answers an `asyncio.Future` on the caller's loop
(`wrap_future`), which the caller may shield: cancelling it cancels the lane's task, a call
cancelled before the lane begins it is closed unrun, and the lane tracks each task so the stop can
wait for them (`idle`). With `timeout_s`, a call not answered by then is a `TimeoutError`, its task
cancelled. A loop that ends without `stop()` leaves the lane `dead`, logged; a call it abandoned
is cancelled before the loop closes, so no caller waits for ever. Once its stop or death has
begun, nothing begins on the lane: a call it takes then, or one whose task has not run yet, is
closed unrun, its caller answered `LaneStopped`, as `call` answers one made after.

`Serving` is the way back to the serving loop, the loop that started the runtime, for what is bound
to it. `call` awaits a coroutine run there; `block` waits on the lane's thread for a synchronous
call made there; `notify` makes a call there and waits for nothing. Each is bounded (C-2.18):
`call` and `block` by their timeouts, a notification by the lane's step rate times the serving
loop's stall (20 Sec.6.2), and one lost or failed there is logged and counted. An answer that
matters is never dropped, since `block` waits out a call that has begun. Calls from one thread
begin in the order they were made. From the serving loop itself, each is a plain call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import inspect
import threading
from collections.abc import Callable, Coroutine
from typing import Any, Final, Protocol

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.context import run_in_thread
from candleviewer.observability.metrics import MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT

#: How long the lane's loop has to start running; past it the runtime fails closed.
LANE_START_S: Final = 5.0
#: How long the stop waits for the lane's thread once its loop is told to stop, out of the OMS's
#: stop reserve (`OmsRuntime.stop`, inside the module's 15 s grace, 20 Sec.6.2).
LANE_JOIN_S: Final = 1.0
#: The bound on an awaited hop to the serving loop: B1's command bound, which every venue call's
#: own bounds are inside, so the hop never cuts one short (`oms_wiring.ServedPort`).
HOP_TIMEOUT_S: Final = CV_COMMAND_TIMEOUT
#: The bound on a blocking hop, B1's write-ahead bound: how long the lane's thread waits for the
#: serving loop to begin a synchronous call (none since #913's L2 gave the lane its own sink and L4
#: read the order-entry gate in place).
BLOCK_TIMEOUT_S: Final = CV_PERSIST_TIMEOUT
#: Each step of the lane thread's own cleanup once its loop has stopped: its five end inside
#: `LANE_JOIN_S`, so a cleanup that runs long ends before the join gives up.
_CLEANUP_S: Final = LANE_JOIN_S / 6
#: The notices to the serving loop that did not take effect, by `reason`: `lost`, or `failed`.
NOTICES_FAILED: Final = "oms_lane_notices_failed_total"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class LaneStopped(RuntimeError):
    """The lane is not running, before `start()` or once its stop or death has begun: nothing runs
    there."""


class Lane(Protocol):
    """`OrderLane` as the runtime drives it (its unit tests step a lane on their own loop)."""

    @property
    def dead(self) -> bool: ...

    async def start(self) -> None: ...

    def call[T](
        self, coro: Coroutine[Any, Any, T], *, timeout_s: float | None = None
    ) -> asyncio.Future[T]: ...

    async def idle(self) -> None: ...

    async def stop(self) -> None: ...


class OrderLane:
    """The order lane: one daemon thread running its own event loop (module docstring)."""

    #: Each start's new loop (its unit tests run the lane on uvloop as well).
    loop_factory = staticmethod(asyncio.new_event_loop)

    def __init__(self, name: str = "oms-order-lane") -> None:
        self._name = name
        #: Orders `call` against `stop`: nothing is queued on the loop once it is told to stop.
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        #: The tasks `call` began, still running, each with its caller's answer; read and changed
        #: on the lane only, until its thread cancels the answers left (`_serve`).
        self._tasks: dict[asyncio.Task[Any], concurrent.futures.Future[Any]] = {}
        self._died = threading.Event()
        #: Set, under the lock, once the stop or the death has begun: nothing begins there after.
        self._stopping = threading.Event()

    @property
    def dead(self) -> bool:
        """Its loop ended without `stop()`, logged (`_serve`): the runtime is `degraded` then."""
        return self._died.is_set()

    async def start(self) -> None:
        """Start the thread, then wait off this loop, at most `LANE_START_S`, until its loop runs;
        else `LaneStopped`, the lane stopped again. A start cancelled meanwhile is `stop()`'s. A
        lane started and not stopped since refuses another start (`RuntimeError`)."""
        with self._lock:
            if self._loop is not None:
                raise RuntimeError("the order lane is already started")
            loop, running = self.loop_factory(), threading.Event()
            self._tasks, self._died, self._stopping = {}, threading.Event(), threading.Event()
            args = (loop, running, self._tasks, self._died, self._stopping, self._lock)
            thread = threading.Thread(target=_serve, args=args, name=self._name, daemon=True)
            try:
                thread.start()
            except BaseException:  # no thread runs the loop: it is closed here
                loop.close()
                raise
            self._loop, self._thread = loop, thread
        if not await run_in_thread(running.wait, LANE_START_S):
            await self.stop()
            raise LaneStopped("the order lane's loop did not start")

    def call[T](
        self, coro: Coroutine[Any, Any, T], *, timeout_s: float | None = None
    ) -> asyncio.Future[T]:
        """Run `coro` on the lane (module docstring); `LaneStopped`, the coroutine closed, when
        the lane is not running, or `dead`. With `timeout_s`, a call not answered by then is a
        `TimeoutError`, its task on the lane cancelled, or never begun."""
        with self._lock:
            try:
                if self._loop is None or self._stopping.is_set():  # stopped, or dead (`_serve`)
                    raise LaneStopped("the order lane is not running")
                answer = _run_on(
                    self._loop, coro, name=f"{self._name}-call", tasks=self._tasks,
                    stopping=self._stopping,
                )  # fmt: skip
            except RuntimeError as exc:  # `LaneStopped`, or a loop closed by the lane's death
                coro.close()
                raise LaneStopped("the order lane is not running") from exc
        if timeout_s is None:
            return answer
        return spawn(_within(answer, timeout_s), name=f"{self._name}-bounded")

    async def idle(self) -> None:
        """Until every task `call` began has ended, the cancelled ones' unwinding included; its
        caller bounds the wait (the stop's share, `oms_wiring._closed`)."""
        await self.call(self._idle())

    async def _idle(self) -> None:
        me = asyncio.current_task()
        while pending := [task for task in self._tasks if task is not me]:
            await asyncio.wait(pending)

    async def stop(self) -> None:
        """Tell the loop to stop, then join the thread off this loop, at most `LANE_JOIN_S`; what
        is left on the lane is cancelled there first. Once begun, `call` refuses."""
        with self._lock:
            loop, thread, self._loop, self._thread = self._loop, self._thread, None, None
            if loop is None or thread is None:
                return
            self._stopping.set()
            with contextlib.suppress(RuntimeError):  # its loop has closed: the lane died
                loop.call_soon_threadsafe(loop.stop)
        await run_in_thread(thread.join, LANE_JOIN_S)
        if thread.is_alive():  # a daemon: it ends with the process
            _log().error("oms_lane_not_joined", join_s=LANE_JOIN_S)


type _Tasks = dict[asyncio.Task[Any], concurrent.futures.Future[Any]]


def _run_on[T](
    loop: asyncio.AbstractEventLoop,
    coro: Coroutine[Any, Any, T],
    *,
    name: str,
    tasks: _Tasks | None = None,
    stopping: threading.Event | None = None,
) -> asyncio.Future[T]:
    """`coro` run as a task on `loop`, in the caller's context, as `run_coroutine_threadsafe`
    does, its answer a future on the caller's loop (`wrap_future`): cancelling it cancels the
    task, and a call cancelled before `loop` takes it is closed unrun. `tasks`, read and changed
    on `loop` only, holds the task and its answer while it runs; a call `loop` takes once
    `stopping` is set is closed unrun, its caller answered `LaneStopped`."""
    answer: concurrent.futures.Future[T] = concurrent.futures.Future()
    loop.call_soon_threadsafe(_begin, coro, answer, name, tasks, stopping)
    return asyncio.wrap_future(answer)


async def _within[T](answer: asyncio.Future[T], timeout_s: float) -> T:
    """`answer` awaited at most `timeout_s`: past it, cancelled, so its call never runs on the
    lane, or is cancelled there, and the caller has a `TimeoutError`."""
    async with asyncio.timeout(timeout_s):
        return await answer


def _begin(
    coro: Coroutine[Any, Any, Any],
    answer: concurrent.futures.Future[Any],
    name: str,
    tasks: _Tasks | None,
    stopping: threading.Event | None,
) -> None:
    if stopping is not None and stopping.is_set():  # the lane stops or dies: nothing begins
        _refused(answer)
        coro.close()
        return
    if answer.cancelled():  # its caller gave up before this loop took it
        coro.close()
        return
    task = spawn(coro, name=name)
    if tasks is not None:
        tasks[task] = answer
    task.add_done_callback(functools.partial(_ended, answer, tasks))
    answer.add_done_callback(functools.partial(_cancel_on, task))


def _refused(answer: concurrent.futures.Future[Any]) -> None:
    """`answer` refused as `call` refuses a call once the lane stops or dies, `LaneStopped`, never
    a cancellation (SEC-S3L1CD-01), unless its caller has given up meanwhile."""
    if answer.set_running_or_notify_cancel():
        answer.set_exception(LaneStopped("the order lane is not running"))


def _ended(
    answer: concurrent.futures.Future[Any],
    tasks: _Tasks | None,
    task: asyncio.Task[Any],
) -> None:
    if tasks is not None:
        tasks.pop(task, None)
    error = None if task.cancelled() else task.exception()
    if task.cancelled() or not isinstance(error, Exception | None):
        answer.cancel()  # an exit (SystemExit, KeyboardInterrupt) never reaches the caller's loop
    elif answer.set_running_or_notify_cancel():
        if error is not None:
            answer.set_exception(error)
        else:
            answer.set_result(task.result())


def _cancel_on(task: asyncio.Task[Any], answer: concurrent.futures.Future[Any]) -> None:
    """The caller cancelled its future, on whichever thread: the task is cancelled on its loop."""
    if answer.cancelled():
        with contextlib.suppress(RuntimeError):  # that loop has closed: nothing runs there
            task.get_loop().call_soon_threadsafe(task.cancel)


def _cancel_left(task: asyncio.Task[Any], tasks: _Tasks) -> None:
    """The cleanup's cancel of `task`. A call whose task has not begun to run is refused first, as
    `_begin` refuses one, since nothing of it ran: uvloop runs one more turn of its loop once the
    death has begun, before `stopping` can be set, and may take a call there. A call begun is only
    cancelled: its outcome is not known."""
    answer, coro = tasks.get(task), task.get_coro()
    unrun = inspect.iscoroutine(coro) and inspect.getcoroutinestate(coro) == inspect.CORO_CREATED
    if answer is not None and unrun:
        _refused(answer)
    task.cancel()


def _run_out(loop: asyncio.AbstractEventLoop, step: Coroutine[Any, Any, Any]) -> None:
    """`step` of the cleanup run on `loop` to its end. A stop that raced the death (a failed start's
    or the lifespan's `stop()`, its `loop.stop` taken by this cleanup) ends one run early, never the
    cleanup: the next run goes on with the same step, within the same bound."""
    ran = loop.run_until_complete(_spawned(step))  # it ends in its first turn, a stop or none
    while True:
        try:
            loop.run_until_complete(ran)
        except RuntimeError:
            if ran.done():  # the step's own error, not a stop's
                raise
        else:
            return


async def _spawned(step: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """`step` spawned on the loop running this, as `spawn` needs one: it returns in its first turn,
    so a stop pending there cannot cut it short, and `_run_out` runs the task to its end."""
    return spawn(step, name="oms-order-lane-cleanup")


def _serve(
    loop: asyncio.AbstractEventLoop, running: threading.Event, tasks: _Tasks, died: threading.Event,
    stopping: threading.Event, lock: threading.Lock,
) -> None:  # fmt: skip
    """The lane's thread: its loop runs until `OrderLane.stop()`; then what is left on it is
    cancelled and awaited, and its async generators and executor are shut down, each bounded and
    run to its end, a stop that raced the death landing there or not (`_run_out`), before the loop
    is closed. A loop that ends any other way marks the lane `died`, logged, and is cleaned up the
    same way. Either way a call still unanswered is cancelled before the loop closes, so its caller
    is answered; one whose task has not run yet is refused, `LaneStopped` (`_cancel_left`). Nothing
    begins there once its loop has ended (`stopping`), and a task begun after the cleanup's last
    round is cancelled, and given a turn, all the same."""
    asyncio.set_event_loop(loop)
    loop.call_soon(running.set)
    try:
        error: str | None = None
        try:
            loop.run_forever()
        except BaseException as exc:  # nothing else watches this thread: the runtime reads `dead`
            error = type(exc).__name__
        finally:
            with lock:  # a call taken before is refused in the cleanup (`_begin`), none after
                if error is not None or not stopping.is_set():  # it ended without `stop()`
                    died.set()
                stopping.set()
        if died.is_set():  # an error out of its loop, or a stop from within it (CR-S3L1C-01)
            _log().critical("oms_lane_died", error=error)
        for _ in range(3):  # a task's cleanup may start another, a few times at most
            if not (left := asyncio.all_tasks(loop)):
                break
            for task in left:
                _cancel_left(task, tasks)
            _run_out(loop, asyncio.wait(left, timeout=_CLEANUP_S))
        with contextlib.suppress(TimeoutError):
            _run_out(loop, asyncio.wait_for(loop.shutdown_asyncgens(), _CLEANUP_S))
        with contextlib.suppress(TimeoutError):
            _run_out(loop, asyncio.wait_for(loop.shutdown_default_executor(), _CLEANUP_S))
        if late := asyncio.all_tasks(loop):  # begun after the last round: cancelled all the same
            for task in late:
                _cancel_left(task, tasks)
            _run_out(loop, asyncio.wait(late, timeout=0))
    finally:
        for answer in list(tasks.values()):  # abandoned: its caller is cancelled, never left
            answer.cancel()
        asyncio.set_event_loop(None)
        loop.close()


class Serving:
    """The way back from the lane to the serving loop (module docstring)."""

    def __init__(self, loop: asyncio.AbstractEventLoop, metrics: Metrics) -> None:
        self._loop = loop
        spec = next(spec for spec in CATALOGUE if spec.name == NOTICES_FAILED)
        notices = metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)
        self._lost, self._failed = notices.labels("lost"), notices.labels("failed")

    def _here(self) -> bool:
        try:
            return asyncio.get_running_loop() is self._loop
        except RuntimeError:  # no loop runs on this thread
            return False

    async def call[T](self, coro: Coroutine[Any, Any, T], *, timeout_s: float = HOP_TIMEOUT_S) -> T:
        """`coro` run on the serving loop and awaited, at most `timeout_s`: then `TimeoutError`,
        its run there cancelled, or never begun if the serving loop had not taken it. Cancelling
        the caller cancels it there too."""
        async with asyncio.timeout(timeout_s):
            if self._here():
                return await coro
            try:
                ran = _run_on(self._loop, coro, name="oms-serving-hop")
            except RuntimeError:  # the serving loop has closed
                coro.close()
                raise
            return await ran

    def block[T](self, fn: Callable[[], T], *, timeout_s: float = BLOCK_TIMEOUT_S) -> T:
        """`fn()` called on the serving loop while this thread waits for its answer: for a
        synchronous caller on the lane, which cannot await. `TimeoutError` when it has not begun
        within `timeout_s`, and then it never will; once begun, its own answer, however long it
        takes, so a refusal is never lost (`audit/machine_events.py`)."""
        if self._here():
            return fn()
        answer: concurrent.futures.Future[T] = concurrent.futures.Future()

        def run() -> None:
            if not answer.set_running_or_notify_cancel():
                return
            try:
                answer.set_result(fn())
            except Exception as exc:  # the waiter raises it
                answer.set_exception(exc)
            finally:
                if not answer.done():  # anything else left `fn`: the waiter is answered too
                    answer.set_exception(RuntimeError("the serving loop's call did not return"))

        self._loop.call_soon_threadsafe(run)
        try:
            return answer.result(timeout_s)
        except TimeoutError:
            if answer.cancel():
                raise
            return answer.result()

    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None:
        """`fn(*args, **kwargs)` called on the serving loop, never awaited: a notification. What
        it raises there is logged by its type; one the closed serving loop cannot take is lost,
        logged. Each such is counted (`NOTICES_FAILED`)."""
        noted = functools.partial(_noted, fn, args, kwargs, self._failed)
        if self._here():
            noted()
            return
        try:
            self._loop.call_soon_threadsafe(noted)
        except RuntimeError:
            self._lost.inc()
            _log().error("oms_lane_notice_lost", call=_named(fn))


def _noted(
    fn: Callable[..., object], args: tuple[Any, ...], kwargs: dict[str, Any], failed: MetricChild
) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # a notification's failure is its own, never its sender's
        failed.inc()
        _log().error("oms_lane_notice_failed", call=_named(fn), error=type(exc).__name__)


def _named(fn: Callable[..., object]) -> str:
    return str(getattr(fn, "__qualname__", type(fn).__name__))
