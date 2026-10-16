"""Session revocation -> WebSocket `bye` + close (23-ws-protocol.md §4.4, §9.5, US-ONB-009).

Transport-agnostic: the (E17) gateway registers one `Closer` per live socket
keyed by session id; the session router's `publish_revocation` calls
`RevocationHub.revoke`, which sends the `bye` frame and closes with 4401. The
reason `user_disabled` (the SR-029 disable cascade) gets the §9.5 `bye` and
4403 instead, so the client returns to login and does not reconnect (#2493).
Latency is observed on `auth_revocation_latency_seconds` (alert > 5 s).

The hub also remembers each revoked session id, with its reason, for one access-token
lifetime (#2739), so an `auth` that was already in flight when the revocation was published
can still be refused: `revoked_reason` / `was_revoked`, and `close_for` builds its `bye`. The
memory is bounded (C-2.18): entries expire after `remember_s`, and past `max_remembered` the
oldest is forgotten first, which reopens the in-flight window for that one session only and
is logged (throttled). A remembered `user_disabled` is never downgraded by a later revocation
of the same session, so the 4403 close survives a repeat (§9.5).
"""

from __future__ import annotations

import contextlib
import math
import time
from collections import OrderedDict, defaultdict
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


#: Seconds a revoked session id is remembered: one access-token lifetime (ADR-0020,
#: `auth.session_service.ACCESS_TOKEN_TTL`, which the composition root passes). A revoked
#: session cannot mint new tokens, so after that no `auth` for it can succeed anyway.
REVOKED_MEMORY_S: Final = 720.0
#: At most this many revoked ids are remembered (C-2.18); the oldest is forgotten first. A live id
#: is forgotten early only once 4096 other sessions are revoked after it within one
#: `REVOKED_MEMORY_S` (about 5.7 a second, sustained).
MAX_REVOKED_IDS: Final = 4096
#: A forced eviction (cap reached while the oldest is still live) is logged at most this often.
EVICTION_LOG_EVERY_S: Final = 60.0


class RevocationHub:
    def __init__(
        self,
        *,
        wall_ms: Callable[[], int] = _wall_ms,
        remember_s: float = REVOKED_MEMORY_S,
        max_remembered: int = MAX_REVOKED_IDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (math.isfinite(remember_s) and remember_s > 0) or max_remembered < 1:
            raise ValueError("remember_s must be finite and > 0 and max_remembered >= 1")
        self._sockets: dict[str, list[Closer]] = defaultdict(list)
        #: Stamps the `user_disabled` bye's `ts`; injectable so tests read a fixed clock.
        self._wall_ms = wall_ms
        self._remember_s = remember_s
        self._max_remembered = max_remembered
        self._monotonic = monotonic
        #: session id -> (monotonic expiry, reason), oldest first. Every entry lives the same
        #: `remember_s` from a non-decreasing clock, so insertion order is expiry order.
        self._revoked: OrderedDict[str, tuple[float, str]] = OrderedDict()
        #: Live entries forgotten because the cap was reached, and when that was last logged.
        self._evicted = 0
        self._evicted_logged_at: float | None = None

    @property
    def remember_s(self) -> float:
        """Seconds a revoked session id is remembered."""
        return self._remember_s

    @property
    def max_remembered(self) -> int:
        """Most revoked session ids remembered at once; past it the oldest is forgotten first."""
        return self._max_remembered

    def _prune(self, now: float) -> None:
        while self._revoked:
            session_id, (expires_at, _) = next(iter(self._revoked.items()))
            if expires_at > now:
                return
            del self._revoked[session_id]

    def _remember(self, session_id: str, reason: str) -> None:
        now = self._monotonic()
        self._prune(now)
        previous = self._revoked.pop(session_id, None)  # a repeat revocation renews the entry
        if previous is not None and previous[1] == "user_disabled":
            reason = "user_disabled"  # never downgrade the 4403 close (§9.5)
        self._revoked[session_id] = (now + self._remember_s, reason)
        while len(self._revoked) > self._max_remembered:
            self._revoked.popitem(last=False)  # pruned above, so this one was still live
            self._evicted += 1
            if (
                self._evicted_logged_at is None
                or now - self._evicted_logged_at >= EVICTION_LOG_EVERY_S
            ):
                self._evicted_logged_at = now
                # A failing log sink must never skip the closes that follow (C-2.12).
                with contextlib.suppress(Exception):
                    _log().warning(
                        "ws revoked-id memory full; oldest live entry forgotten",
                        evicted_total=self._evicted,
                        max_remembered=self._max_remembered,
                    )

    def revoked_reason(self, session_id: str) -> str | None:
        """The reason `session_id` was revoked within the last `remember_s`, else `None`."""
        self._prune(self._monotonic())
        entry = self._revoked.get(session_id)
        return None if entry is None else entry[1]

    def was_revoked(self, session_id: str) -> bool:
        return self.revoked_reason(session_id) is not None

    def register(self, session_id: str, closer: Closer) -> None:
        self._sockets[session_id].append(closer)

    def unregister(self, session_id: str, closer: Closer) -> None:
        if closer in self._sockets.get(session_id, []):
            self._sockets[session_id].remove(closer)
        if not self._sockets.get(session_id):
            self._sockets.pop(session_id, None)

    def close_for(self, reason: str) -> tuple[dict[str, Any], int]:
        """The `bye` and close code for `reason`. §9.5: a disabled user gets its own `bye`
        and 4403 (do not reconnect); every other session revocation closes 4401."""
        if reason == "user_disabled":
            return user_disabled_bye(self._wall_ms()), CLOSE_USER_DISABLED
        return bye_frame(reason), CLOSE_TOKEN_EXPIRED

    async def revoke(self, session_id: str, reason: str = "session_revoked") -> int:
        """Remember `session_id` as revoked, then close every socket of it; returns how many
        closes it attempted. Remembered first, so an `auth` checking during the closes sees it."""
        self._remember(session_id, reason)
        reason = self._revoked[session_id][1]  # a remembered user_disabled wins (§9.5, 4403)
        closers = self._sockets.pop(session_id, [])
        started = time.monotonic()
        for closer in closers:
            try:
                frame, code = self.close_for(reason)
                await closer(frame, code)
            except Exception:
                ws_revocation_close_failures_total.inc()
                # A failing log sink must never skip the closes that follow (C-2.12); the
                # counter above still records the failure.
                with contextlib.suppress(Exception):
                    _log().error(
                        "ws revocation close failed; revoked socket may remain open",
                        session_id=session_id,
                        exc_info=True,
                    )
        if closers:
            auth_revocation_latency_seconds.observe(time.monotonic() - started)
        return len(closers)
