"""G-7 (#3866, SR-E29-15): the REST client never resends an order create that has left.

24 §8.6 "Order creates", under any endpoint class. Bodies are the corpus 503
(`rest/error_503.json`), the `retCode` envelope the REST tests already use and the unreadable
bodies of `test_contract_errors.py`, plus bodies no venue sends (JSON null, a non-integer
`retCode`, a corrupt gzip, a body over the cap, an array nested 100 000 deep); failures are
httpx's own errors from a `MockTransport`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    ExchangeError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.metrics import bybit_rate_limited_total, bybit_rest_requests_total
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient, RestBodyTooLarge
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import http_status, rest
from tests._signing import CREDENTIAL_ID, fake_capability

Outcome = Callable[[httpx.Request], httpx.Response]
Sent = list[httpx.Request]
CREATE = "/v5/order/create"
ERR_503 = "rest/error_503.json"
OVERSIZED = b" " * (2 * 1024 * 1024 + 1)  # over every endpoint class's body cap
DEEP = b"[" * 100_000 + b"]" * 100_000  # valid JSON, past the parser's recursion limit


def _raise(error: type[Exception]) -> Outcome:
    def outcome(request: httpx.Request) -> httpx.Response:
        if issubclass(error, httpx.TransportError):
            raise error("injected", request=request)
        raise error("injected")

    return outcome


def _ret(code: object) -> Outcome:
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
    "non-json": lambda _: httpx.Response(200, text='{"retCode":0,"res'),
    "undecodable": lambda _: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip")
    ),
    "oversized": lambda _: httpx.Response(200, content=OVERSIZED),
    "deep-nesting": lambda _: httpx.Response(200, content=DEEP),
    "no-retcode": lambda _: httpx.Response(200, json={"result": {}}),
    "json-null": lambda _: httpx.Response(200, content=b"null"),
    "json-number": lambda _: httpx.Response(200, content=b"123"),
    "retcode-text": _ret("abc"),
    "retcode-null": _ret(None),
    "retcode-float": _ret(0.5),
    "retcode-false": _ret(False),
    "4xx-retcode-0": lambda _: httpx.Response(422, json={"retCode": 0, "retMsg": "OK"}),
    "10016": _ret(10016),
    "10019": _ret(10019),
}
#: Before any byte left: connecting, or waiting for a pooled connection.
NOT_SENT: dict[str, Outcome] = {
    "connect-error": _raise(httpx.ConnectError),
    "connect-timeout": _raise(httpx.ConnectTimeout),
    "pool-timeout": _raise(httpx.PoolTimeout),
}


def _create_body(path: str) -> dict[str, object]:
    """A create's body as the client must get it: `category` stated (SR-054), and the id on the
    create, or on every item of a batch (#2877)."""
    item = {"symbol": "BTCUSDT", "orderLinkId": "cv-1"}
    if path == "/v5/order/create-batch":
        return {"category": "linear", "request": [item]}
    return {"category": "linear", **item}


def _client(
    outcomes: list[Outcome],
    sent: Sent,
    sleeps: list[float],
    governor: TokenBucketGovernor | None = None,
) -> BybitRestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return outcomes[min(len(sent), len(outcomes)) - 1](request)  # the last one repeats

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com", max_retries=3),
        signer=BybitSigner(fake_capability("k"), CREDENTIAL_ID),
        governor=governor or TokenBucketGovernor(default_capacity=1e3, default_refill_per_s=1e3),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )


async def _post(
    outcomes: list[Outcome],
    path: str = CREATE,
    cls: EndpointClass = EndpointClass.ORDER,
    governor: TokenBucketGovernor | None = None,
) -> tuple[ExchangeError | None, Sent]:
    sent: Sent = []
    async with _client(outcomes, sent, [], governor) as client:
        body = _create_body(path)
        try:
            await client.signed_request("POST", path, body=body, endpoint_class=cls, lane="entry")
        except ExchangeError as error:
            return error, sent
    return None, sent


@pytest.mark.parametrize("cls", list(EndpointClass), ids=str)
@pytest.mark.parametrize(
    ("path", "order_link_id", "order_link_ids"),
    [(CREATE, "cv-1", ("cv-1",)), ("/v5/order/create-batch", None, ("cv-1",))],
    ids=["create", "create-batch"],
)
@pytest.mark.parametrize("outcome", LEFT.values(), ids=LEFT.keys())
async def test_a_create_that_left_is_ambiguous_and_sent_once(
    path: str,
    order_link_id: str | None,
    order_link_ids: tuple[str, ...],
    outcome: Outcome,
    cls: EndpointClass,
) -> None:
    counters = [
        exchange_errors_total.labels(**{"class": c}) for c in ("TRANSPORT_ERROR", "UNKNOWN_STATE")
    ]
    before = [counter._value.get() for counter in counters]  # test-only read, as below

    error, sent = await _post([outcome, OK], path, cls)

    assert isinstance(error, AmbiguousResultError) and len(sent) == 1
    assert (error.order_link_id, error.order_link_ids) == (order_link_id, order_link_ids)
    assert error.retryable is False
    assert [c._value.get() - b for c, b in zip(counters, before, strict=True)] == [1, 0]


async def test_an_oversized_create_answer_keeps_the_caps_count_and_warning() -> None:
    """SR-E12-09's metric and log stay; the request is not counted a second time."""
    counters = [
        bybit_rest_requests_total.labels(endpoint=CREATE, result=r) for r in ("oversized", "error")
    ]
    before = [counter._value.get() for counter in counters]  # test-only read, as elsewhere

    with capture_logs() as logs:
        error, _ = await _post([LEFT["oversized"]])

    assert isinstance(error, AmbiguousResultError) and type(error.__cause__) is RestBodyTooLarge
    assert [c._value.get() - b for c, b in zip(counters, before, strict=True)] == [1, 0]
    warnings = [log["event"] for log in logs if log["log_level"] == "warning"]
    assert warnings == ["bybit_rest_body_too_large", "bybit_rest_create_ambiguous"]


