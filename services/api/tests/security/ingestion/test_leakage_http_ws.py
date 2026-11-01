"""E08-X02 follow-ups #1901 and #1902: leakage probes through a real HTTP response and the
private-WS `auth` path. Register E.

#1901: `POST /exchange-accounts/{id}/keys/{id}/test` is mounted with the real exception handlers
(`install_error_redaction`) and driven over `httpx.ASGITransport`; its signed REST calls run on the
real `BybitRestClient` through a `MockTransport` that answers with recorded error payloads from
`packages/fixtures/bybit`. The status, headers and body of the actual response, the captured logs
and the metric exposition are scanned with `test_leakage.scan` and its synthetic credentials.

#1902: the private-WS `op:auth` probe (`KeyWsProbe`) is driven on a fake socket. No refused-`auth`
frame is recorded under `packages/fixtures/bybit` (its README: "no public example", K01), so none
is invented: only the recorded grant (`private-auth-ok.jsonl`) and failures that need no payload
(a dropped socket, a refused dial, a reply that never comes) are driven. Logs, the result, exception
texts, the metric exposition and the result's serialised form are scanned for the key id, the
signature and the `expires` + signature string.

Each probe proves it can fire: the request that went out is shown to carry the injected credential
(the scan sees it there) and the output is shown to carry none of it.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from prometheus_client import REGISTRY, generate_latest
from structlog.testing import capture_logs

from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.selfcheck import KeySelfCheck
from candleviewer.accounts.verification import VerificationPolicy
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.exchange_keys import make_exchange_keys_router

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit import key_ws_probe

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.key_selfcheck_wiring import JudgedCalls
from candleviewer.key_test_wiring import wire_key_test
from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.settings import Environment
from tests._corpus import frames, http_status, rest
from tests._signing import CREDENTIAL_ID, Call, fake_capability, stand_in_signature
from tests.contract.test_create_api_key_provider import Resolver
from tests.contract.test_test_api_key_provider import _TEST, Route
from tests.security.ingestion import test_leakage as leak
from tests.security.ingestion.test_leakage import API_KEY, UID, scan
from tests.unit.accounts.test_key_selfcheck import EGRESS, NOW, World, target
from tests.unit.accounts.test_key_test import Reads
from tests.unit.exchange.bybit.test_key_ws_probe import NOW_MS, Clock, Stream

#: The fixture `captured` (structlog JSON + a stdlib handler), shared with `test_leakage`.
captured = leak.captured

_ERROR_FILES = {"drift": "error_10002", "rate": "error_10018", "503": "error_503"}
#: What the route's `rest.error` must say, so a test cannot pass without its error path running.
_REST_ERROR = {
    "drift": "clock_drift", "rate": "rate_limited", "503": "service_unavailable",
    "transport": "transport_error",
}  # fmt: skip


def _rest_answer(kind: str, sent: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    """The exchange's REST answers: recorded error payloads, or a dropped connection."""

    def answer(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        if kind == "transport":
            raise httpx.ConnectError("refused", request=req)
        rel = f"rest/{_ERROR_FILES[kind]}.json"
        status = http_status(rel) if kind == "503" else 200
        return httpx.Response(status, json=rest(rel))

    return answer


def _flow(stream: Stream, transport: httpx.MockTransport, calls: list[Call]) -> tuple[World, Any]:
    """The flow behind `POST .../keys/{id}/test`: the real adapter, REST on `transport`, the
    private stream `stream`, both signed by the fake M2 holding `API_KEY`."""
    w = World(target(uid=UID))
    exchange = ExchangeBybitService(
        credentials=fake_capability(API_KEY, calls), rest_transport=transport,
        private_ws_connect=stream.connect, environment="demo",
    )  # fmt: skip

    def venue_calls(key_id: UUID, uid: str) -> JudgedCalls:
        venue = exchange.key_verification_calls("demo", key_id, uid=uid, recv_window_ms=5000)
        return JudgedCalls(exchange, venue)

    job = KeySelfCheck(
        w, venue_calls, gate=w.gate, audit=w, policy=VerificationPolicy(egress_ip=EGRESS),
        env="demo", clock=lambda: NOW, metrics=w.metrics,
    )  # fmt: skip
    ctx = SimpleNamespace(
        settings=SimpleNamespace(environment=Environment.DEMO), exchange_bybit=exchange,
        ingestion=SimpleNamespace(clock_offset_ms=lambda: None),
    )  # fmt: skip
    reads = AccountsRepository(Reads())  # type: ignore[arg-type]  # the two reads a test makes
    imports = SimpleNamespace(flow=SimpleNamespace(accounts=reads))
    flow = wire_key_test(ctx, job, imports)  # type: ignore[arg-type]  # the context's doubles
    return w, flow


def _route(stream: Stream, transport: httpx.MockTransport, calls: list[Call]) -> Route:
    w, flow = _flow(stream, transport, calls)
    return Route(w, flow)


def _wire(response: httpx.Response) -> str:
    """Everything a client sees: status line, every header, the body."""
    heads = "\n".join(f"{k}: {v}" for k, v in response.headers.multi_items())
    return f"{response.status_code}\n{heads}\n{response.text}"


def _request_dump(req: httpx.Request) -> str:
    return "\n".join(f"{k}: {v}" for k, v in req.headers.multi_items()) + str(req.url)


@pytest.mark.parametrize("kind", ["drift", "rate", "503", "transport"])
async def test_http_response_of_the_key_test_route_leaks_nothing_on_a_rest_error(
    kind: str, captured: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[httpx.Request] = []
    calls: list[Call] = []
    stream = Stream(dial=OSError("unreachable"))  # the REST error is the path under test
    route = _route(stream, httpx.MockTransport(_rest_answer(kind, sent)), calls)
    with capture_logs() as events:
        response = await route.post()
    assert response.status_code == 200, response.text
    assert response.json()["rest"]["error"] == _REST_ERROR[kind]
    # The probe can fire: a signed request did go out, and the scan flags that request.
    assert sent, "no signed REST request reached the exchange"
    assert any(API_KEY in _request_dump(r) for r in sent)
    assert scan(_request_dump(sent[0])), "the scan must see the credential in the request"
    blob = "\n".join(
        [_wire(response), captured.getvalue(), repr(events), generate_latest(REGISTRY).decode()]
    )
    assert scan(blob) == [], f"{kind}: leak through the HTTP response or its logs"
    assert not any(stand_in_signature(data) in blob for _, data, _ in calls)


async def test_http_wire_scan_detects_a_planted_credential() -> None:
    # The same scan, on the same wire dump, fires once a credential is planted in it.
    clean = _wire(httpx.Response(200, json={"ok": True}))
    assert scan(clean) == []
    leaked = _wire(httpx.Response(500, json={"detail": API_KEY}, headers={"X-Echo": UID}))
    assert scan(leaked)


# --- #1902: the private-WS `op:auth` path -------------------------------------------------------

_GRANT = frames("ws/private-auth-ok.jsonl")[0]


async def _probe(stream: Stream, calls: list[Call]) -> tuple[object, list[str]]:
    probe = key_ws_probe.KeyWsProbe(stream.connect, monotonic=Clock(), wall_ms=lambda: NOW_MS)
    raised: list[str] = []
    result: object = None
    try:
        result = await probe.probe(fake_capability(API_KEY, calls), "demo", CREDENTIAL_ID)
    except Exception as exc:  # the probe is not meant to raise: any text is scanned too
        raised += [str(exc), repr(exc), repr(exc.__cause__), repr(exc.__context__)]
    return result, raised


def _failures() -> dict[str, Stream]:
    return {
        "dial_refused": Stream(dial=ConnectionRefusedError("refused")),
        "socket_dropped": Stream(ConnectionResetError("reset by peer")),
        "no_reply": Stream(None),
        "recorded_grant": Stream(_GRANT),
    }


@pytest.mark.parametrize("name", list(_failures()))
async def test_private_ws_auth_path_leaks_nothing(
    name: str, captured: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(key_ws_probe, "timeout", lambda _delay: asyncio.timeout(0.01))
    stream, calls = _failures()[name], list[Call]()
    with capture_logs() as events:
        result, raised = await _probe(stream, calls)
    # The probe can fire: where an `auth` went out it carried the key, `expires` and signature,
    # and the same scan flags that frame. Where nothing went out there is nothing to leak.
    needles = [API_KEY]
    if stream.sent:
        auth = json.loads(stream.sent[0])
        expires, signature = str(auth["args"][1]), stand_in_signature(calls[0][1])
        assert (auth["op"], auth["args"][0], auth["args"][2]) == ("auth", API_KEY, signature)
        assert scan(stream.sent[0]), "the scan must see the credential in the frame sent"
        needles += [
            signature,
            expires + signature,
            f"{expires},{signature}",
            f"{expires}, {signature}",
        ]
    else:
        assert name == "dial_refused" and not calls
    blob = "\n".join(
        [
            repr(result),
            *raised,
            captured.getvalue(),
            repr(events),
            generate_latest(REGISTRY).decode(),
        ]
    )
    for needle in needles:
        assert needle not in blob, f"{name}: {needle[:6]}... leaked"
    assert scan(blob, tuple(needles)) == []


async def test_private_ws_auth_reaches_the_route_without_a_leak(
    captured: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End to end: the dropped socket becomes `websocket.error` in the real HTTP answer.
    sent: list[httpx.Request] = []
    stream, calls = Stream(ConnectionResetError("reset by peer")), list[Call]()
    route = _route(stream, httpx.MockTransport(_rest_answer("drift", sent)), calls)
    with capture_logs() as events:
        response = await route.post()
    blob = "\n".join([_wire(response), captured.getvalue(), repr(events)])
    assert stream.sent and API_KEY in stream.sent[0], "an `auth` frame must have gone out"
    assert scan(blob) == []
    assert stand_in_signature(calls[-1][1]) not in blob


async def test_unhandled_error_handler_response_leaks_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A defect inside the exchange call whose text echoes the credentials: the real
    # `unhandled_error_handler` answers 500 and logs, and neither may carry them.
    sent: list[httpx.Request] = []

    def boom(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        raise RuntimeError(f"defect with {API_KEY} and the request {_request_dump(req)}")

    w, flow = _flow(Stream(dial=OSError("unreachable")), httpx.MockTransport(boom), [])
    app = FastAPI()
    install_error_redaction(app)
    router = make_exchange_keys_router(
        None, w, Resolver(), egress_ip=EGRESS, rotation=KeyRotationPolicy(), tests=flow, auth=None
    )
    app.include_router(router)
    # Answer as a server does: the 500 is sent, the app's re-raise is not the client's concern.
    asgi = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"Authorization": "Bearer owner"}
    # The production log chain (format_exc_info + redaction + JSON), not a raw event capture.
    configure_logging(env="ci", level="debug", fmt="json")
    try:
        with respx.mock():
            async with httpx.AsyncClient(transport=asgi, base_url="http://cv") as client:
                response = await client.post(_TEST, headers=headers)
    finally:
        reset_logging()  # stops the listener: every queued record is written
    assert sent and scan(_request_dump(sent[0])), "the request carries the credential"
    logs = capsys.readouterr().out
    assert "unhandled_exception" in logs, "the handler's error log must have been captured"
    # The production redactor's placeholder is `[redacted:<why>]`; `scan` knows `**redacted**`.
    masked = re.sub(r"\[redacted:[a-z-]+\]", "**redacted**", logs)
    assert "[redacted:key-shape]" in logs, "the redactor must have masked the planted key"
    blob = "\n".join([_wire(response), masked])
    assert scan(blob) == [], f"{response.status_code}: leak through the handler"
