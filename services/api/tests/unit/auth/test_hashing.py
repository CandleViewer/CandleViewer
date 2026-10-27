"""Unit tests for `candleviewer.auth.hashing.Hasher` (E09-S01)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, Hasher, constant_time_eq

pytestmark = pytest.mark.asyncio


async def test_hasher_hash_then_verify_roundtrips() -> None:
    hasher = Hasher(pepper="pepper-value")
    digest = await hasher.hash("correct-horse-battery-staple")
    assert await hasher.verify(digest, "correct-horse-battery-staple") is True


async def test_hasher_verify_wrong_password_returns_false() -> None:
    hasher = Hasher(pepper="pepper-value")
    digest = await hasher.hash("correct-horse-battery-staple")
    assert await hasher.verify(digest, "wrong-password") is False


async def test_hasher_verify_dummy_always_false() -> None:
    hasher = Hasher(pepper="pepper-value")
    assert await hasher.verify_dummy("any-password-at-all") is False


async def test_hasher_different_pepper_fails_verification() -> None:
    hasher_a = Hasher(pepper="pepper-a")
    hasher_b = Hasher(pepper="pepper-b")
    digest = await hasher_a.hash("correct-horse-battery-staple")
    assert await hasher_b.verify(digest, "correct-horse-battery-staple") is False


async def test_hasher_needs_rehash_false_for_current_params() -> None:
    hasher = Hasher()
    digest = await hasher.hash("correct-horse-battery-staple", DEFAULT_ARGON2_PARAMS)
    assert hasher.needs_rehash(digest, DEFAULT_ARGON2_PARAMS) is False


async def test_hasher_needs_rehash_true_for_stale_params() -> None:
    hasher = Hasher()
    stale_params = {"m": 8, "t": 1, "p": 1}
    digest = await hasher.hash("correct-horse-battery-staple", stale_params)
    assert hasher.needs_rehash(digest, DEFAULT_ARGON2_PARAMS) is True


def test_constant_time_eq_true_and_false() -> None:
    assert constant_time_eq("abc", "abc") is True
    assert constant_time_eq("abc", "abd") is False


class _ThreadRecordingHasher(Hasher):
    """Records the name of the thread each verify's worker call runs on."""

    def __init__(self, executor: ThreadPoolExecutor) -> None:
        super().__init__(pepper="pepper-value", executor=executor)
        self.threads: list[str] = []

    def _timed_verify_sync(self, password_hash: str, peppered_password: str) -> tuple[bool, float]:
        self.threads.append(threading.current_thread().name)
        return super()._timed_verify_sync(password_hash, peppered_password)


async def test_hasher_with_executor_runs_hash_and_verify_on_that_executor() -> None:
    """#4663: a hasher given a pool runs its verify work there, never on the default pool."""
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="cv-test-pool") as pool:
        hasher = _ThreadRecordingHasher(pool)
        digest = await hasher.hash("correct-horse-battery-staple")
        assert await hasher.verify(digest, "correct-horse-battery-staple") is True

    assert hasher.threads and all(name.startswith("cv-test-pool") for name in hasher.threads)
