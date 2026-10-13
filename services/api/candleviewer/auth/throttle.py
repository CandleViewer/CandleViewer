"""Per-IP login throttle (E09-S01 "Technical notes": "Rate limiting uses a
token bucket keyed on both user_id and source address").

The per-user side of throttling is `users.failed_login_count`/`locked_until`
(persisted, survives a restart — see `LoginService`); this module is the
*independent* per-IP counter so "one attacker cannot lock every account"
(ticket "Scope / Deliverables"). In-process only (single-process deployment,
`20-architecture.md` C4) — a restart clears it, which is acceptable because
the per-account lockout persists across restarts regardless.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

Clock = Callable[[], float]


class PerIpLoginThrottle:
    """Sliding-window counter: more than `max_attempts` failures from one
    source IP within `window_s` seconds are refused, independent of which
    usernames were tried."""

    def __init__(
        self,
        *,
        max_attempts: int = 20,
        window_s: float = 60.0,
        clock: Clock = time.monotonic,
        max_tracked_ips: int = 10_000,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_s = window_s
        self._clock = clock
        self._max_tracked_ips = max_tracked_ips
        self._attempts: dict[str, deque[float]] = {}

    def is_blocked(self, source_ip: str) -> bool:
        self._evict(source_ip)
        return len(self._attempts.get(source_ip, ())) >= self._max_attempts

    def record_failure(self, source_ip: str) -> None:
        self._evict(source_ip)
        if source_ip not in self._attempts and len(self._attempts) >= self._max_tracked_ips:
            # Bounded map (C-2.18 "every queue/collection is bounded"): a
            # single-process, in-memory dict keyed on attacker-controlled
            # source IPs is otherwise an unbounded-memory DoS vector. Drop
            # the oldest-first tracked IP (its window has already had the
            # most time to empty naturally) rather than let the dict grow
            # without limit.
            oldest_ip = next(iter(self._attempts))
            del self._attempts[oldest_ip]
        self._attempts.setdefault(source_ip, deque()).append(self._clock())

    def retry_after_s(self, source_ip: str) -> int:
        """Whole seconds until the oldest counted attempt leaves the window
        (the `Retry-After` value for a blocked key); 0 when not blocked."""
        if not self.is_blocked(source_ip):
            return 0
        oldest = self._attempts[source_ip][0]
        return max(1, math.ceil(oldest + self._window_s - self._clock()))

    def _evict(self, source_ip: str) -> None:
        bucket = self._attempts.get(source_ip)
        if bucket is None:
            return
        cutoff = self._clock() - self._window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if not bucket:
            del self._attempts[source_ip]  # an emptied window frees its slot (#2238)
