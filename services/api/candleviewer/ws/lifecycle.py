"""WS connection lifecycle (E17-S01; `23-ws-protocol.md` §2.2, §4, §8.5, §9.1).

Pure, I/O-free building blocks the gateway drives:

- `ConnState` + `TRANSITIONS`: the §4.1 state machine as an explicit enum and
  transition table (no implicit boolean flags). Not a catalogue statechart
  (B1-B20) - it is the per-frame transport path, which C-2.20 keeps out of the
  statechart runtime.
- `negotiate_subprotocol`: §2.2 subprotocol selection.
- `origin_refusal`: §2.5 `Origin` check on the upgrade (SR-042, SR-183), `header_values`
  (case-insensitive header names) and `RefusalLogLimiter` (the refusal log cap).
- `bye_frame`: the one `bye` builder (§4.4, requirement S11).
- `InboundRateLimiter`: 30 frames/s and 300 frames/min excluding `pong` (§8.5).
- `ConnectRateLimiter`: new authenticated sockets per user per sliding minute (§4.3, #2558).
- `Watchdog`: auth deadline, token expiry, unsolicited ping and heartbeat
  timeout evaluated against an injected monotonic clock (no sleeps).
- `welcome_payload`: the §4.2 `welcome` body with the full §16.2 limits block.
"""

from __future__ import annotations

import enum
import math
import uuid
from collections import OrderedDict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from candleviewer.ws.limits import (
    AUTH_TIMEOUT_S,
    MAX_INBOUND_FRAME_BYTES,
    MAX_SUBSCRIPTIONS,
    MAX_TOPICS_PER_SUB,
)

SUBPROTOCOL_JSON: Final = "cv.v1.json"
SUBPROTOCOL_MSGPACK: Final = "cv.v1.msgpack"
#: Subprotocols this build serves, in server preference order (§2.2): MessagePack, decoded under
#: the SR-185 bounds (`ws/codec.py`), then JSON. The server's order wins over the client's.
SUPPORTED_SUBPROTOCOLS: Final[tuple[str, ...]] = (SUBPROTOCOL_MSGPACK, SUBPROTOCOL_JSON)

HEARTBEAT_INTERVAL_S: Final = 15.0
HEARTBEAT_TIMEOUT_S: Final = 45.0
#: Server sends an unsolicited `ping` after this much outbound silence (§9.1).
SERVER_PING_AFTER_S: Final = 20.0
MAX_CONNECTIONS_PER_USER: Final = 8
#: §4.3 / §16.2 (#2558): sockets one user may newly authenticate in any `AUTH_RATE_WINDOW_S`.
MAX_AUTHS_PER_USER_PER_MIN: Final = 20
AUTH_RATE_WINDOW_S: Final = 60.0
#: The floor of a connect refusal's `bye.retry_after_ms`.
MIN_CONNECT_RETRY_AFTER_MS: Final = 1000
SHUTDOWN_GRACE_MS: Final = 5000
#: Failed `auth` attempts / pre-auth frames / malformed frames before closing.
MAX_AUTH_FAILURES: Final = 3
MAX_UNAUTHENTICATED_FRAMES: Final = 3
MAX_PROTOCOL_VIOLATIONS: Final = 3
RATE_PER_SECOND: Final = 30
RATE_PER_MINUTE: Final = 300

LIMITS_BLOCK: Final[dict[str, int]] = {
    "max_subscriptions": MAX_SUBSCRIPTIONS,
    "max_topics_per_request": MAX_TOPICS_PER_SUB,
    "max_inbound_frame_bytes": MAX_INBOUND_FRAME_BYTES,
    "max_outbound_frame_bytes": 4 * 1024 * 1024,
    "min_throttle_ms": 50,
    "max_symbols_per_connection": 40,
}
FEATURES: Final[dict[str, bool]] = {"replay": True, "binary_payloads": True, "coalescing": True}


class CloseCode(enum.IntEnum):
    """§4.4 close codes."""

    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    TOO_BIG = 1009
    INTERNAL_ERROR = 1011
    TRY_AGAIN_LATER = 1013
    UNAUTHENTICATED = 4401
    FORBIDDEN = 4403
    RATE_LIMITED = 4429
    BAD_CLIENT = 4400


#: §2.5 / §4.4: reason of a refused upgrade (closed `4403` before `accept`, so no `bye`).
ORIGIN_FORBIDDEN: Final = "origin_forbidden"

