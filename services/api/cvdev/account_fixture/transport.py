"""#2893 S7, S9: the account fixture REST transport, its guards and the pack it serves (ADR-0036).

`FixtureTransport` is the `httpx` transport of a fixture stack's account REST clients
(`BybitRestClient(transport=...)`); S10 and S14 wire it in. Every request meets `guards` first:

- A refusal (`refused_host`, `refused_fund_path`, `refused_key`) is never answered: it raises
  `httpx.ConnectError`, as a closed port would, with a fixed message that holds no header value,
  since the client copies it into its `TransportError` (FX-I01). The client retries it, so one
  refusal logs a line per attempt, and the caller gets no verdict (SR-E27-18).
- A signed request whose key is not a pack key id latches the transport, whichever guard refuses
  it first, and the injected read-only gate with `account_fixture_guard` unless the gate holds a
  latch already, which is kept. The latch is process-wide: once one trips, or the gate holds this
  latch, every transport refuses every request, even one already being read or served. Recovery:
  revoke the key, then restart (FX-D01).
- A signature mismatch, or a body past `MAX_BODY_BYTES` that is never read whole, answers the
  pack's `_base/error_10004.json`.
- What passes every guard is served (decisions 6 and 7): a signed call as the scenario its key is
  stored under, an unsigned one only on `PUBLIC_CALLS` and as the stack default
  (`CV_ACCOUNT_FIXTURE`); any other unsigned call is refused as `refused_key`, without a latch.
  The reply follows the pack's lookup rule at the scenario's time and on the injected clock. A
  call nothing answers gets HTTP 404 with no exchange return code, which the client raises as
  `UnknownStateError`: not success, not retried, never a verdict on the key. So does a call signed
  over a body that is not a JSON object, which no `when` can read.

Each answer and refusal is one line of S6's `RequestLog`, which keeps its own rules (no signature,
no secret, no character of a non-fixture key), and each refusal or mismatch one structlog event
whose level is its severity: critical for the P0 refusals (test plan section 0.1), error for a
refusal without one, warning for a mismatch. A line the log cannot write never lets a refusal
through, and withholds an answer. Built at boot, as the constructor reads the whole pack; a request
reads no file. Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, NoReturn, Protocol

import httpx
import structlog

from cvdev.account_fixture import guards
from cvdev.account_fixture.guards import Admission
from cvdev.account_fixture.pack import (
    SERVER_TIME_CALL,
    Pack,
    Scenario,
    UnstubbedCall,
    fixture_key_ids,
    load,
    payload,
    warm,
)
from cvdev.account_fixture.requestlog import (
    OrderFields,
    Outcome,
    RequestLog,
    RequestLogFieldError,
    RequestLogFileError,
)

#: The venue's signature-error code, and the pack's reply carrying it.
SIGNATURE_ERROR: Final = 10004
SIGNATURE_ERROR_REPLY: Final = f"_base/error_{SIGNATURE_ERROR}.json"
#: The most request body the signature check reads (an order is a few hundred bytes).
MAX_BODY_BYTES: Final = 64 * 1024
UNSTUBBED_STATUS: Final = 404
_UNSTUBBED: Final = b'{"error":"account_fixture_unstubbed"}'
#: What an unsigned call may get: the pack's server time, which the adapter asks for unsigned.
PUBLIC_CALLS: Final = frozenset({SERVER_TIME_CALL})
#: An ack whose result names an order (a create's, a cancel's) names the request's (`_echo`); an
#: order the stub creates gets an id derived from its link (uuid5 under this fabricated namespace).
_LINK: Final = "orderLinkId"
_ID: Final = "orderId"
_ORDER_IDS: Final = uuid.UUID("00000000-0000-4000-8000-0000000000f0")
#: The call that lists the open orders, those an overlay seeds among them (`working_orders_2`).
_OPEN_ORDERS: Final = "/v5/order/realtime"
#: The request log's order subset (S6's `OrderFields`, plan section 9.7), each field by the body
#: field it is read from: a trading-stop's SL fields (TC-316, TC-410), all for a create or amend.
_STOP: Final = {"symbol": "symbol", "stop_loss": "stopLoss", "sl_trigger_by": "slTriggerBy"}
_TERMS: Final = {"side": "side", "order_type": "orderType", "qty": "qty", "price": "price"}
_ORDER: Final = _STOP | _TERMS | {"order_link_id": "orderLinkId", "reduce_only": "reduceOnly"}
_ORDER_CALLS: Final = {
    "POST /v5/order/create": _ORDER,
    "POST /v5/order/amend": _ORDER,
    "POST /v5/position/trading-stop": _STOP,
}
#: An amount is read only from a plain decimal string, so the log formats no other `Decimal`.
_AMOUNTS: Final = frozenset({"qty", "price", "stop_loss"})
_PLAIN_DECIMAL: Final = re.compile(r"[0-9]{1,24}(?:\.[0-9]{1,16})?")
_RET_CODE: Final = "retCode"
_MS: Final = timedelta(milliseconds=1)
_JSON: Final = {"Content-Type": "application/json"}
_P0: Final = "p0-critical"
_REASON_TEXT: Final = (
    "The account fixture transport refused a request signed with a key that is not a fixture key. "
    "Revoke that key, then restart."
)
#: Set by the first trip of any transport; only a restart clears it (ADR-0036 decision 4).
_TRIPPED: Final = threading.Event()


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ReadOnlyLatch(Protocol):
    """The process read-only gate (`candleviewer.net.read_only_gate.ReadOnlyGate`), injected."""

    @property
    def latched_reason_code(self) -> str | None: ...

    def latch(self, *, reason_code: str, reason_text: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Answer:
    """A reply to a request that passed the host, fund-path and key-id guards, and what its log
    line says of it."""

    response: httpx.Response
    outcome: Outcome
    scenario: str | None = None
    ret_code: int | None = None
    code_unconfirmed: bool | None = None
    overlays: tuple[str, ...] = ()
    order: OrderFields | None = None


class FixtureTransport(httpx.AsyncBaseTransport):
    """The guards, then the pack (module docstring). `latched` reads true once a non-fixture key
    trips any transport in the process, whatever latch the gate holds, or the gate holds this one.

    `clock` is the stub's: tz-aware, and S10's fixture clock on a stack. `default` is
    `CV_ACCOUNT_FIXTURE`, a key scenario of `pack`."""

    def __init__(
        self,
        pack: Pack,
        *,
        log: RequestLog,
        gate: ReadOnlyLatch,
        clock: Callable[[], datetime],
        default: str,
    ) -> None:
        self._pack, self._log, self._gate, self._clock = pack, log, gate, clock
        self._key_ids = fixture_key_ids(pack)
        if not self._key_ids:
            raise ValueError("the account pack names no fixture key id")
        self._error_reply = json.dumps(payload(pack, SIGNATURE_ERROR_REPLY)).encode()
        self._booted = clock()
        names = {guards.stored_under(key) for key in self._key_ids}
        self._scenarios = {name: load(pack, name, now=self._booted) for name in names}
        if default not in self._scenarios:
            raise ValueError("CV_ACCOUNT_FIXTURE must name a key scenario of the account pack")
        self._default, self._first_seen = default, dict[str, datetime]()
        warm(pack)

    @property
    def latched(self) -> bool:
        """True once a key trips any transport in the process, or its gate (ADR-0036 decision 4)."""
        return _TRIPPED.is_set() or self._gate.latched_reason_code == guards.GUARD_REASON_CODE

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        seen = guards.admit(request, self._key_ids)
        if seen.key_class == "non_fixture":  # whichever guard refuses it first (FX-S01)
            self._trip()
        if seen.refusal is not None or self.latched:
            self._refuse(request, seen)
        body: bytes | None = None
        verified: bool | None = None
        if seen.key_id is not None:
            body = await _body(request)
            verified = body is not None and guards.signature_verifies(request, seen.key_id, body)
        if verified is False:
            answer = self._mismatch(request, seen)
        else:
            answer = await self._serve(request, seen, body)
        if self.latched:  # tripped while this request was read or served: still unanswered
            self._refuse(request, seen)
        if not self._record(request, seen, answer.outcome, verified, answer):
            raise httpx.ConnectError(_message("request_log_failed"), request=request)
        return answer.response

    async def _serve(self, request: httpx.Request, seen: Admission, body: bytes | None) -> Answer:
        """A request that passed every guard, with `body`, the bytes guard 4 verified (None when
        unsigned). An unsigned call meets no key or signature guard, so only a public call is
        answered; any other is refused. The reply is `_selection`'s scenario's at the time since
        it started, which a stub's `when` matches on the verified JSON body: a stub's status, its
        headers and its body, anchored on the clock. A call nothing answers is unstubbed."""
        call = f"{request.method} {request.url.path}"
        if seen.key_id is None and call not in PUBLIC_CALLS:
            self._refuse(request, seen)
        now = self._clock()
        scenario, started = self._selection(seen.key_id, now)
        sent: dict[str, object] | None = None
        at_ms = max(0, (now - started) // _MS)  # before its start, a scenario answers as at it
        overlays = tuple(str(overlay["scenario"]) for overlay in scenario.overlays)
        try:
            sent = _json_object(request, body)
            reply = scenario.at(now, started=started).reply(
                request.method, request.url.path, at_ms=at_ms, body=sent
            )
        except UnstubbedCall:
            response = httpx.Response(UNSTUBBED_STATUS, content=_UNSTUBBED, headers=_JSON)
            order = _order(call, sent)
            return Answer(response, "unstubbed", scenario.name, overlays=overlays, order=order)
        _echo(sent, reply.body, lambda: _listed(scenario.at(now, started=started), at_ms))
        content = json.dumps(reply.body, separators=(",", ":")).encode()
        response = httpx.Response(reply.status, content=content, headers={**_JSON, **reply.headers})
        code = reply.body.get(_RET_CODE) if isinstance(reply.body, dict) else None
        ret_code = code if type(code) is int else None
        unconfirmed, order = reply.code_unconfirmed, _order(call, sent)
        return Answer(response, "served", scenario.name, ret_code, unconfirmed, overlays, order)

    def _selection(self, key_id: str | None, now: datetime) -> tuple[Scenario, datetime]:
        """The scenario a call answers as, and its start: the one its key is stored under, from
        the first call the key signs; for an unsigned call the stack default, from boot. S10's
        switch and anchor files override both per key (ADR-0036 decisions 5 and 6)."""
        if key_id is None:
            return self._scenarios[self._default], self._booted
        started = self._first_seen.setdefault(key_id, now)
        return self._scenarios[guards.stored_under(key_id)], started

    def _mismatch(self, request: httpx.Request, seen: Admission) -> Answer:
        logger().warning(
            "exchange.account_fixture_signature_mismatch", **self._fields(request, seen)
        )
        response = httpx.Response(200, content=self._error_reply, headers=_JSON)
        return Answer(response, "signature_mismatch", ret_code=SIGNATURE_ERROR)

    def _trip(self) -> None:
        """Latch every transport in the process, then the gate unless it holds a latch already,
        which is kept (as the key self-check keeps a more specific one)."""
        _TRIPPED.set()
        if self._gate.latched_reason_code is None:
            self._gate.latch(reason_code=guards.GUARD_REASON_CODE, reason_text=_REASON_TEXT)

    def _refuse(self, request: httpx.Request, seen: Admission) -> NoReturn:
        """Never answered: log, then raise as a closed port would. A request every guard passed
        is refused as a key refusal without a P0: on a latched transport, whose trip carried the
        P0, or when it is unsigned and not public."""
        p0 = seen.refusal is not None
        outcome: Outcome = seen.refusal or "refused_key"
        event = {"outcome": outcome, "priority": _P0 if p0 else None, "latched": self.latched}
        event |= self._fields(request, seen)
        (logger().critical if p0 else logger().error)("exchange.account_fixture_refused", **event)
        self._record(request, seen, outcome, None)
        raise httpx.ConnectError(_message(outcome), request=request)

    def _fields(self, request: httpx.Request, seen: Admission) -> dict[str, Any]:
        """What both logs hold of a request: never a header value, but a pack key id."""
        return {
            "host": seen.host,
            "host_env": seen.host_env,
            "method": request.method,
            "path": request.url.path,
            "key_class": seen.key_class,
            "signing_key_id": seen.key_id,
        }

    def _record(
        self,
        request: httpx.Request,
        seen: Admission,
        outcome: Outcome,
        verified: bool | None,
        answer: Answer | None = None,
    ) -> bool:
        """One request-log line. An order, then a method or path, outside the log's rules is logged
        as null; a line that still cannot be written is reported here and returns false."""
        line = self._fields(request, seen) | {"outcome": outcome, "transport": "rest"}
        stored_under = guards.stored_under(seen.key_id) if seen.key_id else None
        line |= {"verified": verified, "stored_under": stored_under}
        if answer is not None:
            line |= {"scenario": answer.scenario, "status": answer.response.status_code}
            line |= {"overlays": answer.overlays, "order": answer.order}
            line |= {"ret_code": answer.ret_code, "code_unconfirmed": answer.code_unconfirmed}
        try:
            for nulled in ((), ("order",)):
                with contextlib.suppress(RequestLogFieldError):
                    self._log.write(**(line | dict.fromkeys(nulled)))
                    return True
            self._log.write(**(line | dict.fromkeys(("order", "method", "path"))))
        except (RequestLogFieldError, RequestLogFileError, OSError) as exc:
            logger().error(
                "exchange.account_fixture_log_failed", outcome=outcome, error=type(exc).__name__
            )
            return False
        return True


async def _body(request: httpx.Request) -> bytes | None:
    """The body the signature covers, or None past `MAX_BODY_BYTES` (checked per chunk) or when
    it cannot be read without blocking."""
    if not isinstance(request.stream, httpx.AsyncByteStream):
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream:
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _message(code: str) -> str:
    """A refusal's text: a fixed code, never a header value (FX-I01)."""
    return f"the account fixture transport refused the request: {code}"


