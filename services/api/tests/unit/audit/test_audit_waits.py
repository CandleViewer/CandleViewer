"""Pins `audit_waits`: `guarded()`, which the writer tests wait through (#3654)."""

from __future__ import annotations

import asyncio

import pytest
from audit_waits import TaskEnded, guarded


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
