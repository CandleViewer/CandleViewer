"""The trade-group preview's per-user token bucket (E28-T05 S3b, #909; SR-E28-22, PF-D01).

22 `previewTradeGroup` is rate-limited per user rather than idempotency-keyed: a bucket whose rate
and burst are both `Settings.tradegroups_preview_rate_per_user_per_second` (1 to 100 a second).
`try_take` takes a token, or answers the `Retry-After` of the route's `429 rate_limited` in whole
seconds, never under one. The clock is injected (monotonic seconds), so tests never sleep. State
is bounded (C-2.18): one bucket per user and at most `TRACKED_USERS` of them, the least recently
used dropped first and full again if its user returns, as `SessionRateLimiter` keeps sessions.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable
from typing import Final
from uuid import UUID

#: The users whose buckets are kept (C-2.18).
TRACKED_USERS: Final = 1024


class PreviewLimiter:
    """A token bucket per user (module docstring)."""

    def __init__(self, rate_per_second: int, *, clock: Callable[[], float]) -> None:
        if rate_per_second < 1:
            raise ValueError("a preview rate is at least one a second")
        self._rate = float(rate_per_second)  # tokens a second, and the burst
        self._clock = clock
        self._buckets: OrderedDict[UUID, tuple[float, float]] = OrderedDict()

    def try_take(self, user: UUID) -> int | None:
        """None when `user` had a token, now taken; else the whole seconds until one is due."""
        now = self._clock()
        tokens, last = self._buckets.pop(user, (self._rate, now))
        tokens = min(self._rate, tokens + (now - last) * self._rate)
        taken = tokens >= 1.0
        self._buckets[user] = (tokens - 1.0 if taken else tokens, now)  # the most recent last
        while len(self._buckets) > TRACKED_USERS:
            self._buckets.popitem(last=False)
        return None if taken else math.ceil((1.0 - tokens) / self._rate)

    def __len__(self) -> int:
        return len(self._buckets)
