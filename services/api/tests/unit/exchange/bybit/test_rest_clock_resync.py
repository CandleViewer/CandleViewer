"""#1911: a 10002 re-measures the clock (ClockGuard) before the single retry re-signs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from candleviewer.exchange.base.errors import ClockDriftError
from candleviewer.exchange.bybit import rest as rest_module
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.metrics import clock_resync_triggered_total
from tests._corpus import rest
from tests._signing import CREDENTIAL_ID, fake_capability

BASE_URL = "https://api-demo.bybit.com"
PATH = "/v5/account/wallet-balance"
OK = {"retCode": 0, "retMsg": "OK", "result": {}}
WALL_S = 1_000_000.0


async def _no_sleep(_s: float) -> None:
    return None


def _client(
    handler: httpx.MockTransport,
    *,
    offset_ms: Callable[[], int],
    hook: Callable[[], Awaitable[object]] | None = None,
    max_retries: int = 3,
) -> BybitRestClient:
    return BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=max_retries),
        signer=BybitSigner(fake_capability("K"), CREDENTIAL_ID),
        governor=TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0),
        clock_offset_ms_provider=offset_ms,
        transport=handler,
        sleep=_no_sleep,
        wall_clock=lambda: WALL_S,
        on_signature_failure=hook,
    )


async def test_signed_request_10002_resyncs_before_retry_and_resigns_with_fresh_offset() -> None:
    offset = [-10_000]  # host clock jumped back 10 s
    stamps: list[str] = []
    order: list[str] = []
    bodies = iter([rest("rest/error_10002.json"), OK])

    def handler(req: httpx.Request) -> httpx.Response:
        stamps.append(req.headers["X-BAPI-TIMESTAMP"])
        order.append("request")
        return httpx.Response(200, json=next(bodies))

    async def resync() -> None:
        order.append("resync")
        offset[0] = 0  # the re-measure corrected the offset

    client = _client(httpx.MockTransport(handler), offset_ms=lambda: offset[0], hook=resync)
    async with client:
        data = await client.signed_request("GET", PATH)
    assert data["retCode"] == 0
    assert order == ["request", "resync", "request"]
    assert stamps == [str(int(WALL_S * 1000) - 10_000), str(int(WALL_S * 1000))]


async def test_signed_request_second_10002_raises_clock_drift_after_one_resync() -> None:
    calls = [0]

    async def resync() -> None:
        calls[0] += 1

    transport = httpx.MockTransport(
        lambda _r: httpx.Response(200, json=rest("rest/error_10002.json"))
    )
    client = _client(transport, offset_ms=lambda: 0, hook=resync)
    async with client:
        with pytest.raises(ClockDriftError):
            await client.signed_request("GET", PATH)
    assert calls == [1]


async def test_signed_request_failing_resync_hook_still_raises_clock_drift() -> None:
    async def resync() -> None:
        raise RuntimeError("time endpoint down")

    transport = httpx.MockTransport(
        lambda _r: httpx.Response(200, json=rest("rest/error_10002.json"))
    )
    client = _client(transport, offset_ms=lambda: 0, hook=resync)
    async with client:
        with pytest.raises(ClockDriftError):
            await client.signed_request("GET", PATH)


async def test_signed_request_10002_without_hook_retries_once_then_raises() -> None:
    n = [0]

    def handler(_r: httpx.Request) -> httpx.Response:
        n[0] += 1
        return httpx.Response(200, json=rest("rest/error_10002.json"))

    client = _client(httpx.MockTransport(handler), offset_ms=lambda: 0)
    async with client:
        with pytest.raises(ClockDriftError):
            await client.signed_request("GET", PATH)
    assert n[0] == 2


async def test_signed_request_10002_with_clockguard_hook_counts_metric_and_resigns() -> None:
    # Venue clock is 10 s ahead of local; ClockGuard measures that on resync.
    async def fetch() -> tuple[int, float, float]:
        return int((WALL_S + 10.0) * 1_000_000), WALL_S, 0.0

    guard = ClockGuard(fetch, sample_count=1)
    stamps: list[int] = []
    bodies = iter([rest("rest/error_10002.json"), OK])

    def handler(req: httpx.Request) -> httpx.Response:
        stamps.append(int(req.headers["X-BAPI-TIMESTAMP"]))
        return httpx.Response(200, json=next(bodies))

    before = clock_resync_triggered_total.labels(reason="signature_failure")._value.get()
    client = _client(
        httpx.MockTransport(handler),
        offset_ms=lambda: guard.offset_us() // 1000,
        hook=guard.resync_after_signature_failure,
    )
    async with client:
        await client.signed_request("GET", PATH)
    after = clock_resync_triggered_total.labels(reason="signature_failure")._value.get()
    assert after == before + 1
    assert stamps[1] - stamps[0] == 10_000  # retry re-signed with the fresh offset
    assert guard.health_severity() == "critical"  # drift alarm state (E08-S07)


async def test_signed_request_hung_resync_hook_times_out_and_retry_still_happens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rest_module, "_SIGNATURE_RESYNC_TIMEOUT_S", 0.01)
    never = asyncio.Event()  # never set: the hook hangs forever
    n = [0]

    async def hung() -> None:
        await never.wait()

    def handler(_r: httpx.Request) -> httpx.Response:
        n[0] += 1
        return httpx.Response(200, json=rest("rest/error_10002.json"))

    client = _client(httpx.MockTransport(handler), offset_ms=lambda: 0, hook=hung)
    async with client:
        with pytest.raises(ClockDriftError):
            await client.signed_request("GET", PATH)
    assert n[0] == 2  # the single retry still happened after the bounded wait
