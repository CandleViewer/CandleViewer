"""`BybitRestClient.headroom` (E08-T10, #5111): the public client's `MARKET_DATA` headroom, read
from the governor without taking a token, which the instrument refresh route checks before it
schedules a fetch (C-12.7). No request is made (C-13.5)."""

from __future__ import annotations

import httpx

from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient


def _refuse(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request expected: {request.url}")


async def test_headroom_reads_the_public_market_data_bucket_without_taking_a_token() -> None:
    governor = TokenBucketGovernor()
    config = RestClientConfig(base_url="https://api.bybit.com")
    async with BybitRestClient(
        config, governor=governor, transport=httpx.MockTransport(_refuse)
    ) as client:
        tokens, wait_s = client.headroom()
        assert tokens >= 1.0 and wait_s == 0.0
        assert client.headroom() == (tokens, wait_s)  # a read spends nothing
        expected = governor.headroom("public", EndpointClass.MARKET_DATA, lane="poll")
        assert client.headroom() == expected


async def test_headroom_reports_an_empty_bucket_and_its_wait() -> None:
    governor = TokenBucketGovernor()
    config = RestClientConfig(base_url="https://api.bybit.com")
    async with BybitRestClient(
        config, governor=governor, transport=httpx.MockTransport(_refuse)
    ) as client:
        tokens, _ = client.headroom()
        governor.drain("public", EndpointClass.MARKET_DATA, tokens + 5.0)
        drained, wait_s = client.headroom()
        assert drained < 1.0 and wait_s > 0.0