#: reason -> (close code, reconnect). Every server-initiated close maps here.
CLOSE_REASONS: Final[dict[str, tuple[CloseCode, bool]]] = {
    "normal": (CloseCode.NORMAL, False),
    "shutdown": (CloseCode.GOING_AWAY, True),
    "protocol_violation": (CloseCode.PROTOCOL_ERROR, False),
    "unsupported_protocol": (CloseCode.PROTOCOL_ERROR, False),
    ORIGIN_FORBIDDEN: (CloseCode.FORBIDDEN, False),
    "frame_too_big": (CloseCode.TOO_BIG, False),
    "internal_error": (CloseCode.INTERNAL_ERROR, True),
    "server_shedding_load": (CloseCode.TRY_AGAIN_LATER, True),
    "auth_timeout": (CloseCode.UNAUTHENTICATED, True),
    "auth_failed": (CloseCode.UNAUTHENTICATED, True),
    "not_authenticated": (CloseCode.UNAUTHENTICATED, True),
    "token_expired": (CloseCode.UNAUTHENTICATED, True),
    "session_revoked": (CloseCode.UNAUTHENTICATED, True),
    "user_disabled": (CloseCode.FORBIDDEN, False),
    "client_rate_limited": (CloseCode.RATE_LIMITED, True),
    "slow_consumer": (CloseCode.RATE_LIMITED, True),
    "too_many_connections": (CloseCode.RATE_LIMITED, True),
    "heartbeat_timeout": (CloseCode.GOING_AWAY, True),
    "bad_client": (CloseCode.BAD_CLIENT, False),
}
#: The `cv_ws_closes_total{reason}` label of a `bye` reason that is not a key of `CLOSE_REASONS`.
#: The one name for that bucket, for the label a close counts under and the series bound at import.
OTHER_CLOSE_REASON: Final = "other"

_MESSAGES: Final[dict[str, str]] = {
    "shutdown": "Server restarting.",
    "auth_timeout": "No successful auth within the auth window.",
    "auth_failed": "Authentication failed.",
    "not_authenticated": "Frames sent before auth_ok.",
    "token_expired": "Access token expired; refresh and re-auth.",
    "client_rate_limited": "Inbound frame rate exceeded.",
    "heartbeat_timeout": "No traffic within the heartbeat timeout.",
    "too_many_connections": "Connection limit per user exceeded; oldest idle closed.",
}
#: `bye.message` of a connect-rate refusal (§4.3): the cause, not `_MESSAGES`' inbound-frame text.
CONNECT_RATE_MESSAGE: Final = "Per-user connect rate exceeded; retry after retry_after_ms."


class ConnState(enum.StrEnum):
    """§4.1 lifecycle states (`Subscribed`/`Resyncing` are entered by E17-S02/S03)."""

    CONNECTING = "connecting"
    NEGOTIATED = "negotiated"
    HELLO_SENT = "hello_sent"
    AWAITING_AUTH = "awaiting_auth"
    AUTHENTICATED = "authenticated"
    REAUTHENTICATING = "reauthenticating"
    SUBSCRIBED = "subscribed"
    RESYNCING = "resyncing"
    CLOSING = "closing"
    CLOSED = "closed"


class ConnEvent(enum.StrEnum):
    OPEN_NEGOTIATED = "open_negotiated"
    HELLO = "hello"
    WELCOME_SENT = "welcome_sent"
    AUTH_OK = "auth_ok"
    REAUTH = "reauth"
    REAUTH_FAILED = "reauth_failed"
    SUB_OK = "sub_ok"
    GAP = "gap"
    SNAPSHOT = "snapshot"
    CLOSE = "close"
    CLOSED = "closed"