@pytest.mark.parametrize("code", [10016, 10019])
async def test_a_create_10016_or_10019_is_counted_as_raised_never_as_a_rate_limit(
    code: int,
) -> None:
    """#2863, order paths: no bucket drain, no rate-limit counter; the venue's code is kept."""
    counters = [
        bybit_rate_limited_total.labels(code=str(code)),
        exchange_errors_total.labels(**{"class": "RATE_LIMITED"}),
        exchange_errors_total.labels(**{"class": "TRANSPORT_ERROR"}),
    ]
    before = [counter._value.get() for counter in counters]  # test-only read, as elsewhere
    governor = TokenBucketGovernor(default_capacity=9, clock=lambda: 0.0)  # it never refills

    error, _ = await _post([_ret(code)], governor=governor)

    assert [c._value.get() - b for c, b in zip(counters, before, strict=True)] == [0, 0, 1]
    assert governor.remaining("public", EndpointClass.ORDER) == 8  # the attempt's own token
    assert isinstance(error, AmbiguousResultError)
    assert (error.exchange_ret_code, error.exchange_ret_msg) == (code, "x")


@pytest.mark.parametrize("outcome", NOT_SENT.values(), ids=NOT_SENT.keys())
async def test_a_create_that_never_left_is_retried_under_the_same_id(outcome: Outcome) -> None:
    error, sent = await _post([outcome, OK])
    assert error is None and len(sent) == 2 and sent[0].content == sent[1].content

    error, sent = await _post([outcome])  # the retries run out: plain, never ambiguous
    assert type(error) is TransportError and len(sent) == 4


@pytest.mark.parametrize("code", [10006, 10002])
async def test_a_create_the_venue_refused_unprocessed_is_retried_under_the_same_id(
    code: int,
) -> None:
    """A rate-limit refusal, or the single 10002 re-measure: the venue created nothing."""
    error, sent = await _post([_ret(code), OK])
    assert error is None and len(sent) == 2 and sent[0].content == sent[1].content


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
    """A transport fault or a 5xx takes the client's 3 retries; the venue's outage takes 3
    attempts in all, as 24 §8.6's rows say (#2863)."""
    error, sent = await _post([LEFT[outcome]], path, cls)

    assert error is not None and not isinstance(error, AmbiguousResultError)
    assert len(sent) == (3 if outcome == "10016" else 4)


@pytest.mark.parametrize("code", [110079, 999999])
async def test_a_create_answered_with_an_open_outcome_code_is_never_retryable(code: int) -> None:
    """110079, or a code the mapping lacks: polled and reconciled, never resent (24 §8.6)."""
    error, sent = await _post([_ret(code), OK])
    assert isinstance(error, UnknownStateError) and error.retryable is False and len(sent) == 1

    error, sent = await _post([_ret(code), OK], "/v5/order/cancel")  # other paths: unchanged
    assert isinstance(error, UnknownStateError) and error.retryable is True and len(sent) == 1


@pytest.mark.parametrize("path", ["/v5/order/amend", "/v5/order/cancel"])
@pytest.mark.parametrize(
    "outcome", ["undecodable", "json-null", "retcode-text", "oversized", "deep-nesting"]
)
async def test_amend_and_cancel_skip_the_create_only_answer_checks(path: str, outcome: str) -> None:
    sent: Sent = []
    untyped = (TypeError, ValueError, RecursionError, httpx.DecodingError)  # as before #3866
    async with _client([LEFT[outcome]], sent, []) as client:
        with pytest.raises((ExchangeError, *untyped)) as caught:
            body = _create_body(path)
            await client.signed_request(
                "POST", path, body=body, endpoint_class=EndpointClass.ORDER, lane="entry"
            )

    assert not isinstance(caught.value, AmbiguousResultError) and len(sent) == 1


@pytest.mark.parametrize("signed", [False, True], ids=["market-data", "account"])
@pytest.mark.parametrize("outcome", ["read-timeout", "5xx", "10016", "10019"])
async def test_reads_keep_their_retry_with_full_jitter(signed: bool, outcome: str) -> None:
    sent: Sent = []
    sleeps: list[float] = []
    async with _client([LEFT[outcome]], sent, sleeps) as client:
        with pytest.raises(ExchangeError) as caught:
            if signed:
                await client.signed_request("GET", "/v5/account/wallet-balance", lane="poll")
            else:
                await client.get_public("/v5/market/kline")

    attempts = 3 if outcome in ("10016", "10019") else 4  # the venue's outage: 3 (#2863)
    assert not isinstance(caught.value, AmbiguousResultError) and len(sent) == attempts
    assert all(2**n / 2 <= wait <= 2**n for n, wait in enumerate(sleeps, 1))
    assert len(sleeps) == attempts - 1


@given(
    st.lists(st.sampled_from([*LEFT, *NOT_SENT, "10006", "10002", "ok"]), min_size=1, max_size=8),
    st.sampled_from(EndpointClass),
)
def test_no_outcome_sequence_sends_a_create_again_after_it_left(
    kinds: list[str], cls: EndpointClass
) -> None:
    table = LEFT | NOT_SENT | {"10006": _ret(10006), "10002": _ret(10002), "ok": OK}
    _, sent = asyncio.run(_post([table[kind] for kind in kinds], CREATE, cls))

    met = [kinds[min(i, len(kinds) - 1)] for i in range(len(sent))]
    assert not any(kind in LEFT for kind in met[:-1])
