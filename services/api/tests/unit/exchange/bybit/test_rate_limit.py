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
