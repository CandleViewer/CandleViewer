"""The `/drawings` per-user write bucket (#2727, SR-E14-05; E14 threat model DR33, RR4).

Every `createDrawing`, `updateDrawing`, `deleteDrawing` and `batchUpsertDrawings` call takes one
token from its caller's bucket of `WRITE_BURST`, refilled at `WRITES_PER_MINUTE` a minute, in the
token-bucket style of `ws/limits.py`'s frame bucket. A call that finds no token is answered
`429 rate_limited` with `Retry-After` in whole seconds, never under one. The clock is injected
(monotonic seconds), so tests never sleep. State is bounded (C-2.18): at most `TRACKED_USERS`
buckets, the least recently used dropped first and full again if its user returns.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Final

WRITES_PER_MINUTE: Final = 60
WRITE_BURST: Final = 20
#: The users whose buckets are kept (C-2.18).
TRACKED_USERS: Final = 1024


class DrawingsWriteLimiter:
    """A token bucket per user (module docstring)."""

    def __init__(
        self,
        *,
        per_minute: int = WRITES_PER_MINUTE,
        burst: int = WRITE_BURST,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute < 1 or burst < 1:
            raise ValueError("a write bucket refills at least once a minute and holds a token")
        self._rate = per_minute / 60.0  # tokens a second
        self._burst = float(burst)
        self._clock = clock
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def try_take(self, user: str) -> int | None:
        """None when `user` had a token, now taken; else the whole seconds until one is due."""
        now = self._clock()
        tokens, last = self._buckets.pop(user, (self._burst, now))
        tokens = min(self._burst, tokens + max(0.0, now - last) * self._rate)
        taken = tokens >= 1.0
        self._buckets[user] = (tokens - 1.0 if taken else tokens, now)  # the most recent last
        while len(self._buckets) > TRACKED_USERS:
            self._buckets.popitem(last=False)
        return None if taken else max(1, math.ceil((1.0 - tokens) / self._rate))

    def __len__(self) -> int:
        return len(self._buckets)


__all__ = ["TRACKED_USERS", "WRITES_PER_MINUTE", "WRITE_BURST", "DrawingsWriteLimiter"]
