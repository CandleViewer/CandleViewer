"""Live WS gateway endpoint (`23-ws-protocol.md` §2.2, §4, §8.5, §9; E17-S01).

One socket = one `_Connection` with exactly one reader and one writer task,
both spawned via `cv.obs.spawn` and owned by the handler (`20-architecture.md` TG5):

- **Negotiation** (§2.2): the subprotocol is chosen before `accept`; when the
  client offers none we serve -> close `1002` before the handshake completes.
- **hello -> welcome** (§4.2): any other first frame -> `bye` + `1002`.
- **auth -> auth_ok** (§4.3): the token is read ONLY from the `auth` frame
  body, never the URL. Verified by the injected E09 `authenticate`; the
  `PrincipalSnapshot` is resolved by the `ConnectionRegistry` (the same RBAC
  source REST uses); the socket is registered with the `RevocationHub`.
  Three failures -> `bye auth_failed` + `4401` + a `warning` audit entry.
- **In-place re-auth** (§4.1): a later `auth` re-validates and swaps the
  principal without touching subscriptions.
- **Heartbeats / deadlines** (§9.1): the writer polls a `Watchdog` on the
  injected clock (auth timeout, token expiry, unsolicited `ping`, heartbeat
  timeout), so tests drive time instead of sleeping.
- **Inbound limits**: size checked before decoding (`1009`); 30/s and 300/min
  excluding `pong` (`client_rate_limited`, then `4429`).
- Every server-initiated close goes through `_Connection.close_with`, which
  queues `bye` ahead of the close frame (requirement S11).

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
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.context import spawn
from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.lifecycle import (
    CLOSE_REASONS,
    MAX_AUTH_FAILURES,
    MAX_CONNECTIONS_PER_USER,
    MAX_PROTOCOL_VIOLATIONS,
    MAX_UNAUTHENTICATED_FRAMES,
    SHUTDOWN_GRACE_MS,
    ConnEvent,
    InboundRateLimiter,
    Lifecycle,
    Watchdog,
    negotiate_subprotocol,
    welcome_payload,
)
from candleviewer.ws.lifecycle import bye_frame as lifecycle_bye
from candleviewer.ws.limits import AUTH_TIMEOUT_S, MAX_INBOUND_FRAME_BYTES
from candleviewer.ws.metrics import (
    cv_ws_auth_failures_total,
    cv_ws_clients,
    cv_ws_clock_skew_ms,
    cv_ws_closes_total,
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
#: Upper bound for the writer to flush `bye` + close once the reader stopped.
CLOSE_FLUSH_TIMEOUT_S: Final = 2.0
#: Token lifetime assumed when `authenticate` reports no expiry (E09
#: ACCESS_TOKEN_TTL is 12 min); measured from the successful `auth`.
DEFAULT_TOKEN_TTL_S: Final = 12 * 60.0

#: (raw access token) -> (session_id, user_id) or (session_id, user_id,
#: token expires_at); raises on any invalid token.
AuthResult = tuple[str, uuid.UUID] | tuple[str, uuid.UUID, datetime]
Authenticate = Callable[[str], Awaitable[AuthResult]]
Clock = Callable[[], float]
WallClockMs = Callable[[], int]


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

    def broadcast_system(self, body: dict[str, Any]) -> int:
        """Push one `system` frame (e.g. §12.5 `kill_switch`) to every authenticated socket."""
        conns = [c for c in self._live if c.lifecycle.authenticated]
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
        conns = [c for c in self._live if c.lifecycle.authenticated]
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
        self.authz: ConnectionAuthz | None = None
        self.emitter: TopicEmitter | None = None
        self.system_seq = 0
        self.auth_failures = 0
        self.unauth_frames = 0
        self.violations = 0
        self.rate_strikes = 0
        self.closing = False
        self.close_code: int | None = None
        self.opened_at = now

    # -- outbound -----------------------------------------------------------

    def push(self, frame: dict[str, Any]) -> None:
        """Queue one frame; a full queue is a slow consumer (C-2.18 policy)."""
        if self.closing:
            return
        if self.outbound.qsize() >= OUTBOUND_QUEUE_MAX:
            self.close_with("slow_consumer")
            return
        self.outbound.put_nowait(frame)

    async def send(self, frame: dict[str, Any]) -> None:
        """Async adapter for `ConnectionRegistry` / `handle_sub`."""
        self.push(frame)

    def push_system(self, body: dict[str, Any]) -> None:
        self.system_seq += 1
        self.push(
            {"t": "d", "ch": SYSTEM_TOPIC, "s": self.system_seq, "ts": self.wall_ms(), "e": "j"}
            | {"p": body}
        )

    def close_with(
        self,
        reason: str,
        *,
        retry_after_ms: int | None = None,
        bye: dict[str, Any] | None = None,
    ) -> None:
        """The ONE server-initiated close path: `bye`, then the close frame (S11).

        May exceed the `push` bound by exactly these items so a full queue
        can still be closed; every later push is dropped."""
        if self.closing:
            return
        self.closing = True
        frame = bye or lifecycle_bye(reason, now_ms=self.wall_ms(), retry_after_ms=retry_after_ms)
        code = int(frame["p"]["code"])
        bye_reason = str(frame["p"].get("reason", reason))
        cv_ws_closes_total.labels(reason=bye_reason[:40]).inc()
        if self.lifecycle.can(ConnEvent.CLOSE):
            self.lifecycle.fire(ConnEvent.CLOSE)
        for item in (frame, _CLOSE, code):
            self.outbound.put_nowait(item)
        _log().info(
            "ws close",
            connection_id=self.connection_id,
            reason=reason,
            code=code,
            user_id=str(self.user_id) if self.user_id else None,
            session_id=self.session_id,
        )

    async def closer(self, frame: dict[str, Any], code: int) -> None:
        """`RevocationHub` / registry eviction hook -> same close path."""
        del code  # carried inside the bye frame
        self.close_with(str(frame["p"]["reason"]), bye=frame)

    async def evict(self) -> None:
        self.close_with("slow_consumer")

    # -- inbound ------------------------------------------------------------

    def decode(self, msg: Mapping[str, Any], max_frame_bytes: int) -> Any:
        """One ASGI receive message -> decoded frame; `None` after an oversize close.

        Size is checked on the raw payload BEFORE any decoding (1009)."""
        raw: str | bytes = msg.get("text") or msg.get("bytes") or ""
        size = len(raw.encode()) if isinstance(raw, str) else len(raw)
        if size > max_frame_bytes:
            self.close_with("frame_too_big")
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return []  # malformed: handled as a non-object frame

    def violation(self, frame_id: Any, code: str = "frame_malformed") -> None:
        """Malformed/unexpected frame after `hello`; 3 strikes -> `4400` (§4.4)."""
        self.violations += 1
        if self.violations >= MAX_PROTOCOL_VIOLATIONS:
            self.close_with("bad_client")
        else:
            self.push(build_ws_error(code, id=_str_or_none(frame_id)))


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


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
) -> APIRouter:
    """The `/ws` endpoint. `clock` (monotonic seconds) drives every deadline,
    so tests inject a fake clock; `tick_s` is only the poll cadence."""
    router = APIRouter()
    gateway_hub = hub if hub is not None else GatewayHub()
    killed = kill_switch or (lambda: {"engaged": False, "scope": "global"})

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

    async def do_auth(conn: _Connection, frame: dict[str, Any]) -> None:
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
            if reauth and user_id != conn.user_id:
                failure = "user_mismatch"
                raise PermissionError("re-auth must keep the same user")
            principal = await registry.resolve(user_id)
        except Exception:
            cv_ws_auth_failures_total.labels(reason=failure).inc()
            conn.auth_failures += 1
            if reauth:
                conn.lifecycle.fire(ConnEvent.REAUTH_FAILED)
            if conn.auth_failures >= MAX_AUTH_FAILURES:
                await audit_auth_failure(conn)
                conn.close_with("auth_failed")
            else:
                conn.push(build_ws_error("auth_failed", id=_str_or_none(frame.get("id"))))
            return
        conn.auth_failures = 0
        now, now_ms = conn.clock(), conn.wall_ms()
        if len(result) == 3:
            expires_ms = int(result[2].timestamp() * 1000)
        else:
            expires_ms = now_ms + int(DEFAULT_TOKEN_TTL_S * 1000)
        conn.watchdog.auth_deadline = None
        conn.watchdog.token_expires_at = now + max(0, expires_ms - now_ms) / 1000
        if conn.session_id != session_id:
            if conn.session_id is not None:
                revocation_hub.unregister(conn.session_id, conn.closer)
            revocation_hub.register(session_id, conn.closer)
        conn.session_id, conn.user_id = session_id, user_id
        if conn.authz is None:
            conn.authz = ConnectionAuthz(
                principal, registry.services, connection_id=conn.connection_id
            )
            registry.register(conn.authz, conn.send, conn.evict, conn.closer)
            svc = registry.services
            conn.emitter = TopicEmitter(
                conn.push,
                connection_id=conn.connection_id,
                wall_ms=conn.wall_ms,
                clock=conn.clock,
                source=svc.snapshots,
                cache=svc.snapshot_cache,
            )
            if svc.sequencing is not None:
                svc.sequencing.register(conn.authz, conn.emitter)
            revoked: list[dict[str, Any]] = []
        else:
            # Subscriptions + sequences are kept; only ones the refreshed
            # principal no longer allows are revoked (§9.5, same RBAC source).
            frames = conn.authz.apply_snapshot(principal, now_ms)
            revoked = [f for f in frames if f["t"] == "revoked"]
        conn.lifecycle.fire(ConnEvent.AUTH_OK)
        payload = auth_ok_payload(
            principal,
            session_id=session_id,
            token_expires_at_ms=expires_ms,
            kill_switch=killed(),
        )
        conn.push(_reply("auth_ok", frame.get("id"), ts=now_ms, p=payload))
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
            results = handle_unsub(conn.authz, frame)
            conn.push(_reply("unsub_ok", fid, ts=conn.wall_ms(), p={"results": results}))
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
                return
            conn.watchdog.last_inbound = conn.clock()
            frame = conn.decode(msg, max_frame_bytes)
            if frame is None:
                return
            await dispatch(conn, frame)

    async def writer(conn: _Connection) -> None:
        pings = 0
        while True:
            try:
                item = await asyncio.wait_for(conn.outbound.get(), timeout=tick_s)
            except TimeoutError:
                due = conn.watchdog.due(conn.clock())
                if due == "ping" and not conn.closing:
                    pings += 1
                    now_ms = conn.wall_ms()
                    conn.push(
                        {
                            "t": "ping",
                            "id": f"s-hb-{pings}",
                            "ts": now_ms,
                            "p": {"server_ms": now_ms},
                        }
                    )
                elif due is not None and due != "ping":
                    conn.close_with(due)
                continue
            if item is _CLOSE:
                code = await conn.outbound.get()
                conn.close_code = code
                with contextlib.suppress(Exception):
                    await conn.ws.close(code=code)
                return
            await conn.ws.send_text(json.dumps(item, separators=(",", ":")))
            conn.watchdog.last_outbound = conn.clock()

    @router.websocket(WS_PATH)
    async def ws_endpoint(ws: WebSocket) -> None:
        # §4.3: a token in the URL query string is never read; it is ignored.
        encoding = negotiate_subprotocol(ws.scope.get("subprotocols") or ())
        if encoding is None:
            await ws.close(code=int(CLOSE_REASONS["unsupported_protocol"][0]))
            return
        await ws.accept(subprotocol=encoding)
        conn = _Connection(
            ws, encoding=encoding, clock=clock, wall_ms=wall_ms, auth_timeout_s=auth_timeout_s
        )
        conn.lifecycle.fire(ConnEvent.OPEN_NEGOTIATED)
        gateway_hub.add(conn)
        cv_ws_clients.inc()
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
        except WebSocketDisconnect:
            pass
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
            if fault is None:
                fault = await _join_writer(write_task)
            if fault is not None:
                _log().error(
                    "ws connection fault", connection_id=conn.connection_id, exc_info=fault
                )
                with contextlib.suppress(Exception):  # S11: bye before the 1011 close
                    bye = lifecycle_bye("internal_error", now_ms=wall_ms())
                    await ws.send_text(json.dumps(bye))
                    await ws.close(code=int(CLOSE_REASONS["internal_error"][0]))
            gateway_hub.discard(conn)
            cv_ws_clients.dec()
            if conn.authz is not None:
                if registry.services.sequencing is not None:
                    registry.services.sequencing.unregister(conn.authz)
                registry.unregister(conn.authz)
            if conn.session_id is not None:
                revocation_hub.unregister(conn.session_id, conn.closer)
            if conn.lifecycle.can(ConnEvent.CLOSE):
                conn.lifecycle.fire(ConnEvent.CLOSE)
            conn.lifecycle.fire(ConnEvent.CLOSED)
            structlog.contextvars.unbind_contextvars("connection_id", "user_id", "session_id")

    return router
