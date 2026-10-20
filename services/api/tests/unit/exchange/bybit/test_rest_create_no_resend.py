"""G-7 (#3866, SR-E29-15): the REST client never resends an order create that has left.

24 §8.6 "Order creates". Bodies are the corpus 503 (`rest/error_503.json`) and the `retCode`
envelope the REST tests already use; failures are httpx's own errors from a `MockTransport`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.base.errors import AmbiguousResultError, ExchangeError, TransportError
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import http_status, rest
from tests._signing import CREDENTIAL_ID, fake_capability

Outcome = Callable[[httpx.Request], httpx.Response]
Sent = list[httpx.Request]
CREATE = "/v5/order/create"
ERR_503 = "rest/error_503.json"


def _raise(error: type[Exception]) -> Outcome:
    def outcome(request: httpx.Request) -> httpx.Response:
        if issubclass(error, httpx.TransportError):
            raise error("injected", request=request)
        raise error("injected")

    return outcome


def _ret(code: int) -> Outcome:
    return lambda _: httpx.Response(200, json={"retCode": code, "retMsg": "x", "result": {}})


OK = _ret(0)
#: After the send: the create may have reached the exchange.
LEFT: dict[str, Outcome] = {
    "read-timeout": _raise(httpx.ReadTimeout),
    "write-timeout": _raise(httpx.WriteTimeout),
    "read-error": _raise(httpx.ReadError),
    "write-error": _raise(httpx.WriteError),
    "remote-protocol": _raise(httpx.RemoteProtocolError),
    "bare-timeout": _raise(TimeoutError),
    "5xx": lambda _: httpx.Response(http_status(ERR_503), json=rest(ERR_503)),
    "10016": _ret(10016),
    "10019": _ret(10019),
}
#: Before any byte left: connecting, or waiting for a pooled connection.
NOT_SENT: dict[str, Outcome] = {
    "connect-error": _raise(httpx.ConnectError),
    "connect-timeout": _raise(httpx.ConnectTimeout),
    "pool-timeout": _raise(httpx.PoolTimeout),
}


def _client(outcomes: list[Outcome], sent: Sent, sleeps: list[float]) -> BybitRestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return outcomes[min(len(sent), len(outcomes)) - 1](request)  # the last one repeats

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com", max_retries=3),
        signer=BybitSigner(fake_capability("k"), CREDENTIAL_ID),
        governor=TokenBucketGovernor(default_capacity=1e3, default_refill_per_s=1e3),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )


async def _post(
    outcomes: list[Outcome], path: str = CREATE, cls: EndpointClass = EndpointClass.ORDER
) -> tuple[ExchangeError | None, Sent]:
    sent: Sent = []
    async with _client(outcomes, sent, []) as client:
        body = {"symbol": "BTCUSDT", "orderLinkId": "cv-1"}
        try:
            await client.signed_request("POST", path, body=body, endpoint_class=cls)
        except ExchangeError as error:
            return error, sent
    return None, sent


@pytest.mark.parametrize("path", [CREATE, "/v5/order/create-batch"])
@pytest.mark.parametrize("outcome", LEFT.values(), ids=LEFT.keys())
async def test_a_create_that_left_is_ambiguous_and_sent_once(path: str, outcome: Outcome) -> None:
    error, sent = await _post([outcome, OK], path)

    assert isinstance(error, AmbiguousResultError) and len(sent) == 1
    assert error.order_link_id == "cv-1" and error.retryable is False


@pytest.mark.parametrize("outcome", NOT_SENT.values(), ids=NOT_SENT.keys())
async def test_a_create_that_never_left_is_retried_under_the_same_id(outcome: Outcome) -> None:
    error, sent = await _post([outcome, OK])
    assert error is None and len(sent) == 2 and sent[0].content == sent[1].content

    error, sent = await _post([outcome])  # the retries run out: plain, never ambiguous
    assert type(error) is TransportError and len(sent) == 4


@pytest.mark.parametrize(
    ("path", "cls"),
    [
        ("/v5/order/amend", EndpointClass.ORDER),
        ("/v5/order/cancel", EndpointClass.ORDER),
        ("/v5/position/trading-stop", EndpointClass.POSITION),
    ],
)
@pytest.mark.parametrize("outcome", ["read-timeout", "5xx", "10016"])
async def test_amend_cancel_and_trading_stop_keep_their_retry(
    path: str, cls: EndpointClass, outcome: str
) -> None:
    error, sent = await _post([LEFT[outcome]], path, cls)

    assert error is not None and not isinstance(error, AmbiguousResultError) and len(sent) == 4


@pytest.mark.parametrize("signed", [False, True], ids=["market-data", "account"])
@pytest.mark.parametrize("outcome", ["read-timeout", "5xx", "10016", "10019"])
async def test_reads_keep_their_retry_with_full_jitter(signed: bool, outcome: str) -> None:
    sent: Sent = []
    sleeps: list[float] = []
    async with _client([LEFT[outcome]], sent, sleeps) as client:
        with pytest.raises(ExchangeError) as caught:
            if signed:
                await client.signed_request("GET", "/v5/account/wallet-balance")
            else:
                await client.get_public("/v5/market/kline")

    assert not isinstance(caught.value, AmbiguousResultError) and len(sent) == 4
    assert all(2**n / 2 <= wait <= 2**n for n, wait in enumerate(sleeps, 1)) and len(sleeps) == 3


@given(
    st.lists(st.sampled_from([*LEFT, *NOT_SENT, "10006", "10002", "ok"]), min_size=1, max_size=8)
)
def test_no_outcome_sequence_sends_a_create_again_after_it_left(kinds: list[str]) -> None:
    table = LEFT | NOT_SENT | {"10006": _ret(10006), "10002": _ret(10002), "ok": OK}
    _, sent = asyncio.run(_post([table[kind] for kind in kinds]))

    met = [kinds[min(i, len(kinds) - 1)] for i in range(len(sent))]
    assert not any(kind in LEFT for kind in met[:-1])
