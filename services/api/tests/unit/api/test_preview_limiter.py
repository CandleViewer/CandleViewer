"""E28-T05 S3b (#909): the preview's per-user token bucket (SR-E28-22, PF-D01; 22
`previewTradeGroup`, AC 8). A burst of the rate, then `Retry-After` in whole seconds, never under
one; it refills at the rate up to the burst, per user, on an injected clock, holding at most 1,024
users (C-2.18). The rate is `CV_TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND`: 20 unless set, and
a value outside 1-100 refuses startup."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from candleviewer.api.preview_limiter import TRACKED_USERS, PreviewLimiter
from candleviewer.settings import TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND, Settings

_ENV = "CV_TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND"
A, B = UUID(int=1), UUID(int=2)


class _Clock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        return self.t


def test_a_burst_of_the_rate_then_a_whole_second_retry_after_per_user() -> None:
    clock = _Clock()
    limiter = PreviewLimiter(20, clock=clock)
    assert [limiter.try_take(A) for _ in range(21)] == [None] * 20 + [1]
    clock.t += 0.01  # a fifth of a token: the wait is a fraction, the answer a whole second
    assert limiter.try_take(A) == 1
    assert limiter.try_take(B) is None  # another user's bucket is its own


def test_the_bucket_refills_at_the_rate_up_to_the_burst() -> None:
    """Times a binary fraction apart, so the arithmetic is exact."""
    clock = _Clock()
    limiter = PreviewLimiter(20, clock=clock)
    assert [limiter.try_take(A) for _ in range(20)] == [None] * 20
    clock.t += 0.0625  # 1.25 tokens at 20 a second
    assert [limiter.try_take(A), limiter.try_take(A)] == [None, 1]
    clock.t += 3600.0  # idle: full again, never past the burst
    assert [limiter.try_take(A) for _ in range(21)] == [None] * 20 + [1]
    later = _Clock()
    slow = PreviewLimiter(1, clock=later)
    assert [slow.try_take(A), slow.try_take(A)] == [None, 1]
    later.t += 0.75
    assert slow.try_take(A) == 1  # a quarter of a second to wait: one whole second
    later.t += 0.25
    assert slow.try_take(A) is None
    with pytest.raises(ValueError, match="at least one"):
        PreviewLimiter(0, clock=later)


def test_the_buckets_are_bounded_to_the_least_recently_used_1024_users() -> None:
    """C-2.18: past the bound the least recently used user's bucket goes, full again on return."""
    assert TRACKED_USERS == 1024
    limiter = PreviewLimiter(1, clock=_Clock())
    old, kept = UUID(int=10**6), UUID(int=10**6 + 1)
    assert [limiter.try_take(old), limiter.try_take(kept), limiter.try_take(old)] == [None, None, 1]
    assert all(limiter.try_take(UUID(int=n)) is None for n in range(TRACKED_USERS - 1))
    assert len(limiter) == TRACKED_USERS
    assert limiter.try_take(old) == 1  # `kept` was the least recently used, not `old`
    assert limiter.try_take(kept) is None


@pytest.fixture
def _no_rate_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv(_ENV, raising=False)
    return monkeypatch


def test_the_rate_is_20_unless_set_and_startup_refuses_one_outside_1_to_100(
    _no_rate_env: pytest.MonkeyPatch,
) -> None:
    """22 names the setting and its default of 20 a second."""
    assert Settings().tradegroups_preview_rate_per_user_per_second == 20
    assert TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND == 20
    for value in ("1", "100"):
        _no_rate_env.setenv(_ENV, value)
        assert Settings().tradegroups_preview_rate_per_user_per_second == int(value)
    for value in ("0", "101"):
        _no_rate_env.setenv(_ENV, value)
        with pytest.raises(ValidationError, match="tradegroups_preview_rate_per_user_per_second"):
            Settings()
