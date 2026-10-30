"""Live WS gateway endpoint (`23-ws-protocol.md` §2.2, §4, §8.5, §9; E17-S01).

One socket = one `_Connection` with exactly one reader and one writer task,
both spawned via `cv.obs.spawn` and owned by the handler (`20-architecture.md` TG5):

- **Origin** (§2.5, SR-042/SR-183): checked first, against `CV_ALLOWED_ORIGINS`; the
  allow-list decides. A missing, duplicated, `null` or unlisted `Origin` is closed `4403`
  before `accept` (HTTP 403, no `bye`): no negotiation, frame, auth or store access. Each
  refusal is counted and logged with the source address MeshOnly admitted, with a cap, and
  audited (`auth.ws_origin_refused`) within the `OriginRefusalAudit` bounds (#2269).
- **Negotiation** (§2.2): the subprotocol is chosen before `accept`; when the
  client offers none we serve -> close `1002` before the handshake completes, counted
  as `unsupported_protocol` as the origin refusal is counted as `origin_forbidden`.
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
  A user disabled meanwhile is refused too, on a session no revocation names (one a refresh
  rotated): the registry remembers the disable for one access-token lifetime, and a registration
  on a token issued at or before it gets `bye user_disabled` + `4403`, never `auth_ok` (#3413).
  The identity ends at the token's expiry as `authenticate` reports it (the
  first refusal on time grounds); an already-expired token is refused like
  any failed `auth`. Revocation is pushed through the `RevocationHub`; the
  idle lock intentionally does not end the socket (E09-S03; #2259).
  Three failures -> `bye auth_failed` + `4401` + a `warning` audit entry.
  An `AuthRefused` from `authenticate` (an enrolment-only session, #2295, or a user
  disabled since its lookup, `user_disabled` as above) closes at once with its own
  `bye` (`4403`): not a failure, and nothing is registered. It is logged, and an
  enrolment-only one audited, with the socket's source address; a `user_disabled` one is counted
  in `cv_ws_revoked_total` as `refuse_disabled` counts it, and its line also names the session.
  The principal must be the token's user's, or the `auth` fails as `user_mismatch` (#415):
  a first `auth` checks it before it registers, `apply_snapshot` every later snapshot.
- **`system` snap** (§12.1, #4992): a socket's first `auth_ok` its principal may see `system` on
  is followed by the `system` snap, `s` 1 (`kind` `health`: the latest health frame, the kill switch
  `auth_ok` gave, the role's flags), then deltas from `s` 2. A `system` frame offered before the
  snap is held and follows it, so no delta ever precedes it. An in-place re-`auth` sends none.
- **Connect rate** (§4.3, #2558): a new socket's first successful `auth` is counted per user
  (`GatewayHub.admit_connect`, `CV_WS_MAX_AUTHS_PER_USER_PER_MIN` per sliding minute). Past the
  limit the socket gets `bye client_rate_limited` + `4429` instead of `auth_ok`: it never
  authenticates, so it writes no `ws.connection.closed` row. Failed and in-place re-`auth`s are
  not counted.
- **In-place re-auth** (§4.1): a later `auth` re-validates and swaps the
  principal without touching subscriptions. The old session stays registered
  with the hub until the new one is accepted. It keeps the user, checked twice: the token's
  user here and the snapshot's by `ConnectionAuthz.apply_snapshot` (#415). Either check
  alone refuses another user as one failed `auth` (`user_mismatch`).
- **Heartbeats / deadlines** (§9.1): the writer checks a `Watchdog` before
  every dequeue and every send, not only when idle, on the injected clocks
  (auth timeout, token expiry on both clocks, unsolicited `ping`, heartbeat
  timeout), so tests drive time instead of sleeping. From the first `auth_ok` a timer the
  connection owns runs the same check at the token expiry and the heartbeat deadline (#3100),
  so those closes, and with the flag on their flush deadline, start then even while the writer
  is parked in a send. A re-`auth` re-arms it; it stops at the first close; a check that raises
  on it ends the connection `internal_error` (as a writer fault does, if no close took); and
  teardown cancels it first.
- **Inbound limits**: size checked before decoding (`1009`), 8 KiB until the first `auth_ok`;
  30/s and 300/min (`client_rate_limited`, then `4429`), in tokens a frame takes by its size,
  charged once per frame of every kind before the frame is decoded, so a refused frame is never
  decoded and its `err` has no `id`.
  From the first `auth_ok` a frame that opens with `t: "pong"` is counted only once its
  `PongBudget` is spent, and one over `MAX_PONG_BYTES` closes `protocol_violation` (§8.5), never
  decoded. A JSON frame past the container cap or the SR-185 value bound (over-counted on its
  text) is malformed and never decoded; one within them decodes through the C decoder, its depth
  checked on the decoded value (SR-184).
  An envelope `id` that is not a string of at most `ENVELOPE_ID_MAX_LEN` characters is dropped
  before the frame is handled, so no reply echoes it (§13.1, #2572). Fair scheduling between
  connections: the reader yields to the loop after each frame it handles, and `handle_sub` within
  a long `sub`.
- Every server-initiated close after `accept` goes through `_Connection.close_with`, which
  queues `bye` ahead of the close frame (requirement S11), except the handler's own fault `bye`
  and 1011, which the handler counts itself. Token expiry and revocation seal the close:
  anything still queued is dropped, `bye` next.
- **Fan-out span** (the gateway segment of budget #6, from the subscription's hub turn, not bus
  receipt): `TopicEmitter` queues one data frame (`snap` / `d`) of a subscription in
  `SAMPLE_EVERY` with the clock reading at which the hub took it (a `snap`: on entry to
  `TopicEmitter.snapshot`, so its build is inside the span), and the writer observes
  `cv_ws_fanout_seconds` for it, weighted, once the send has returned. Unsampled frames
  carry no stamp and read no clock. Control frames and dropped frames are not observed; a
  client's drain wait, a slow consumer's backlog and replay frames are inside the span. The
  same stamped frame's encode time and size are observed too, in the codec its connection
  negotiated (`kind="json"` for `json.dumps` text, `kind="msgpack"` for MessagePack bytes; timed
  with `perf_counter`, not the injected clock), and its CVWB body was timed by the encoder.
  While latency telemetry is on, that frame also carries a span id `sp` (23 §3.1): its bytes
  are observed without it, and once it is sent the writer logs a debug `ws frame span` record.

- **Backpressure flag** (E17-T03, `CV_WS_BACKPRESSURE_ENABLED`, default on since #4883):
  `ws/pipeline.py` replaces the outbound queue. Frames are encoded once at push (where a
  stamped frame's encode is timed and sized), onto two lanes inside one 8 MiB / 2 000-frame
  budget, which the §8.4 ladder holds from the first `auth_ok` (drop, `backpressure`
  re-snapshot, `slow_consumer` close); the writer drains it. A control frame that ends or resets
  a subscription's stream drops what it overtakes of it (§8.4 Lanes). The `bye` takes a terminal
  slot, and every close flushes under one deadline, past which the socket goes with no `bye`
  (§4.4, §8.4); the close audit records the ladder's trigger and an expired flush (§4.3). The
  hub's deltas go through the pipeline's pacer (§8.1); the writer's turn closes due windows. It
  also classifies the connection every `CV_WS_CLASSIFY_INTERVAL_MS`, announcing a class change on
  `system` (§8.3), and sends the RTT probe `ping`, whose `pong` `dispatch` hands the pipeline at
  the frame's receipt (§9.1). The idle heartbeat `ping` is unchanged; while the probe runs, the
  outbound traffic does not idle long enough for it to fire.

Bounds (C-2.18): outbound queue `OUTBOUND_QUEUE_MAX` (full -> `slow_consumer`
close), or the pipeline's budget with the flag on; rate-limiter window,
`MAX_CONNECTIONS_PER_USER` per user (oldest idle connection closed),
`MAX_AUTHS_PER_USER_PER_MIN` new sockets per user per minute (state only for users
active in the last window), `MAX_UNAUTHENTICATED_SOCKETS` sockets awaiting auth and
`AUTH_CALL_TIMEOUT_S` per `auth` call (#2155). Transport only: no business logic, no data fan-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.net import RESOLVED_SOURCE_KEY
from candleviewer.observability.context import current_request_id, current_request_uuid, spawn
from candleviewer.settings import CLOSE_AUDIT_TIMEOUT_S, CLOSE_FLUSH_TIMEOUT_S
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.codec import (
    MAX_MSGPACK_VALUES,
    MAX_PREAUTH_MSGPACK_VALUES,
    decode_client_frame,
    encode_server_frame,
)
from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.lifecycle import (
    CLOSE_REASONS,
    CONNECT_RATE_MESSAGE,
    MAX_AUTH_FAILURES,
    MAX_AUTHS_PER_USER_PER_MIN,
    MAX_CONNECTIONS_PER_USER,
    MAX_PROTOCOL_VIOLATIONS,
    MAX_UNAUTHENTICATED_FRAMES,
    ORIGIN_FORBIDDEN,
    OTHER_CLOSE_REASON,
    REFUSAL_LOG_LIMIT,
    REFUSAL_LOG_WINDOW_S,
    SHUTDOWN_GRACE_MS,
    SUBPROTOCOL_MSGPACK,
    ConnectRateLimiter,
    ConnEvent,
    DecodeBudget,
    InboundRateLimiter,
    Lifecycle,
    OriginRefusal,
    PongBudget,
    RefusalLog,
    RefusalLogLimiter,
    Watchdog,
    clamp_ms,
    client_epoch_ms,
    header_values,
    negotiate_subprotocol,
    origin_refusal,
    welcome_features,
    welcome_payload,
)
from candleviewer.ws.lifecycle import bye_frame as lifecycle_bye
from candleviewer.ws.limits import (
    AUTH_CALL_TIMEOUT_S,
    AUTH_TIMEOUT_S,
    ENVELOPE_ID_MAX_LEN,
    INBOUND_WEIGHT_CONTAINERS,
    INBOUND_WEIGHT_VALUES,
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_CONTAINERS,
    MAX_JSON_DEPTH,
    MAX_PONG_BYTES,
    MAX_PREAUTH_FRAME_BYTES,
    MAX_UNAUTHENTICATED_SOCKETS,
    inbound_frame_weight,
    json_nests_deeper,
    json_values_over_count,
)
from candleviewer.ws.metrics import (
    FANOUT_SECONDS,
    JSON_ENCODE_SECONDS,
    JSON_FRAME_BYTES,
    MSGPACK_ENCODE_SECONDS,
    MSGPACK_FRAME_BYTES,
    SAMPLE_EVERY,
    count_audit_failure,
    cv_ws_auth_failures_total,
    cv_ws_clock_skew_ms,
    cv_ws_closes_total,
    cv_ws_connect_rate_limited_total,
    cv_ws_connections_in_use,
    cv_ws_decode_budget_refused_total,
    cv_ws_handshake_seconds,
    cv_ws_overflow_total,
    cv_ws_system_frames_withheld_total,
    frame_bytes,
)
from candleviewer.ws.origin_audit import OriginRefusalAudit
from candleviewer.ws.outbound import Key, Spanned, data_key
from candleviewer.ws.pacing import never_stalled
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SnapshotUserMismatch,
    Subscription,
    audit_rebuild_refusal,
    auth_ok_payload,
    handle_ctl,
    handle_unsub,
)
from candleviewer.ws.permissions import handle_sub as _handle_sub
from candleviewer.ws.pipeline import (
    CLOSE_FLUSH_DEADLINE,
    ConnectionPipeline,
    Terminal,
    slow_consumer_bye,
)
from candleviewer.ws.revocation import (
    CLOSE_USER_DISABLED,
    RevocationHub,
    user_disabled_bye,
    ws_revoked_total,
)
from candleviewer.ws.sequencing import TopicEmitter
from candleviewer.ws.system_filter import (
    FlagVisible,
    kill_switch_view,
    system_view,
    withheld_reason,
)

WS_PATH = "/ws"
#: #3907: the REST contract's server base (`22-api-openapi.yaml` `servers`). The gateway's one route
#: is also served under it, as `/api/v1/ws`: the external URL the web client opens (23 section
#: 2.1). The same router is included twice, so it is one gateway, not a second one.
WS_SERVER_BASE: Final = "/api/v1"
SYSTEM_TOPIC: Final = "system"
#: #4992: the `system` frames a socket holds while its snap is not yet queued (the `auth_ok` turn's
#: one flag read, at most `AUTH_CALL_TIMEOUT_S`); past it the oldest goes and the newest stay
#: (C-2.18). A socket whose principal holds no role holds nothing: it is cut every frame.
SYSTEM_HELD_MAX: Final = 256
OUTBOUND_QUEUE_MAX: Final = 1024
#: The items `close_with` queues past the `push` bound: `bye`, the close sentinel and its code.
CLOSE_ITEMS: Final = 3
#: #2155 (§4.3): the `bye` reason of a socket shed at `GatewayHub.max_unauthenticated`.
SHED_REASON: Final = "server_shedding_load"
WATCHDOG_TICK_S: Final = 0.05
#: #571: a writer yields the loop after this many sends in a row. A send to a writable socket
#: never suspends (loopback, a fast peer), so a writer that suspended only on an empty queue would
#: write a whole backlog (up to 2 000 frames, 8 MiB) in one loop turn, and every other connection,
#: the loop's timers and the `/metrics` listener sharing the loop would wait for all of it: under
#: load the loop then never keeps its timers and a scrape goes unanswered. A count, not a time: a
#: send parked on a full socket has already given the loop its turns, which a clock cannot tell.
WRITER_SLICE_FRAMES: Final = 32
#: #3100: the close timer reads its deadlines again at least every this many ticks (1 s by default),
#: so a clock no loop timer can wait on is read within it: the wall clock, which an NTP step or a
#: resume moves on its own, or an injected `clock` that is not the loop's.
CLOSE_RECHECK_TICKS: Final = 20
#: #3100: the least delay of the timer's re-arm after a check that found nothing due. uvloop rounds
#: a delay to whole milliseconds and can fire a little early, so the rest is waited to the
#: millisecond, not a tick; only a check that raised is re-armed a tick on.
CLOSE_REARM_MIN_S: Final = 0.001
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


#: Writes the record of an `AuthRefused` once the gateway supplies the socket's source address.
RefusalAudit = Callable[[str | None], Awaitable[None]]
FlagSnapshot = Callable[[uuid.UUID, frozenset[str]], Awaitable[dict[str, Any] | None]]
#: §12.1 (#4992): the latest `health` frame for the `system` snap, `None` while there is none yet.
SystemBaseline = Callable[[], Mapping[str, Any] | None]
#: The fields of a `health` frame the snap carries (§12.1, §15.9 `health`); `kind` is the snap's.
SNAP_HEALTH_FIELDS: Final = (
    "health",
    "components",
    "exchange",
    "clock_offset_ms",
    "degraded_topics",
)
#: §9.6 (#3085): the view-as binding of the session an `auth` presents, `None` when it holds no
#: context. A read it cannot make raises, and the `auth` fails: never a scope it could not check.
#: `ViewAsService.evaluate` in production (`view_as_wiring.SessionViewAs`).
ViewAsRead = Callable[[str], Awaitable[ViewAsBinding | None]]


#: §9.6 (#3085): the client frame types of §3.1; each reads or tunes the connection. A type added
#: later that changes server-side state is an action frame unless the change that adds it lists
#: it here; while its session views as another user, the gateway refuses an action frame.
READ_FRAME_TYPES: Final = frozenset(
    {"hello", "auth", "ping", "pong", "sub", "unsub", "ctl", "resync"}
)
ACTION_FRAME_TYPES: Final[frozenset[str]] = frozenset()


class ViewAsFrameRefusals(Protocol):
    """§9.6: writes a refused action frame's `admin.view_as_refused` (the viewer and the viewer's
    session the actor, the frame type the object, never its payload) within the viewer's refusal
    budget. True: written. `view_as_wiring.SessionViewAsRefusals` over S6's recorder."""

    async def refuse_frame(
        self,
        *,
        viewer_user_id: uuid.UUID,
        viewer_session_id: str,
        frame_type: str,
        ip: str | None,
        request_id: uuid.UUID | None = None,
    ) -> bool: ...


