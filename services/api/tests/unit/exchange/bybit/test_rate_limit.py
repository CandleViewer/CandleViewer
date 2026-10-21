"""Token-bucket tests (ticket scenario "Rate budget is shared per UID").

Uses an injected, manually-advanced clock — no real `time.sleep`/wall-clock
waits (`40-testing.md` "No sleeps: fake clocks").
"""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.models import RateLane
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.mark.asyncio
async def test_acquire_consumes_one_token() -> None:
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=2.0, default_refill_per_s=1.0, ip_budget_per_5s=1000, clock=clock
    )
    await governor.acquire("uid-1", EndpointClass.MARKET_DATA, lane="poll")
    assert governor.remaining("uid-1", EndpointClass.MARKET_DATA) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_bucket_is_shared_across_callers_for_same_uid() -> None:
    """Two concurrent callers using keys of the same UID draw from one
    bucket — the combined rate never exceeds the configured budget
    (acceptance criterion 2)."""
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.0, ip_budget_per_5s=1000, clock=clock
    )
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry")
    assert governor.remaining("uid-1", EndpointClass.ORDER) == pytest.approx(0.0)

    # A second caller with a *different key* but the same UID must see the
    # already-drained bucket (shared, not per-key).
    waiter = asyncio.ensure_future(governor.acquire("uid-1", EndpointClass.ORDER, lane="entry"))
    await asyncio.sleep(0)
    assert not waiter.done()
    clock.advance(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter


@pytest.mark.asyncio
async def test_different_uid_has_independent_bucket() -> None:
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.0, ip_budget_per_5s=1000, clock=clock
    )
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry")
    assert governor.remaining("uid-1", EndpointClass.ORDER) == pytest.approx(0.0)
    assert governor.remaining("uid-2", EndpointClass.ORDER) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_refill_over_time_restores_tokens() -> None:
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=1.0, ip_budget_per_5s=1000, clock=clock
    )
    await governor.acquire("uid-1", EndpointClass.MARKET_DATA, lane="poll")
    assert governor.remaining("uid-1", EndpointClass.MARKET_DATA) == pytest.approx(0.0)
    clock.advance(1.0)
    assert governor.remaining("uid-1", EndpointClass.MARKET_DATA) == pytest.approx(1.0)


def test_drain_reduces_tokens_by_advertised_amount() -> None:
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=10.0, default_refill_per_s=0.0, ip_budget_per_5s=1000, clock=clock
    )
    governor.drain("uid-1", EndpointClass.ORDER, 4.0)
    assert governor.remaining("uid-1", EndpointClass.ORDER) == pytest.approx(6.0)


def test_observe_header_overrides_local_accounting() -> None:
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=10.0, default_refill_per_s=0.0, ip_budget_per_5s=1000, clock=clock
    )
    governor.observe_header("uid-1", EndpointClass.ORDER, 2)
    assert governor.remaining("uid-1", EndpointClass.ORDER) == pytest.approx(2.0)


# -- G-8 (#2877): lanes, bounded waits and the process-wide IP gate (OM-D08, rulings R3, R5) ----


class _Sleeps:
    """The injected sleep: it advances the fake clock and records each wait."""

    def __init__(self, clock: _FakeClock) -> None:
        self.clock, self.waits = clock, list[float]()

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.clock.advance(seconds)


@pytest.mark.parametrize("lane", ["critical", "entry", "poll"])
@pytest.mark.asyncio
async def test_every_lane_draws_the_same_buckets_until_the_reserve_lands(lane: RateLane) -> None:
    """R3: the lane is taken on every acquisition and served alike (E34-T02 builds the reserve)."""
    governor = TokenBucketGovernor(
        default_capacity=2.0, default_refill_per_s=1.0, ip_budget_per_5s=1000, clock=_FakeClock()
    )
    await governor.acquire("uid-1", EndpointClass.ORDER, lane=lane)
    assert governor.remaining("uid-1", EndpointClass.ORDER) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_a_wait_within_the_deadline_sleeps_on_the_injected_sleep() -> None:
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=2.0, ip_budget_per_5s=1000, clock=clock,
        sleep=sleeps,
    )  # fmt: skip
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry")
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry", deadline_s=0.75)
    assert sleeps.waits == [pytest.approx(0.5)] and clock.t == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_a_wait_past_the_deadline_is_refused_and_gives_its_tokens_back() -> None:
    clock = _FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=5.0, default_refill_per_s=5.0, ip_budget_per_5s=1, clock=clock
    )
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry")  # the IP bucket is empty
    with pytest.raises(RateBudgetExceededError) as refused:
        await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry", deadline_s=1.0)
    assert refused.value.retry_after_s == pytest.approx(5.0)  # one IP token: 5 s at 1 per 5 s
    assert governor.remaining("uid-1", EndpointClass.ORDER) == pytest.approx(4.0)  # given back


