"""Per-user `/admin/audit` limiter: rate, concurrency, LRU bound (fake clock, no sleeps)."""

from __future__ import annotations

import pytest

from candleviewer.api.audit_limiter import AuditQueryLimiter, AuditQueryRefused, AuditVerifyLimiter


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


def test_verify_runs_count_only_when_started_and_the_hour_rolls() -> None:
    clock = _Clock()
    lim = AuditVerifyLimiter(rate_per_hour=2, clock=clock)
    for _ in range(5):  # checks alone (a 409, a 429, a 503) never count
        assert lim.retry_after("owner") is None
    lim.record_start("owner")
    clock.now += 600
    lim.record_start("owner")
    assert lim.retry_after("owner") == 3000  # until the first run leaves the hour
    assert lim.retry_after("other") is None  # per user
    clock.now += 3000
    assert lim.retry_after("owner") is None


def test_verify_limiter_bound_evicts_only_users_with_no_run_in_the_hour() -> None:
    clock = _Clock()
    lim = AuditVerifyLimiter(rate_per_hour=5, tracked_users=2, clock=clock)
    lim.record_start("a")
    lim.record_start("b")
    assert lim.retry_after("c") == 1  # no room: refused, never let through uncounted
    clock.now += 3600  # a's and b's runs leave the hour
    assert lim.retry_after("c") is None
    lim.record_start("c")
    assert len(lim._users) <= 2
