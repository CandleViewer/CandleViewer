"""Live WS gateway endpoint (`23-ws-protocol.md` §2.2, §4, §8.5, §9; E17-S01).

One socket = one `_Connection` with exactly one reader and one writer task,
both spawned via `cv.obs.spawn` and owned by the handler (`20-architecture.md` TG5):

- **Origin** (§2.5, SR-042/SR-183): checked first, against `CV_ALLOWED_ORIGINS`; the
  allow-list decides. A missing, duplicated, `null` or unlisted `Origin` is closed `4403`
  before `accept` (HTTP 403, no `bye`): no negotiation, frame, auth or store access. Each
  refusal is counted and logged with the source address MeshOnly admitted, with a cap.
- **Negotiation** (§2.2): the subprotocol is chosen before `accept`; when the
  client offers none we serve -> close `1002` before the handshake completes.
  `cv.v1.msgpack` whenever offered: then client frames go to the SR-185 decoder and
  server frames are MessagePack (`ws/codec.py`). A frame of the other subprotocol's
  kind (text on msgpack, binary on JSON) is malformed.
- **hello -> welcome** (§4.2): any other first frame -> `bye` + `1002`.
- **auth -> auth_ok** (§4.3): the token is read ONLY from the `auth` frame
  body, never the URL. Verified by the injected E09 `authenticate`; the
  `PrincipalSnapshot` is resolved by the `ConnectionRegistry` (the same RBAC
  source REST uses). The socket registers with the `RevocationHub` for the
  presented session as soon as `authenticate` returns, so a session revoked
  while the `auth` is in flight gets no `auth_ok`: the hub closes the socket,
  or remembers the revocation and the gateway closes it the same way (#2739).
  The identity ends at the token's expiry as `authenticate` reports it (the
  first refusal on time grounds); an already-expired token is refused like
  any failed `auth`. Revocation is pushed through the `RevocationHub`; the
  idle lock intentionally does not end the socket (E09-S03; #2259).
  Three failures -> `bye auth_failed` + `4401` + a `warning` audit entry.
- **In-place re-auth** (§4.1): a later `auth` re-validates and swaps the
  principal without touching subscriptions. The old session stays registered
  with the hub until the new one is accepted.
- **Heartbeats / deadlines** (§9.1): the writer checks a `Watchdog` before
  every dequeue and every send, not only when idle, on the injected clocks
  (auth timeout, token expiry on both clocks, unsolicited `ping`, heartbeat
  timeout), so tests drive time instead of sleeping.
- **Inbound limits**: size checked before decoding (`1009`); 30/s and 300/min
  excluding `pong` (`client_rate_limited`, then `4429`). An envelope `id` that is not a
  string of at most `ENVELOPE_ID_MAX_LEN` characters is dropped before the frame is
  handled, so no reply echoes it (§13.1, #2572).
- Every server-initiated close goes through `_Connection.close_with`, which
  queues `bye` ahead of the close frame (requirement S11). Token expiry and
  revocation seal the close: anything still queued is dropped, `bye` next.
- **Fan-out span** (the gateway segment of budget #6, from the subscription's hub turn, not bus
  receipt): `TopicEmitter` queues one data frame (`snap` / `d`) of a subscription in
  `SAMPLE_EVERY` with the clock reading at which the hub took it, and the writer observes
  `cv_ws_fanout_seconds` for it, weighted, once `send_text` has returned. Unsampled frames
  carry no stamp and read no clock. Control frames and dropped frames are not observed; a
  client's drain wait, a slow consumer's backlog and replay frames are inside the span.

Bounds (C-2.18): outbound queue `OUTBOUND_QUEUE_MAX` (full -> `slow_consumer`
close), rate-limiter window, `MAX_CONNECTIONS_PER_USER` per user (oldest idle
connection closed). Transport only: no business logic, no data fan-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.net import RESOLVED_SOURCE_KEY
from candleviewer.observability.context import current_request_id, spawn
from candleviewer.settings import CLOSE_AUDIT_TIMEOUT_S, CLOSE_FLUSH_TIMEOUT_S
from candleviewer.ws.codec import decode_client_frame, encode_server_frame
from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.lifecycle import (
    CLOSE_REASONS,
    MAX_AUTH_FAILURES,
    MAX_CONNECTIONS_PER_USER,
    MAX_PROTOCOL_VIOLATIONS,
    MAX_UNAUTHENTICATED_FRAMES,
    ORIGIN_FORBIDDEN,
    OTHER_CLOSE_REASON,
    REFUSAL_LOG_LIMIT,
    REFUSAL_LOG_WINDOW_S,
    SHUTDOWN_GRACE_MS,
    SUBPROTOCOL_MSGPACK,
    ConnEvent,
    InboundRateLimiter,
    Lifecycle,
    OriginRefusal,
    RefusalLog,
    RefusalLogLimiter,
    Watchdog,
    header_values,
    negotiate_subprotocol,
    origin_refusal,
    welcome_payload,
)
from candleviewer.ws.lifecycle import bye_frame as lifecycle_bye
from candleviewer.ws.limits import (
    AUTH_TIMEOUT_S,
    ENVELOPE_ID_MAX_LEN,
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_DEPTH,
    json_depth_exceeds,
)
from candleviewer.ws.metrics import (
    FANOUT_SECONDS,
    SAMPLE_EVERY,
    cv_ws_auth_failures_total,
    cv_ws_clock_skew_ms,
    cv_ws_closes_total,
    cv_ws_connections_in_use,
    cv_ws_handshake_seconds,
)
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    auth_ok_payload,
    handle_ctl,
    handle_unsub,
)
from candleviewer.ws.permissions import handle_sub as _handle_sub
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import TopicEmitter

WS_PATH = "/ws"
SYSTEM_TOPIC: Final = "system"
OUTBOUND_QUEUE_MAX: Final = 1024
WATCHDOG_TICK_S: Final = 0.05
#: Close reasons audited at `warning` rather than `info` (E17-S01 Security notes; a fault too).
WARNING_CLOSES: Final = frozenset({"auth_failed", "slow_consumer", "internal_error"})
#: The close code uvicorn's own shutdown sends every socket it closes (no `bye`). A client may send
#: it too, which uvicorn forwards alike: `closed_reason` tells them apart by the server's state.
SERVER_RESTART_CLOSE: Final = 1012

#: (raw access token) -> (session_id, user_id, token expires_at); raises on any
#: invalid token. The expiry is mandatory and timezone-aware: the first instant
#: the session service refuses the token on time grounds (E09
#: `access_token_expires_at`). The gateway never assumes a default lifetime.
AuthResult = tuple[str, uuid.UUID, datetime]
Authenticate = Callable[[str], Awaitable[AuthResult]]
Clock = Callable[[], float]
WallClockMs = Callable[[], int]

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS: Final = timedelta(milliseconds=1)


class AuthenticatorContractError(RuntimeError):
    """The injected `authenticate` returned no timezone-aware token expiry. That
    is a server fault, not a client auth failure: the socket closes `1011` and
    nothing is served (fail closed, #2259)."""


def _token_expiry_ms(result: AuthResult) -> int:
    """The token expiry of an `authenticate` result as epoch ms. It is floored,
    so it is never later than the real expiry."""
    expires_at = result[2] if len(result) == 3 else None
    if not isinstance(expires_at, datetime) or expires_at.utcoffset() is None:
        raise AuthenticatorContractError(
            "authenticate must return (session_id, user_id, timezone-aware expires_at)"
        )
    return (expires_at - _EPOCH) // _ONE_MS


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


_CLOSE = object()  # writer sentinel: the next queue item is the close code
_WRITER_DONE: Final = "cv-ws-writer-done"  # cancel msg: writer finished, stop reading


class GatewayHub:
    """Every live connection: per-user cap (§4, 8 per user) and the §9.4
    planned-shutdown broadcast. Bounded by the per-user cap after auth and
    by the auth timeout before it."""

    def __init__(self, *, max_per_user: int = MAX_CONNECTIONS_PER_USER) -> None:
        self.max_per_user = max_per_user
        #: The server is shutting down: set by `shutdown()` and by `candleviewer.server` when its
        #: own shutdown begins (a forced exit or a failure may never reach `shutdown()`). Only
        #: `WsRuntime.start()` clears it, for an in-process restart. `closed_reason` reads it to
        #: tell uvicorn's own `1012` from one a client sends.
        self.shutting_down = False
        self._live: set[_Connection] = set()
        self._empty = asyncio.Event()
        self._empty.set()

    def __len__(self) -> int:
        return len(self._live)

    def add(self, conn: _Connection) -> None:
        self._live.add(conn)
        self._empty.clear()

    def discard(self, conn: _Connection) -> None:
        self._live.discard(conn)
        if not self._live:
            self._empty.set()

    async def wait_empty(self) -> None:
        """Return once every connection handler has finished (callers bound it)."""
        await self._empty.wait()

    def of_user(self, user_id: uuid.UUID) -> list[_Connection]:
        return [c for c in self._live if c.user_id == user_id]

    def enforce_cap(self, newcomer: _Connection) -> None:
        """Close the oldest-idle connections of `newcomer`'s user above the cap."""
        if newcomer.user_id is None:
            return
        others = [c for c in self.of_user(newcomer.user_id) if c is not newcomer]
        others.sort(key=lambda c: c.watchdog.last_inbound)
        while len(others) + 1 > self.max_per_user:
            others.pop(0).close_with("too_many_connections")

    def _authenticated(self) -> list[_Connection]:
        return [c for c in self._live if c.lifecycle.authenticated]

    def authenticated_count(self) -> int:
        """How many connections `shutdown()` sends the `shutdown_notice` (every one gets the
        `bye`)."""
        return len(self._authenticated())

    def broadcast_system(self, body: dict[str, Any]) -> int:
        """Push one `system` frame (e.g. §12.5 `kill_switch`) to every authenticated socket."""
        conns = self._authenticated()
        for conn in conns:
            conn.push_system(body)
        return len(conns)

    async def shutdown(
        self,
        *,
        reason: str = "deploy",
        message: str = "Backend restarting.",
        expected_downtime_ms: int = 20_000,
        grace_ms: int = SHUTDOWN_GRACE_MS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> int:
        """§9.4: `shutdown_notice` on `system`, wait the grace period, close
        `1001`. Returns the number of connections notified."""
        self.shutting_down = True
        conns = self._authenticated()
        for conn in conns:
            conn.push_system(
                {
                    "kind": "shutdown_notice",
                    "reason": reason,
                    "closing_in_ms": grace_ms,
                    "message": message,
                    "expected_downtime_ms": expected_downtime_ms,
                }
            )
        await sleep(grace_ms / 1000)
        for conn in list(self._live):
            conn.close_with("shutdown", retry_after_ms=expected_downtime_ms)
        return len(conns)


def close_reason_label(reason: str) -> str:
    """Bounded `reason` label: a known §13.6 close/bye reason, else `OTHER_CLOSE_REASON`.
    `ws/metrics.py` binds every one of them at import."""
    return reason if reason in CLOSE_REASONS else OTHER_CLOSE_REASON


def closed_reason(
    conn: _Connection, fault: BaseException | None, *, server_shutting_down: bool = False
) -> str:
    """Why a connection ended, for its audit row: the `bye`'s reason (bounded like the metric
    label, `other` for a malformed `bye`), else `internal_error` after a fault, else `shutdown`
    when the server is shutting down and its host ended the socket, else `client_closed`.

    The host ends it with uvicorn's own `1012`, or by cancelling the handler when its graceful
    timeout expires (no close code at all). Any other code is the client's: a close it sent, or
    a drop the reader saw (`websocket.disconnect`) or the writer saw (a send that failed). While
    the server is shutting down three cases cannot be told apart. Two read `shutdown` though the
    client did it: its own `1012`, and a drop it makes unseen just before the host cancels the
    handler. The third reads `client_closed` though the host did it: a send that fails in that
    window looks the same whether the client left or the host already closed the socket, and the
    writer's end stops a busy reader (a re-auth that hangs) before it reads the host's `1012`."""
    if conn.bye_frame is not None:
        body = conn.bye_frame.get("p")
        return close_reason_label(str(body.get("reason", "")) if isinstance(body, dict) else "")
    if fault is not None:
        return "internal_error"
    if server_shutting_down and conn.disconnect_code in (None, SERVER_RESTART_CLOSE):
        return "shutdown"
    return "client_closed"


def _source_ip(scope: Mapping[str, Any]) -> str | None:
    """The address MeshOnly admitted (trusted-proxy aware), else `scope["client"]`.

    `scope["client"]` is the TCP peer: uvicorn does not rewrite it from `X-Forwarded-For`
    (#2275), so only MeshOnly's configured trusted proxy can name another address."""
    admitted = (scope.get("state") or {}).get(RESOLVED_SOURCE_KEY)
    if admitted:
        return str(admitted)
    client = scope.get("client")
    return str(client[0]) if client else None


class _Connection:
    """One socket's state; the handler owns its reader and writer tasks."""

    def __init__(
        self,
        ws: WebSocket,
        *,
        encoding: str,
        clock: Clock,
        wall_ms: WallClockMs,
        auth_timeout_s: float,
    ) -> None:
        self.ws = ws
        self.encoding = encoding
        #: §2.2: every frame, both ways, is MessagePack (`ws/codec.py`); else JSON text.
        self.msgpack = encoding == SUBPROTOCOL_MSGPACK
        self.connection_id = f"ws_{uuid.uuid4().hex[:12]}"
        self.clock = clock
        self.wall_ms = wall_ms
        self.lifecycle = Lifecycle()
        now = clock()
        self.watchdog = Watchdog(
            auth_deadline=now + auth_timeout_s, last_inbound=now, last_outbound=now
        )
        self.rate = InboundRateLimiter()
        #: Bounded by `push` (OUTBOUND_QUEUE_MAX) plus the two close items.
        self.outbound: asyncio.Queue[Any] = asyncio.Queue()
        self.user_id: uuid.UUID | None = None
        self.session_id: str | None = None
        #: The session an `auth` in flight registered with the `RevocationHub` (#2739): it becomes
        #: `session_id` when that auth is accepted and is dropped however else the auth ends.
        self.pending_session_id: str | None = None
        self.authz: ConnectionAuthz | None = None
        self.emitter: TopicEmitter | None = None
        self.system_seq = 0
        self.auth_failures = 0
        self.unauth_frames = 0
        self.violations = 0
        self.rate_strikes = 0
        self.closing = False
        #: Set by a sealed close (token expiry, revocation): the identity is over,
        #: so nothing but `bye_frame` may still be sent (#2259 review).
        self.sealed = False
        self.bye_frame: dict[str, Any] | None = None
        #: The close code of a disconnect the gateway did not send (`closed_reason`).
        self.disconnect_code: int | None = None
        self.close_code: int | None = None
        #: The token's real expiry (epoch ms), also checked on the wall clock.
        self.token_expires_at_ms: int | None = None
        self.opened_at = now

    def due(self) -> str | None:
        """The watchdog verdict now. Token expiry fires on whichever clock gets
        there first: the monotonic deadline set at `auth`, or the wall clock,
        which an NTP step or a resume moves on its own (#2259 review)."""
        if self.token_expires_at_ms is not None and self.wall_ms() >= self.token_expires_at_ms:
            return "token_expired"
        return self.watchdog.due(self.clock())

    # -- outbound -----------------------------------------------------------

    def push(self, frame: dict[str, Any], received: float | None = None) -> None:
        """Queue one frame; a full queue is a slow consumer (C-2.18 policy). A sampled data frame
        comes with `received`, the `clock` reading at which the hub took it, and is queued with it
        as `(received, frame)`: the writer observes `cv_ws_fanout_seconds` from that pair once the
        socket has the frame. It never reaches the wire, and a frame dropped from the queue (a
        seal, a full queue) is never observed. Any other frame is queued bare."""
        if self.closing:
            return
        if self.outbound.qsize() >= OUTBOUND_QUEUE_MAX:
            self.close_with("slow_consumer")
            return
        self.outbound.put_nowait(frame if received is None else (received, frame))

    async def send(self, frame: dict[str, Any]) -> None:
        """Registry / `handle_sub` adapter; silent before the first `auth_ok` (SR-189)."""
        if self.lifecycle.authenticated:
            self.push(frame)

    def push_system(self, body: dict[str, Any]) -> None:
        self.system_seq += 1
        self.push(
            {"t": "d", "ch": SYSTEM_TOPIC, "s": self.system_seq, "ts": self.wall_ms(), "e": "j"}
            | {"p": body}
        )

    async def send_frame(self, frame: dict[str, Any]) -> None:
        """Write one frame in the negotiated encoding (§2.2, §3.2)."""
        if self.msgpack:
            await self.ws.send_bytes(encode_server_frame(frame))
        else:
            await self.ws.send_text(json.dumps(frame, separators=(",", ":")))

    def close_with(
        self,
        reason: str,
        *,
        retry_after_ms: int | None = None,
        bye: dict[str, Any] | None = None,
        seal: bool = False,
    ) -> None:
        """The ONE server-initiated close path: `bye`, then the close frame (S11).

        `seal=True` is for closes that end the identity (token expiry,
        revocation): every frame still queued is dropped and the `bye` is the
        next frame sent, even if another close is already under way (#2259
        review). Otherwise the `bye` follows the frames already queued. May
        exceed the `push` bound by exactly these items so a full queue can
        still be closed; every later push is dropped."""
        if self.closing:
            if seal and not self.sealed:
                # An identity-ending event during a close already under way.
                dropped = self._seal()
                label = str(bye["p"].get("reason", reason)) if bye is not None else reason
                cv_ws_closes_total.labels(reason=close_reason_label(label)).inc()
                _log().info(
                    "ws close sealed",
                    connection_id=self.connection_id,
                    reason=reason,
                    dropped=dropped,
                    user_id=str(self.user_id) if self.user_id else None,
                    session_id=self.session_id,
                )
            return
        self.closing = True
        frame = bye or lifecycle_bye(reason, now_ms=self.wall_ms(), retry_after_ms=retry_after_ms)
        code = int(frame["p"]["code"])
        bye_reason = str(frame["p"].get("reason", reason))
        cv_ws_closes_total.labels(reason=close_reason_label(bye_reason)).inc()
        if self.lifecycle.can(ConnEvent.CLOSE):
            self.lifecycle.fire(ConnEvent.CLOSE)
        dropped = self._seal() if seal else 0
        self.bye_frame = frame
        for item in (frame, _CLOSE, code):
            self.outbound.put_nowait(item)
        _log().info(
            "ws close",
            connection_id=self.connection_id,
            reason=reason,
            code=code,
            dropped=dropped,
            user_id=str(self.user_id) if self.user_id else None,
            session_id=self.session_id,
        )

    def _seal(self) -> int:
        """End the identity: drop every queued frame except a pending close
        (`bye`, the close sentinel, its code). Returns how many were dropped."""
        self.sealed = True
        kept: list[Any] = []
        dropped = 0
        while not self.outbound.empty():
            item = self.outbound.get_nowait()
            if item is self.bye_frame or item is _CLOSE or isinstance(item, int):
                kept.append(item)
            else:
                dropped += 1
        for item in kept:
            self.outbound.put_nowait(item)
        return dropped

    async def closer(self, frame: dict[str, Any], code: int) -> None:
        """`RevocationHub` / registry hook: the session or user is gone, so the
        close is sealed (nothing still queued for it is delivered)."""
        del code  # carried inside the bye frame
        self.close_with(str(frame["p"]["reason"]), bye=frame, seal=True)

    async def evict(self) -> None:
        self.close_with("slow_consumer")

    # -- inbound ------------------------------------------------------------

    def decode(self, msg: Mapping[str, Any], max_frame_bytes: int) -> Any:
        """One ASGI receive message -> decoded frame; `None` after an oversize close.

        Size is checked on the raw payload BEFORE any decoding (1009). Each subprotocol has one
        frame kind (§2.2): a text frame on `cv.v1.msgpack` and a binary one on `cv.v1.json` are
        malformed. The SR-185 decoder (`ws/codec.py`) decodes msgpack."""
        raw: str | bytes = msg.get("text") or msg.get("bytes") or ""
        size = len(raw.encode()) if isinstance(raw, str) else len(raw)
        if size > max_frame_bytes:
            self.close_with("frame_too_big")
            return None
        try:
            if self.msgpack:
                return [] if isinstance(raw, str) else decode_client_frame(raw)
            if isinstance(raw, bytes):
                return []  # a binary frame on cv.v1.json: a violation, never decoded
            if json_depth_exceeds(raw, MAX_JSON_DEPTH):
                return []  # SR-184: too deep -> protocol violation, never decoded
            return json.loads(raw)
        except (ValueError, RecursionError):  # MsgpackFrameError is a ValueError
            return []  # malformed: handled as a non-object frame (a violation)

    def violation(self, frame_id: Any, code: str = "frame_malformed") -> None:
        """Malformed/unexpected frame after `hello`; 3 strikes -> `4400` (§4.4)."""
        self.violations += 1
        if self.violations >= MAX_PROTOCOL_VIOLATIONS:
            self.close_with("bad_client")
        else:
            self.push(build_ws_error(code, id=_str_or_none(frame_id)))


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _is_envelope_id(value: Any) -> bool:
    """§13.1 `envelope.id`: a string of at most `ENVELOPE_ID_MAX_LEN` characters."""
    return isinstance(value, str) and len(value) <= ENVELOPE_ID_MAX_LEN


async def _join_writer(task: asyncio.Task[None]) -> BaseException | None:
    """Await the cancelled writer; return its fault, if any. A cancellation
    aimed at the *handler* (not the writer) is re-raised, never swallowed."""
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        return exc
    return None


@contextlib.contextmanager
def _step(conn: _Connection, name: str) -> Iterator[None]:
    """One synchronous step of a connection's teardown. A failure is logged with the step's name
    and never raised: the steps after it still run, and it cannot replace the `CancelledError`
    the handler is ending with (a lease release that raises, say)."""
    try:
        yield
    except Exception:
        _log().error(
            "ws teardown step failed", connection_id=conn.connection_id, step=name, exc_info=True
        )


def _reply(t: str, frame_id: Any, **fields: Any) -> dict[str, Any]:
    """Envelope with `id` echoed only when the request carried a string id (§13.1)."""
    out: dict[str, Any] = {"t": t}
    if isinstance(frame_id, str):
        out["id"] = frame_id
    return out | fields


def make_ws_router(
    *,
    authenticate: Authenticate,
    registry: ConnectionRegistry,
    revocation_hub: RevocationHub,
    # §2.5 allow-list (`Settings.allowed_origin_set`, shared with REST). No default, so no
    # caller can build a router that skips the check; an empty set refuses every upgrade.
    allowed_origins: frozenset[str],
    hub: GatewayHub | None = None,
    audit: AuditEmitter | None = None,
    auth_timeout_s: float = AUTH_TIMEOUT_S,
    max_frame_bytes: int = MAX_INBOUND_FRAME_BYTES,
    clock: Clock = time.monotonic,
    wall_ms: WallClockMs = _wall_ms,
    tick_s: float = WATCHDOG_TICK_S,
    server_version: str = "0.0.0",
    git_sha: str = "unknown",
    kill_switch: Callable[[], dict[str, Any]] | None = None,
    system_notices: Callable[[], list[dict[str, Any]]] | None = None,
) -> APIRouter:
    """The `/ws` endpoint. `clock` (monotonic seconds) drives every deadline,
    so tests inject a fake clock; `tick_s` is only the poll cadence."""
    router = APIRouter()
    gateway_hub = hub if hub is not None else GatewayHub()
    killed = kill_switch or (lambda: {"engaged": False, "scope": "global"})
    refusal_log = RefusalLogLimiter()

    def log_refusal(cause: OriginRefusal, scope: Mapping[str, Any]) -> None:
        """§2.5: a capped warning per refused upgrade; never a header value."""
        verdict = refusal_log.admit(cause, clock())
        if verdict is RefusalLog.LINE:
            _log().warning(
                "ws upgrade refused",
                reason=ORIGIN_FORBIDDEN,
                check=cause.value,
                source_ip=_source_ip(scope),
            )
        elif verdict is RefusalLog.SUMMARY:
            _log().warning(
                "ws upgrade refusals suppressed",
                reason=ORIGIN_FORBIDDEN,
                check=cause.value,
                limit=REFUSAL_LOG_LIMIT,
                window_s=REFUSAL_LOG_WINDOW_S,
            )

    async def audit_auth_failure(conn: _Connection) -> None:
        """`warning` audit entry for the 3rd failed `auth` (§4.3). Never
        carries the token. Best effort: the close is not held hostage."""
        if audit is None:
            return
        try:
            await audit.emit(
                "auth.login_failed",
                actor_label="ws",
                actor_user_id=conn.user_id,
                object_kind="ws_connection",
                object_id=conn.connection_id,
                outcome=AuditOutcome.FAILURE,
                severity=Severity.WARNING,
                reason="ws_auth_failed",
            )
        except Exception:
            _log().warning("ws auth-failure audit not written", exc_info=True)

    async def audit_close(conn: _Connection, fault: BaseException | None) -> None:
        """`ws.connection.closed` for a socket that authenticated (E17-S01, #2486): `warning`
        for `WARNING_CLOSES`, `info` otherwise. An unauthenticated close is not audited, so a
        peer without a session cannot flood the log (its 3rd failed `auth` already is). Never
        the token. Best effort (threat model WS-R04): the teardown waits at most
        `CLOSE_AUDIT_TIMEOUT_S` for the sink, and a failure in here, working out the reason
        included, is logged and never raised. One loss it cannot avoid: a cancellation of the
        handler that lands inside the emit (the host's graceful-timeout cancel, or a second one
        such as the loop's own teardown) is honoured and abandons a write that has not started;
        `AuditWriter.emit` finishes one that has."""
        if audit is None or conn.user_id is None:
            return
        try:
            reason = closed_reason(conn, fault, server_shutting_down=gateway_hub.shutting_down)
            async with asyncio.timeout(CLOSE_AUDIT_TIMEOUT_S):
                await audit.emit(
                    "ws.connection.closed",
                    actor_label="ws",
                    actor_user_id=conn.user_id,
                    actor_ip=_source_ip(conn.ws.scope),
                    session_id=conn.session_id,
                    object_kind="ws_connection",
                    object_id=conn.connection_id,
                    outcome=AuditOutcome.SUCCESS,
                    severity=Severity.WARNING if reason in WARNING_CLOSES else Severity.INFO,
                    reason=reason,
                    request_id=current_request_id(),
                )
        except Exception:
            # Not "not written": a write that timed out may still land (the writer shields it).
            _log().warning(
                "ws close audit not confirmed", connection_id=conn.connection_id, exc_info=True
            )

    async def do_auth(conn: _Connection, frame: dict[str, Any]) -> None:
        """One `auth` frame. However it ends short of `auth_ok` (a failure, a refusal, a close,
        a cancellation), the hub registration `run_auth` made for the presented session is
        dropped here, so no closer outlives its `auth` (#2739)."""
        try:
            await run_auth(conn, frame)
        finally:
            if conn.pending_session_id is not None:
                revocation_hub.unregister(conn.pending_session_id, conn.closer)
                conn.pending_session_id = None

    async def run_auth(conn: _Connection, frame: dict[str, Any]) -> None:
        body = frame.get("p")
        token = body.get("access_token") if isinstance(body, dict) else None
        reauth = conn.lifecycle.authenticated
        if reauth:
            conn.lifecycle.fire(ConnEvent.REAUTH)
        failure = "rejected"
        try:
            if not isinstance(token, str) or not token:
                failure = "missing_token"
                raise ValueError("missing access_token")
            result = await authenticate(token)
            session_id, user_id = result[0], result[1]
            expires_ms = _token_expiry_ms(result)
            if reauth and user_id != conn.user_id:
                failure = "user_mismatch"
                raise PermissionError("re-auth must keep the same user")
            if session_id != conn.session_id:
                # #2739: before the next await, so a revocation published from here on closes
                # this socket. `do_auth` drops it again unless this auth is accepted.
                revocation_hub.register(session_id, conn.closer)
                conn.pending_session_id = session_id
            snap = await registry.resolve(user_id)  # versioned: never undoes a newer one
            now, now_ms = conn.clock(), conn.wall_ms()
            if expires_ms <= now_ms:
                failure = "token_expired"  # never `auth_ok` an identity that is already dead
                raise PermissionError("access token already expired")
            if conn.authz is None:  # SR-189: register, then re-check, under the auth deadline
                conn.authz = ConnectionAuthz(
                    snap.principal,
                    registry.services,
                    connection_id=conn.connection_id,
                    version=snap.version,
                )
                registry.register(conn.authz, conn.send, conn.evict, conn.closer)
                await registry.recheck(conn.authz)
                revoked: list[dict[str, Any]] = []
            else:
                # Subscriptions + sequences are kept; only ones the refreshed
                # principal no longer allows are revoked (§9.5, same RBAC source).
                frames = await registry.apply(conn.authz, snap, now_ms, event="reauth")
                revoked = [f for f in frames if f["t"] == "revoked"]
        except AuthenticatorContractError:
            raise  # a server fault, not a failed auth: the handler closes 1011
        except Exception:
            if not reauth and conn.authz is not None:  # the SR-189 re-check failed: undo
                registry.unregister(conn.authz)
                conn.authz = None
            # C-2.9: count the failure and audit the 3rd one even when the socket
            # began closing while this auth was in flight.
            cv_ws_auth_failures_total.labels(reason=failure).inc()
            conn.auth_failures += 1
            third = conn.auth_failures >= MAX_AUTH_FAILURES
            if third:
                await audit_auth_failure(conn)
            if conn.closing:
                return  # already closing: no lifecycle step, no err, no second close
            if reauth:
                conn.lifecycle.fire(ConnEvent.REAUTH_FAILED)
            if third:
                conn.close_with("auth_failed")
            else:
                conn.push(build_ws_error("auth_failed", id=_str_or_none(frame.get("id"))))
            return
        if conn.closing:
            return  # closed (expiry, revocation) while this auth was in flight: no auth_ok
        if (ended := revocation_hub.revoked_reason(session_id)) is not None:
            # #2739: revoked before the registration above (inside `authenticate`), so the hub
            # closed nothing. Close it as the hub would: its `bye` and code (4403 for a disabled
            # user), sealed, no auth_ok.
            await conn.closer(*revocation_hub.close_for(ended))
            return
        conn.auth_failures = 0
        conn.watchdog.auth_deadline = None
        conn.watchdog.token_expires_at = now + (expires_ms - now_ms) / 1000
        conn.token_expires_at_ms = expires_ms  # the same instant on the wall clock
        if conn.session_id != session_id:  # the old registration goes only after the check
            if conn.session_id is not None:
                revocation_hub.unregister(conn.session_id, conn.closer)
            conn.pending_session_id = None  # registered above, and now the socket's own
        conn.session_id, conn.user_id = session_id, user_id
        if not reauth:
            svc = registry.services
            conn.emitter = TopicEmitter(
                conn.push,
                connection_id=conn.connection_id,
                wall_ms=conn.wall_ms,
                clock=conn.clock,
                source=svc.snapshots,
                cache=svc.snapshot_cache,
                push_data=conn.push,
            )
            if svc.sequencing is not None:
                svc.sequencing.register(conn.authz, conn.emitter)
        conn.lifecycle.fire(ConnEvent.AUTH_OK)
        payload = auth_ok_payload(
            conn.authz.principal,  # the applied snapshot: the newest, never the stale read
            session_id=session_id,
            token_expires_at_ms=expires_ms,
            kill_switch=killed(),
        )
        conn.push(_reply("auth_ok", frame.get("id"), ts=now_ms, p=payload))
        # E27-T02: current degraded/read-only state, so a client connecting after the
        # transition still gets the blocking notice (§6 `system`, CMP-092). First auth only:
        # an in-place re-auth (token refresh) keeps the socket's existing state.
        if not reauth:
            for body in system_notices() if system_notices is not None else ():
                conn.push_system(body)
        for f in revoked:
            conn.push(f)
        structlog.contextvars.bind_contextvars(user_id=str(user_id), session_id=session_id)
        _log().info(
            "ws authenticated",
            connection_id=conn.connection_id,
            subprotocol=conn.encoding,
            reauth=reauth,
        )
        if not reauth:
            cv_ws_handshake_seconds.observe(max(0.0, conn.clock() - conn.opened_at))
            gateway_hub.enforce_cap(conn)

    def pong(conn: _Connection, frame: dict[str, Any]) -> None:
        now_ms = conn.wall_ms()
        p: dict[str, Any] = {"server_ms": now_ms}
        body = frame.get("p")
        client_ms = body.get("client_ms") if isinstance(body, dict) else None
        if isinstance(client_ms, int) and not isinstance(client_ms, bool):
            p["rtt_hint_ms"] = max(0, now_ms - client_ms)
        conn.push(_reply("pong", frame.get("id"), ts=now_ms, p=p))

    def flush(conn: _Connection) -> None:
        if conn.authz is not None and conn.emitter is not None:
            conn.emitter.flush_pending(list(conn.authz.by_id.values()))

    async def dispatch(conn: _Connection, frame: Any) -> None:
        if isinstance(frame, dict) and "id" in frame and not _is_envelope_id(frame["id"]):
            del frame["id"]  # #2572: never echoed, on any reply; the frame is still handled
        kind = frame.get("t") if isinstance(frame, dict) else None
        fid = frame.get("id") if isinstance(frame, dict) else None
        if kind != "pong" and not conn.rate.allow(conn.clock()):
            conn.rate_strikes += 1
            if conn.rate_strikes > 1:
                conn.close_with("client_rate_limited", retry_after_ms=1000)
            else:
                conn.push(build_ws_error("client_rate_limited", id=_str_or_none(fid)))
            return
        if not conn.lifecycle.can(ConnEvent.HELLO) and kind == "hello":
            conn.violation(fid, "protocol_violation")
        elif conn.lifecycle.can(ConnEvent.HELLO):
            if kind != "hello" or not isinstance(frame, dict):
                conn.close_with("protocol_violation")  # §4.2: hello must be first
                return
            conn.lifecycle.fire(ConnEvent.HELLO)
            body = frame.get("p")
            clock_ms = body.get("clock_ms") if isinstance(body, dict) else None
            now_ms = conn.wall_ms()
            if isinstance(clock_ms, int) and not isinstance(clock_ms, bool):
                cv_ws_clock_skew_ms.observe(abs(now_ms - clock_ms))
            welcome = welcome_payload(
                encoding=conn.encoding.removeprefix("cv.v1."),
                server_version=server_version,
                git_sha=git_sha,
                connection_id=conn.connection_id,
                server_time_ms=now_ms,
                client_clock_ms=clock_ms,
                auth_timeout_s=auth_timeout_s,
            )
            conn.push(_reply("welcome", fid, ts=now_ms, p=welcome))
            conn.lifecycle.fire(ConnEvent.WELCOME_SENT)
        elif not isinstance(frame, dict) or not isinstance(kind, str):
            conn.violation(fid)
        elif kind == "ping":
            pong(conn, frame)
        elif kind == "pong":
            pass  # reply to a server ping; inbound traffic already recorded
        elif kind == "auth":
            await do_auth(conn, frame)
        elif not conn.lifecycle.authenticated:
            conn.unauth_frames += 1
            if conn.unauth_frames >= MAX_UNAUTHENTICATED_FRAMES:
                conn.close_with("not_authenticated")
            else:
                conn.push(build_ws_error("not_authenticated", id=_str_or_none(fid)))
        elif kind == "sub" and conn.authz is not None:
            await _handle_sub(conn.authz, frame, conn.send, now_ms=conn.wall_ms())
            if conn.authz.by_id and conn.lifecycle.can(ConnEvent.SUB_OK):
                conn.lifecycle.fire(ConnEvent.SUB_OK)
            flush(conn)  # §7.1: the `snap` follows `sub_ok`, before any `d`
        elif kind == "unsub" and conn.authz is not None:
            # §5.3 idempotent; §6.2 `system` is permanent (refused, stays attached).
            conn.push(handle_unsub(conn.authz, frame, conn.wall_ms()))
        elif kind == "ctl" and conn.authz is not None:
            conn.push(handle_ctl(conn.authz, frame, conn.wall_ms()))
            flush(conn)  # `ctl_ok { resnapshot }` then the `reconfigure` snap
        elif kind == "resync" and conn.authz is not None and conn.emitter is not None:
            conn.emitter.client_resync(conn.authz, frame)
        else:
            conn.violation(fid)

    async def reader(conn: _Connection) -> None:
        while not conn.closing:
            msg = await conn.ws.receive()
            if msg.get("type") == "websocket.disconnect":
                conn.disconnect_code = msg.get("code")
                return
            conn.watchdog.last_inbound = conn.clock()
            frame = conn.decode(msg, max_frame_bytes)
            if frame is None:
                return
            await dispatch(conn, frame)

    def watch(conn: _Connection) -> bool:
        """Apply the watchdog; True when an unsolicited `ping` is due. Runs
        before every dequeue and every send, not only on an idle tick, so a
        socket fed faster than `tick_s` still expires (#2259 review)."""
        due = conn.due()
        if due == "token_expired":
            conn.close_with(due, seal=True)  # also seals a close already under way
        elif due == "ping":
            return not conn.closing
        elif due is not None:
            conn.close_with(due)
        return False

    async def writer(conn: _Connection) -> None:
        pings = 0
        while True:
            if watch(conn):
                pings += 1
                now_ms = conn.wall_ms()
                conn.push(
                    {"t": "ping", "id": f"s-hb-{pings}", "ts": now_ms, "p": {"server_ms": now_ms}}
                )
            try:
                item = await asyncio.wait_for(conn.outbound.get(), timeout=tick_s)
            except TimeoutError:
                continue
            if item is _CLOSE:
                code = await conn.outbound.get()
                conn.close_code = code
                with contextlib.suppress(Exception):
                    await conn.ws.close(code=code)
                return
            watch(conn)  # the dequeue may have waited a tick; a ping is queued only above
            if conn.sealed and item is not conn.bye_frame:
                continue  # the identity ended while this frame was queued: never send it
            try:
                if type(item) is tuple:  # the hub's sampled data frame, queued with its stamp
                    received, item = item
                    await conn.send_frame(item)
                    now = conn.clock()  # the watchdog's send time, which this frame also observes
                    conn.watchdog.last_outbound = now
                    FANOUT_SECONDS.observe(now - received, SAMPLE_EVERY)
                else:  # every other frame: no stamp, no observation
                    await conn.send_frame(item)
                    conn.watchdog.last_outbound = conn.clock()
            except WebSocketDisconnect as exc:
                conn.disconnect_code = exc.code  # the client left mid-send; the reader saw nothing
                raise

    @router.websocket(WS_PATH)
    async def ws_endpoint(ws: WebSocket) -> None:
        # §2.5 (SR-042, SR-183): first of all - before negotiation, `accept`, any frame,
        # auth or store access. Closing before `accept` refuses the upgrade (HTTP 403).
        raw_headers = ws.scope.get("headers") or ()
        refused = origin_refusal(
            header_values(raw_headers, b"origin"),
            header_values(raw_headers, b"sec-fetch-site"),
            allowed_origins,
        )
        if refused is not None:
            cv_ws_closes_total.labels(reason=ORIGIN_FORBIDDEN).inc()
            log_refusal(refused, ws.scope)
            await ws.close(code=int(CLOSE_REASONS[ORIGIN_FORBIDDEN][0]))
            return
        # §4.3: a token in the URL query string is never read; it is ignored.
        encoding = negotiate_subprotocol(ws.scope.get("subprotocols") or ())
        if encoding is None:
            # Closed before `accept`, so not through `close_with`: it counts itself, as the origin
            # refusal above does.
            cv_ws_closes_total.labels(reason="unsupported_protocol").inc()
            await ws.close(code=int(CLOSE_REASONS["unsupported_protocol"][0]))
            return
        await ws.accept(subprotocol=encoding)
        conn = _Connection(
            ws, encoding=encoding, clock=clock, wall_ms=wall_ms, auth_timeout_s=auth_timeout_s
        )
        conn.lifecycle.fire(ConnEvent.OPEN_NEGOTIATED)
        gateway_hub.add(conn)
        cv_ws_connections_in_use.inc()
        structlog.contextvars.bind_contextvars(connection_id=conn.connection_id)
        # TG5: exactly one reader (this handler task) and one writer task,
        # owned here and always cancelled + awaited before returning (C-2.18).
        write_task = spawn(writer(conn), name=f"{conn.connection_id}-writer")
        handler = asyncio.current_task()
        reading = True

        def _writer_done(_t: asyncio.Task[None]) -> None:
            # The close frame is out (or the writer failed): stop the blocked read.
            if reading and handler is not None:
                handler.cancel(msg=_WRITER_DONE)

        write_task.add_done_callback(_writer_done)
        fault: BaseException | None = None
        try:
            await reader(conn)
            reading = False
            if conn.closing:
                # Let the writer flush `bye` + close frame (bounded), then stop.
                await asyncio.wait({write_task}, timeout=CLOSE_FLUSH_TIMEOUT_S)
        except WebSocketDisconnect as exc:
            conn.disconnect_code = exc.code
        except asyncio.CancelledError as exc:
            if not (
                exc.args == (_WRITER_DONE,) and handler is not None and handler.uncancel() == 0
            ):
                raise  # a real cancellation of the handler: honour it
        except Exception as exc:
            fault = exc
        finally:
            reading = False
            write_task.cancel()
            try:
                if fault is None:
                    fault = await _join_writer(write_task)
                if fault is not None:
                    # The handler's own `bye` and 1011 do not go through `close_with`: count here.
                    cv_ws_closes_total.labels(reason="internal_error").inc()
                    _log().error(
                        "ws connection fault", connection_id=conn.connection_id, exc_info=fault
                    )
                    with contextlib.suppress(Exception):  # S11: bye before the 1011 close
                        bye = lifecycle_bye("internal_error", now_ms=wall_ms())
                        await conn.send_frame(bye)
                        await ws.close(code=int(CLOSE_REASONS["internal_error"][0]))
            finally:
                # Whatever leaves the `try` above runs the whole tail: `_join_writer` re-raises the
                # handler's own cancellation (uvicorn's graceful-timeout cancel, mid-read), and a
                # skipped tail leaks the hub entry, registries, upstream leases and the close
                # audit. That `CancelledError` still propagates once the tail is done. Each
                # synchronous step has its own guard, so one that raises (a lease release, say)
                # is logged and neither skips the others nor replaces that cancellation.
                with _step(conn, "hub"):
                    gateway_hub.discard(conn)
                with _step(conn, "gauge"):
                    cv_ws_connections_in_use.dec()
                if conn.authz is not None:
                    with _step(conn, "sequencing"):
                        if registry.services.sequencing is not None:
                            registry.services.sequencing.unregister(conn.authz)
                    with _step(conn, "registry"):
                        registry.unregister(conn.authz)
                if conn.session_id is not None:
                    with _step(conn, "revocation"):
                        revocation_hub.unregister(conn.session_id, conn.closer)
                try:
                    await audit_close(conn, fault)
                finally:
                    with _step(conn, "lifecycle"):
                        if conn.lifecycle.can(ConnEvent.CLOSE):
                            conn.lifecycle.fire(ConnEvent.CLOSE)
                        conn.lifecycle.fire(ConnEvent.CLOSED)
                    structlog.contextvars.unbind_contextvars(
                        "connection_id", "user_id", "session_id"
                    )

    return router