@pytest.mark.asyncio
async def test_an_ip_hold_longer_than_the_deadline_is_refused_at_once() -> None:
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(clock=clock, sleep=sleeps)
    governor.hold_ip(600.0)
    with pytest.raises(RateBudgetExceededError) as refused:
        await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical", deadline_s=5.0)
    assert sleeps.waits == []
    assert refused.value.retry_after_s == pytest.approx(600.0)
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical")  # unbounded: waits
    assert sleeps.waits == [pytest.approx(600.0)]


@pytest.mark.asyncio
async def test_a_capped_view_shares_the_ip_gate_and_buckets_and_adds_its_own_cap() -> None:
    """R5: key verification shares the process IP bucket and hold, with its own 50 per 5 s."""
    clock = _FakeClock()
    process = TokenBucketGovernor(ip_budget_per_5s=600, clock=clock)
    view = process.capped(2)
    await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll")
    await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll")
    assert process._ip.bucket.tokens == pytest.approx(598.0)  # the process's IP bucket paid
    assert process.remaining("uid-1", EndpointClass.ACCOUNT) == pytest.approx(8.0)
    with pytest.raises(RateBudgetExceededError):  # the view's own cap, 2 per 5 s, is spent
        await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll", deadline_s=0.1)
    await process.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll")  # the process is not capped
    view.hold_ip(30.0)
    assert process.ip_hold_remaining_s() == pytest.approx(30.0)  # one hold for both


@pytest.mark.asyncio
async def test_acquire_ip_only_waits_on_the_injected_sleep() -> None:
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(ip_budget_per_5s=1, clock=clock, sleep=sleeps)
    await governor.acquire_ip_only()
    await governor.acquire_ip_only()
    assert sleeps.waits and sum(sleeps.waits) == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_a_deadline_bounds_the_queue_behind_a_busy_bucket() -> None:
    """24 §8.7: the lane's wait bounds the queue for a bucket too. A taker holding the bucket's
    lock (one with no deadline, sleeping for its token) never keeps a critical acquire past its
    wait: it is refused at once, with nothing taken, and the next acquire goes through."""
    governor = TokenBucketGovernor()
    bucket = governor._get_bucket("uid-1", EndpointClass.ORDER)
    await bucket.lock.acquire()  # a taker in front, holding the lock
    with pytest.raises(RateBudgetExceededError, match="busy past the lane's wait"):
        async with asyncio.timeout(1.0):  # a guard: the refusal comes at once
            await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical", deadline_s=0.0)
    assert bucket.tokens == pytest.approx(10.0)
    bucket.lock.release()
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical", deadline_s=0.0)
    assert not bucket.lock.locked()


@pytest.mark.asyncio
async def test_a_deadline_lets_a_taker_queue_behind_a_busy_bucket_for_what_it_leaves() -> None:
    """24 §8.7: the queue counts against the lane's wait, and only that. Two critical acquires
    of 5 s each behind a drained bucket that refills a token a second both get their token: the
    second queues on the bucket while the first waits for its own, never refused at once."""
    clock = _FakeClock()

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)
        await asyncio.sleep(0)  # yields once, so the other taker queues meanwhile

    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=1.0, clock=clock, sleep=sleep
    )
    governor.drain("uid-1", EndpointClass.ORDER, 1.0)
    takers = [
        governor.acquire("uid-1", EndpointClass.ORDER, lane="critical", deadline_s=5.0)
        for _ in range(2)
    ]
    async with asyncio.timeout(1.0):  # a guard: virtual time, so it ends at once
        await asyncio.gather(*takers)
    assert clock() == pytest.approx(2.0)  # one token a second, each waited for in turn


@pytest.mark.asyncio
async def test_a_view_refused_in_the_queue_gives_its_cap_token_back() -> None:
    governor = TokenBucketGovernor()
    view = governor.capped(5)
    bucket = governor._get_bucket("uid-1", EndpointClass.ACCOUNT)
    await bucket.lock.acquire()
    with pytest.raises(RateBudgetExceededError):
        async with asyncio.timeout(1.0):  # a guard: the refusal comes at once
            await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll", deadline_s=0.0)
    bucket.lock.release()
    assert view._cap is not None and view._cap.tokens == pytest.approx(5.0)


def test_a_capped_view_holds_every_attribute_of_its_governor() -> None:
    """A view is a copy: an attribute the governor gains is never missing from a view, and the
    IP gate and buckets are the governor's own; only the cap is the view's."""
    governor = TokenBucketGovernor()
    view = governor.capped(5)
    assert vars(view).keys() == vars(governor).keys()
    assert (view._ip, view._buckets) == (governor._ip, governor._buckets)
    assert view._ip is governor._ip and view._buckets is governor._buckets
    assert governor._cap is None and view._cap is not None