S, E = ConnState, ConnEvent
#: (state, event) -> next state. Any pair absent here is illegal; `CLOSE` is
#: legal from every live state (§4.1 "Closing reachable from everywhere").
TRANSITIONS: Final[dict[tuple[ConnState, ConnEvent], ConnState]] = {
    (S.CONNECTING, E.OPEN_NEGOTIATED): S.NEGOTIATED,
    (S.NEGOTIATED, E.HELLO): S.HELLO_SENT,
    (S.HELLO_SENT, E.WELCOME_SENT): S.AWAITING_AUTH,
    (S.AWAITING_AUTH, E.AUTH_OK): S.AUTHENTICATED,
    (S.AUTHENTICATED, E.REAUTH): S.REAUTHENTICATING,
    (S.SUBSCRIBED, E.REAUTH): S.REAUTHENTICATING,
    (S.REAUTHENTICATING, E.AUTH_OK): S.AUTHENTICATED,
    # A failed re-auth keeps the still-valid prior identity until it expires.
    (S.REAUTHENTICATING, E.REAUTH_FAILED): S.AUTHENTICATED,
    (S.AUTHENTICATED, E.SUB_OK): S.SUBSCRIBED,
    (S.SUBSCRIBED, E.SUB_OK): S.SUBSCRIBED,
    (S.SUBSCRIBED, E.GAP): S.RESYNCING,
    (S.RESYNCING, E.SNAPSHOT): S.SUBSCRIBED,
    **{(s, E.CLOSE): S.CLOSING for s in ConnState if s not in (S.CLOSING, S.CLOSED)},
    (S.CLOSING, E.CLOSED): S.CLOSED,
}
del S, E


class IllegalTransition(Exception):
    """A (state, event) pair the §4.1 table does not allow."""


class Lifecycle:
    """Holds the current `ConnState`; every change goes through `fire`."""

    def __init__(self) -> None:
        self.state = ConnState.CONNECTING
        self.history: list[ConnState] = [self.state]

    def can(self, event: ConnEvent) -> bool:
        return (self.state, event) in TRANSITIONS

    def fire(self, event: ConnEvent) -> ConnState:
        nxt = TRANSITIONS.get((self.state, event))
        if nxt is None:
            raise IllegalTransition(f"{event.value} illegal in {self.state.value}")
        self.state = nxt
        self.history.append(nxt)
        return nxt

    @property
    def authenticated(self) -> bool:
        return self.state in (
            ConnState.AUTHENTICATED,
            ConnState.REAUTHENTICATING,
            ConnState.SUBSCRIBED,
            ConnState.RESYNCING,
        )


def negotiate_subprotocol(
    offered: Iterable[str], supported: tuple[str, ...] = SUPPORTED_SUBPROTOCOLS
) -> str | None:
    """§2.2: the first server-preferred subprotocol the client offered, else None."""
    wanted = {o.strip() for o in offered}
    return next((p for p in supported if p in wanted), None)


class OriginRefusal(enum.StrEnum):
    """§2.5 bounded refusal cause: the `check` log field, never a header value."""

    ORIGIN_MISSING = "origin_missing"
    ORIGIN_NULL = "origin_null"
    CROSS_SITE = "cross_site"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"


#: §2.5: `Sec-Fetch-Site` values that label an unlisted origin's refusal as `cross_site`.
CROSS_SITE_FETCHES: Final = frozenset({"cross-site", "same-site"})
#: §2.5: the serialised opaque origin (sandboxed frame, `file:`, `data:`); never admitted.
NULL_ORIGIN: Final = "null"


def header_values(raw: Iterable[tuple[bytes, bytes]], name: bytes) -> list[str]:
    """Every value of header `name` (lowercase) in raw ASGI headers, matching names in any
    case: servers lowercase them, but a refusal must never hinge on that."""
    return [value.decode("latin-1") for key, value in raw if key.lower() == name]


def origin_refusal(
    origins: Sequence[str], fetch_sites: Sequence[str], allowed: frozenset[str]
) -> OriginRefusal | None:
    """§2.5 upgrade check (SR-042, SR-183); None admits the upgrade.

    `origins` / `fetch_sites` are every `Origin` / `Sec-Fetch-Site` value received. The
    allow-list decides: exactly one `Origin`, not `null` (even if listed) and in `allowed`
    (exact match once trailing `/` is dropped, as `Settings.allowed_origin_set` normalises)
    is admitted whatever `Sec-Fetch-Site` says. Everything else is refused, with no
    non-browser exemption. `Sec-Fetch-Site` only labels an unlisted origin's refusal:
    `cross-site` / `same-site` is the cross-site hijacking signature (`cross_site`)."""
    if not origins:
        return OriginRefusal.ORIGIN_MISSING
    if len(origins) > 1:
        return OriginRefusal.ORIGIN_NOT_ALLOWED  # ambiguous: never pick one
    origin = origins[0].strip().rstrip("/")
    if origin.lower() == NULL_ORIGIN:
        return OriginRefusal.ORIGIN_NULL
    if origin in allowed:
        return None
    if any(site.strip().lower() in CROSS_SITE_FETCHES for site in fetch_sites):
        return OriginRefusal.CROSS_SITE
    return OriginRefusal.ORIGIN_NOT_ALLOWED


