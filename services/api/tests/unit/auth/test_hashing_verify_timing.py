"""#2097: `Hasher.verify` times the Argon2id call in its worker thread and keeps the result per
context (`last_verify_ms`), which the perf-only login `Server-Timing` header reads.

The clock is an injected fake, so every expected duration is exact (no sleeps, C-13.7).
"""

from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from candleviewer.auth.hashing import Hasher, last_verify_ms

_PASSWORD = "correct horse battery staple"


class _FakePerfCounter:
    """Returns the scripted readings in order and records the thread of each read."""

    def __init__(self, *readings: float) -> None:
        self._readings = list(readings)
        self.threads: list[int] = []

    def __call__(self) -> float:
        self.threads.append(threading.get_ident())
        return self._readings.pop(0)


def _hasher(*readings: float) -> tuple[Hasher, _FakePerfCounter]:
    counter = _FakePerfCounter(*readings)
    return Hasher(perf_counter=counter), counter


def test_last_verify_ms_is_none_in_a_context_without_a_verify() -> None:
    assert contextvars.Context().run(last_verify_ms) is None


async def test_verify_records_the_argon2_time_in_milliseconds() -> None:
    digest = await Hasher().hash(_PASSWORD)
    hasher, _ = _hasher(10.0, 10.2125)
    assert await hasher.verify(digest, _PASSWORD) is True
    assert last_verify_ms() == pytest.approx(212.5)


async def test_verify_records_the_time_of_a_failed_verify_on_the_same_path() -> None:
    """The dummy-hash path (unknown user, SR-014) runs the identical timed call."""
    hasher, _ = _hasher(5.0, 5.25)
    assert await hasher.verify_dummy("not the password") is False
    assert last_verify_ms() == pytest.approx(250.0)


async def test_verify_reads_the_clock_in_the_worker_thread_only() -> None:
    """Only the Argon2id call is timed: both reads happen in the `to_thread` worker, never
    on the event loop, so queueing for a worker thread is not counted."""
    hasher, counter = _hasher(1.0, 1.1)
    await hasher.verify_dummy("x")
    loop_thread = threading.get_ident()
    assert len(counter.threads) == 2
    assert counter.threads[0] == counter.threads[1]
    assert counter.threads[0] != loop_thread


async def test_concurrent_verifies_each_keep_their_own_time() -> None:
    """Two requests in flight at once never see each other's value (one context per task)."""

    async def one_request(hasher: Hasher) -> float | None:
        await hasher.verify_dummy("x")
        return last_verify_ms()

    fast, _ = _hasher(0.0, 0.1)
    slow, _ = _hasher(0.0, 0.3)
    fast_ms, slow_ms = await asyncio.gather(one_request(fast), one_request(slow))
    assert fast_ms == pytest.approx(100.0)
    assert slow_ms == pytest.approx(300.0)


async def test_a_verify_in_a_child_task_does_not_leak_into_the_caller() -> None:
    hasher, _ = _hasher(0.0, 0.5)
    before = last_verify_ms()
    assert await asyncio.create_task(hasher.verify_dummy("x")) is False
    assert last_verify_ms() == before