# -- the round-3 fold (#2877): give back on a cut, an untrusted header, and each edge pinned ---


class _Parked:
    """An injected sleep that parks its caller until it is cancelled: a wait cut from outside."""

    def __init__(self) -> None:
        self.parked = asyncio.Event()

    async def __call__(self, _seconds: float) -> None:
        self.parked.set()
        await asyncio.Event().wait()


@pytest.mark.parametrize("cut", ["cancel", "timeout"])
@pytest.mark.asyncio
async def test_an_acquire_cut_while_it_waits_gives_its_tokens_back(cut: str) -> None:
    """A taker parked on the empty IP bucket has taken its cap and UID tokens already; a cancel,
    or the caller's own timeout (key verification cuts each call at 5 s), gives both back, as a
    refusal does: nothing is spent on a request that is never sent."""
    sleep = _Parked()
    governor = TokenBucketGovernor(ip_budget_per_5s=1, clock=_FakeClock(), sleep=sleep)
    await governor.acquire_ip_only()  # the IP bucket is empty now
    view = governor.capped(5)
    if cut == "cancel":
        waiter = asyncio.ensure_future(view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll"))
        await sleep.parked.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    else:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0):  # due at once: it cuts the first wait
                await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll")
    assert view._cap is not None and view._cap.tokens == pytest.approx(5.0)
    assert governor.remaining("uid-1", EndpointClass.ACCOUNT) == pytest.approx(10.0)


@pytest.mark.parametrize("remaining", [-5, -(10**9)])
@pytest.mark.asyncio
async def test_a_limit_status_below_zero_empties_the_bucket_and_no_more(remaining: int) -> None:
    """The venue's header is untrusted (`rest.py`): a negative figure must not push the bucket
    so far below zero that its next token is hours or years away."""
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(
        default_capacity=10.0, default_refill_per_s=5.0, ip_budget_per_5s=1000, clock=clock,
        sleep=sleeps,
    )  # fmt: skip
    governor.observe_header("uid-1", EndpointClass.ORDER, remaining)
    assert governor.headroom("uid-1", EndpointClass.ORDER, lane="critical") == (0.0, 0.2)
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical")
    assert sleeps.waits == [pytest.approx(0.2)]  # one refill interval at 5 tokens a second


@pytest.mark.asyncio
async def test_a_capped_view_refills_its_cap_at_its_own_rate() -> None:
    """SR-E27-05: 5 per 5 s is one token a second, so the sixth acquisition waits 1 s for it."""
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(clock=clock, sleep=sleeps)
    view = governor.capped(5)
    for _ in range(5):
        await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll")
    assert sleeps.waits == []
    await view.acquire("uid-1", EndpointClass.ACCOUNT, lane="poll")
    assert sleeps.waits == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_a_long_token_wait_polls_each_second_and_sees_a_hold_set_meanwhile() -> None:
    """A bucket 100 s from its token is polled at most a second at a time, so an IP hold set
    while the taker waits (a `10018` on another client) is waited out before the next poll."""
    clock = _FakeClock()
    waits: list[float] = []
    governor: TokenBucketGovernor | None = None

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.advance(seconds)
        if len(waits) == 1 and governor is not None:
            governor.hold_ip(30.0)

    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.01, ip_budget_per_5s=1000, clock=clock,
        sleep=sleep,
    )  # fmt: skip
    governor.drain("uid-1", EndpointClass.ORDER, 1.0)
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical")
    assert waits[:2] == [pytest.approx(1.0), pytest.approx(30.0)]
    assert all(wait <= 1.0 for wait in waits[2:])


@pytest.mark.asyncio
async def test_a_token_due_exactly_at_the_deadline_is_taken() -> None:
    """The deadline is inclusive: a wait that ends on it is waited, never refused."""
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=1.0, ip_budget_per_5s=1000, clock=clock,
        sleep=sleeps,
    )  # fmt: skip
    governor.drain("uid-1", EndpointClass.ORDER, 1.0)
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="entry", deadline_s=1.0)
    assert sleeps.waits == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_an_ip_hold_ending_exactly_at_the_deadline_is_waited_out() -> None:
    clock = _FakeClock()
    sleeps = _Sleeps(clock)
    governor = TokenBucketGovernor(clock=clock, sleep=sleeps)
    governor.hold_ip(5.0)
    await governor.acquire("uid-1", EndpointClass.ORDER, lane="critical", deadline_s=5.0)
    assert sleeps.waits == [pytest.approx(5.0)]
