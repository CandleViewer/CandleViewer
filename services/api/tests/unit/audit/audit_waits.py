"""Waits for the audit unit tests that never read the wall clock (C-13.7; #3654, #3709).

`guarded()` awaits an event unless a watched task (a writer's flusher, a lane's drain) ends first;
then it raises at once, with that task's failure as the cause, instead of waiting for an event that
cannot come any more.

`VirtualTimeLoop` is an event loop on a fake clock. The clock stands still while a callback is
ready or a job runs on the loop's default executor, and moves to the next timer only when the loop
would otherwise block. Every `asyncio.timeout`, `sleep` and `wait_for`, in a test and in the code
under test, then runs on fake seconds: a deadline passes when nothing else can happen, never
because the runner is slow. `idle()` resolves at the next point where nothing is ready; a loop with
nothing ready, nothing scheduled and no thread job in flight raises `VirtualClockDeadlock` instead
of blocking for ever. `virtual` runs an `async def` test on a fresh one."""

from __future__ import annotations

import asyncio
import functools
import selectors
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from candleviewer.observability.context import spawn


class TaskEnded(AssertionError):
    """A watched task ended before the awaited event; what it raised is the `__cause__`."""


async def guarded[T](awaitable: Coroutine[Any, Any, T], *watch: asyncio.Task[Any] | None) -> T:
    """Await `awaitable`, unless a task in `watch` ends first, even before the call: then raise
    `TaskEnded` from what it raised, if anything. The event wins a tie: `awaitable` runs in a task
    `spawn()` starts, whose first step comes before the race is judged, so a flusher that set its
    alarm and died, before the call or inside the wait, counts as the event."""
    tasks = {task for task in watch if task is not None}
    if not tasks:
        return await awaitable
    waiter = spawn(awaitable, name="guarded")
    try:
        await asyncio.wait({waiter, *tasks}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not waiter.done():
            waiter.cancel()
    if waiter.done():
        return waiter.result()
    ended = next(task for task in tasks if task.done())
    cause = None if ended.cancelled() else ended.exception()
    raise TaskEnded(f"{ended.get_name()} ended before the awaited event") from cause


class VirtualClockDeadlock(RuntimeError):
    """Nothing is ready, nothing is scheduled and no thread job is in flight; or idle waiters keep
    waking with nothing else moving."""


#: Tellings of the idle waiters in a row, with neither the clock moving nor a job landing, before
#: the loop gives up: far more than a test's own chain of steps, far fewer than a spin would make.
_MAX_TOLD = 100_000


class _Selector(selectors.BaseSelector):
    """The loop's selector: `select()` moves the fake clock where the real one would block."""

    def __init__(self) -> None:
        self._real = selectors.DefaultSelector()
        self.loop: VirtualTimeLoop | None = None

    def register(self, fileobj: Any, events: int, data: Any = None) -> selectors.SelectorKey:
        return self._real.register(fileobj, events, data)

    def unregister(self, fileobj: Any) -> selectors.SelectorKey:
        return self._real.unregister(fileobj)

    def modify(self, fileobj: Any, events: int, data: Any = None) -> selectors.SelectorKey:
        return self._real.modify(fileobj, events, data)

    def get_map(self) -> Mapping[Any, selectors.SelectorKey]:
        return self._real.get_map()

    def close(self) -> None:
        self._real.close()

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        assert self.loop is not None
        if timeout is not None and timeout <= 0:  # callbacks are ready: no time passes
            return self.loop._worked(self._real)
        return self.loop._idle_point(self._real, timeout)


#: Raised where a job `_CountingPool` counted was not wrapped by `run_in_executor()` at once.
_UNWRAPPED = "run_in_executor() did not wrap its job in create_future(): the count would stick"


class _CountingPool(ThreadPoolExecutor):
    """The loop's default executor, where `run_in_executor(None, ...)` sends a job, and so
    `thread_future`, `run_in_thread` and `asyncio.to_thread`. `submit()` runs in the loop thread
    inside `run_in_executor` and counts the job on the loop. The count ends when the future that
    `run_in_executor` wraps the job in at once is done, in the loop thread, after the result (or
    a cancellation) has reached it. A done-callback on the job itself would run in the job's
    thread before `run_in_executor`'s own, so its hop to the loop could land ahead of the result."""

    def __init__(self, loop: VirtualTimeLoop) -> None:
        super().__init__(thread_name_prefix="asyncio")
        self._loop = loop

    def submit[**P, T](self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        job = super().submit(fn, *args, **kwargs)
        self._loop._submitted()
        return job


class VirtualTimeLoop(asyncio.SelectorEventLoop):
    """A selector loop whose `time()` is a fake clock (see the module docstring). A job on its
    default executor (`_CountingPool`) counts as in flight from `run_in_executor` until its result
    reaches the loop; meanwhile the loop waits for it in real time and the fake clock stands still.
    A job on any other executor is not counted, as a plain thread is not: pass a `_CountingPool` to
    count it. The audit code sends every thread hop to the default executor."""

    def __init__(self) -> None:
        selector = _Selector()
        super().__init__(selector)
        selector.loop = self
        self._fake_now = 0.0
        self._in_flight = 0  # executor jobs whose result has not reached the loop yet
        self._progress = 0  # a pass that ran callbacks, a job that landed, the clock that moved
        self._told = -1  # `_progress` when the idle waiters were last told
        self._told_in_a_row = 0  # tellings since the clock last moved or a job last landed
        self._idle_waiters: list[asyncio.Future[None]] = []
        self.made: list[asyncio.Task[Any]] = []  # ended ones too, unlike `asyncio.all_tasks()`
        self.set_task_factory(self._make)
        self._wrapping = False  # `_CountingPool` counted a job; `run_in_executor` wraps it next
        self.set_default_executor(_CountingPool(self))

    def _make(
        self, loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, Any], **kwargs: Any
    ) -> asyncio.Task[Any]:
        """The task factory: the task `create_task()` (as `spawn()` calls it) asked for, with the
        caller's context, kept in `made` so a test can name one that ended before it looked."""
        task = asyncio.Task(coro, loop=loop, **kwargs)
        self.made.append(task)
        return task

    def time(self) -> float:
        return self._fake_now

    def idle(self, *watch: asyncio.Task[Any]) -> asyncio.Future[None]:
        """Resolved at the next point where nothing is ready, at most once per progress, or as soon
        as a task in `watch` ends. Await it directly: a waiter woken through another future (as by
        `asyncio.wait`) runs one pass later, and that pass counts as progress."""
        waiter = self.create_future()
        self._idle_waiters.append(waiter)

        def wake(_task: asyncio.Task[Any]) -> None:
            if not waiter.done():
                waiter.set_result(None)

        def unhook(_waiter: asyncio.Future[None]) -> None:
            for task in watch:
                task.remove_done_callback(wake)

        for task in watch:
            task.add_done_callback(wake)
        waiter.add_done_callback(unhook)
        return waiter

    def _submitted(self) -> None:
        """`_CountingPool.submit()` took a job: it is in flight until its wrap is done."""
        if self._wrapping:
            raise RuntimeError(_UNWRAPPED)
        self._wrapping = True
        self._in_flight += 1

    def create_future(self) -> asyncio.Future[Any]:
        future = super().create_future()
        if self._wrapping:  # `run_in_executor` wraps the job `_submitted()` just counted
            self._wrapping = False
            future.add_done_callback(self._landed)
        return future

    def _landed(self, _future: asyncio.Future[Any]) -> None:
        self._in_flight -= 1
        self._progress += 1
        self._told_in_a_row = 0

    async def shutdown_default_executor(self, *args: Any, **kwargs: Any) -> None:
        """Its join runs in a plain thread, not an executor job: count it as one. Else the fake
        clock would run out at once the 300 s `asyncio.run` gives the join (a RuntimeWarning, and
        no join), or raise `VirtualClockDeadlock` when no timeout is given."""
        self._in_flight += 1
        try:
            await super().shutdown_default_executor(*args, **kwargs)
        finally:
            self._in_flight -= 1

    def _worked(self, real: selectors.BaseSelector) -> list[tuple[selectors.SelectorKey, int]]:
        self._progress += 1
        return real.select(0)

    def _idle_point(
        self, real: selectors.BaseSelector, timeout: float | None
    ) -> list[tuple[selectors.SelectorKey, int]]:
        """Nothing is ready: tell the idle waiters (they run in this same pass), else wait for an
        executor job in real time, else move the fake clock to the next timer."""
        if self._wrapping:  # a counted job no future will release
            raise RuntimeError(_UNWRAPPED)
        waiting = [waiter for waiter in self._idle_waiters if not waiter.done()]
        if waiting and self._told != self._progress:
            self._told_in_a_row += 1
            if self._told_in_a_row > _MAX_TOLD:  # waiters that wake each other, nothing moving
                raise VirtualClockDeadlock(f"idle waiters told {_MAX_TOLD} times, nothing moved")
            self._idle_waiters.clear()
            self._told = self._progress
            for waiter in waiting:
                waiter.set_result(None)
            return real.select(0)
        if self._in_flight:
            return real.select(None)  # its result wakes the loop through the self-pipe
        if timeout is None:
            raise VirtualClockDeadlock("nothing is ready or scheduled, and no thread job runs")
        self._fake_now += timeout
        self._progress += 1
        self._told_in_a_row = 0
        return real.select(0)


def virtual[**P](test: Callable[P, Coroutine[Any, Any, None]]) -> Callable[P, None]:
    """Run an `async def` test on a fresh `VirtualTimeLoop`; pytest sees a plain test function
    with the same fixtures and parameters."""

    @functools.wraps(test)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(test(*args, **kwargs), loop_factory=VirtualTimeLoop)

    return run