#: §2.5 log cap: refusal lines per cause per window; the counter still counts every refusal.
REFUSAL_LOG_LIMIT: Final = 10
REFUSAL_LOG_WINDOW_S: Final = 60.0


class RefusalLog(enum.Enum):
    """What one refusal may log under `RefusalLogLimiter`."""

    LINE = "line"
    SUMMARY = "summary"
    NONE = "none"


class RefusalLogLimiter:
    """Fixed-window cap on §2.5 refusal log lines, per cause: the first `limit` refusals of
    a cause in a window log a line, the next logs one summary, the rest are only counted.

    Bounded (C-2.18): one entry per `OriginRefusal` value; time is an injected monotonic
    clock reading, so tests drive windows without sleeping."""

    def __init__(
        self, *, limit: int = REFUSAL_LOG_LIMIT, window_s: float = REFUSAL_LOG_WINDOW_S
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._seen: dict[OriginRefusal, tuple[float, int]] = {}

    def admit(self, cause: OriginRefusal, now: float) -> RefusalLog:
        start, count = self._seen.get(cause, (now, 0))
        if now - start >= self._window_s:
            start, count = now, 0
        count += 1
        self._seen[cause] = (start, count)
        if count <= self._limit:
            return RefusalLog.LINE
        return RefusalLog.SUMMARY if count == self._limit + 1 else RefusalLog.NONE


def bye_frame(
    reason: str,
    *,
    now_ms: int | None = None,
    retry_after_ms: int | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """§4.4 / §13.6 `bye`; `code` and `reconnect` come from `CLOSE_REASONS`. `message` overrides
    the reason's stock text (a reason can have more than one cause)."""
    code, reconnect = CLOSE_REASONS[reason]
    p: dict[str, Any] = {
        "code": int(code),
        "reason": reason,
        "message": message or _MESSAGES.get(reason, reason.replace("_", " ")),
        "reconnect": reconnect,
    }
    if retry_after_ms is not None:
        p["retry_after_ms"] = retry_after_ms
    frame: dict[str, Any] = {"t": "bye", "p": p}
    if now_ms is not None:
        frame["ts"] = now_ms
    return frame


class InboundRateLimiter:
    """Sliding-window counter: 30 frames per 1 s and 300 per 60 s (§8.5).

    Bounded: the deque never holds more than `per_minute` timestamps.
    """

    def __init__(self, per_second: int = RATE_PER_SECOND, per_minute: int = RATE_PER_MINUTE):
        self._per_second = per_second
        self._per_minute = per_minute
        self._stamps: deque[float] = deque(maxlen=per_minute + 1)

    def allow(self, now: float) -> bool:
        """Record one frame at monotonic `now`; False when over either limit."""
        while self._stamps and now - self._stamps[0] >= 60.0:
            self._stamps.popleft()
        last_second = sum(1 for t in self._stamps if now - t < 1.0)
        if last_second >= self._per_second or len(self._stamps) >= self._per_minute:
            return False
        self._stamps.append(now)
        return True


class ConnectRateLimiter:
    """Per-user sliding-window cap on new authenticated sockets (§4.3, #2558): at most `limit`
    successful first `auth`s per user in any `AUTH_RATE_WINDOW_S`.

    `admit(user_id, now)` records one and returns None. When the user already holds `limit` in the
    window it records nothing and returns the advised `retry_after_ms`: the time until the oldest
    of them leaves the window, rounded up to a whole millisecond, never below
    `MIN_CONNECT_RETRY_AFTER_MS`. A stamp leaves the window once it is a full window old (the same
    exclusive edge as `InboundRateLimiter`). The caller offers only a new socket's first
    successful `auth`: a failed `auth` and an in-place re-`auth` never get here, and a refusal
    leaves no trace, so a refused client cannot lengthen its own wait. `first_refusal` tells the
    caller whether to log a refusal: once per user per window, the rest are only counted.

    Bounded (C-2.18): a user holds at most `limit` timestamps, and users are kept in the order of
    their newest stamp, so each `admit` first drops, from the front, every user whose newest stamp
    has left the window. Memory follows the users active in the last window, not every user ever
    seen, with no timer or task to own. `now` is an injected monotonic reading, so tests drive
    windows without sleeping."""

    def __init__(self, limit: int = MAX_AUTHS_PER_USER_PER_MIN) -> None:
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        self._limit = limit
        self._stamps: OrderedDict[uuid.UUID, deque[float]] = OrderedDict()
        self._logged: OrderedDict[uuid.UUID, float] = OrderedDict()  # user -> last logged refusal

    @property
    def limit(self) -> int:
        return self._limit

    def __len__(self) -> int:
        """The users holding at least one stamp in the window."""
        return len(self._stamps)

    def admit(self, user_id: uuid.UUID, now: float) -> int | None:
        """Count one new socket of `user_id` at monotonic `now`; None admits it, else the
        `retry_after_ms` to advise."""
        self._drop_idle(now)
        stamps = self._stamps.get(user_id)
        if stamps is None:
            stamps = self._stamps[user_id] = deque(maxlen=self._limit)
        while stamps and now - stamps[0] >= AUTH_RATE_WINDOW_S:
            stamps.popleft()
        if len(stamps) >= self._limit:
            wait_ms = math.ceil((stamps[0] + AUTH_RATE_WINDOW_S - now) * 1000)
            return max(MIN_CONNECT_RETRY_AFTER_MS, wait_ms)
        stamps.append(now)
        self._stamps.move_to_end(user_id)
        return None

    def first_refusal(self, user_id: uuid.UUID, now: float) -> bool:
        """True for a user's first refusal in the last window: the caller logs that one and only
        counts the rest, like `RefusalLogLimiter` for refused upgrades. Bounded (C-2.18): one entry
        per user refused in the last window, in logging order, aged out from the front."""
        while self._logged and now - next(iter(self._logged.values())) >= AUTH_RATE_WINDOW_S:
            self._logged.popitem(last=False)
        if user_id in self._logged:
            return False
        self._logged[user_id] = now
        return True

    def _drop_idle(self, now: float) -> None:
        """Forget every user whose newest stamp has left the window (the front is the stalest)."""
        while self._stamps:
            stalest = next(iter(self._stamps))
            if now - self._stamps[stalest][-1] < AUTH_RATE_WINDOW_S:
                return
            del self._stamps[stalest]


def welcome_payload(
    *,
    encoding: str,
    server_version: str,
    git_sha: str,
    connection_id: str,
    server_time_ms: int,
    client_clock_ms: object,
    auth_timeout_s: float = AUTH_TIMEOUT_S,
    heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
    heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S,
) -> dict[str, Any]:
    """§4.2 body. `clock_skew_ms` = server time - client `clock_ms` (reported, never corrected);
    omitted when the client sent no integer clock."""
    p: dict[str, Any] = {
        "protocol": "cv.v1",
        "encoding": encoding,
        "server_version": server_version,
        "git_sha": git_sha,
        "connection_id": connection_id,
        "server_time_ms": server_time_ms,
        "auth_required": True,
        "auth_timeout_ms": int(auth_timeout_s * 1000),
        "heartbeat": {
            "interval_ms": int(heartbeat_interval_s * 1000),
            "timeout_ms": int(heartbeat_timeout_s * 1000),
        },
        "limits": dict(LIMITS_BLOCK),
        "features": dict(FEATURES),
    }
    if isinstance(client_clock_ms, int) and not isinstance(client_clock_ms, bool):
        p["clock_skew_ms"] = server_time_ms - client_clock_ms
    return p


@dataclass
class Watchdog:
    """Deadline bookkeeping on an injected monotonic clock (seconds).

    `due(now)` returns the close reason that has fired, `"ping"` when an
    unsolicited server ping is due, or None. The gateway polls it from one
    owned timer task, so no per-beat allocation and no sleeps in tests.
    """

    auth_deadline: float | None
    last_inbound: float
    last_outbound: float
    token_expires_at: float | None = None
    heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S
    ping_after_s: float = SERVER_PING_AFTER_S

    def due(self, now: float) -> str | None:
        if self.auth_deadline is not None and now >= self.auth_deadline:
            return "auth_timeout"
        if self.token_expires_at is not None and now >= self.token_expires_at:
            return "token_expired"
        if now - self.last_inbound >= self.heartbeat_timeout_s:
            return "heartbeat_timeout"
        if now - self.last_outbound >= self.ping_after_s:
            return "ping"
        return None
