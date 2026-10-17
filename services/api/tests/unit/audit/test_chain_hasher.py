"""`ChainHasher`: its own bounded thread pool, refusal past `max_pending`, and a cancelled
caller that waits for its job (the slot it holds covers the CPU work). Threads are
synchronised with events, never with sleeps."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator

import pytest

from candleviewer.audit.hashing import ChainHasher, ChainHasherBusy

_WAIT_S = 5.0  # a hang guard: a regression must fail its test, not hang the run


@pytest.fixture
async def gate() -> AsyncIterator[tuple[threading.Event, threading.Event]]:
    """Async so that its teardown runs before the loop is closed: closing the loop waits for a
    `run()` whose worker is blocked on `release`, so a test that failed first would hang."""
    started, release = threading.Event(), threading.Event()
    yield started, release
    release.set()  # never leave a worker blocked


def _blocking(started: threading.Event, release: threading.Event) -> str:
    started.set()
    release.wait()
    return threading.current_thread().name


async def test_runs_on_its_own_named_threads() -> None:
    hasher = ChainHasher()
    name = await hasher.run(lambda: threading.current_thread().name)
    assert name.startswith("cv-audit-hash") and hasher.pending == 0
    hasher.shutdown()


async def test_refuses_past_max_pending_then_recovers(
    gate: tuple[threading.Event, threading.Event],
) -> None:
    started, release = gate
    hasher = ChainHasher(workers=1, max_pending=1)
    first = asyncio.ensure_future(hasher.run(lambda: _blocking(started, release)))
    assert await asyncio.to_thread(started.wait, _WAIT_S), "the first job never started"
    second = asyncio.ensure_future(hasher.run(lambda: "second"))
    # A cap that let it in would queue it behind the blocked job. Wait without cancelling
    # (a cancelled `run` waits for its job), then free the worker so a failure ends here.
    done, _ = await asyncio.wait({second}, timeout=_WAIT_S)
    release.set()
    assert done, "a call past the cap was queued, not refused"
    with pytest.raises(ChainHasherBusy):
        second.result()
    assert (await asyncio.wait_for(first, _WAIT_S)).startswith("cv-audit-hash")
    assert hasher.pending == 0
    assert await hasher.run(lambda: "third") == "third"
    hasher.shutdown()


async def test_a_queued_job_dropped_by_shutdown_is_refused_not_cancelled(
    gate: tuple[threading.Event, threading.Event],
) -> None:
    """F8-2: `shutdown` cancels the jobs still queued. Their callers were not cancelled, so
    they are refused like any call the hasher cannot take (the router answers 503) and the
    cancellation does not escape `AuditQueryService.query`."""
    started, release = gate
    hasher = ChainHasher(workers=1, max_pending=2)
    first = asyncio.ensure_future(hasher.run(lambda: _blocking(started, release)))
    assert await asyncio.to_thread(started.wait, _WAIT_S), "the first job never started"
    queued = asyncio.ensure_future(hasher.run(lambda: "queued"))
    await asyncio.sleep(0)  # one scheduler turn: it is submitted behind the running job
    assert hasher.pending == 2
    hasher.shutdown()
    with pytest.raises(ChainHasherBusy):
        await asyncio.wait_for(queued, _WAIT_S)
    release.set()
    assert (await asyncio.wait_for(first, _WAIT_S)).startswith("cv-audit-hash")  # still finishes
    assert hasher.pending == 0


async def test_a_cancelled_caller_whose_job_is_dropped_stays_cancelled(
    gate: tuple[threading.Event, threading.Event],
) -> None:
    """A caller's own cancellation is never turned into a refusal, even when `shutdown`
    drops its queued job as well."""
    started, release = gate
    hasher = ChainHasher(workers=1, max_pending=2)
    first = asyncio.ensure_future(hasher.run(lambda: _blocking(started, release)))
    assert await asyncio.to_thread(started.wait, _WAIT_S), "the first job never started"
    queued = asyncio.ensure_future(hasher.run(lambda: "queued"))
    await asyncio.sleep(0)  # one scheduler turn: it is submitted behind the running job
    queued.cancel()
    hasher.shutdown()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(queued, _WAIT_S)
    release.set()
    await asyncio.wait_for(first, _WAIT_S)
    assert hasher.pending == 0


async def test_cancelled_caller_waits_for_its_job_to_finish(
    gate: tuple[threading.Event, threading.Event],
) -> None:
    started, release = gate
    hasher = ChainHasher(workers=1, max_pending=1)
    task = asyncio.ensure_future(hasher.run(lambda: _blocking(started, release)))
    await asyncio.to_thread(started.wait)
    for _ in range(2):  # repeated cancellation still waits
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done() and hasher.pending == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hasher.pending == 0
    hasher.shutdown()


async def test_job_error_propagates_and_frees_the_slot() -> None:
    hasher = ChainHasher(max_pending=1)

    def boom() -> None:
        raise KeyError("x")

    with pytest.raises(KeyError):
        await hasher.run(boom)
    assert hasher.pending == 0 and await hasher.run(lambda: 1) == 1
    hasher.shutdown()


async def test_shut_down_hasher_refuses() -> None:
    hasher = ChainHasher()
    hasher.shutdown()
    with pytest.raises(ChainHasherBusy):
        await hasher.run(lambda: 1)
