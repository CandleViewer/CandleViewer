"""#1908: 10018/10006 honour `X-Bapi-Limit-Reset-Timestamp`; 10018 holds the IP.

Fixture-driven (`tests/_corpus`), MockTransport, fake clock - no real sleeps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.metrics import (
    bybit_ip_hold_remaining_seconds,
    bybit_rate_limited_total,
)
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from tests._corpus import rest

BASE_URL = "https://api-demo.bybit.com"
WALL_S = 1_000_000.0  # fake wall clock (epoch s)
OFFSET_MS = 2_000  # venue clock is 2 s ahead of local (ClockGuard offset)
OK = {"retCode": 0, "retMsg": "OK", "result": {}}


Handler = Callable[[httpx.Request], httpx.Response]


class _World:
    """Virtual time shared by the governor, the client and the sleeper."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.sent_at: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def wall(self) -> float:
        return WALL_S + self.now


def _client(
    world: _World,
    handler: Handler,
    *,
    uid: str = "public",
    governor: TokenBucketGovernor | None = None,
) -> tuple[BybitRestClient, TokenBucketGovernor]:
    gov = governor or TokenBucketGovernor(
        default_capacity=1000.0,
        default_refill_per_s=1000.0,
        clock=lambda: world.now,
        sleep=world.sleep,
    )

    def _wrapped(request: httpx.Request) -> httpx.Response:
        world.sent_at.append(world.now)
        return handler(request)

    client = BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=2),
        uid=uid,
        governor=gov,
        clock_offset_ms_provider=lambda: OFFSET_MS,
        transport=httpx.MockTransport(_wrapped),
        sleep=world.sleep,
        random_fn=lambda: 0.0,
        wall_clock=world.wall,
    )
    return client, gov


def _reset_header(world: _World, in_s: float) -> dict[str, str]:
    venue_now_ms = int((world.wall()) * 1000) + OFFSET_MS
    return {"X-Bapi-Limit-Reset-Timestamp": str(venue_now_ms + int(in_s * 1000))}


def _seq(responses: list[httpx.Response]) -> Handler:
    it = iter(responses)
    return lambda _req: next(it)


@pytest.mark.parametrize("fixture", ["rest/error_10018.json"])
async def test_rate_limit_10018_with_reset_header_waits_for_reset(fixture: str) -> None:
    world = _World()
    hdr = _reset_header(world, 30.0)
    client, _ = _client(
        world,
        _seq([httpx.Response(200, json=rest(fixture), headers=hdr), httpx.Response(200, json=OK)]),
    )
    async with client:
        await client.get_public("/v5/market/kline")
    assert world.sent_at[1] - world.sent_at[0] >= 30.0


async def test_rate_limit_10018_reset_wait_uses_clockguard_offset() -> None:
    world = _World()
    # Venue epoch 30 s ahead of *venue-now*; a client ignoring the offset would wait 32 s.
    hdr = _reset_header(world, 30.0)
    client, _ = _client(
        world,
        _seq(
            [
                httpx.Response(200, json=rest("rest/error_10018.json"), headers=hdr),
                httpx.Response(200, json=OK),
            ]
        ),
    )
    async with client:
        await client.get_public("/v5/market/kline")
    # Reset wait is exactly 30 s (offset cancelled); the 600 s IP hold then governs the retry.
    assert 30.0 in [round(s, 3) for s in world.sleeps]


async def test_rate_limit_10018_holds_every_uid_for_ten_minutes() -> None:
    world = _World()
    hdr = _reset_header(world, 5.0)
    client_a, gov = _client(
        world,
        _seq(
            [
                httpx.Response(200, json=rest("rest/error_10018.json"), headers=hdr),
                httpx.Response(200, json=OK),
            ]
        ),
        uid="acct-a",
    )
    client_b, _ = _client(
        world, lambda _r: httpx.Response(200, json=OK), uid="acct-b", governor=gov
    )
    async with client_a, client_b:
        await client_a.get_public("/v5/market/kline")
        first_a_retry = world.sent_at[1]
        assert first_a_retry - world.sent_at[0] >= 600.0
        assert gov.ip_hold_remaining_s() == 0.0  # the hold elapsed with the wait
        # a second UID after a fresh 10018 hold is also throttled
        gov.hold_ip(600.0)
        before = world.now
        await client_b.get_public("/v5/market/kline")
        assert world.sent_at[-1] - before >= 600.0


