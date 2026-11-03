"""E21-X02 (#652; 22 `getHeatmap` "Bounds"): the backfill folds' bounded executor
(`orderflow.heatmap_history.run_fold`). At most `MAX_CONCURRENT_FOLDS` folds run at once in the
process, each on a worker of its own, never the loop's default executor; a fold waiting for a slot
waits on the loop, never in the executor's queue (C-2.18); and a slot comes back when its fold
returns on its thread, not when its caller stops waiting, or at once when the executor refuses the
fold. No sleeps: every wait is an event."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from candleviewer.orderflow.heatmap_history import (
    FOLD_THREAD_PREFIX,
    FOLDS,
    MAX_CONCURRENT_FOLDS,
    run_fold,
)

#: A bound on every thread wait here, so a failing test never strands a fold worker.
_WAIT_S = 30.0


class _Folds:
    """Folds that enter, tell the loop, and hold their worker until `release`."""

    def __init__(self, n: int) -> None:
        self.loop = asyncio.get_running_loop()
        self.entered = [asyncio.Event() for _ in range(n)]
        self.release = threading.Event()

    def fold(self, i: int) -> str:
        self.loop.call_soon_threadsafe(self.entered[i].set)
        self.release.wait(_WAIT_S)
        return threading.current_thread().name

    def queued(self) -> int:
        """Folds waiting in the executor's own queue (a private read: C-2.18 is the subject)."""
        pool = FOLDS._pool
        return 0 if pool is None else pool._work_queue.qsize()


@pytest.fixture
def released() -> Iterator[list[_Folds]]:
    """Every `_Folds` a test makes is released at its end, whatever it asserted."""
    made: list[_Folds] = []
    yield made
    for folds in made:
        folds.release.set()


async def test_at_most_the_bound_of_folds_run_at_once_in_the_process(
    released: list[_Folds],
) -> None:
    folds = _Folds(MAX_CONCURRENT_FOLDS + 2)
    released.append(folds)
    tasks = [asyncio.create_task(run_fold(folds.fold, i)) for i in range(len(folds.entered))]
    for event in folds.entered[:MAX_CONCURRENT_FOLDS]:
        await event.wait()
    # the others wait on the loop for a slot: the gate is exhausted, nothing waits in the queue
    assert FOLDS.gate().locked() and folds.queued() == 0
    assert [t.done() for t in tasks] == [False] * len(tasks)
    assert [e.is_set() for e in folds.entered[MAX_CONCURRENT_FOLDS:]] == [False, False]
    folds.release.set()
    names = await asyncio.gather(*tasks)
    assert all(name.startswith(FOLD_THREAD_PREFIX) for name in names), names


async def test_a_fold_runs_on_its_own_worker_not_the_default_executor() -> None:
    name = await run_fold(lambda: threading.current_thread().name)
    assert name.startswith(FOLD_THREAD_PREFIX)
    assert getattr(asyncio.get_running_loop(), "_default_executor", None) is None


async def test_a_cancelled_folds_slot_comes_back_when_its_thread_returns(
    released: list[_Folds],
) -> None:
    folds = _Folds(MAX_CONCURRENT_FOLDS + 1)
    released.append(folds)
    first = [asyncio.create_task(run_fold(folds.fold, i)) for i in range(MAX_CONCURRENT_FOLDS)]
    for event in folds.entered[:MAX_CONCURRENT_FOLDS]:
        await event.wait()
    late = asyncio.create_task(run_fold(folds.fold, MAX_CONCURRENT_FOLDS))
    first[0].cancel()  # its caller stops waiting; its fold still holds its worker
    with pytest.raises(asyncio.CancelledError):
        await first[0]
    assert FOLDS.gate().locked() and folds.queued() == 0 and not late.done()
    folds.release.set()  # the folds return: their slots come back, and the late one runs
    assert (await late).startswith(FOLD_THREAD_PREFIX)
    await first[1]


async def test_a_fold_that_raises_gives_its_slot_back() -> None:
    def broken() -> None:
        raise ValueError("a fold that raises")

    for _ in range(MAX_CONCURRENT_FOLDS + 1):
        with pytest.raises(ValueError, match="raises"):
            await run_fold(broken)
    assert not FOLDS.gate().locked()


async def test_a_fold_the_executor_refuses_raises_and_gives_its_slot_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusing = ThreadPoolExecutor(1)
    refusing.shutdown()  # it refuses every fold submitted to it
    monkeypatch.setattr(FOLDS, "_pool", refusing)
    async with asyncio.timeout(_WAIT_S):  # a slot kept by a refusal leaves the last one waiting
        for _ in range(MAX_CONCURRENT_FOLDS + 1):
            with pytest.raises(RuntimeError, match="shutdown"):
                await run_fold(threading.current_thread)
    assert not FOLDS.gate().locked()
