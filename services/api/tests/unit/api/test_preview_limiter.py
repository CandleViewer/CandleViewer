"""E28-T05 S3b (#909): the preview's per-user token bucket (SR-E28-22, PF-D01; 22
`previewTradeGroup`, AC 8). A burst of the rate, then `Retry-After` in whole seconds, never under
one; it refills at the rate up to the burst, per user, on an injected clock, holding at most 1,024
users (C-2.18). The rate is `CV_TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND`: 20 unless set, and
a value outside 1-100 refuses startup. The burst is the rate unless set (#4834: the checks' bucket
holds twice its rate)."""

from __future__ import annotations

from fractions import Fraction
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.api.preview_limiter import TRACKED_USERS, PreviewLimiter
from candleviewer.settings import TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND, Settings

_ENV = "CV_TRADEGROUPS_PREVIEW_RATE_PER_USER_PER_SECOND"
A, B, C = UUID(int=1), UUID(int=2), UUID(int=3)


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


def test_a_clock_that_steps_back_neither_refills_nor_lengthens_the_wait() -> None:
    clock = _Clock()
    limiter = PreviewLimiter(2, clock=clock)
    assert limiter.try_take(A) is None
    clock.t -= 5.0  # the token left is kept, and none is added for the step
    assert [limiter.try_take(A), limiter.try_take(A)] == [None, 1]
    clock.t += 0.5  # due when the answer said, not once the clock passes the old stamp
    assert limiter.try_take(A) is None


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


def test_a_burst_above_the_rate_is_held_and_refills_at_the_rate() -> None:
    """Times a binary fraction apart, so the arithmetic is exact."""
    clock = _Clock()
    limiter = PreviewLimiter(10, burst=20, clock=clock)
    assert [limiter.try_take(A) for _ in range(21)] == [None] * 20 + [1]
    clock.t += 0.125  # 1.25 tokens at 10 a second
    assert [limiter.try_take(A), limiter.try_take(A)] == [None, 1]
    clock.t += 3600.0  # idle: full again, never past the burst
    assert [limiter.try_take(A) for _ in range(21)] == [None] * 20 + [1]
    assert limiter.try_take(B) is None  # another user's bucket is its own, and starts full
    with pytest.raises(ValueError, match="at least one"):
        PreviewLimiter(10, burst=0, clock=clock)


def test_the_burst_is_the_rate_unless_set() -> None:
    clock = _Clock()
    for limiter in (PreviewLimiter(3, clock=clock), PreviewLimiter(3, burst=None, clock=clock)):
        assert [limiter.try_take(A) for _ in range(4)] == [None] * 3 + [1]


def test_calls_far_above_the_rate_settle_at_the_rate_after_the_burst() -> None:
    """64 calls a second against 10 a second and a burst of 20: over 8 seconds the bucket admits
    its burst and the rate's share of the time."""
    clock = _Clock()
    limiter = PreviewLimiter(10, burst=20, clock=clock)
    admitted = 0
    for call in range(8 * 64 + 1):
        clock.t = 50.0 + call / 64
        admitted += limiter.try_take(A) is None
    assert admitted == 20 + 10 * 8


_STEPS = st.lists(st.tuples(st.integers(0, 640), st.sampled_from([A, B, C])), max_size=150)


@settings(deadline=None)
@given(steps=_STEPS, rate=st.integers(1, 100), burst=st.integers(1, 200))
def test_admitted_calls_never_exceed_burst_plus_rate_times_elapsed(
    steps: list[tuple[int, UUID]], rate: int, burst: int
) -> None:
    """Against a reference model in exact fractions, over random gaps (in 64ths of a second) and
    users: each call is admitted as the model says, and a user's admitted calls never pass the burst
    plus the rate times the time since its first call."""
    clock, now = _Clock(), Fraction(0)
    limiter = PreviewLimiter(rate, burst=burst, clock=clock)
    held: dict[UUID, tuple[Fraction, Fraction]] = {}  # tokens, and the instant they were counted
    first: dict[UUID, Fraction] = {}
    admitted: dict[UUID, int] = {}
    for ticks, user in steps:
        now += Fraction(ticks, 64)
        clock.t = 50.0 + float(now)
        tokens, last = held.get(user, (Fraction(burst), now))
        tokens = min(Fraction(burst), tokens + (now - last) * rate)
        taken = tokens >= 1
        held[user] = (tokens - taken, now)
        assert (limiter.try_take(user) is None) == taken
        first.setdefault(user, now)
        admitted[user] = admitted.get(user, 0) + taken
        assert admitted[user] <= burst + rate * (now - first[user])


def _answers(ticks: list[int], rate: int, burst: int, then: int | None = None) -> list[int | None]:
    """The answer to each call, `ticks` (64ths of a second) apart, then to one `then` seconds on."""
    clock = _Clock()
    limiter = PreviewLimiter(rate, burst=burst, clock=clock)
    out: list[int | None] = []
    for gap in ticks:
        clock.t += gap / 64
        out.append(limiter.try_take(A))
    if then is not None:
        clock.t += then
        out.append(limiter.try_take(A))
    return out


@settings(deadline=None)
@given(
    ticks=st.lists(st.integers(0, 640), max_size=60),
    rate=st.integers(1, 100),
    burst=st.integers(1, 200),
)
def test_retry_after_is_a_whole_second_never_under_one_and_never_late(
    ticks: list[int], rate: int, burst: int
) -> None:
    """After a refusal the bucket has a token once the wait has passed, and not a second sooner."""
    for i, wait in enumerate(_answers(ticks, rate, burst)):
        if wait is None:
            continue
        assert type(wait) is int and wait >= 1
        assert _answers(ticks[: i + 1], rate, burst, then=wait)[-1] is None
        assert _answers(ticks[: i + 1], rate, burst, then=wait - 1)[-1] is not None
