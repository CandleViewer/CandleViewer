"""`ChainHasher`: its own bounded thread pool, refusal past `max_pending`, and a cancelled
caller that waits for its job (the slot it holds covers the CPU work). Threads are
synchronised with events, never with sleeps."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator

import pytest

from candleviewer.audit.hashing import ChainHasher, ChainHasherBusy


@pytest.fixture
def gate() -> Iterator[tuple[threading.Event, threading.Event]]:
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
    await asyncio.to_thread(started.wait)
    with pytest.raises(ChainHasherBusy):
        await hasher.run(lambda: "second")
    release.set()
    assert (await first).startswith("cv-audit-hash") and hasher.pending == 0
    assert await hasher.run(lambda: "third") == "third"
    hasher.shutdown()


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
