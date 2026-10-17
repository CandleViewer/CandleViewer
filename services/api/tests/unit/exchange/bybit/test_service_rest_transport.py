"""#2893 S4: the exchange adapter's account REST transport, chosen once when the adapter is built.

The seam agreed with #836's owner: `ExchangeBybitService(rest_transport=...)` keeps the transport
and `key_verification_calls` builds every key-verification client on it. Production passes none, so
httpx keeps its own transport and the request path gains no branch; that, and the composition
root's side, are in `tests/unit/test_account_fixture_wiring.py`. Replies: the documented-shape
`tests/fixtures/key_verification/` (README there). `respx` answers nothing here, so a request that
missed the injected transport fails instead of leaving the process. No network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import respx
from structlog.testing import capture_logs

from candleviewer.exchange.bybit import key_verify
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, PROBE_PATH
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.logging import reset_logging
from tests._signing import CREDENTIAL_ID, fake_capability

FIXTURES = Path(__file__).parents[3] / "fixtures" / "key_verification"
REPLIES = {KEY_INFO_PATH: "key_info_trade.json", PROBE_PATH: "wallet_balance.json"}
UID, DEMO = "1000001", "api-demo.bybit.com"
#: What a repr or a log line would show of the transport, or of its one field.
MARK = "cv-2893-s4-transport-mark"


def _answering(sent: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        body = json.loads((FIXTURES / REPLIES[request.url.path]).read_text(encoding="utf-8"))
        return httpx.Response(200, json=body)

    return answer


class _MarkedTransport(httpx.MockTransport):
    """A transport that any repr of it, or of its field, gives away."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        super().__init__(handler)
        self.mark = MARK

    def __repr__(self) -> str:
        return MARK


class _ClosableTransport(httpx.MockTransport):
    """A transport that frees what it holds on `aclose()`, as a stateful one would: once closed,
    it serves nothing more."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        super().__init__(handler)
        self.closes = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.closes:
            raise httpx.ConnectError("closed", request=request)
        return await super().handle_async_request(request)

    async def aclose(self) -> None:
        self.closes += 1


def _calls(svc: ExchangeBybitService) -> key_verify.KeyVerificationCalls:
    return svc.key_verification_calls("demo", CREDENTIAL_ID, uid=UID, recv_window_ms=5000)


async def test_an_injected_transport_receives_the_self_checks_key_info_and_probe_requests() -> None:
    sent: list[httpx.Request] = []
    transport = httpx.MockTransport(_answering(sent))
    svc = ExchangeBybitService(credentials=fake_capability(), rest_transport=transport)

    with respx.mock():
        calls = _calls(svc)
        facts = await calls.key_info()
        await calls.probe()
        await calls.aclose()

    assert facts.uid == UID
    assert [(r.url.host, r.url.path) for r in sent] == [(DEMO, KEY_INFO_PATH), (DEMO, PROBE_PATH)]
    assert all(r.headers["X-BAPI-SIGN"] for r in sent)  # signed by M2, as without the seam


async def test_closing_each_keys_client_leaves_the_shared_transport_open_and_serving() -> None:
    """Every key's client is built on the one transport and closed after its check: none of them
    closes it, so it still serves the next key's request."""
    sent: list[httpx.Request] = []
    transport = _ClosableTransport(_answering(sent))
    svc = ExchangeBybitService(credentials=fake_capability(), rest_transport=transport)

    with respx.mock():
        for calls in (_calls(svc), _calls(svc)):
            await calls.key_info()
            await calls.aclose()
        later = _calls(svc)
        await later.probe()
        await later.aclose()

    assert transport.closes == 0
    assert [r.url.path for r in sent] == [KEY_INFO_PATH, KEY_INFO_PATH, PROBE_PATH]


async def test_the_transport_stays_out_of_every_repr_and_log() -> None:
    """hcl-worker-1's ask 1: the adapter, the calls, the client and its httpx client, and every
    log event of both calls show neither the transport nor its field."""
    transport = _MarkedTransport(_answering([]))
    svc = ExchangeBybitService(credentials=fake_capability(), rest_transport=transport)
    reset_logging()  # structlog's defaults: every level reaches the capture, whatever ran before

    with capture_logs() as logs, respx.mock():
        calls = _calls(svc)
        await calls.key_info()
        await calls.probe()
    await calls.aclose()

    client = calls._client
    shown = [repr(svc), repr(calls), repr(client), repr(client._client), repr(logs)]
    assert [s for s in shown if MARK in s or "_MarkedTransport" in s] == []
    assert [e["event"] for e in logs].count("bybit_rest_request") == 2  # the logs were captured
