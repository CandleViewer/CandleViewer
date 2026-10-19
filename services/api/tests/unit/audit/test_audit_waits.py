"""Pins `audit_waits`: `guarded()`, which the writer and lane tests wait through (#3654), and
`VirtualTimeLoop`'s held clock and raise paths, on which the lane tests run (#3709)."""

from __future__ import annotations

import asyncio
import time

import audit_waits
import pytest
from audit_waits import TaskEnded, VirtualClockDeadlock, VirtualTimeLoop, guarded, virtual


async def dies(alarm: asyncio.Event | None = None) -> None:
    """A worker that fails, setting `alarm` first in the same step, as a flusher's death does."""
    if alarm is not None:
        alarm.set()
    raise RuntimeError("the worker died")


@pytest.mark.parametrize("before", [False, True], ids=["while-waiting", "before-the-call"])
@pytest.mark.parametrize("stopped", [False, True], ids=["failed", "stopped"])
async def test_guarded_worker_that_ends_ends_the_wait_with_its_error(
    before: bool, stopped: bool
) -> None:
    worker = asyncio.create_task(asyncio.Event().wait() if stopped else dies())
    if stopped:
        worker.cancel()
    if before:
        await asyncio.wait({worker})
    with pytest.raises(TaskEnded) as ended:
        await guarded(asyncio.Event().wait(), worker)
    assert isinstance(ended.value.__cause__, type(None) if stopped else RuntimeError)


@pytest.mark.parametrize("before", [False, True], ids=["while-waiting", "before-the-call"])
async def test_guarded_alarm_set_as_the_worker_dies_wins_the_tie(before: bool) -> None:
    alarm = asyncio.Event()
    worker = asyncio.create_task(dies(alarm))
    if before:
        await asyncio.wait({worker})
    assert await guarded(alarm.wait(), worker) is True
    assert isinstance(worker.exception(), RuntimeError)


async def test_guarded_cancelled_caller_cancels_its_waiter_and_no_worker() -> None:
    worker, cancelled = asyncio.create_task(asyncio.Event().wait()), asyncio.Event()

    async def wait() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    caller = asyncio.create_task(guarded(wait(), worker))
    await asyncio.sleep(0)  # the caller is inside its wait
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert cancelled.is_set() and not worker.done()
    worker.cancel()


def test_virtual_loop_with_nothing_ready_scheduled_or_in_flight_raises() -> None:
    with pytest.raises(VirtualClockDeadlock, match="nothing is ready or scheduled"):
        asyncio.run(asyncio.Event().wait(), loop_factory=VirtualTimeLoop)


@virtual
async def test_virtual_loop_holds_the_clock_while_a_thread_job_runs() -> None:
    loop = asyncio.get_running_loop()
    start = loop.time()
    # 0.3 real seconds in a thread outlast a 0.1 s timeout only if the clock moves meanwhile.
    await asyncio.wait_for(asyncio.to_thread(time.sleep, 0.3), 0.1)
    assert loop.time() == start


def test_virtual_loop_raises_when_idle_waiters_only_wake_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_waits, "_MAX_TOLD", 50)  # the cap, lowered to keep this fast

    async def woken_a_pass_late() -> None:
        loop = asyncio.get_running_loop()
        assert isinstance(loop, VirtualTimeLoop)
        while True:  # through `asyncio.wait`, each wake costs a pass, which counts as progress
            await asyncio.wait({loop.idle()})

    with pytest.raises(VirtualClockDeadlock, match="told 50 times"):
        asyncio.run(woken_a_pass_late(), loop_factory=VirtualTimeLoop)
