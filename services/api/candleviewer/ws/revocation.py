"""Session revocation -> WebSocket `bye` + close (23-ws-protocol.md §4.4, §9.5, US-ONB-009).

Transport-agnostic: the (E17) gateway registers one `Closer` per live socket
keyed by session id; the session router's `publish_revocation` calls
`RevocationHub.revoke`, which sends the `bye` frame and closes with 4401. The
reason `user_disabled` (the SR-029 disable cascade) gets the §9.5 `bye` and
4403 instead, so the client returns to login and does not reconnect (#2493).
Latency is observed on `auth_revocation_latency_seconds` (alert > 5 s).
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Final, Literal

import structlog

from candleviewer.observability.metrics import Counter, Histogram


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


CLOSE_TOKEN_EXPIRED = 4401

auth_revocation_latency_seconds = Histogram(
    "ws_session_revocation_close_seconds",
    "Seconds from session revocation to its WebSocket being closed.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ws_revocation_close_failures_total = Counter(
    "ws_session_revocation_close_failures_total",
    "WebSocket closes that failed during session revocation (socket may remain open).",
)

#: §9.5 / §13.6 closed `revoked.reason` set - no internal detail ever leaks through it.
RevokedReason = Literal[
    "permission_revoked",
    "account_scope_changed",
    "user_disabled",
    "session_revoked",
    "key_revoked",
    "account_disabled",
    "replay_session_ended",
    "resync_rate_limited",
    "topic_removed",
]
CLOSE_USER_DISABLED: Final = 4403

ws_revoked_total = Counter(
    "cv_ws_revoked_total", "WS subscriptions revoked mid-connection.", labelnames=("reason",)
)

_REVOKED_MESSAGES: Final[dict[str, str]] = {
    "permission_revoked": "Access to this data was withdrawn.",
    "account_scope_changed": "Access to one or more accounts was withdrawn.",
    "user_disabled": "Your user was disabled.",
    "session_revoked": "Your session was ended.",
    "key_revoked": "The account's API key was revoked.",
    "account_disabled": "The account was disabled.",
    "replay_session_ended": "The replay session ended.",
    "resync_rate_limited": "Too many resyncs on this topic.",
    "topic_removed": "This topic is no longer available.",
}


def revoked_frame(
    ch: str,
    reason: RevokedReason,
    *,
    now_ms: int,
    removed_accounts: list[str] | None = None,
    resubscribe_allowed: bool = False,
) -> dict[str, Any]:
    """§9.5 `revoked` frame; `reason` is from the closed set, the message is fixed copy."""
    p: dict[str, Any] = {
        "reason": reason,
        "message": _REVOKED_MESSAGES[reason],
        "resubscribe_allowed": resubscribe_allowed,
    }
    if removed_accounts:
        p["removed_accounts"] = removed_accounts
    return {"t": "revoked", "ch": ch, "ts": now_ms, "p": p}


def user_disabled_bye(now_ms: int) -> dict[str, Any]:
    """§9.5: the disabled user's sockets get `bye user_disabled` then close 4403."""
    return {
        "t": "bye",
        "ts": now_ms,
        "p": {
            "code": CLOSE_USER_DISABLED,
            "reason": "user_disabled",
            "message": "Your user was disabled.",
            "reconnect": False,
        },
    }


Closer = Callable[[dict[str, Any], int], Awaitable[None]]  # (bye frame, close code)


def bye_frame(reason: str) -> dict[str, Any]:
    return {
        "t": "bye",
        "p": {
            "code": CLOSE_TOKEN_EXPIRED,
            "reason": reason,
            "message": "session revoked",
            "reconnect": False,
        },
    }


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


class RevocationHub:
    def __init__(self, *, wall_ms: Callable[[], int] = _wall_ms) -> None:
        self._sockets: dict[str, list[Closer]] = defaultdict(list)
        #: Stamps the `user_disabled` bye's `ts`; injectable so tests read a fixed clock.
        self._wall_ms = wall_ms

    def register(self, session_id: str, closer: Closer) -> None:
        self._sockets[session_id].append(closer)

    def unregister(self, session_id: str, closer: Closer) -> None:
        if closer in self._sockets.get(session_id, []):
            self._sockets[session_id].remove(closer)
        if not self._sockets.get(session_id):
            self._sockets.pop(session_id, None)

    def _close_for(self, reason: str) -> tuple[dict[str, Any], int]:
        """The `bye` and close code for `reason`. §9.5: a disabled user gets its own `bye`
        and 4403 (do not reconnect); every other session revocation closes 4401."""
        if reason == "user_disabled":
            return user_disabled_bye(self._wall_ms()), CLOSE_USER_DISABLED
        return bye_frame(reason), CLOSE_TOKEN_EXPIRED

    async def revoke(self, session_id: str, reason: str = "session_revoked") -> int:
        """Close every socket of `session_id`; returns how many were closed."""
        closers = self._sockets.pop(session_id, [])
        started = time.monotonic()
        for closer in closers:
            try:
                frame, code = self._close_for(reason)
                await closer(frame, code)
            except Exception:
                ws_revocation_close_failures_total.inc()
                _log().error(
                    "ws revocation close failed; revoked socket may remain open",
                    session_id=session_id,
                    exc_info=True,
                )
        if closers:
            auth_revocation_latency_seconds.observe(time.monotonic() - started)
        return len(closers)
