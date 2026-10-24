"""The order lane (29-statechart-adoption-plan.md CV-C13; 20-architecture.md Sec.4.1 rule 1 and
Sec.6.2; E29-T04 #913 slice 3 L1): one daemon thread running its own event loop, so the OMS never
shares a loop with the platform lane. Composition root, not a module.

`OrderLane` is the thread and its loop. `OmsRuntime.start()` starts it and composes the OMS there,
and `stop()` stops it last. `call(coro)` runs a coroutine on the lane from any other loop, as
`run_coroutine_threadsafe` does, and answers an `asyncio.Future` on the caller's loop
(`wrap_future`), which the caller may shield: cancelling it cancels the lane's task, a call
cancelled before the lane begins it is closed unrun, and the lane tracks each task so the stop can
wait for them (`idle`).

`Serving` is the way back to the serving loop, the loop that started the runtime, for what is bound
to it. `call` awaits a coroutine run there; `block` waits on the lane's thread for a synchronous
call made there; `notify` makes a call there and waits for nothing. Each is bounded (C-2.18); an
answer that matters is never dropped, since `block` waits out a call that has begun. Calls from one
thread land in the order they were made. From the serving loop itself, each is a plain call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import threading
from collections.abc import Callable, Coroutine
from typing import Any, Final, Protocol

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.context import run_in_thread
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
#: serving loop to begin a synchronous call (the order-entry gate, a bundle's sink append).
BLOCK_TIMEOUT_S: Final = CV_PERSIST_TIMEOUT
#: Each step of the lane thread's own cleanup once its loop has stopped.
_CLEANUP_S: Final = LANE_JOIN_S / 5


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class LaneStopped(RuntimeError):
    """The lane is not running, before `start()` or once `stop()` has begun: nothing runs there."""


class Lane(Protocol):
    """`OrderLane` as the runtime drives it (its unit tests step a lane on their own loop)."""

    async def start(self) -> None: ...

    def call[T](self, coro: Coroutine[Any, Any, T]) -> asyncio.Future[T]: ...

    async def idle(self) -> None: ...

    async def stop(self) -> None: ...


class OrderLane:
    """The order lane: one daemon thread running its own event loop (module docstring)."""

    def __init__(self, name: str = "oms-order-lane") -> None:
        self._name = name
        #: Orders `call` against `stop`: nothing is queued on the loop once it is told to stop.
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        #: The tasks `call` began, still running; read and changed on the lane only.
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        """Start the thread, then wait off this loop, at most `LANE_START_S`, until its loop runs;
        else `LaneStopped`, the lane stopped again. A start cancelled meanwhile is `stop()`'s."""
        loop, running = asyncio.new_event_loop(), threading.Event()
        thread = threading.Thread(target=_serve, args=(loop, running), name=self._name, daemon=True)
        thread.start()
        with self._lock:
            self._loop, self._thread = loop, thread
        if not await run_in_thread(running.wait, LANE_START_S):
            await self.stop()
            raise LaneStopped("the order lane's loop did not start")

    def call[T](self, coro: Coroutine[Any, Any, T]) -> asyncio.Future[T]:
        """Run `coro` on the lane (module docstring); `LaneStopped`, the coroutine closed, when
        the lane is not running."""
        with self._lock:
            if self._loop is None:
                coro.close()
                raise LaneStopped("the order lane is not running")
            return _run_on(self._loop, coro, name=f"{self._name}-call", tasks=self._tasks)

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
            loop.call_soon_threadsafe(loop.stop)
        await run_in_thread(thread.join, LANE_JOIN_S)
        if thread.is_alive():  # a daemon: it ends with the process
            _log().error("oms_lane_not_joined", join_s=LANE_JOIN_S)


def _run_on[T](
    loop: asyncio.AbstractEventLoop,
    coro: Coroutine[Any, Any, T],
    *,
    name: str,
    tasks: set[asyncio.Task[Any]] | None = None,
) -> asyncio.Future[T]:
    """`coro` run as a task on `loop`, in the caller's context, as `run_coroutine_threadsafe`
    does, its answer a future on the caller's loop (`wrap_future`): cancelling it cancels the
    task, and a call cancelled before `loop` takes it is closed unrun. `tasks`, read and changed
    on `loop` only, holds the task while it runs."""
    answer: concurrent.futures.Future[T] = concurrent.futures.Future()
    loop.call_soon_threadsafe(_begin, coro, answer, name, tasks)
    return asyncio.wrap_future(answer)


def _begin(
    coro: Coroutine[Any, Any, Any],
    answer: concurrent.futures.Future[Any],
    name: str,
    tasks: set[asyncio.Task[Any]] | None,
) -> None:
    if answer.cancelled():  # its caller gave up before this loop took it
        coro.close()
        return
    task = spawn(coro, name=name)
    if tasks is not None:
        tasks.add(task)
    task.add_done_callback(functools.partial(_ended, answer, tasks))
    answer.add_done_callback(functools.partial(_cancel_on, task))


def _ended(
    answer: concurrent.futures.Future[Any],
    tasks: set[asyncio.Task[Any]] | None,
    task: asyncio.Task[Any],
) -> None:
    if tasks is not None:
        tasks.discard(task)
    if task.cancelled():
        answer.cancel()
    elif answer.set_running_or_notify_cancel():
        if (error := task.exception()) is not None:
            answer.set_exception(error)
        else:
            answer.set_result(task.result())


def _cancel_on(task: asyncio.Task[Any], answer: concurrent.futures.Future[Any]) -> None:
    """The caller cancelled its future, on whichever thread: the task is cancelled on its loop."""
    if answer.cancelled():
        with contextlib.suppress(RuntimeError):  # that loop has closed: nothing runs there
            task.get_loop().call_soon_threadsafe(task.cancel)


def _serve(loop: asyncio.AbstractEventLoop, running: threading.Event) -> None:
    """The lane's thread: its loop runs until `OrderLane.stop()`; then what is left on it is
    cancelled and awaited, and its async generators and executor are shut down, each bounded,
    before the loop is closed."""
    asyncio.set_event_loop(loop)
    loop.call_soon(running.set)
    try:
        loop.run_forever()
        for _ in range(3):  # a task's cleanup may start another, a few times at most
            if not (left := asyncio.all_tasks(loop)):
                break
            for task in left:
                task.cancel()
            loop.run_until_complete(asyncio.wait(left, timeout=_CLEANUP_S))
        with contextlib.suppress(TimeoutError):
            loop.run_until_complete(asyncio.wait_for(loop.shutdown_asyncgens(), _CLEANUP_S))
        with contextlib.suppress(TimeoutError):
            loop.run_until_complete(asyncio.wait_for(loop.shutdown_default_executor(), _CLEANUP_S))
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class Serving:
    """The way back from the lane to the serving loop (module docstring)."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

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
        logged."""
        noted = functools.partial(_noted, fn, args, kwargs)
        if self._here():
            noted()
            return
        try:
            self._loop.call_soon_threadsafe(noted)
        except RuntimeError:
            _log().error("oms_lane_notice_lost", call=_named(fn))


def _noted(fn: Callable[..., object], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # a notification's failure is its own, never its sender's
        _log().error("oms_lane_notice_failed", call=_named(fn), error=type(exc).__name__)


def _named(fn: Callable[..., object]) -> str:
    return str(getattr(fn, "__qualname__", type(fn).__name__))