def _json_object(request: httpx.Request, body: bytes | None) -> dict[str, object] | None:
    """The JSON object body a stub's `when` matches: only one the signature covers, so never a
    GET's or DELETE's (guard 4 signs their query), which is None. No stub answers any other body
    that is not a JSON object (`UnstubbedCall`), and the pack holds no venue 10001 reply for it."""
    if body is None or request.method in guards.QUERY_SIGNED:
        return None
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        value = None
    if not isinstance(value, dict):
        raise UnstubbedCall(f"{request.method} {request.url.path}: the body is not a JSON object")
    return value


def _order(call: str, sent: Mapping[str, object] | None) -> OrderFields | None:
    """The request log's order subset of a verified create, amend or trading-stop body: each field
    as sent, an amount as a `Decimal`. The log's own rules judge every value (`_record`)."""
    named = _ORDER_CALLS.get(call)
    if named is None or sent is None:
        return None
    values: dict[str, Any] = {name: sent.get(field) for name, field in named.items()}
    for name in _AMOUNTS.intersection(values):
        if isinstance(text := values[name], str) and _PLAIN_DECIMAL.fullmatch(text):
            values[name] = Decimal(text)
    return OrderFields(**values)


def _echo(sent: Mapping[str, object] | None, body: Any, listed: Callable[[], list[Any]]) -> None:
    """An ack whose result names an order (a create's, a cancel's) names the one the request names,
    never another: an order the open-order list holds (an overlay seeds it) as listed, matched by
    its id, else its link; any other as sent, with no link if none is sent and, if no id is, an id
    derived from the link, the same for the same link, so a retry matches its create (C-2.10)."""
    result = body.get("result") if isinstance(body, dict) else None
    if sent is None or not isinstance(result, dict) or _LINK not in result:
        return
    link, order_id = sent.get(_LINK), sent.get(_ID)
    key, value = (_ID, order_id) if isinstance(order_id, str) and order_id else (_LINK, link)
    if not isinstance(value, str) or not value:
        return
    if listed_order := next((o for o in listed() if o.get(key) == value), None):
        result[_ID], result[_LINK] = listed_order.get(_ID), listed_order.get(_LINK)
    else:
        result[_ID] = value if key == _ID else str(uuid.uuid5(_ORDER_IDS, value))
        result[_LINK] = link if isinstance(link, str) else ""


def _listed(scenario: Scenario, at_ms: int) -> list[Any]:
    """The orders the open-order list holds now; none on an error, or if nothing answers it."""
    try:
        body = scenario.reply("GET", _OPEN_ORDERS, at_ms=at_ms, body=None).body
    except UnstubbedCall:
        return []
    result = body.get("result") if isinstance(body, dict) else None
    orders = result.get("list") if isinstance(result, dict) else None
    return [o for o in orders if isinstance(o, dict)] if isinstance(orders, list) else []
