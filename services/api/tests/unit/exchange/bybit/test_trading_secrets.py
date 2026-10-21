"""No credential leaves the trading port (G-8, #2877; SR-E29-08 item 4, C-2.7, C-12.6).

A Hypothesis run seeds the call's own key id and signature where a venue could echo them: the
answer's message, its result fields known and unknown, a malformed body and the response
headers. None of them may reach an ack, a record, a raised exception (its text, chain or
traceback) or a log line. The REST client masks its own credential values in an answer before
decoding it; the port strips every exception it raises of cause and context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import CancelOrderRequest
from candleviewer.exchange.bybit.rest import _mask
from candleviewer.exchange.bybit.trading import BybitTradingPort
from tests._corpus import rest
from tests._signing import fake_capability
from tests.unit.exchange.bybit._trading import RecordingGovernor, account, link, place

_SIGNER_IDS = st.text(
    alphabet="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789", min_size=18, max_size=36
)
_WHERE = st.sampled_from(["message", "unknown-field", "known-field", "malformed", "header"])
_CALL = st.sampled_from(["cancel", "create", "read"])


def _echo(where: str, call: str) -> Callable[[httpx.Request], httpx.Response]:
    """A venue that echoes the request's own key id and signature in one place."""

    def handler(request: httpx.Request) -> httpx.Response:
        key, sig = request.headers["X-BAPI-API-KEY"], request.headers["X-BAPI-SIGN"]
        seeded = f"seen {key} and {sig}"
        base = rest("rest/trading-cancel-reply.json")
        if call == "read":
            base = rest("rest/trading-account-info.json")
        if where == "message":
            body: Any = {"retCode": 110001, "retMsg": seeded}
        elif where == "unknown-field":
            body = {**base, "result": {**base["result"], "echo": seeded}}
        elif where == "known-field":
            field = "marginMode" if call == "read" else "orderLinkId"
            body = {**base, "result": {**base["result"], field: seeded}}
        elif where == "malformed":
            return httpx.Response(200, content=f'{{"retCode":0,"result":"{seeded}"'.encode())
        else:
            return httpx.Response(200, json=base, headers={"X-Echo": seeded})
        return httpx.Response(200, json=body)

    return handler


async def _run(port: BybitTradingPort, call: str) -> list[str]:
    """Everything the call hands back or raises, as text."""
    out: list[str] = []
    try:
        if call == "cancel":
            request = CancelOrderRequest(account=account(), symbol="BTCUSDT", order_link_id=link())
            out.append((await port.cancel_order(request)).model_dump_json())
        elif call == "create":
            out.append((await port.place_order(place())).model_dump_json())
        else:
            out.append((await port.account_info(account())).model_dump_json())
    except ExchangeError as exc:
        out += ["".join(traceback.format_exception(exc)), repr(exc), str(exc.user_message)]
        chained: BaseException | None = exc
        while chained is not None:
            out.append(repr(chained))
            chained = chained.__cause__ or chained.__context__
    return out


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(key_id=_SIGNER_IDS, where=_WHERE, call=_CALL)
def test_no_seeded_credential_reaches_an_ack_a_record_an_exception_or_a_log(
    key_id: str, where: str, call: str, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[httpx.Request] = []
    handler = _echo(where, call)

    def recording(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    port = BybitTradingPort(
        environment="demo",
        credentials=fake_capability(key_id),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(recording),
        max_retries=0,
    )
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    with capture_logs() as logs:
        texts = asyncio.run(_run(port, call))
    texts += [json.dumps(logs, default=str), caplog.text]

    signatures = {request.headers["X-BAPI-SIGN"] for request in sent}
    assert sent and all(request.headers["X-BAPI-API-KEY"] == key_id for request in sent)
    for secret in (key_id, *signatures):
        assert all(secret not in text for text in texts), where
    assert all("sign" not in str(request.url.params).lower() for request in sent)


def test_the_client_masks_only_values_long_enough_to_be_its_credentials() -> None:
    """A key id or MAC is never this short; masking a short value would rewrite the body."""
    body = b'{"retMsg":"key fixture-signer-id and k","takeProfit":"0"}'
    masked = _mask(body, ("fixture-signer-id", "k"))
    assert masked == b'{"retMsg":"key **redacted** and k","takeProfit":"0"}'
    assert _mask(body, ()) == body


#: A figure a reply could carry (an equity, a balance): it must stay out of every error text.
_FIGURE = "987654321.123456789"


def _port(handler: Callable[[httpx.Request], httpx.Response]) -> BybitTradingPort:
    return BybitTradingPort(
        environment="demo",
        credentials=fake_capability("fixture-signer-id"),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )


@pytest.mark.parametrize("call", ["read", "cancel"])
async def test_a_reply_without_a_return_code_leaves_none_of_its_content_in_the_error(
    call: str,
) -> None:
    """Ruling 11: the error names the body's type and size, never what it holds."""
    unanswered = {"retMsg": "OK", "result": {"totalEquity": _FIGURE, "orderId": _FIGURE}}
    port = _port(lambda _request: httpx.Response(200, json=unanswered))

    texts = await _run(port, call)

    assert any("no usable retCode (dict," in text for text in texts)
    assert all(_FIGURE not in text for text in texts)


async def test_a_transport_fault_leaves_none_of_its_httpx_text_in_the_error() -> None:
    def gone(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"socket gone reading {_FIGURE}", request=request)

    texts = await _run(_port(gone), "read")

    assert any("(ReadTimeout)" in text for text in texts)
    assert all(_FIGURE not in text for text in texts)


@pytest.mark.parametrize("failure", ["5xx", "unreadable", "venue-code"])
async def test_no_frame_of_a_raised_error_holds_the_signed_request(failure: str) -> None:
    """SR-E29-08: the port strips the traceback too. The REST client's frames, whose locals
    hold the signed headers, never travel with an error the port raises: no frame is the
    client's or the port's attempt, and no frame of the product holds the key id or a MAC."""
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if failure == "5xx":
            return httpx.Response(503, json=rest("rest/error_503.json"))
        if failure == "unreadable":
            return httpx.Response(200, content=b'{"retCode":0,"result":')
        return httpx.Response(200, json={"retCode": 10001, "retMsg": "params error"})

    port = _port(answer)
    with pytest.raises(ExchangeError) as caught:
        if failure == "venue-code":
            await port.account_info(account())
        else:
            request = CancelOrderRequest(account=account(), symbol="BTCUSDT", order_link_id=link())
            await port.cancel_order(request)

    frames = []
    tb = caught.value.__traceback__
    while tb is not None:
        frames.append(tb.tb_frame)
        tb = tb.tb_next
    names = {frame.f_code.co_name for frame in frames}
    assert sent and not names & {"_request", "signed_request", "_attempt"}
    secrets = {"fixture-signer-id", *(request.headers["X-BAPI-SIGN"] for request in sent)}
    product = [f for f in frames if "/candleviewer/" in f.f_code.co_filename.replace("\\", "/")]
    assert product and not any(s in repr(f.f_locals) for f in product for s in secrets)
