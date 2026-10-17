"""Per-user limiter for `GET /admin/audit` (contract #2392, "Limits").

At most `rate_per_minute` calls a minute and `max_concurrent` calls in flight per
user, across all of the user's sessions. Past either limit the caller answers
`429` with `Retry-After`. State is bounded (C-2.18): an LRU map of at most
`tracked_users` users, and per user at most `rate_per_minute` timestamps. The
clock is injected (monotonic seconds) so tests never sleep.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from candleviewer.settings import Settings

_WINDOW_S = 60.0


class AuditQueryRefused(Exception):
    """The per-user rate or concurrency limit was hit (→ `429`)."""

    def __init__(self, reason: str, retry_after_s: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_s = retry_after_s


@dataclass(slots=True)
class _UserState:
    stamps: deque[float] = field(default_factory=deque)
    inflight: int = 0


class AuditQueryLease:
    """One admitted call. `release()` is idempotent; call it in a `finally`."""

    def __init__(self, state: _UserState) -> None:
        self._state: _UserState | None = state

    def release(self) -> None:
        if self._state is not None:
            self._state.inflight -= 1
            self._state = None


class AuditQueryLimiter:
    def __init__(
        self,
        *,
        rate_per_minute: int = 60,
        max_concurrent: int = 2,
        tracked_users: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = rate_per_minute
        self._max_concurrent = max_concurrent
        self._cap = tracked_users
        self._clock = clock
        self._users: OrderedDict[str, _UserState] = OrderedDict()

    def __len__(self) -> int:
        return len(self._users)

    def acquire(self, user: str) -> AuditQueryLease:
        now = self._clock()
        state = self._users.pop(user, None) or _UserState()
        self._users[user] = state  # most recently used last
        self._evict()
        while state.stamps and now - state.stamps[0] >= _WINDOW_S:
            state.stamps.popleft()
        if state.inflight >= self._max_concurrent:
            raise AuditQueryRefused("concurrency", 1)
        if len(state.stamps) >= self._rate:
            wait = math.ceil(_WINDOW_S - (now - state.stamps[0]))
            raise AuditQueryRefused("rate", max(1, wait))
        state.stamps.append(now)
        state.inflight += 1
        return AuditQueryLease(state)

    def _evict(self) -> None:
        """Drop the least recently used idle users past the bound. A user with a call in
        flight is never dropped, so a lease can always be released against live state."""
        if len(self._users) <= self._cap:
            return
        for key in [k for k, s in self._users.items() if s.inflight == 0]:
            if len(self._users) <= self._cap:
                break
            del self._users[key]


_HOUR_S = 3600.0
#: The `audit_verify_rate_per_hour` default: verify runs a user may start in a rolling hour.
VERIFY_RATE_PER_HOUR: int = Settings.model_fields["audit_verify_rate_per_hour"].default


class AuditVerifyLimiter:
    """Per-user `POST /admin/audit/verify` runs in a rolling hour (#2446,
    `audit_verify_rate_per_hour`). Only a run that starts counts: the caller checks
    `retry_after` and calls `record_start` once the run's write-ahead record is written, so a
    `409`, a `429` or a `503` never counts. State is bounded (C-2.18): at most
    `tracked_users` users; one with no run in the hour is evicted first, and a new user that
    finds no room is refused rather than let through uncounted."""

    def __init__(
        self,
        *,
        rate_per_hour: int = VERIFY_RATE_PER_HOUR,
        tracked_users: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate, self._cap, self._clock = rate_per_hour, tracked_users, clock
        self._users: OrderedDict[str, deque[float]] = OrderedDict()

    def retry_after(self, user: str) -> int | None:
        """Seconds until `user` may start a run, or `None` when it may start one now."""
        now = self._clock()
        for window in self._users.values():
            while window and now - window[0] >= _HOUR_S:
                window.popleft()
        stamps = self._users.get(user)
        if stamps is None:
            idle = [k for k, s in self._users.items() if not s]
            for key in idle[: max(0, len(self._users) - self._cap + 1)]:
                del self._users[key]
            return None if len(self._users) < self._cap else 1
        if len(stamps) < self._rate:
            return None
        return max(1, math.ceil(stamps[0] + _HOUR_S - now))

    def record_start(self, user: str) -> None:
        stamps = self._users.pop(user, None) or deque()
        stamps.append(self._clock())
        self._users[user] = stamps  # most recently used last
