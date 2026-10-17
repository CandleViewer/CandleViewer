"""#2893 S7: the account fixture REST transport, its guard path (ADR-0036 decision 4).

`FixtureTransport` is the `httpx` transport of a fixture stack's account REST clients
(`BybitRestClient(transport=...)`); S9 and S14 wire it in. Every request meets `guards` first:

- A refusal (`refused_host`, `refused_fund_path`, `refused_key`) is never answered: it raises
  `httpx.ConnectError`, as a closed port would, with a fixed message that holds no header value,
  since the client copies it into its `TransportError` (FX-I01). The client retries it, so one
  refusal logs a line per attempt, and the caller gets no verdict (SR-E27-18).
- A key-id trip latches the transport, so every later request is refused, even one already being
  read or served, and latches the injected read-only gate with `account_fixture_guard` unless the
  gate holds a latch already, which is kept. Recovery: revoke the key, then restart (FX-D01).
- A signature mismatch, or a body past `MAX_BODY_BYTES` that is never read whole, answers the
  pack's `_base/error_10004.json`.
- What passes every guard is answered by `_serve`, the seam where S9 serves the pack. Until then it
  answers HTTP 404 with no exchange return code, which the client raises as `UnknownStateError`:
  not success, not retried, never a verdict on the key.

Each answer and refusal is one line of S6's `RequestLog`, which keeps its own rules (no signature,
no secret, no character of a non-fixture key), and each refusal or mismatch one structlog event
whose level is its severity: critical for the P0 refusals (test plan section 0.1), error for a
refusal only the latch causes, warning for a mismatch. A line the log cannot write never lets a
refusal through, and withholds an answer. Built at boot, as the constructor reads the pack; a
request reads no file. Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, NoReturn, Protocol

import httpx
import structlog

from cvdev.account_fixture import guards
from cvdev.account_fixture.guards import Admission
from cvdev.account_fixture.pack import Pack, _payload, fixture_key_ids
from cvdev.account_fixture.requestlog import (
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
_JSON: Final = {"Content-Type": "application/json"}
_P0: Final = "p0-critical"
_REASON_TEXT: Final = (
    "The account fixture transport refused a request signed with a key that is not a fixture key. "
    "Revoke that key, then restart."
)


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


class FixtureTransport(httpx.AsyncBaseTransport):
    """The guard path (module docstring); `latched` reads true once a key id trips."""

    def __init__(self, pack: Pack, *, log: RequestLog, gate: ReadOnlyLatch) -> None:
        self._pack, self._log, self._gate = pack, log, gate
        self._key_ids = fixture_key_ids(pack)
        if not self._key_ids:
            raise ValueError("the account pack names no fixture key id")
        self._error_reply = json.dumps(_payload(pack, SIGNATURE_ERROR_REPLY)).encode()
        self._latched = False

    @property
    def latched(self) -> bool:
        return self._latched

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        seen = guards.admit(request, self._key_ids)
        if seen.refusal == "refused_key":
            self._trip()
        if seen.refusal is not None or self._latched:
            self._refuse(request, seen)
        verified: bool | None = None
        if seen.key_id is not None:
            body = await _body(request)
            verified = body is not None and guards.signature_verifies(request, seen.key_id, body)
        if verified is False:
            answer = self._mismatch(request, seen)
        else:
            answer = await self._serve(request, seen)
        if self._latched:  # tripped while this request was read or served: still unanswered
            self._refuse(request, seen)
        if not self._record(request, seen, answer.outcome, verified, answer):
            raise httpx.ConnectError(_message("request_log_failed"), request=request)
        return answer.response

    async def _serve(self, request: httpx.Request, seen: Admission) -> Answer:
        """A request that passed every guard. S9 answers from the pack here (the key's scenario,
        or the stack default when unsigned); until then every call is unstubbed."""
        response = httpx.Response(UNSTUBBED_STATUS, content=_UNSTUBBED, headers=_JSON)
        return Answer(response, "unstubbed")

    def _mismatch(self, request: httpx.Request, seen: Admission) -> Answer:
        logger().warning(
            "exchange.account_fixture_signature_mismatch", **self._fields(request, seen)
        )
        response = httpx.Response(200, content=self._error_reply, headers=_JSON)
        return Answer(response, "signature_mismatch", ret_code=SIGNATURE_ERROR)

    def _trip(self) -> None:
        """Latch the transport, then the gate unless it holds a latch already, which is kept (as
        the key self-check keeps a more specific one)."""
        self._latched = True
        if self._gate.latched_reason_code is None:
            self._gate.latch(reason_code=guards.GUARD_REASON_CODE, reason_text=_REASON_TEXT)

    def _refuse(self, request: httpx.Request, seen: Admission) -> NoReturn:
        """Never answered: log, then raise as a closed port would. A latched transport refuses a
        request every guard passed as a key refusal, without the P0 its trip carried."""
        p0 = seen.refusal is not None
        outcome: Outcome = seen.refusal or "refused_key"
        event = {"outcome": outcome, "priority": _P0 if p0 else None, "latched": self._latched}
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
        """One request-log line. A method or path outside the log's rules is logged as null; a
        line that still cannot be written is reported here and returns false."""
        line = self._fields(request, seen) | {"outcome": outcome, "transport": "rest"}
        stored_under = guards.stored_under(seen.key_id) if seen.key_id else None
        line |= {"verified": verified, "stored_under": stored_under}
        if answer is not None:
            line |= {"scenario": answer.scenario, "status": answer.response.status_code}
            line |= {"ret_code": answer.ret_code, "code_unconfirmed": answer.code_unconfirmed}
        try:
            try:
                self._log.write(**line)
            except RequestLogFieldError:
                self._log.write(**(line | {"method": None, "path": None}))
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
