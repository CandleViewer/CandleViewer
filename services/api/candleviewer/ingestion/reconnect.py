"""Reconnect policy + connection-rate guard (E08-T04).

Full-jitter exponential backoff (0.5 s -> 30 s) and a sliding-window guard that
keeps connection opens below the per-IP limit (500 / 5 min; default headroom 480).
`ReconnectPolicy` lives in `exchange.base.reconnect` (G-8b, #3963), beside the adapter's
one `ConnectionBudget`, whose public lane the composition root gives the public stream; it is
re-exported here for ingestion's callers. The guard is a unit-test double now (its docstring).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from candleviewer.exchange.base.reconnect import ReconnectPolicy

__all__ = ["ConnectionRateGuard", "ReconnectPolicy"]


class ConnectionRateGuard:
    """Schedules opens so no window of `window_s` holds `>= limit` opens.

    No production caller since G-8b (#3963): the composition root gives the public stream the
    public lane of the adapter's `ConnectionBudget` (24 §14.2 rule 13), and the chaos rig and
    the E08-X02 suite draw on that lane too. It stays only as the guard seven unit-test modules
    under `tests/unit/ingestion/` build for `ConnectionManager`, which G-8b's write set leaves
    alone; moving them to the lane lets it go."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        limit: int = 480,
        window_s: float = 300.0,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self._clock = clock
        self._limit = limit
        self._window = window_s
        self._opens: deque[float] = deque()

    def reserve(self) -> float:
        """Reserve one open slot; returns the delay (s) before it may be issued."""
        now = self._clock()
        start = now
        if len(self._opens) >= self._limit:
            start = max(now, self._opens[-self._limit] + self._window)
        self._opens.append(start)
        while len(self._opens) > self._limit:
            self._opens.popleft()
        return start - now

    def remaining(self) -> int:
        now = self._clock()
        used = sum(1 for t in self._opens if now - self._window < t <= now + self._window)
        return max(0, self._limit - used)
