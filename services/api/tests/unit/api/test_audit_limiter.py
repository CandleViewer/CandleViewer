"""Per-user `/admin/audit` limiter: rate, concurrency, LRU bound (fake clock, no sleeps)."""

from __future__ import annotations

import pytest

from candleviewer.api.audit_limiter import AuditQueryLimiter, AuditQueryRefused


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limit_refuses_with_retry_after_then_recovers() -> None:
    clock = _Clock()
    lim = AuditQueryLimiter(rate_per_minute=3, max_concurrent=10, clock=clock)
    for _ in range(3):
        lim.acquire("u").release()
        clock.now += 10
    with pytest.raises(AuditQueryRefused) as err:
        lim.acquire("u")
    assert err.value.reason == "rate"
    assert err.value.retry_after_s == 30
    clock.now += 30
    lim.acquire("u").release()


def test_concurrency_limit_and_release_idempotent() -> None:
    lim = AuditQueryLimiter(rate_per_minute=100, max_concurrent=2, clock=_Clock())
    a, b = lim.acquire("u"), lim.acquire("u")
    with pytest.raises(AuditQueryRefused) as err:
        lim.acquire("u")
    assert (err.value.reason, err.value.retry_after_s) == ("concurrency", 1)
    a.release()
    a.release()  # second release must not free another slot
    c = lim.acquire("u")
    with pytest.raises(AuditQueryRefused):
        lim.acquire("u")
    b.release()
    c.release()


def test_users_are_independent() -> None:
    lim = AuditQueryLimiter(rate_per_minute=1, clock=_Clock())
    lim.acquire("a")
    lim.acquire("b")
    with pytest.raises(AuditQueryRefused):
        lim.acquire("a")


def test_lru_bound_evicts_idle_users_only() -> None:
    lim = AuditQueryLimiter(tracked_users=2, max_concurrent=5, clock=_Clock())
    busy = lim.acquire("busy")
    lim.acquire("x").release()
    lim.acquire("y").release()
    lim.acquire("z").release()
    assert len(lim) == 2  # busy (in flight) is pinned, one idle user remains
    assert "busy" in lim._users
    busy.release()
    assert busy._state is None
