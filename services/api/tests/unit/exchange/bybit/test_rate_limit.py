"""Token-bucket tests (ticket scenario "Rate budget is shared per UID").

Uses an injected, manually-advanced clock — no real `time.sleep`/wall-clock
waits (`40-testing.md` "No sleeps: fake clocks").
"""

from __future__ import annotations

import asyncio

import pytest

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
