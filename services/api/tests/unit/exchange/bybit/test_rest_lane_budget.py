"""A lane's wait bounds the whole signed call, retries included (G-8, #2877; 24 §8.7).

Each attempt takes its own token within what is left of the wait; a retry whose pause (a backoff,
the venue's reset time or an IP hold) would end past it is not made, and the last attempt's own
failure is raised at once; a token refused once something has been sent raises that failure, so
"nothing was sent" is said only when it is true. Without a wait (the public clients) the retries
are as before. Virtual time: the governor's clock, the client's and the sleeper are one; no network.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from candleviewer.exchange.base.errors import (
    RateBudgetExceededError,
    RateLimitError,
    TransportError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import http_status, rest
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.unit.exchange.bybit._trading import FakeClock

BASE_URL = "https://api-demo.bybit.com"
CANCEL_BODY = {"category": "linear", "symbol": "BTCUSDT", "orderId": "e-1"}
CREATE_BODY = {"category": "linear", "symbol": "BTCUSDT", "orderLinkId": "cv-link-1"}
#: The documented rate-limit envelope with the other code, a test input.
LIMITED_10006 = {**rest("rest/error_10018.json"), "retCode": 10006}
UNAVAILABLE = rest("rest/error_503.json")


def _client(
    clock: FakeClock,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    governor: TokenBucketGovernor | None = None,
) -> tuple[BybitRestClient, TokenBucketGovernor]:
    """A signed client with three retries and no jitter (each backoff is its floor: 1, 2, 4 s)."""
    gov = governor or TokenBucketGovernor(
        default_capacity=1000.0, default_refill_per_s=1000.0, clock=clock.now, sleep=clock.sleep
    )
    client = BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=3),
        uid="100001",
        signer=BybitSigner(fake_capability("fixture-signer-id"), CREDENTIAL_ID),
        governor=gov,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        random_fn=lambda: 0.0,
        monotonic=clock.now,
    )
    return client, gov


def _unavailable(sent: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(http_status("rest/error_503.json"), json=UNAVAILABLE)

    return handler


async def _cancel(client: BybitRestClient, wait_s: float | None) -> object:
    async with client:
        return await client.signed_request(
            "POST",
            "/v5/order/cancel",
            body=CANCEL_BODY,
            endpoint_class=EndpointClass.ORDER,
            lane="critical",
            budget_wait_s=wait_s,
        )


async def test_a_lane_wait_stops_the_backoffs_that_would_end_past_it() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    client, _ = _client(clock, _unavailable(sent))

    with pytest.raises(TransportError, match="HTTP 503 after 3 attempts"):
        await _cancel(client, 5.0)

    assert clock.sleeps == [1.0, 2.0] and len(sent) == 3  # a third pause (4 s) would end at 7 s


async def test_without_a_lane_wait_every_retry_is_made_as_before() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    client, _ = _client(clock, _unavailable(sent))

    with pytest.raises(TransportError, match="HTTP 503 after 4 attempts"):
        await _cancel(client, None)

    assert clock.sleeps == [1.0, 2.0, 4.0] and len(sent) == 4


async def test_a_hold_set_while_the_call_was_out_stops_its_retry_at_once() -> None:
    """Another client's `10018` holds the IP for 10 s while this cancel is answered `10006`:
    its 1 s backoff fits the 5 s wait, the hold does not, so the answer comes back unslept."""
    clock = FakeClock()
    governor = TokenBucketGovernor(clock=clock.now, sleep=clock.sleep)
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        governor.hold_ip(10.0)
        return httpx.Response(200, json=LIMITED_10006)

    client, _ = _client(clock, handler, governor=governor)

    with pytest.raises(RateLimitError) as limited:
        await _cancel(client, 5.0)

    assert limited.value.exchange_ret_code == 10006
    assert (clock.sleeps, len(sent)) == ([], 1)


async def test_a_token_refused_after_only_unsent_attempts_says_nothing_was_sent() -> None:
    """A connect error proves nothing left; when the retry's token is then refused, nothing
    was sent at all, and the refusal says so."""
    clock = FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )
    sent: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        raise httpx.ConnectError("refused", request=request)

    client, _ = _client(clock, refuse, governor=governor)

    async with client:
        with pytest.raises(RateBudgetExceededError, match="nothing was sent"):
            await client.signed_request(
                "POST",
                "/v5/order/create",
                body=CREATE_BODY,
                endpoint_class=EndpointClass.ORDER,
                lane="critical",
                budget_wait_s=5.0,
            )

    assert len(sent) == 1 and clock.sleeps == [1.0]


async def test_a_token_refused_after_a_sent_attempt_raises_that_attempts_failure() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )
    client, _ = _client(clock, _unavailable(sent), governor=governor)

    with pytest.raises(TransportError, match="HTTP 503 after 1 attempts"):
        await _cancel(client, 5.0)

    assert len(sent) == 1 and clock.sleeps == [1.0]  # the answer, never "nothing was sent"