async def test_rate_limit_10006_with_reset_header_waits_without_ip_hold() -> None:
    world = _World()
    hdr = _reset_header(world, 12.0)
    client, gov = _client(
        world,
        _seq([httpx.Response(200, json=_ret(10006), headers=hdr), httpx.Response(200, json=OK)]),
    )
    async with client:
        await client.get_public("/v5/market/kline")
    assert 12.0 <= world.sent_at[1] - world.sent_at[0] < 600.0
    assert gov.ip_hold_remaining_s() == 0.0


def _ret(code: int) -> dict[str, object]:
    return {"retCode": code, "retMsg": "too many visits", "result": {}}


@pytest.mark.parametrize("raw", ["garbage", "", "1", "1000030"])  # last: seconds, not ms
async def test_rate_limit_unusable_reset_header_falls_back_to_default_backoff(raw: str) -> None:
    world = _World()
    client, _ = _client(
        world,
        _seq(
            [
                httpx.Response(
                    200, json=_ret(10006), headers={"X-Bapi-Limit-Reset-Timestamp": raw}
                ),
                httpx.Response(200, json=OK),
            ]
        ),
    )
    async with client:
        await client.get_public("/v5/market/kline")
    assert world.sleeps and max(world.sleeps) <= 2.0  # 2**1 * (0.5 + 0.0)


async def test_rate_limit_10006_increments_code_labelled_counter() -> None:
    world = _World()
    # prometheus_client exposes no public per-child read; reading `_value` is test-only.
    before = bybit_rate_limited_total.labels(code="10006")._value.get()
    client, _ = _client(
        world, _seq([httpx.Response(200, json=_ret(10006)), httpx.Response(200, json=OK)])
    )
    async with client:
        await client.get_public("/v5/market/kline")
    assert bybit_rate_limited_total.labels(code="10006")._value.get() == before + 1


async def test_rate_limit_exhausted_retries_raise_rate_limit_error() -> None:
    world = _World()
    client, _ = _client(world, lambda _r: httpx.Response(200, json=_ret(10006)))
    async with client:
        with pytest.raises(RateLimitError):
            await client.get_public("/v5/market/kline")


async def test_rate_limit_far_future_reset_header_is_clamped_to_cap() -> None:
    world = _World()
    hdr = _reset_header(world, 7 * 86_400.0)
    client, gov = _client(
        world,
        _seq([httpx.Response(200, json=_ret(10006), headers=hdr), httpx.Response(200, json=OK)]),
    )
    async with client:
        await client.get_public("/v5/market/kline")
    assert world.sent_at[1] - world.sent_at[0] == pytest.approx(900.0)
    assert gov.ip_hold_remaining_s() == 0.0


async def test_rate_limit_10018_far_future_header_holds_ip_at_most_cap() -> None:
    world = _World()
    hdr = _reset_header(world, 7 * 86_400.0)
    client, _ = _client(
        world,
        _seq(
            [
                httpx.Response(200, json=rest("rest/error_10018.json"), headers=hdr),
                httpx.Response(200, json=OK),
            ]
        ),
    )
    async with client:
        await client.get_public("/v5/market/kline")
    assert world.sent_at[1] - world.sent_at[0] == pytest.approx(900.0)


def test_governor_hold_ip_never_extends_beyond_cap() -> None:
    world = _World()
    gov = TokenBucketGovernor(clock=lambda: world.now, sleep=world.sleep)
    gov.hold_ip(10**9)
    assert gov.ip_hold_remaining_s() == pytest.approx(900.0)
    assert bybit_ip_hold_remaining_seconds._value.get() == pytest.approx(900.0)


async def test_governor_hold_gauge_clears_after_hold_elapses() -> None:
    world = _World()
    gov = TokenBucketGovernor(clock=lambda: world.now, sleep=world.sleep)
    gov.hold_ip(600.0)
    await gov.acquire("u", EndpointClass.MARKET_DATA, lane="poll")
    assert bybit_ip_hold_remaining_seconds._value.get() == 0.0


async def test_governor_acquire_queued_on_lock_observes_hold_set_meanwhile() -> None:
    world = _World()
    gov = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=1.0, clock=lambda: world.now, sleep=world.sleep
    )
    bucket = gov._get_bucket("u", EndpointClass.MARKET_DATA)
    await bucket.lock.acquire()
    waiter = asyncio.create_task(gov.acquire("u", EndpointClass.MARKET_DATA, lane="poll"))
    await asyncio.sleep(0)  # waiter is now queued on the bucket lock, past the first check
    gov.hold_ip(600.0)
    bucket.lock.release()
    await waiter
    assert world.now >= 600.0