def _context_of(binding: ViewAsBinding | None) -> str | None:
    return None if binding is None else str(binding.context_id)


class AuthRefused(Exception):
    """Raised by the injected `authenticate` for a live token whose session may not use the
    socket: an enrolment-only session (#2295, §4.3), or one whose user was disabled or deleted
    since its lookup (`user_disabled`, as a late registration, #3413). The socket closes at once
    with a `bye` carrying `reason` (a `CLOSE_REASONS` key); it is not a failed `auth`, and the
    socket is never registered. *audit*, when given, is awaited once that sealed close is
    queued, with the socket's source address, so the record names it as the HTTP twin's does
    (C-2.9). Only `session_id` and `user_id` of *ids* join the gateway's log line of the refusal."""

    def __init__(
        self, reason: str, *, audit: RefusalAudit | None = None, ids: dict[str, str] | None = None
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.audit = audit
        self.ids = ids or {}


def _token_expiry_ms(result: AuthResult) -> int:
    """The token expiry of an `authenticate` result as epoch ms. It is floored,
    so it is never later than the real expiry."""
    expires_at = result[2] if len(result) == 3 else None
    if not isinstance(expires_at, datetime) or expires_at.utcoffset() is None:
        raise AuthenticatorContractError(
            "authenticate must return (session_id, user_id, timezone-aware expires_at)"
        )
    return (expires_at - _EPOCH) // _ONE_MS


class AuthCallTimeout(Exception):
    """An `auth` call (the arg names it) outlived its bound: a server fault, not a failed `auth`."""


@contextlib.asynccontextmanager
async def _auth_call(call: str, bound_s: float) -> AsyncIterator[None]:
    """One external call of an `auth`, bounded (C-2.18). Its expiry raises `AuthCallTimeout`; a
    `TimeoutError` the call raises itself stays a failed `auth`; a cancellation passes through."""
    scope = asyncio.timeout(bound_s)
    try:
        async with scope:
            yield
    except TimeoutError:
        if not scope.expired():
            raise
        raise AuthCallTimeout(call) from None


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _log_span(connection_id: str, sp: str, ch: str | None, s: int | None, fanout_s: float) -> None:
    """The backend half of a sampled frame's trace (23 §3.1): after the send, one debug record
    keyed by the frame's `sp`, with its `ch`, `s` and fan-out span (`cv_ws_fanout_seconds`), never
    its payload. It exists only while the process logs at debug (`CV_LOG_LEVEL=debug`, from which
    `configure_logging` sets both the root level and structlog's filter), so the root level is
    checked first: below debug a stamped frame builds no logger. A run-time override of `ws`
    (E04-T02, stdlib levels only) can hide the record, not show it."""
    if logging.root.isEnabledFor(logging.DEBUG):
        _log().debug(
            "ws frame span",
            connection_id=connection_id,
            span_id=sp,
            ch=ch,
            s=s,
            fanout_ms=round(fanout_s * 1000, 3),
        )


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


_CLOSE = object()  # writer sentinel: the next queue item is the close code
#: `_Connection.decode`'s answer for a frame over its size cap or `MAX_PONG_BYTES`, whose close is
#: already queued: the reader stops. Not `None`: `null` (JSON) and nil (msgpack) decode to `None`,
#: and a frame that does is a non-object strike like any other malformed frame (#2905).
_OVERSIZE = object()
#: `_Connection.decode`'s answer for a frame the inbound rate refused before it was decoded: its
#: strike is already counted (`err`, or the close), and there is nothing to dispatch.
_REFUSED = object()


@dataclass(frozen=True, slots=True)
class _Weighed:
    """A frame `_Connection.weigh` sized and weighed, not yet charged or decoded (#4924)."""

    raw: str | bytes
    values: int  # the MessagePack value budget in force
    counted: int  # a JSON frame's value over-count
    bound: int  # its values, bounded above, up to one past the value bound
    boxes: int  # a MessagePack frame's containers, bounded above, up to one past the cap
    weight: int
    pong: bool
    pong_bound: bool


_WRITER_DONE: Final = "cv-ws-writer-done"  # cancel msg: writer finished, stop reading


class GatewayHub:
    """Every live connection: per-user cap (§4, 8 per user), the per-user connect rate (§4.3,
    20 new sockets per user per minute) and the §9.4 planned-shutdown broadcast. Bounded by the
    per-user cap after auth and by `max_unauthenticated` before it (#2155)."""

    def __init__(
        self,
        *,
        max_per_user: int = MAX_CONNECTIONS_PER_USER,
        max_auths_per_min: int = MAX_AUTHS_PER_USER_PER_MIN,
        max_unauthenticated: int = MAX_UNAUTHENTICATED_SOCKETS,
    ) -> None:
        self.max_per_user = max_per_user
        self.max_unauthenticated = max_unauthenticated
        #: The server is shutting down: set by `shutdown()` and by `candleviewer.server` when its
        #: own shutdown begins (a forced exit or a failure may never reach `shutdown()`). Only
        #: `WsRuntime.start()` clears it, for an in-process restart. `closed_reason` reads it to
        #: tell uvicorn's own `1012` from one a client sends.
        self.shutting_down = False
        self.connect_rate = ConnectRateLimiter(max_auths_per_min)
        self._live: set[_Connection] = set()
        #: The sockets between `accept` and their first `auth_ok` (`admit_unauthenticated`).
        self._unauthenticated: set[_Connection] = set()
        #: #4924 (§8.5): each user's decode budget, kept while the user holds a live socket and,
        #: after the last one, until it has refilled to its burst (`_idle`, pruned whenever the hub
        #: touches the map): bounded by the live users plus those whose last socket closed within
        #: the refill time (16 s), which the per-user connect rate bounds in turn.
        self._budgets: dict[uuid.UUID, DecodeBudget] = {}
        #: #4924 (§8.5): each user's decode turn (`_Connection.decode_turn`), kept with its budget.
        self._turns: dict[uuid.UUID, asyncio.Lock] = {}
        self._idle: set[uuid.UUID] = set()
        self._empty = asyncio.Event()
        self._empty.set()

    def __len__(self) -> int:
        return len(self._live)

    @property
    def unauthenticated(self) -> int:
        """How many sockets count against `max_unauthenticated` now."""
        return len(self._unauthenticated)

    def admit_unauthenticated(self, conn: _Connection) -> None:
        """#2155 (§4.3): count `conn` until its first `auth_ok` (`mark_authenticated`) or its end
        (`discard`). The handler calls it right before the `try` whose `finally` discards it, with
        no await since it found fewer than `max_unauthenticated` counted (else it sheds `conn`)."""
        self._unauthenticated.add(conn)

    def mark_authenticated(self, conn: _Connection) -> None:
        """`conn` sent its first `auth_ok`, so it stops counting; a re-auth never counts."""
        self._unauthenticated.discard(conn)

    def add(self, conn: _Connection) -> None:
        self._live.add(conn)
        self._empty.clear()

    def discard(self, conn: _Connection) -> None:
        self._live.discard(conn)
        self._unauthenticated.discard(conn)
        user = conn.user_id
        if user is not None and user in self._budgets:
            if not any(c.user_id == user for c in self._live):
                self._idle.add(user)  # the user's last socket: the budget waits to refill
            self._prune(conn.clock())
        if not self._live:
            self._empty.set()

    def decode_budget(self, user_id: uuid.UUID, now: float) -> DecodeBudget:
        """The decode budget every socket of `user_id` shares (§8.5, #4924), made at its first
        `auth_ok`; a socket that authenticates while it is still refilling after the user's last
        socket closed gets the same one, at its level."""
        self._idle.discard(user_id)
        self._prune(now)
        budget = self._budgets.get(user_id)
        if budget is None:
            budget = self._budgets[user_id] = DecodeBudget()
            self._turns[user_id] = asyncio.Lock()
        return budget

    def decode_turn(self, user_id: uuid.UUID) -> asyncio.Lock:
        """The decode turn every socket of `user_id` shares (§8.5, #4924), kept with its budget
        (`decode_budget` first)."""
        return self._turns[user_id]

    def _prune(self, now: float) -> None:
        """Drop the budgets of users with no live socket once they have refilled to the burst:
        one made afresh would be the same."""
        for user in [u for u in self._idle if self._budgets[u].full(now)]:
            self._idle.discard(user)
            del self._budgets[user], self._turns[user]

    async def wait_empty(self) -> None:
        """Return once every connection handler has finished (callers bound it)."""
        await self._empty.wait()

    def of_user(self, user_id: uuid.UUID) -> list[_Connection]:
        return [c for c in self._live if c.user_id == user_id]

    def admit_connect(self, user_id: uuid.UUID, now: float) -> int | None:
        """Count one new socket of `user_id` at monotonic `now` (its first successful `auth`):
        None admits it, else the `retry_after_ms` of the refusal (`ConnectRateLimiter.admit`)."""
        return self.connect_rate.admit(user_id, now)

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
        """How many connections `shutdown()` offers the `shutdown_notice` (each gets its §15.9
        view of it, or none; every one gets the `bye`)."""
        return len(self._authenticated())

    def system_sessions(
        self,
    ) -> list[tuple[uuid.UUID, frozenset[str], Callable[[dict[str, Any]], None]]]:
        """Each authenticated socket's subject, roles and `system` push (the feature-flag
        push). A viewing socket's subject is its target (§9.6), whose flags REST resolves too:
        a viewing request answers as its subject (#3085)."""
        return [
            (c.authz.principal.user_id, c.authz.principal.roles, c.push_system)
            for c in self._authenticated()
            if c.user_id is not None and c.authz is not None
        ]

    def broadcast_system(self, body: dict[str, Any]) -> int:
        """Offer one `system` frame (e.g. §12.5 `kill_switch`) to every authenticated socket: each
        queues its §15.9 view of it, or nothing. Returns how many were offered it. An
        `account_notice`'s `exchange_account_ids` is a `list` of canonical lowercase UUID strings
        (`str(UUID)`), never a set or a `UUID`, so the Owner's whole frame encodes as each cut does
        (§15.9, SEC-5; the producer's check is `oms_stream_wiring.checked_notice`)."""
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
        `1001`. Returns the number of connections offered the notice (§15.9 filters it per role)."""
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


class _WriterSlice:
    """#571: a writer's sends since it last gave the loop a turn. `sent()` after each send yields
    once `WRITER_SLICE_FRAMES` have gone by."""

    __slots__ = ("_sends",)

    def __init__(self) -> None:
        self._sends = 0

    def restart(self) -> None:
        """A new slice: the writer is about to wait for a frame, so the loop gets its turns."""
        self._sends = 0

    async def sent(self) -> None:
        self._sends += 1
        if self._sends >= WRITER_SLICE_FRAMES:
            await asyncio.sleep(0)
            self._sends = 0


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
        backpressure: BackpressureConfig | None = None,
        flag_visible: FlagVisible | None = None,
        tick_s: float = WATCHDOG_TICK_S,
        close_flush_s: float = CLOSE_FLUSH_TIMEOUT_S,
        loop_stall: Callable[[], float] | None = None,
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
        #: §8.5: from the first `auth_ok`, the `pong`s that `rate` does not count.
        self.pongs = PongBudget()
        #: #4924 (§8.5): the decode budget of the user, shared by its sockets, from the first
        #: `auth_ok` (`GatewayHub.decode_budget`); None before it, so a socket that has not
        #: authenticated draws on its own rate only.
        self.decode_budget: DecodeBudget | None = None
        #: #4924 (§8.5): the user's decode turn, shared by its sockets: a frame of weight above 1
        #: is handled only while its socket holds it, its whole handling (decode and dispatch),
        #: one such frame at a time across the user's sockets, each held to the loop turn after
        #: it (the reader's `sleep(0)`).
        self.decode_turn: asyncio.Lock | None = None
        #: Data frames stop at `OUTBOUND_QUEUE_MAX` (`push`); the `CLOSE_ITEMS` still fit (C-2.18).
        self.outbound: asyncio.Queue[Any] = asyncio.Queue(maxsize=OUTBOUND_QUEUE_MAX + CLOSE_ITEMS)
        self.user_id: uuid.UUID | None = None
        self.session_id: str | None = None
        #: The session an `auth` in flight registered with the `RevocationHub` (#2739): it becomes
        #: `session_id` when that auth is accepted and is dropped however else the auth ends.
        self.pending_session_id: str | None = None
        self.authz: ConnectionAuthz | None = None
        #: #415: the one registered with the permission registry for SR-189, kept apart from
        #: `authz`, so teardown always unregisters it.
        self.registered: ConnectionAuthz | None = None
        self.emitter: TopicEmitter | None = None
        self.system_seq = 0
        #: #4992 (§12.1): set once this socket's `system` snap is queued. Until then a `system`
        #: frame its principal may see is held here, not queued, so no `d` ever precedes the snap;
        #: the snap queues them after itself, re-cut under the principal then applied.
        self.system_snapped = False
        self.system_held: deque[dict[str, Any]] = deque(maxlen=SYSTEM_HELD_MAX)
        #: §15.9 (E42-T03): the flag keys a Manager or Viewer may learn; `None`, no key.
        self.flag_visible = flag_visible
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
        #: §9.6 (#3085): the view-as context the socket authenticated into, and its `expires_at`
        #: (epoch ms, wall clock): the socket closes `view_as_expired` then, with no REST call.
        self.view_as_context_id: str | None = None
        self.view_as_expires_at_ms: int | None = None
        #: #3100: the one close timer (`arm_close_timer`), from the first `auth_ok` until a close.
        self.close_timer: asyncio.Handle | None = None
        self.tick_s, self.recheck_s = tick_s, CLOSE_RECHECK_TICKS * tick_s
        self.timer_stopped = False
        #: Set by the handler: ends the writer as its own fault would, when a check that raised
        #: on the close timer left no close (`_close_timer_fired`); that check's is `timer_fault`.
        self.end_writer: Callable[[], object] = lambda: None
        self.timer_fault: BaseException | None = None
        #: #415: the flush timer (`arm_flush_deadline`), which ends a writer still running at its
        #: deadline, and whether it fired. With the flag on a close's flush is the pipeline's.
        self.close_flush_s = close_flush_s if backpressure is None else backpressure.close_flush_s
        self.flush_timer: asyncio.TimerHandle | None = None
        self.flush_passed = False
        self.opened_at = now
        #: E17-T03 (#412): the budgeted outbound path while `CV_WS_BACKPRESSURE_ENABLED` is on;
        #: None keeps `outbound` and its `OUTBOUND_QUEUE_MAX` push bound.
        self.pipeline: ConnectionPipeline | None = None
        if backpressure is not None:
            self.pipeline = ConnectionPipeline(
                encoding=encoding,
                config=backpressure,
                close=self.close_with,
                wall_ms=wall_ms,
                connection_id=self.connection_id,
                stalled=loop_stall or never_stalled,
            )

    def due(self) -> str | None:
        """The watchdog verdict now. Token expiry fires on whichever clock gets
        there first: the monotonic deadline set at `auth`, or the wall clock,
        which an NTP step or a resume moves on its own (#2259 review). A view-as context's
        `expires_at` fires on the wall clock, as the server's own reading of it does (§9.6)."""
        if self.token_expires_at_ms is not None and self.wall_ms() >= self.token_expires_at_ms:
            return "token_expired"
        expiry = self.view_as_expires_at_ms
        if expiry is not None and self.wall_ms() >= expiry:
            return "view_as_expired"
        return self.watchdog.due(self.clock())

    def watch(self) -> bool:
        """Apply the watchdog; True when an unsolicited `ping` is due. The writer runs it before
        every dequeue and every send, not only on an idle tick, so a socket fed faster than
        `tick_s` still expires (#2259 review); the close timer runs it at each deadline (#3100)."""
        due = self.due()
        if due in ("token_expired", "view_as_expired"):
            self.close_with(due, seal=True)  # also seals a close already under way
        elif due == "ping":
            return not self.closing
        elif due is not None:
            self.close_with(due)
        return False

    def close_in(self) -> float:
        """Seconds to the next close deadline: the token expiry on either clock, a view-as
        context's expiry and the heartbeat deadline. Each is compared as `due` compares it, so
        it is positive exactly while its close is not due. The timer runs only until a close,
        so it reads nothing else."""
        dog, now = self.watchdog, self.clock()
        terms = [dog.heartbeat_timeout_s - (now - dog.last_inbound)]
        if dog.token_expires_at is not None:
            terms.append(dog.token_expires_at - now)
        if self.token_expires_at_ms is not None:
            terms.append((self.token_expires_at_ms - self.wall_ms()) / 1000)
        if self.view_as_expires_at_ms is not None:
            terms.append((self.view_as_expires_at_ms - self.wall_ms()) / 1000)
        return min(terms)

    def arm_close_timer(self, floor_s: float = 0.0) -> None:
        """#3100: (re-)arm the connection's one close timer, cancelling the one it replaces. It
        runs `watch` at `close_in`, or `recheck_s` from now if that is sooner, never sooner than
        `floor_s`, so the token-expiry and heartbeat closes are queued at their deadline even
        while the writer is parked in a send. It waits on the loop's clock for what is left on
        `clock` (in production both read the monotonic clock); after `stop_close_timer`, none."""
        if self.close_timer is not None:
            self.close_timer.cancel()
            self.close_timer = None
        if not self.timer_stopped:
            delay = max(floor_s, min(self.close_in(), self.recheck_s))
            loop = asyncio.get_running_loop()
            self.close_timer = loop.call_later(delay, self._close_timer_fired)

    def _close_timer_fired(self) -> None:
        """The timer's turn: the writer's check, then the next arm while no close is under way.
        A check that raises fails closed (`internal_error`): the close first, then the log line,
        each guarded. If no close took (the fault came after `close_with` began: no `bye`, or
        with the flag on no flush deadline), the connection ends as on a writer fault: the writer
        is cancelled and the handler sends `bye internal_error` + `1011` itself. A cancellation
        raised here cancels no task, so it fails closed too, then is re-raised: the check's own,
        or one raised by the fail-closed close, which the `Exception` guard on that close does not
        take, so it is held until the fold and the log line are done (when both are raised, the
        check's own is re-raised and the close's is dropped). Any other `BaseException` passes
        through. After a check that found nothing due the rest is waited to the millisecond
        (`CLOSE_REARM_MIN_S`). The re-arm after a check that raised, a tick later, is defence in
        depth: the fail-closed close sets `closing` before anything in it can raise, so no flow
        reaches it today; were that to change, the timer would not spin."""
        self.close_timer = None
        failed = False
        cancelled: asyncio.CancelledError | None = None
        try:
            self.watch()
        except (Exception, asyncio.CancelledError) as exc:
            failed = True
            try:
                with contextlib.suppress(Exception):
                    self.close_with("internal_error")
            except asyncio.CancelledError as stopped:
                cancelled = stopped  # held for the fold and the log line below, then re-raised
            pipe = self.pipeline
            if self.bye_frame is None or (pipe is not None and pipe.deadline is None):
                self.bye_frame = None  # the close never took: the handler sends its own `bye`
                self.timer_fault = exc
                self.end_writer()
            with contextlib.suppress(Exception):
                _log().error(
                    "ws close timer failed",
                    connection_id=self.connection_id,
                    error=type(exc).__name__,
                    exc_info=exc,
                )
            if not isinstance(exc, Exception):
                raise
        if cancelled is not None:
            raise cancelled
        if not self.closing:
            self.arm_close_timer(self.tick_s if failed else CLOSE_REARM_MIN_S)

    def stop_close_timer(self) -> None:
        """Teardown (C-2.18, TG5): the close and flush timers are cancelled, none armed after."""
        self.timer_stopped = True
        self.arm_close_timer()
        self.stop_flush_deadline()

    def arm_flush_deadline(self, delay: float) -> None:
        """#415: end the writer `delay` s from now (loop clock) if it still runs then: flag off a
        close's `close_flush_s`, and from `accept` to the first `auth_ok` `auth_timeout_s` plus it.
        The earliest stands; none after teardown, after one fired, or with no loop (no writer)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        when = loop.time() + delay
        if self.timer_stopped or self.flush_passed:
            return
        if self.flush_timer is not None:
            if self.flush_timer.when() <= when:
                return
            self.flush_timer.cancel()
        self.flush_timer = loop.call_at(when, self._flush_deadline_passed)

    def stop_flush_deadline(self) -> None:
        """#415: at the first `auth_ok` (its accept-time bound ends) and at teardown."""
        if self.flush_timer is not None:
            self.flush_timer.cancel()
            self.flush_timer = None

    def _flush_deadline_passed(self) -> None:
        """#415: the socket closes `slow_consumer` unless a close is under way, and the writer ends
        even if that raises, so the handler tears the socket down. A writer still running had a peer
        that stopped reading: counted and logged as the flag-on path does (`abandon`)."""
        self.flush_timer, self.flush_passed = None, True
        try:
            if not self.closing:
                self.close_with("slow_consumer")
        finally:
            running = bool(self.end_writer())  # False: it had ended, its flush made it in time
        if not running:
            return
        reason = str(self.bye_frame["p"]["reason"]) if self.bye_frame is not None else None
        if self.pipeline is not None:  # counted once per connection, as its writer's expiry
            self.pipeline.abandon(reason)
        else:
            cv_ws_overflow_total.labels(reason=CLOSE_FLUSH_DEADLINE).inc()
            fields = {"connection_id": self.connection_id, "reason": reason}
            _log().warning("ws close deadline passed", **fields, flush_abandoned=True)

    # -- outbound -----------------------------------------------------------

    def push(self, frame: dict[str, Any], received: float | None = None) -> None:
        """Queue one frame; a full queue is a slow consumer (C-2.18 policy). A sampled data frame
        comes with `received`, the `clock` reading at which the hub took it, and is queued with it
        as `(received, frame)`: the writer observes `cv_ws_fanout_seconds` from that pair once the
        socket has the frame, and times and sizes its encode (`cv_ws_frame_*`) before the send. It
        never reaches the wire, and with the flag off a frame dropped from the queue (a seal, a
        full queue) is never observed. Any other frame is queued bare. With the flag on the
        pipeline queues it (`ws/pipeline.py`), the stamp on its `Queued`: it encodes the frame
        once, at push, and times and sizes a stamped one there, so the writer observes only the
        fan-out span, and a stamped frame that a close drops after its push is in
        `cv_ws_frame_*` but not in `cv_ws_fanout_seconds`."""
        if self.closing:
            return
        if self.pipeline is not None:
            self.pipeline.push(frame, received)
            return
        if self.outbound.qsize() >= OUTBOUND_QUEUE_MAX:
            self.close_with("slow_consumer")
            return
        self.outbound.put_nowait(frame if received is None else (received, frame))

    async def send(self, frame: dict[str, Any]) -> None:
        """Registry / `handle_sub` adapter; silent before the first `auth_ok` (SR-189)."""
        if self.lifecycle.authenticated:
            self.push(frame)

    def push_system(self, body: dict[str, Any], *, snap: bool = False) -> None:
        """Queue `body` on `system` as this socket's principal may see it now (SR-188, §15.9):
        whole, its role-neutral fields only, or nothing, and then it takes no `s` (S3). A frame
        left out because of what it is or who the socket is, not its role's cut, is counted by
        `withheld_reason` (`cv_ws_system_frames_withheld_total`; never its content).

        #4992 (§12.1): `snap` queues `body` as the socket's `system` snap, once (`s` 1), then the
        frames held for it as deltas. Until it is queued, a frame the principal may see is held,
        not queued, so no delta ever precedes the snap. A second snap is ignored; a snap the
        principal may see none of (no role) leaves the socket unsnapped, so a later `auth_ok`
        may send it."""
        view = self._system_view(body)
        if view is None:
            return
        if snap and self.system_snapped:
            return
        if not snap and not self.system_snapped:  # the snap goes first; this follows it
            self.system_held.append(body)
            return
        views = [("snap" if snap else "d", view)]
        if snap:
            self.system_snapped = True
            held = list(self.system_held)
            self.system_held.clear()
            views += [("d", cut) for item in held if (cut := self._system_view(item)) is not None]
        for kind, cut in views:
            self.system_seq += 1  # the snap's is 1: no delta took one before it
            self.push(
                {
                    "t": kind,
                    "ch": SYSTEM_TOPIC,
                    "s": self.system_seq,
                    "ts": self.wall_ms(),
                    "e": "j",
                }
                | {"p": cut}
            )

    def _system_view(self, body: dict[str, Any]) -> Mapping[str, Any] | None:
        """The principal's §15.9 view of `body` now, counting a frame withheld for what it is
        or who the socket is (`withheld_reason`), never for its role's cut."""
        principal = None if self.authz is None else self.authz.principal
        view = system_view(body, principal, flag_visible=self.flag_visible)
        if view is None and (reason := withheld_reason(body, principal)) is not None:
            cv_ws_system_frames_withheld_total.labels(reason=reason).inc()
        return view

    def encode_frame(self, frame: dict[str, Any]) -> str | bytes:
        """One frame in the negotiated encoding (§2.2, §3.2): MessagePack bytes on
        `cv.v1.msgpack`, else compact JSON text."""
        if self.msgpack:
            return encode_server_frame(frame)
        return json.dumps(frame, separators=(",", ":"))

    async def send_payload(self, payload: str | bytes) -> None:
        """Write an encoded frame: a binary WS frame for bytes, a text one for text."""
        if isinstance(payload, bytes):
            await self.ws.send_bytes(payload)
        else:
            await self.ws.send_text(payload)

    async def send_frame(self, frame: dict[str, Any]) -> None:
        """Write one frame in the negotiated encoding (§2.2, §3.2)."""
        await self.send_payload(self.encode_frame(frame))

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
        still be closed; every later push is dropped.

        With the flag on the `bye` takes the pipeline's terminal slot instead: a sealed or
        `slow_consumer` close clears both lanes, any other keeps only the priority lane ahead
        of the `bye` (`23-ws-protocol.md` §8.4)."""
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
        if self.pipeline is not None:
            self.sealed = seal
            self.bye_frame = frame
            flush = not (seal or bye_reason == "slow_consumer")
            dropped = self.pipeline.close(frame, code, flush=flush)
        else:
            dropped = self._seal() if seal else 0
            self.bye_frame = frame
            for item in (frame, _CLOSE, code):
                self.outbound.put_nowait(item)
            self.arm_flush_deadline(self.close_flush_s)  # #415: the flag on's bound, flag off
        # #571: at its audit row's severity, with step 3's trigger when step 3 closed it.
        pipe = self.pipeline
        step3 = {} if pipe is None or pipe.trigger is None else {"trigger": pipe.trigger}
        log = _log().warning if bye_reason in WARNING_CLOSES else _log().info
        log(
            "ws close",
            connection_id=self.connection_id,
            reason=reason,
            code=code,
            dropped=dropped,
            user_id=str(self.user_id) if self.user_id else None,
            session_id=self.session_id,
            **step3,
        )

    def log_ended(self, fault: BaseException | None, *, server_shutting_down: bool) -> None:
        """#571: `ws connection ended`, once per connection at its teardown, authenticated or
        not, whoever closed it: `warning` for `internal_error`, else `info`. The close code is
        the server's 1011 after a fault, else its `bye`'s, else the client's (None when the drop
        carried none); the class is the pipeline's last, none with the flag off or unattached."""
        reason = closed_reason(self, fault, server_shutting_down=server_shutting_down)
        if fault is not None:
            code: int | None = int(CLOSE_REASONS["internal_error"][0])
        elif self.bye_frame is not None:
            code = int(self.bye_frame["p"]["code"])
        else:
            code = self.disconnect_code
        ladder = None if self.pipeline is None else self.pipeline.ladder
        cls = {} if ladder is None else {"connection_class": str(ladder.pacer.cls)}
        log = _log().warning if reason == "internal_error" else _log().info
        log(
            "ws connection ended",
            connection_id=self.connection_id,
            initiator="client" if reason == "client_closed" else "server",
            close_code=code,
            reason=reason,
            duration_ms=round((self.clock() - self.opened_at) * 1000),
            authenticated=self.user_id is not None,
            **cls,
        )

    def _seal(self) -> int:
        """End the identity: drop every queued frame except a pending close
        (`bye`, the close sentinel, its code). Returns how many were dropped."""
        self.sealed = True
        if self.pipeline is not None:
            return self.pipeline.seal()
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

    def purge(self, subs: list[Subscription]) -> set[Key]:
        """`ConnectionAuthz.on_purge` (#415, §9.5): the queued frames of what a change revokes, a
        grant or a permission withdrawn alike, are dropped before `permission_change` is queued,
        whatever the flag. Every `d` and `snap` of `subs` goes, from both lanes with the flag on;
        every other item keeps its place. Counted per frame as
        `cv_ws_overflow_total{reason="withdrawn"}`. Returns the keys whose frames went."""
        keys = {(sub.ch, sub.replay_session_id) for sub in subs}
        gone: list[Key] = []
        if self.pipeline is not None:
            gone = self.pipeline.queue.purge(keys)
        else:  # the queue's own order, as `_seal` keeps it; a sampled frame is `(received, frame)`
            for item in [self.outbound.get_nowait() for _ in range(self.outbound.qsize())]:
                frame = item[1] if type(item) is tuple else item
                key = data_key(frame) if isinstance(frame, dict) else None
                if key is not None and key in keys:
                    gone.append(key)
                else:
                    self.outbound.put_nowait(item)
        if gone:
            cv_ws_overflow_total.labels(reason="withdrawn").inc(len(gone))
        return set(gone)

    async def evict(self) -> None:
        """Registry hook: sending a `permission_change` or `revoked` stalled or failed, or the
        swap or the settle around them raised, so the connection closes `slow_consumer` with
        nothing still queued ahead of its `bye` (#415, §9.5), whatever the flag: sealed with the
        flag off; with it on, the step 3 `bye`, which clears both lanes (`retry_after_ms` 3 000 and
        the generic message, `23-ws-protocol.md` §8.4). A close already under way stays the
        connection's one close (§8.6): it is sealed (with the flag on, the priority lane goes too),
        and counted and logged as no second close."""
        if self.closing and not self.sealed:
            dropped = self._seal()
            _log().info(
                "ws eviction sealed",
                connection_id=self.connection_id,
                dropped=dropped,
                user_id=str(self.user_id) if self.user_id else None,
                session_id=self.session_id,
            )
        elif self.pipeline is not None:
            self.close_with("slow_consumer", bye=slow_consumer_bye(self.wall_ms()))
        else:
            self.close_with("slow_consumer", seal=True)

    # -- inbound ------------------------------------------------------------

    def decode(self, msg: Mapping[str, Any], max_frame_bytes: int) -> Any:
        """One ASGI receive message -> decoded frame; `_OVERSIZE` after an oversize close,
        `_REFUSED` when the inbound rate refused it (`charge`), undecoded.

        Until the first `auth_ok` (which sets `user_id`), the frame before `hello` included, the
        size cap is the smaller `MAX_PREAUTH_FRAME_BYTES` (SR-040) and a MessagePack frame is
        decoded under the smaller value budget `MAX_PREAUTH_MSGPACK_VALUES` (SR-185). A JSON
        frame with more than `MAX_JSON_CONTAINERS` `[` and `{` characters, or more values than
        `MAX_MSGPACK_VALUES` by `json_values_over_count` (the one value bound of both encodings,
        #4924), is malformed, and is never decoded or depth-checked (SR-184).

        Size is checked on the raw payload BEFORE any decoding (1009). Each subprotocol has one
        frame kind (§2.2): a text frame on `cv.v1.msgpack` and a binary one on `cv.v1.json` are
        malformed. The payload is the `bytes` value unless that is `None`, else the text (or
        `""`), and its type is the kind (`bytes` binary, `str` text), empty or not: `b""` is a
        binary frame. The SR-185 decoder (`ws/codec.py`) decodes msgpack. For any frame a
        conforming ASGI server delivers (`bytes` under `bytes`, `str` under `text`), this does
        not raise: a refusal is `[]`, and a decoded `None` (`null`, nil) is no envelope, so
        `dispatch` counts a strike for either.

        From the first `auth_ok`, a `pong` over `MAX_PONG_BYTES` closes `protocol_violation` and
        the reader stops (§8.5): one whose first member is `t: "pong"` (`_leads_with_pong`) is
        never decoded, any other once decoded. A frame over the bound that opens with `t: "pong"`
        closes the same way even if the rest would not parse or repeats `t`: no `frame_malformed`
        strike.

        Every other frame is charged once, before any decode work (`charge`): from the first
        `auth_ok` one that opens with `t: "pong"` against the `pong` budget first, any other kind,
        `ping` included, against the inbound rate."""
        weighed = self.weigh(msg, max_frame_bytes)
        return weighed if weighed is _OVERSIZE else self.decode_weighed(weighed)

    def weigh(self, msg: Mapping[str, Any], max_frame_bytes: int) -> Any:
        """`decode`'s first half, before any decode work: the frame sized, checked against its
        caps and weighed (`_Weighed`), or `_OVERSIZE` after an oversize close. The reader holds
        the user's decode turn between the two halves when the weight is above 1 (#4924)."""
        binary = msg.get("bytes")
        raw: str | bytes = binary if binary is not None else (msg.get("text") or "")
        cap, values = max_frame_bytes, MAX_MSGPACK_VALUES
        if self.user_id is None:
            cap, values = min(cap, MAX_PREAUTH_FRAME_BYTES), MAX_PREAUTH_MSGPACK_VALUES
        # A binary payload (`bytes`, `bytearray`, `memoryview`) is sized by its length. A character
        # is at least one byte, so a text past `cap` in characters is over it and is not encoded.
        size = len(raw)
        if isinstance(raw, str) and size <= cap:
            size = len(raw.encode())
        if size > cap:
            self.close_with("frame_too_big")
            return _OVERSIZE
        authed = self.user_id is not None
        pong = authed and _leads_with_pong(raw, msgpack=self.msgpack)
        pong_bound = authed and size > MAX_PONG_BYTES
        if pong_bound and pong:
            self.close_with("protocol_violation")
            return _OVERSIZE
        # #4924: a frame's values, bounded above before decode, and only up to one past the value
        # bound (`_parse` refuses the rest): a JSON frame's over-counted on its text, once, here;
        # a MessagePack frame's by twice its size (a container is charged twice, a value takes a
        # byte), and its containers by its size, up to one past the container cap.
        counted = json_values_over_count(raw) if isinstance(raw, str) and not self.msgpack else 0
        bound = min(2 * size if self.msgpack else counted, MAX_MSGPACK_VALUES + 1)
        boxes = min(size, MAX_JSON_CONTAINERS + 1) if self.msgpack else 0
        weight = inbound_frame_weight(size, bound, boxes)
        return _Weighed(raw, values, counted, bound, boxes, weight, pong, pong_bound)

    def decode_weighed(self, w: _Weighed) -> Any:
        """`decode`'s second half: charge the frame (`charge`), then decode it."""
        raw, values, counted, bound, weight = w.raw, w.values, w.counted, w.bound, w.weight
        shared = weight > 1  # the tokens past the first also draw on the user's decode budget
        charged_as = self.charge(pong=w.pong, weight=weight, shared=shared)
        if charged_as is None:
            return _REFUSED
        decoded: list[int] = []
        frame = self._parse(raw, values, counted, decoded)
        pong_bound = w.pong_bound
        if pong_bound and isinstance(frame, dict) and frame.get("t") == "pong":
            self.close_with("protocol_violation")  # its `t` comes later, or is written otherwise
            return _OVERSIZE
        if charged_as == "pong" and not (isinstance(frame, dict) and frame.get("t") == "pong"):
            # It opened with `t: "pong"` and is another kind: the rate counts it as any frame.
            if self.charge(pong=False, weight=weight, shared=shared) is None:
                return _REFUSED
        if decoded:  # MessagePack: its counts now known, what its size took past them comes back
            held, boxes = decoded
            refund = bound // INBOUND_WEIGHT_VALUES - held // INBOUND_WEIGHT_VALUES
            refund += w.boxes // INBOUND_WEIGHT_CONTAINERS - boxes // INBOUND_WEIGHT_CONTAINERS
            if refund > 0:
                self.rate.refund(refund)
                if self.decode_budget is not None:
                    self.decode_budget.refund(refund)
        return frame

    def charge(self, *, pong: bool, weight: int, shared: bool = False) -> str | None:
        """Charge one inbound frame before it is decoded (§8.5): `"pong"` when the `pong` budget
        took it, `"rate"` when the inbound rate did, None when it is refused. From the first
        `auth_ok`, a `shared` frame also needs its `weight - 1` tokens from the user's decode
        budget (#4924): checked first, taken only once the rate has admitted it, with no await
        between, so a refusal takes nothing from either.

        A `pong` (`decode` has read its leading `t` from the first `auth_ok`) takes from its own
        budget first; past it, and for every other frame, the inbound rate takes `weight` tokens,
        the frame's size weight (`inbound_frame_weight`, #4924). A refusal
        is the rate's strike: the first an `err` `client_rate_limited` with no `id` (the frame is
        never read), the next the `4429` close, which the close's metric and audit row record."""
        now = self.clock()
        if pong and self.pongs.allow(now):
            return "pong"
        budget = self.decode_budget if shared else None
        if budget is not None and not budget.can(now, weight - 1):
            cv_ws_decode_budget_refused_total.inc()
        elif self.rate.allow(now, weight):
            if budget is not None:
                budget.take(weight - 1)
            return "rate"
        self.rate_strikes += 1
        if self.rate_strikes > 1:
            self.close_with("client_rate_limited", retry_after_ms=1000)
        else:
            self.push(build_ws_error("client_rate_limited", id=None))
        return None

    def _parse(self, raw: str | bytes, values: int, counted: int, decoded: list[int]) -> Any:
        """`decode`'s parse of a frame within its size caps: the decoded value, `[]` if refused.
        `counted` is a JSON frame's value over-count (`json_values_over_count`); a MessagePack
        decode appends the values it charged to `decoded`."""
        try:
            if self.msgpack:
                if isinstance(raw, str):
                    return []
                return decode_client_frame(raw, max_values=values, charged=decoded)
            if isinstance(raw, bytes):
                return []  # a binary frame on cv.v1.json: a violation, never decoded
            openers = raw.count("[") + raw.count("{")  # not string-aware: it can only over-count
            if openers > MAX_JSON_CONTAINERS:
                return []  # SR-184: too many containers -> protocol violation, never decoded
            if counted > MAX_MSGPACK_VALUES:
                return []  # #4924: past the SR-185 value bound, as on msgpack -> never decoded
            value = json.loads(raw)  # the C decoder; its nesting is bounded by the cap above
            if openers > MAX_JSON_DEPTH and json_nests_deeper(value, MAX_JSON_DEPTH):
                return []  # SR-184: too deep -> protocol violation (fewer openers cannot nest so)
            return value
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


#: §8.5: a JSON text frame whose first member is `"t": "pong"`, JSON whitespace around its tokens.
_JSON_PONG: Final = re.compile(r'[ \t\n\r]*\{[ \t\n\r]*"t"[ \t\n\r]*:[ \t\n\r]*"pong"')
#: The same first member in MessagePack, after a fixmap header of 1 to 15 entries.
_MSGPACK_PONG: Final = b"\xa1t\xa4pong"


def _leads_with_pong(raw: str | bytes, *, msgpack: bool) -> bool:
    """True when `raw`, a frame of its subprotocol's kind (§2.2), opens with the member `t: "pong"`:
    in JSON text within its first `MAX_PONG_BYTES` characters, in MessagePack as a fixmap's first
    fixstr key and value. An envelope has one `t` (§3.1), so a conforming frame it matches is a
    `pong`. From `auth_ok`, a frame over the bound that it matches closes `protocol_violation`
    even if the rest would not parse or repeats `t`, rather than counting a `frame_malformed`
    strike. Anything else is False and is decoded as usual."""
    if msgpack:
        return (
            isinstance(raw, bytes | bytearray)
            and b"\x81" <= raw[:1] <= b"\x8f"
            and raw.startswith(_MSGPACK_PONG, 1)
        )
    return isinstance(raw, str) and _JSON_PONG.match(raw, 0, MAX_PONG_BYTES) is not None


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


def _fault_flush(conn: _Connection) -> contextlib.AbstractAsyncContextManager[object]:
    """The bound on a fault's `bye` and 1011: the close flush deadline with the flag on (a peer
    that stopped reading would park them, `_bounded_flush`), none with it off, as before."""
    if conn.pipeline is None:
        return contextlib.nullcontext()
    return _bounded_flush(conn.pipeline)


@contextlib.asynccontextmanager
async def _bounded_flush(pipe: ConnectionPipeline) -> AsyncIterator[asyncio.Timeout]:
    """With a close under way, what is left of its deadline (one deadline, never a second window:
    `23-ws-protocol.md` §8.4); else a fresh `close_flush_s`. Past it the flush is abandoned with
    no `bye` and logged as the writer's is, and counted unless the writer's expiry already was
    (`ConnectionPipeline.abandon` counts once per connection)."""
    deadline = pipe.deadline
    scope = (
        asyncio.timeout(pipe.config.close_flush_s)
        if deadline is None
        else asyncio.timeout_at(deadline)
    )
    try:
        async with scope:
            yield scope
    except TimeoutError:
        if not scope.expired():
            raise
        pipe.abandon("internal_error")


def _reply(t: str, frame_id: Any, **fields: Any) -> dict[str, Any]:
    """Envelope with `id` echoed only when the request carried a string id (§13.1)."""
    out: dict[str, Any] = {"t": t}
    if isinstance(frame_id, str):
        out["id"] = frame_id
    return out | fields


def include_ws_router(app: FastAPI, router: APIRouter) -> None:
    """#3907: serve the gateway's route at `WS_PATH` and under `WS_SERVER_BASE`.

    One router, one endpoint and one hub: the second include copies the route under the prefix,
    so both paths run the same handler with the same guards, limits and audit. FastAPI replays a
    router's startup and shutdown hooks once per include, so this router may carry none
    (`make_ws_router` adds none): a hook would run twice."""
    if router.on_startup or router.on_shutdown:
        raise ValueError(
            "the WS router may carry no startup or shutdown hook: each include replays it"
        )
    app.include_router(router)
    app.include_router(router, prefix=WS_SERVER_BASE)


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
    # §2.5 refusal audit (#2269): `create_app` binds it to the app's shared refusal-audit
    # tracker. Without it a refused upgrade is still refused and counted, not audited.
    origin_audit: OriginRefusalAudit | None = None,
    auth_timeout_s: float = AUTH_TIMEOUT_S,
    auth_call_timeout_s: float = AUTH_CALL_TIMEOUT_S,
    max_frame_bytes: int = MAX_INBOUND_FRAME_BYTES,
    clock: Clock = time.monotonic,
    wall_ms: WallClockMs = _wall_ms,
    tick_s: float = WATCHDOG_TICK_S,
    server_version: str = "0.0.0",
    git_sha: str = "unknown",
    kill_switch: Callable[[], dict[str, Any]] | None = None,
    system_notices: Callable[[], list[dict[str, Any]]] | None = None,
    # §15.9 (E42-T03): which flag keys a Manager or Viewer may learn, built by the composition
    # root from the flag registry. Without it a flag reaches the Owner alone (fail closed).
    flag_visible: FlagVisible | None = None,
    # §15.9 (#4517): the full flag set a principal's roles may see, as one `feature_flags` frame
    # (`None`: nothing), sent right after `auth_ok`. Without it no snapshot is sent.
    flag_snapshot: FlagSnapshot | None = None,
    # §12.1 (#4992): the latest `health` frame (`HealthSystemPublisher.latest`), `None` before the
    # first, for the `system` snap at `auth_ok`. Without it the snap carries no health fields.
    system_baseline: SystemBaseline | None = None,
    backpressure: BackpressureConfig | None = None,
    close_flush_s: float = CLOSE_FLUSH_TIMEOUT_S,
    # §9.6 (#3085): the view-as binding an `auth` reads (`ViewAsRead`). Without it no session is
    # bound to a context, as before view-as: the composition root wires it on the real backend.
    view_as: ViewAsRead | None = None,
    # §9.6: the record of a viewing session's refused action frame. Without it the frame is still
    # refused (`err`), with no record.
    view_as_refusals: ViewAsFrameRefusals | None = None,
    # #4833: the server loop's stall to date (`LoopStall`), which the flag-on RTT probe leaves
    # out. Without it a stall of the loop counts as the client's RTT, as before #4833.
    loop_stall: Callable[[], float] | None = None,
) -> APIRouter:
    """The gateway endpoint, served at `/ws` and `/api/v1/ws` (`include_ws_router`).

    `clock` (monotonic seconds) drives every deadline but one, so tests
    inject a fake clock; `tick_s` is only the poll cadence. The exception is the close flush
    deadline with the flag on, which runs on the event loop's clock: only an `asyncio.Timeout`
    can cancel a send that a peer which stopped reading has parked (`ws/pipeline.py`). So does
    each `auth` call's bound, `auth_call_timeout_s` (#2155), for a call that never returns. The
    close timer (#3100) is a loop timer too, armed for what is left of a deadline on `clock` and
    every `CLOSE_RECHECK_TICKS` ticks at most, so a fake `clock` still drives it.

    `backpressure` (E17-T03, #412) selects the budgeted outbound pipeline (`ws/pipeline.py`,
    `23-ws-protocol.md` §8.4): its budget binds both lanes, and a close flushes under its
    deadline. `None`, today's path, keeps the `OUTBOUND_QUEUE_MAX` push bound. A config also
    makes the `welcome` advertise `features.coalescing` (§4.2); the default is on since #4883
    (the owner ruling of 2026-10-29 on E17-Q03, #568; chaos scenarios 2 and 3 pass, #410). Without
    a config the `welcome` says `coalescing: false`.

    #415: flag off, a close flushes within `close_flush_s` (loop clock), then a writer parked on a
    send ends; until the first `auth_ok`, `auth_timeout_s` plus that bound from `accept` ends one,
    flag on or off."""
    router = APIRouter()
    gateway_hub = hub if hub is not None else GatewayHub()
    killed = kill_switch or (lambda: {"engaged": False, "scope": "global"})
    refusal_log = RefusalLogLimiter()
    features = welcome_features(coalescing=backpressure is not None)

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
        """`warning` audit entry for the 3rd failed `auth` (§4.3), with the source address so that
        failures aggregate per source as well as per identity (SR-187). Never carries the token.
        Best effort, bounded at `CLOSE_AUDIT_TIMEOUT_S`: the close is not held hostage, and a row
        not confirmed is logged and counted, a cancelled one counted (SR-E17-04)."""
        if audit is None:
            return
        try:
            async with asyncio.timeout(CLOSE_AUDIT_TIMEOUT_S):
                await audit.emit(
                    "auth.login_failed",
                    actor_label="ws",
                    actor_user_id=conn.user_id,
                    actor_ip=_source_ip(conn.ws.scope),
                    object_kind="ws_connection",
                    object_id=conn.connection_id,
                    outcome=AuditOutcome.FAILURE,
                    severity=Severity.WARNING,
                    reason="ws_auth_failed",
                    request_id=current_request_id(),
                )
        except asyncio.CancelledError:
            count_audit_failure()
            raise
        except Exception:
            count_audit_failure()
            _log().warning(
                "ws auth-failure audit not confirmed",
                connection_id=conn.connection_id,
                exc_info=True,
            )

    async def audit_close(conn: _Connection, fault: BaseException | None) -> None:
        """`ws.connection.closed` for a socket that authenticated (E17-S01, #2486): `warning`
        for `WARNING_CLOSES`, `info` otherwise. An unauthenticated close is not audited, so a
        peer without a session cannot flood the log (its 3rd failed `auth` already is). Never
        the token. Best effort (threat model WS-R04): the teardown waits at most
        `CLOSE_AUDIT_TIMEOUT_S` for the sink, and a failure in here, working out the reason
        included, is logged and never raised. One loss it cannot avoid: a cancellation of the
        handler that lands inside the emit (the host's graceful-timeout cancel, or a second one
        such as the loop's own teardown) is honoured and abandons a write that has not started;
        `AuditWriter.emit` finishes one that has. Every row not confirmed, a cancelled one too,
        counts in `cv_ws_audit_failures_total` (SR-E17-04)."""
        if audit is None or conn.user_id is None:
            return
        try:
            reason = closed_reason(conn, fault, server_shutting_down=gateway_hub.shutting_down)
            # Flag on: the step 3 trigger and an expired flush (§4.3), when there is either.
            state = conn.pipeline.audit_state() if conn.pipeline is not None else None
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
                    **({} if state is None else {"after_state": state}),
                )
        except Exception:
            count_audit_failure()  # SR-E17-04: `timeout` or `error`, before a logger can fail
            # Not "not written": a write that timed out may still land (the writer shields it).
            _log().warning(
                "ws close audit not confirmed", connection_id=conn.connection_id, exc_info=True
            )
        except asyncio.CancelledError:
            count_audit_failure()  # the loss above, counted; the cancellation still propagates
            raise

    def refuse_connect(conn: _Connection, user_id: uuid.UUID, retry_after_ms: int) -> None:
        """§4.3 (#2558): the user's connect budget is spent. `bye client_rate_limited` + `4429`
        instead of `auth_ok`, so the socket never authenticates: `conn.user_id` and the session
        stay unset, no revocation hook is registered and `audit_close` writes no row, which is
        the point of the limit. The permission registration this `auth` made for the SR-189
        re-check is undone by the handler's teardown, as for any closing socket. Every refusal
        is counted in `cv_ws_connect_rate_limited_total` (and, as a close, in
        `cv_ws_closes_total`). The user-attributed warning is capped: it is logged for a user's
        first refusal in a window and names the user and the peer address, never the token. Every
        close still writes the generic `ws close` line, which names no user."""
        cv_ws_connect_rate_limited_total.inc()
        if gateway_hub.connect_rate.first_refusal(user_id, conn.clock()):
            _log().warning(
                "ws connect rate limited",
                connection_id=conn.connection_id,
                user_id=str(user_id),
                source_ip=_source_ip(conn.ws.scope),
                limit=gateway_hub.connect_rate.limit,
                retry_after_ms=retry_after_ms,
            )
        bye = lifecycle_bye(
            "client_rate_limited",
            now_ms=conn.wall_ms(),
            retry_after_ms=retry_after_ms,
            message=CONNECT_RATE_MESSAGE,
        )
        conn.close_with("client_rate_limited", bye=bye)

    async def refuse_disabled(conn: _Connection, user_id: uuid.UUID) -> None:
        """#3413 (SR-029, UL1-E2): the user was disabled at or after this socket's access token
        was issued, and the socket registered after the per-user close, which therefore missed
        it. It is closed as the hub closes the `auth` of a revoked session (#2739): `bye
        user_disabled` and 4403, sealed, never `auth_ok`. Counted in
        `cv_ws_revoked_total{reason="user_disabled"}`; the warning names the user, never the
        token."""
        ws_revoked_total.labels(reason="user_disabled").inc()
        await conn.closer(user_disabled_bye(conn.wall_ms()), CLOSE_USER_DISABLED)
        _log().warning(
            "ws auth refused",
            connection_id=conn.connection_id,
            reason="user_disabled",
            user_id=str(user_id),
            source_ip=_source_ip(conn.ws.scope),
        )

    def auth_call_late(conn: _Connection, call: str, *, reauth: bool, fresh: bool) -> None:
        """#2155 (§4.3): an `auth` call outlived `auth_call_timeout_s`. A server fault, not a failed
        `auth` (no strike, no audit row): `bye internal_error` + `1011`, a re-auth's too. The SR-189
        registration a `fresh` one made goes here (#415: only the one this `auth` made), its
        `RevocationHub` one in `do_auth`, as a failure's do."""
        if fresh and conn.authz is not None:
            registry.unregister(conn.authz)
            conn.authz = conn.registered = None
        _log().warning(
            "ws auth call timed out",
            connection_id=conn.connection_id,
            call=call,
            reauth=reauth,
            timeout_s=auth_call_timeout_s,
        )
        conn.close_with("internal_error")

    async def shed(conn: _Connection) -> None:
        """#2155 (§4.3): `max_unauthenticated` sockets await auth, so this one is closed at once:
        `bye server_shedding_load` (retry after the auth window) and `1013`, within the close flush
        deadline; no frame read, task or slot. Always counted; its warning is capped as §2.5's."""
        retry_after_ms = int(auth_timeout_s * 1000)
        cv_ws_closes_total.labels(reason=SHED_REASON).inc()
        if (verdict := refusal_log.admit(SHED_REASON, clock())) is RefusalLog.LINE:
            _log().warning(
                "ws socket shed",
                reason=SHED_REASON,
                limit=gateway_hub.max_unauthenticated,
                retry_after_ms=retry_after_ms,
                source_ip=_source_ip(conn.ws.scope),
            )
        elif verdict is RefusalLog.SUMMARY:
            _log().warning(
                "ws socket sheds suppressed", reason=SHED_REASON, limit=REFUSAL_LOG_LIMIT
            )
        bye = lifecycle_bye(SHED_REASON, now_ms=conn.wall_ms(), retry_after_ms=retry_after_ms)
        with contextlib.suppress(Exception):  # gone or not reading: the refusal stands regardless
            async with asyncio.timeout(CLOSE_FLUSH_TIMEOUT_S):
                await conn.send_frame(bye)
                await conn.ws.close(code=int(bye["p"]["code"]))

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

    async def read_view_as(session_id: str) -> ViewAsBinding | None:
        """§9.6: the session's view-as binding, under the `auth` call bound. A read in flight
        across an end's commit can return the context that end just closed: the socket binds
        to it, and its next re-`auth`, at most one access-token lifetime later, or its own
        expiry closes it, as after a close that failed (the backstop)."""
        if view_as is None:
            return None
        async with _auth_call("view_as", auth_call_timeout_s):
            return await view_as(session_id)

    def view_as_refusal(read: ViewAsBinding | None, socket_context: str | None) -> str | None:
        """§9.6: why an `auth` that read `read` is refused, or `None`. A held context refuses
        with `view_as_expired`; a context other than the socket's (none, or another one: a
        re-`auth`, or a start or an end during this `auth`) with `view_as_changed`, so `None`
        never widens a viewing socket to the viewer's scope (S4-SEC-08). A refresh keeps the
        context, so its re-`auth` keeps the socket."""
        if read is not None and read.phase is ViewAsPhase.HELD:
            return "view_as_expired"
        if _context_of(read) != socket_context:
            return "view_as_changed"
        return None

    async def refuse_action_frame(conn: _Connection, kind: str, fid: Any) -> None:
        """§9.6: a viewing session's action frame changes nothing: one refusal record within the
        viewer's budget, bounded, then `err` `view_as_read_only` with the frame's `id`, whatever
        the record did (one that fails is counted). No strike: the socket stays open."""
        authz, session_id = conn.authz, conn.session_id
        if view_as_refusals is not None and authz is not None and session_id is not None:
            try:
                async with asyncio.timeout(CLOSE_AUDIT_TIMEOUT_S):
                    await view_as_refusals.refuse_frame(
                        viewer_user_id=authz.actor_user_id,
                        viewer_session_id=session_id,
                        frame_type=kind,
                        ip=_source_ip(conn.ws.scope),
                        request_id=authz.request_id,  # the socket's upgrade (#3990)
                    )
            except Exception:
                count_audit_failure()  # SR-E17-04: the `err` is sent anyway (§9.6)
        conn.push(build_ws_error("view_as_read_only", id=_str_or_none(fid)))

    async def run_auth(conn: _Connection, frame: dict[str, Any]) -> None:
        body = frame.get("p")
        token = body.get("access_token") if isinstance(body, dict) else None
        reauth = conn.lifecycle.authenticated
        fresh = conn.authz is None  # #415: only the `auth` that registers undoes the registration
        if reauth:
            conn.lifecycle.fire(ConnEvent.REAUTH)
        failure = "rejected"
        try:
            if not isinstance(token, str) or not token:
                failure = "missing_token"
                raise ValueError("missing access_token")
            async with _auth_call("authenticate", auth_call_timeout_s):
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
            bound = await read_view_as(session_id)  # authenticated: never a revoked session's
            before = conn.view_as_context_id if reauth else _context_of(bound)
            if (refusal := view_as_refusal(bound, before)) is not None:
                raise AuthRefused(refusal, ids={"session_id": session_id})
            # §9.6: a live context's socket is served in its target's scope, the viewer acting
            subject = user_id if bound is None else bound.target_user_id
            async with _auth_call("resolve", auth_call_timeout_s):
                snap = await registry.resolve(subject)  # versioned: never undoes a newer one
            if bound is not None and snap.principal.is_owner:  # §9.6: a target is never an Owner
                raise AuthRefused("view_as_expired", ids={"session_id": session_id})
            now, now_ms = conn.clock(), conn.wall_ms()
            if expires_ms <= now_ms:
                failure = "token_expired"  # never `auth_ok` an identity that is already dead
                raise PermissionError("access token already expired")
            if conn.closing:  # #415: closed while this auth was in flight: nothing to register
                return
            if conn.authz is None:  # SR-189: register, then re-check, under the auth deadline
                if snap.principal.user_id != subject:  # #415: built from the subject only
                    raise SnapshotUserMismatch("a permission snapshot of another user")
                conn.authz = ConnectionAuthz(
                    snap.principal,
                    registry.services,
                    connection_id=conn.connection_id,
                    version=snap.version,
                    clock=conn.clock,  # SR-193: the rebuild budget's window
                    viewer_user_id=None if bound is None else user_id,  # §9.6: who acts
                    request_id=current_request_uuid(),  # the upgrade's: the socket's own
                )
                registry.register(conn.authz, conn.send, conn.evict, conn.closer)
                conn.registered = conn.authz
                async with _auth_call("recheck", auth_call_timeout_s):
                    await registry.recheck(conn.authz)
                if conn.closing:  # §9.6: the re-read found the target an Owner and ended the view
                    return
                revoked: list[dict[str, Any]] = []
            else:
                # Subscriptions + sequences are kept; only ones the refreshed
                # principal no longer allows are revoked (§9.5, same RBAC source).
                frames = await registry.apply(conn.authz, snap, now_ms, event="reauth")
                revoked = [f for f in frames if f["t"] == "revoked"]
            if view_as is not None:  # §9.6: a start or an end during this `auth`, as SR-189 does
                bound = await read_view_as(session_id)
                if (refusal := view_as_refusal(bound, before)) is not None:
                    raise AuthRefused(refusal, ids={"session_id": session_id})
        except AuthenticatorContractError:
            raise  # a server fault, not a failed auth: the handler closes 1011
        except AuthCallTimeout as late:
            auth_call_late(conn, str(late), reauth=reauth, fresh=fresh)
            return
        except AuthRefused as refused:
            # §4.3: refused at once, never `auth_ok`, not counted as a failure, nothing left
            # registered; a re-auth ends the earlier identity too (#2295).
            if fresh and conn.authz is not None:  # §9.6's re-read refuses after registering
                registry.unregister(conn.authz)
                conn.authz = conn.registered = None
            source_ip = _source_ip(conn.ws.scope)
            if refused.reason == "user_disabled":  # SR-029, counted as `refuse_disabled` counts
                ws_revoked_total.labels(reason="user_disabled").inc()
            _log().warning(
                "ws auth refused",
                connection_id=conn.connection_id,
                reason=refused.reason,
                reauth=reauth,
                source_ip=source_ip,
                **{k: v for k, v in refused.ids.items() if k in ("session_id", "user_id")},
            )
            # Sealed first: no frame of the earlier identity waits on the audit write (§4.3).
            conn.close_with(refused.reason, seal=True)
            if refused.audit is not None:
                await refused.audit(source_ip)
            return
        except Exception as exc:
            if isinstance(exc, SnapshotUserMismatch):  # #415: a snapshot of another user, from
                failure = "user_mismatch"  # any check, is refused as another user's token is
            if fresh and conn.authz is not None:  # the SR-189 re-check failed: undo
                registry.unregister(conn.authz)
                conn.authz = conn.registered = None
            # C-2.9: count the failure and audit the 3rd one even when the socket
            # began closing while this auth was in flight.
            cv_ws_auth_failures_total.labels(reason=failure).inc()
            conn.auth_failures += 1
            # A closed `reason` and counts only: the exception text can carry client input.
            _log().warning(
                "ws auth failed",
                connection_id=conn.connection_id,
                reason=failure,
                attempt=conn.auth_failures,
                reauth=reauth,
                source_ip=_source_ip(conn.ws.scope),
            )
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
        if registry.issued_before_disable(user_id, expires_ms):
            # #3413: the per-user close ran before this socket registered, on a session the
            # hub was never told about (a refresh had rotated it). The registry remembers.
            await refuse_disabled(conn, user_id)
            return
        if not reauth:
            # Only a new socket's first SUCCESSFUL auth is counted (failures have their own 3
            # strikes, a re-auth is a token refresh), and only here. `admit_connect` checks and
            # records in one synchronous step, so concurrent sockets of one user cannot overshoot
            # the limit. Nothing awaits between it and `auth_ok`, so no other task can close or
            # cancel a counted socket before it is answered. It precedes `enforce_cap`, so a
            # refused socket never evicts a live one. The clock is read here, after the awaits
            # above: `now` predates them and would age the stamp.
            retry_after_ms = gateway_hub.admit_connect(user_id, conn.clock())
            if retry_after_ms is not None:
                refuse_connect(conn, user_id, retry_after_ms)
                return
        conn.auth_failures = 0
        conn.watchdog.auth_deadline = None
        conn.watchdog.token_expires_at = now + (expires_ms - now_ms) / 1000
        conn.token_expires_at_ms = expires_ms  # the same instant on the wall clock
        conn.view_as_context_id = _context_of(bound)
        conn.view_as_expires_at_ms = (  # floored, as the token's expiry is
            None if bound is None else (bound.expires_at - _EPOCH) // _ONE_MS
        )
        conn.arm_close_timer()  # #3100: at the new expiry, a re-auth's too
        conn.stop_flush_deadline()  # #415: the bound from `accept` ends at the first `auth_ok`
        if conn.session_id != session_id:  # the old registration goes only after the check
            if conn.session_id is not None:
                revocation_hub.unregister(conn.session_id, conn.closer)
            conn.pending_session_id = None  # registered above, and now the socket's own
        conn.session_id, conn.user_id = session_id, user_id
        conn.decode_budget = gateway_hub.decode_budget(user_id, conn.clock())  # #4924: shared
        conn.decode_turn = gateway_hub.decode_turn(user_id)
        conn.authz.session_id = session_id  # E17-R-16: its audit rows name the session
        # §9.6: a context's end closes the sockets bound to it, and only those (`close_context`).
        revocation_hub.bind(session_id, conn.closer, conn.view_as_context_id)
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
                span_id=svc.span_ids,
            )
            if svc.sequencing is not None:  # flag on: the pipeline paces the deltas (§8.1)
                sink = conn.emitter if conn.pipeline is None else conn.pipeline
                svc.sequencing.register(conn.authz, sink)
            if conn.pipeline is not None:  # E17-T03: the §8.4 ladder, from the first auth_ok
                conn.pipeline.attach(conn.authz, conn.emitter, conn.push_system)
            # #415 (§9.5), whatever the flag: a change's purge, and the snapshots that follow it
            conn.authz.on_purge = conn.purge
            conn.authz.on_settle = lambda subs: settle(conn, subs)
        conn.lifecycle.fire(ConnEvent.AUTH_OK)
        principal = conn.authz.principal  # the applied snapshot: the newest, never the stale read
        state = killed()  # one read: `auth_ok` and the `system` snap give the same state (#4992)
        view = kill_switch_view(state, principal)  # SR-188: as the `system` topic gives it
        payload = auth_ok_payload(
            principal,
            user_id=str(user_id),  # §9.6: the session's own user, the target's scope
            session_id=session_id,
            token_expires_at_ms=expires_ms,
            git_sha=git_sha,  # §4.3 (E09-X02 F-8): the exact build, after authentication only
            **({} if view is None else {"kill_switch": view}),  # none for a principal with no role
        )
        conn.push(_reply("auth_ok", frame.get("id"), ts=now_ms, p=payload))
        if not conn.system_snapped:  # §12.1 (#4992): the socket's first `auth_ok` it may see
            body = await system_snap_body(conn, state, principal.user_id, principal.roles)
            conn.push_system(body, snap=True)
        elif flag_snapshot is not None:  # an in-place re-auth: the flag set under its roles
            await push_flag_snapshot(conn, flag_snapshot, principal.user_id, principal.roles)
        # E27-T02: current degraded/read-only state, so a client connecting after the
        # transition still gets the blocking notice (§6 `system`, CMP-092). First auth only:
        # an in-place re-auth (token refresh) keeps the socket's existing state.
        if not reauth:
            for body in system_notices() if system_notices is not None else ():
                conn.push_system(body)
        for f in revoked:
            conn.push(f)
        await registry.settle(conn.authz, conn.evict)  # §9.5: a narrowing's snaps follow
        if revoked:  # E17-R-13 (WS-R02): their rows, once the frames are queued, as a change's
            await registry.audit_revoked(conn.authz, revoked)
        structlog.contextvars.bind_contextvars(user_id=str(user_id), session_id=session_id)
        _log().info(
            "ws authenticated",
            connection_id=conn.connection_id,
            subprotocol=conn.encoding,
            reauth=reauth,
        )
        if not reauth:
            cv_ws_handshake_seconds.observe(max(0.0, conn.clock() - conn.opened_at))
            gateway_hub.mark_authenticated(conn)
            gateway_hub.enforce_cap(conn)

    async def system_snap_body(
        conn: _Connection,
        state: Mapping[str, Any],
        user_id: uuid.UUID,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        """§12.1 (#4992): the body of the socket's `system` snap, `kind` `health`: the latest health
        frame's fields, the kill-switch `state` that `auth_ok` gave, and the flag set the roles may
        see (§15.9: the topic snapshot carries the full set). A failed read costs its fields, never
        the snap or the `auth`; with no health frame yet the snap carries none (unknown).
        `push_system` cuts it per role, as every `system` frame."""
        body: dict[str, Any] = {"kind": "health"}
        if flag_snapshot is not None:  # first: the health read then follows with no await
            flags = await read_flag_snapshot(conn, flag_snapshot, user_id, roles)
            if flags is not None and isinstance(flags.get("feature_flags"), Mapping):
                body["feature_flags"] = flags["feature_flags"]
        body["kill_switch"] = state
        if system_baseline is not None:
            try:
                health = system_baseline()
            except Exception:
                _log().exception("ws system baseline failed", connection_id=conn.connection_id)
                health = None
            if health is not None:
                body |= {key: health[key] for key in SNAP_HEALTH_FIELDS if key in health}
        return body

    async def read_flag_snapshot(
        conn: _Connection,
        snapshot: FlagSnapshot,
        user_id: uuid.UUID,
        roles: frozenset[str],
    ) -> dict[str, Any] | None:
        """The principal's flag snapshot; `None` for none, or for a failed read (logged)."""
        try:
            async with _auth_call("flag_snapshot", auth_call_timeout_s):
                return await snapshot(user_id, roles)
        except Exception:
            _log().exception("ws flag snapshot failed", connection_id=conn.connection_id)
            return None

    async def push_flag_snapshot(
        conn: _Connection,
        snapshot: FlagSnapshot,
        user_id: uuid.UUID,
        roles: frozenset[str],
    ) -> None:
        """Queue the principal's flag snapshot; a failed read costs the frame, never the `auth`."""
        body = await read_flag_snapshot(conn, snapshot, user_id, roles)
        if body is not None:
            conn.push_system(body)

    def pong(conn: _Connection, frame: dict[str, Any]) -> None:
        now_ms = conn.wall_ms()
        p: dict[str, Any] = {"server_ms": now_ms}
        body = frame.get("p")
        client_ms = client_epoch_ms(body.get("client_ms")) if isinstance(body, dict) else None
        if client_ms is not None:  # E17-R-10: any other value is ignored, as if absent
            p["rtt_hint_ms"] = clamp_ms(max(0, now_ms - client_ms))
        conn.push(_reply("pong", frame.get("id"), ts=now_ms, p=p))

    def pending(authz: ConnectionAuthz) -> set[str]:
        return {sid for sid, sub in authz.by_id.items() if sub.snapshot_pending}

    def flush(conn: _Connection, fresh: set[str]) -> None:
        """Snapshot the pending subscriptions after a `sub` or `ctl`; a `machines` one only when
        this frame made it pending (`fresh`). After that only a publish on its topic wakes it,
        never an inbound frame (§6.4). Flag on, the pipeline contains a build that raises."""
        if conn.authz is not None and conn.emitter is not None:
            subs = conn.authz.by_id.values()
            sink = conn.emitter if conn.pipeline is None else conn.pipeline
            sink.flush_pending(
                [s for s in subs if s.topic.entity_kind is None or s.sub_id in fresh]
            )

    def settle(conn: _Connection, subs: list[Subscription]) -> None:
        """Once a permission change's frames are queued: the `reconfigure` snapshots of what its
        narrowing re-pended (`subs`, nothing else), built under the new scope (§9.5). One that
        raises is contained to its subscription (§10.1): flag on, by the pipeline; flag off, as
        the hub contains one (`SequencingHub._snapshot_failed`), left pending with its reason
        for the next flush, and nothing closes. The flag-off `ws snapshot failed` line is the
        settle's own: one per subscription per change, not throttled as the hub's is (§9.5)."""
        if conn.pipeline is not None:
            conn.pipeline.flush_pending(subs)
        elif (emitter := conn.emitter) is not None:
            for sub in subs:
                try:
                    emitter.flush_pending((sub,))
                except Exception as exc:  # contained to `sub`, as the hub contains one
                    sub.snapshot_pending = True  # a raise may follow the build, which cleared it
                    fam = sub.topic.family  # by family and error class, never the text (C-12.6)
                    fields = {"family": fam.family, "error": type(exc).__name__}
                    with contextlib.suppress(Exception):  # a failing logger changes nothing
                        log = _log().error if fam.never_throttled else _log().warning
                        log("ws snapshot failed", connection_id=conn.connection_id, **fields)

    async def dispatch(conn: _Connection, frame: Any) -> None:
        if isinstance(frame, dict) and "id" in frame and not _is_envelope_id(frame["id"]):
            del frame["id"]  # #2572: never echoed, on any reply; the frame is still handled
        kind = frame.get("t") if isinstance(frame, dict) else None
        fid = frame.get("id") if isinstance(frame, dict) else None
        # §8.5: the frame was charged against the inbound rate before it was decoded (`charge`).
        if not conn.lifecycle.can(ConnEvent.HELLO) and kind == "hello":
            conn.violation(fid, "protocol_violation")
        elif conn.lifecycle.can(ConnEvent.HELLO):
            if kind != "hello" or not isinstance(frame, dict):
                conn.close_with("protocol_violation")  # §4.2: hello must be first
                return
            conn.lifecycle.fire(ConnEvent.HELLO)
            body = frame.get("p")
            clock_ms = client_epoch_ms(body.get("clock_ms")) if isinstance(body, dict) else None
            now_ms = conn.wall_ms()
            if clock_ms is not None:  # E17-R-10: any other value is ignored, as if absent
                cv_ws_clock_skew_ms.observe(abs(clamp_ms(now_ms - clock_ms)))
            welcome = welcome_payload(
                encoding=conn.encoding.removeprefix("cv.v1."),
                server_version=server_version,
                connection_id=conn.connection_id,
                server_time_ms=now_ms,
                client_clock_ms=clock_ms,
                features=features,
                auth_timeout_s=auth_timeout_s,
                max_inbound_frame_bytes=max_frame_bytes,
            )
            conn.push(_reply("welcome", fid, ts=now_ms, p=welcome))
            conn.lifecycle.fire(ConnEvent.WELCOME_SENT)
        elif not isinstance(frame, dict) or not isinstance(kind, str):
            conn.violation(fid)
        elif kind == "ping":
            pong(conn, frame)
        elif kind == "pong":  # a reply to a server ping; inbound traffic already recorded
            if conn.pipeline is not None and isinstance(fid, str):  # flag on: maybe the probe's
                conn.pipeline.pong(fid, conn.watchdog.last_inbound)  # at its receipt (§9.1)
        elif kind == "auth":
            await do_auth(conn, frame)
        elif not conn.lifecycle.authenticated:
            conn.unauth_frames += 1
            if conn.unauth_frames >= MAX_UNAUTHENTICATED_FRAMES:
                conn.close_with("not_authenticated")
            else:
                conn.push(build_ws_error("not_authenticated", id=_str_or_none(fid)))
        elif kind in ACTION_FRAME_TYPES and conn.authz is not None and conn.authz.viewing:
            await refuse_action_frame(conn, kind, fid)
        elif kind == "sub" and conn.authz is not None:
            held = pending(conn.authz)
            await _handle_sub(conn.authz, frame, conn.send, now_ms=conn.wall_ms())
            if conn.authz.by_id and conn.lifecycle.can(ConnEvent.SUB_OK):
                conn.lifecycle.fire(ConnEvent.SUB_OK)
            flush(conn, pending(conn.authz) - held)  # §7.1: the `snap` follows `sub_ok`
        elif kind == "unsub" and conn.authz is not None:
            # §5.3 idempotent; §6.2 `system` is permanent (refused, stays attached).
            conn.push(handle_unsub(conn.authz, frame, conn.wall_ms()))
        elif kind == "ctl" and conn.authz is not None:
            held = pending(conn.authz)
            conn.push(handle_ctl(conn.authz, frame, conn.wall_ms()))
            flush(conn, pending(conn.authz) - held)  # `ctl_ok { resnapshot }`, then its snap
            await audit_rebuild_refusal(conn.authz)  # #3476: after the reply, if one is due
        elif kind == "resync" and conn.authz is not None and conn.emitter is not None:
            if (revoked := conn.emitter.client_resync(conn.authz, frame)) is not None:
                await registry.audit_revoked(conn.authz, [revoked])  # SR-187: its row
            await audit_rebuild_refusal(conn.authz)  # #3476: after the reply, if one is due
        else:
            conn.violation(fid)

    async def reader(conn: _Connection) -> None:
        while not conn.closing:
            msg = await conn.ws.receive()
            if msg.get("type") == "websocket.disconnect":
                conn.disconnect_code = msg.get("code")
                return
            conn.watchdog.last_inbound = conn.clock()
            weighed = conn.weigh(msg, max_frame_bytes)
            if weighed is _OVERSIZE:
                return
            # #4924 (§8.5): a frame of weight above 1 waits for its user's decode turn, which each
            # socket of the user holds for one such frame and the loop turn after it (FIFO).
            turn = conn.decode_turn if weighed.weight > 1 else None
            async with turn if turn is not None else contextlib.nullcontext():
                frame = conn.decode_weighed(weighed)
                if frame is _OVERSIZE:
                    return
                if frame is not _REFUSED:  # a refused frame's strike is already counted
                    await dispatch(conn, frame)
                if not conn.closing:  # fair scheduling between connections: one frame per turn,
                    await asyncio.sleep(0)  # as `receive` returns at once while frames are queued

    async def writer(conn: _Connection) -> None:
        if conn.pipeline is not None:
            await budgeted_writer(conn, conn.pipeline)
            return
        pings = 0
        turn = _WriterSlice()
        while True:
            if conn.watch():
                pings += 1
                now_ms = conn.wall_ms()
                conn.push(
                    {"t": "ping", "id": f"s-hb-{pings}", "ts": now_ms, "p": {"server_ms": now_ms}}
                )
            if conn.outbound.empty():
                turn.restart()  # the `get` below waits: the loop gets its turns
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
            conn.watch()  # the dequeue may have waited a tick; a ping is queued only above
            if conn.sealed and item is not conn.bye_frame:
                continue  # the identity ended while this frame was queued: never send it
            try:
                if type(item) is tuple:  # the hub's sampled data frame, queued with its stamp
                    received, item = item
                    began = perf_counter()  # its encode time and size too, with the same weight
                    payload = conn.encode_frame(item)
                    seconds = perf_counter() - began
                    # The pair of the connection's codec. A JSON text is ASCII: chars are bytes.
                    sp = item.get("sp")  # left out of the size (23 §3.1)
                    size = frame_bytes(payload, sp, msgpack=conn.msgpack)
                    if conn.msgpack:
                        MSGPACK_ENCODE_SECONDS.observe(seconds, SAMPLE_EVERY)
                        MSGPACK_FRAME_BYTES.observe(size, SAMPLE_EVERY)
                    else:
                        JSON_ENCODE_SECONDS.observe(seconds, SAMPLE_EVERY)
                        JSON_FRAME_BYTES.observe(size, SAMPLE_EVERY)
                    await conn.send_payload(payload)
                    del payload  # the encoded copy (up to 4 MiB, a snapshot chunk) is not kept idle
                    now = conn.clock()  # the watchdog's send time, which this frame also observes
                    conn.watchdog.last_outbound = now
                    FANOUT_SECONDS.observe(now - received, SAMPLE_EVERY)
                    if sp is not None:
                        _log_span(conn.connection_id, sp, item["ch"], item["s"], now - received)
                else:  # every other frame: no stamp, no observation
                    await conn.send_frame(item)
                    conn.watchdog.last_outbound = conn.clock()
            except WebSocketDisconnect as exc:
                conn.disconnect_code = exc.code  # the client left mid-send; the reader saw nothing
                raise
            await turn.sent()

    async def budgeted_writer(conn: _Connection, pipe: ConnectionPipeline) -> None:
        """The writer with the flag on (still the one writer task, TG5): the priority lane
        first, each payload as the pipeline encoded it; after a close, what the close kept, then
        the `bye` and the close frame. The close's flush deadline bounds all of it: past it the
        flush is abandoned with no `bye` (§4.4), counted (`ConnectionPipeline.abandon`), and the
        handler tears the socket down. A stamped frame's encode was observed at push: the writer
        observes only its fan-out span. Before each pop it runs the ladder's `service` (`drain`)."""
        queue = pipe.queue
        pings = 0
        turn = _WriterSlice()
        try:
            async with asyncio.timeout(None) as deadline:
                pipe.arm(deadline)
                while True:
                    if conn.watch():
                        pings += 1
                        now_ms = conn.wall_ms()
                        ping = {"t": "ping", "id": f"s-hb-{pings}", "ts": now_ms}
                        conn.push(ping | {"p": {"server_ms": now_ms}})
                    pipe.service(conn.clock())  # the ladder's drain, before each pop
                    item = queue.pop()
                    if item is None:
                        if pipe.terminal is not None:
                            await send_bye(conn, pipe.terminal)
                            return
                        queue.ready.clear()
                        wait = pipe.wait_s(conn.clock(), tick_s)  # to the next window, if sooner
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(queue.ready.wait(), timeout=wait)
                        turn.restart()
                        continue
                    conn.watch()  # a close may land after the pop: send only what it keeps
                    end = pipe.terminal
                    if end is not None and not (item.priority and end.flush):
                        continue
                    try:
                        await conn.send_payload(item.payload)
                    except WebSocketDisconnect as exc:
                        conn.disconnect_code = exc.code
                        raise
                    now = conn.clock()
                    conn.watchdog.last_outbound = now
                    if item.received is not None:
                        FANOUT_SECONDS.observe(now - item.received, SAMPLE_EVERY)
                        if isinstance(item, Spanned) and item.key is not None:
                            fanout = now - item.received
                            _log_span(conn.connection_id, item.sp, item.key[0], item.s, fanout)
                    await turn.sent()  # after the span: the yield is not fan-out time
        except TimeoutError:
            if not deadline.expired():
                raise
            pipe.abandon(pipe.terminal.bye["p"].get("reason") if pipe.terminal else None)
        finally:
            pipe.disarm()

    async def send_bye(conn: _Connection, end: Terminal) -> None:
        """The terminal slot: `bye`, then the close frame (S11)."""
        try:
            await conn.send_frame(end.bye)
        except WebSocketDisconnect as exc:
            conn.disconnect_code = exc.code
            raise
        conn.watchdog.last_outbound = conn.clock()
        conn.close_code = end.code
        with contextlib.suppress(Exception):
            await conn.ws.close(code=end.code)

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
            if origin_audit is not None:  # bounded; never raises a write's failure (#2269)
                await origin_audit.record(refused, _source_ip(ws.scope))
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
            ws,
            encoding=encoding,
            clock=clock,
            wall_ms=wall_ms,
            auth_timeout_s=auth_timeout_s,
            backpressure=backpressure,
            flag_visible=flag_visible,
            tick_s=tick_s,
            close_flush_s=close_flush_s,
            loop_stall=loop_stall,
        )
        if gateway_hub.unauthenticated >= gateway_hub.max_unauthenticated:  # #2155 (§4.3)
            await shed(conn)
            return
        conn.lifecycle.fire(ConnEvent.OPEN_NEGOTIATED)
        gateway_hub.add(conn)
        cv_ws_connections_in_use.inc()
        structlog.contextvars.bind_contextvars(connection_id=conn.connection_id)
        # TG5: exactly one reader (this handler task) and one writer task,
        # owned here and always cancelled + awaited before returning (C-2.18).
        write_task = spawn(writer(conn), name=f"{conn.connection_id}-writer")
        conn.end_writer = write_task.cancel  # #3100: a close timer fault that left no close
        handler = asyncio.current_task()
        reading = True

        def _writer_done(_t: asyncio.Task[None]) -> None:
            # The close frame is out (or the writer failed): stop the blocked read.
            if reading and handler is not None:
                handler.cancel(msg=_WRITER_DONE)

        write_task.add_done_callback(_writer_done)
        fault: BaseException | None = None
        gateway_hub.admit_unauthenticated(conn)  # #2155: no await since the cap check above
        conn.arm_flush_deadline(auth_timeout_s + conn.close_flush_s)  # #415: until `auth_ok`
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
            conn.stop_close_timer()  # first: no deadline closes a connection that is ending
            reading = False
            write_task.cancel()
            try:
                if fault is None:
                    fault = await _join_writer(write_task) or conn.timer_fault
                if fault is not None:
                    # The handler's own `bye` and 1011 do not go through `close_with`: count here.
                    # A fault after a `close_with` is counted under both reasons (that close was
                    # initiated, and this `bye` plus 1011 supersedes it on the wire), so alerts
                    # should key on `reason="internal_error"`, not on the sum.
                    cv_ws_closes_total.labels(reason="internal_error").inc()
                    _log().error(
                        "ws connection fault", connection_id=conn.connection_id, exc_info=fault
                    )
                    with contextlib.suppress(Exception):  # S11: bye before the 1011 close
                        bye = lifecycle_bye("internal_error", now_ms=wall_ms())
                        async with _fault_flush(conn):  # flag on: the close flush deadline
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
                # #415, defence in depth: the undo sites reset `registered` with `authz`, so no
                # path resets `authz` alone today; if one does, what was registered is released.
                if conn.authz is None:
                    conn.authz = conn.registered
                if conn.pipeline is not None:
                    with _step(conn, "pipeline"):
                        conn.pipeline.release()
                if conn.authz is not None:
                    conn.authz.on_purge = conn.authz.on_settle = None  # `on_drop`: the pipeline's
                    with _step(conn, "sequencing"):
                        if registry.services.sequencing is not None:
                            registry.services.sequencing.unregister(conn.authz)
                    with _step(conn, "registry"):
                        registry.unregister(conn.authz)
                if conn.session_id is not None:
                    with _step(conn, "revocation"):
                        revocation_hub.unregister(conn.session_id, conn.closer)
                with _step(conn, "ended"):
                    conn.log_ended(fault, server_shutting_down=gateway_hub.shutting_down)
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
