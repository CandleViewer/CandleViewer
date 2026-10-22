"""Reconnect policy and the per-IP WebSocket connection budget (E08-T04; G-8b, #3963).

`ReconnectPolicy` is full-jitter exponential backoff (0.5 s to 30 s), moved here from
`ingestion/reconnect.py`, which re-exports it, so the private stream in the exchange adapter,
which may not import ingestion, backs off the same way (24 §14.2 rule 13).

`ConnectionBudget` is the one window of WebSocket opens every socket of the process draws on
(C-12.7, OM-D07; 24 §14.2 rule 13, G-8b ruling 5): at most `limit` opens in any `window_s` (the
venue allows 500 new connections per 5 minutes; 480 keeps headroom). Public opens stop
`private_reserve` short of it, so private streams can always reconnect; private opens may take
every slot; `testApiKey`'s key probe counts inside the window, at most `probe_cap` per window,
never in the private reserve, and never waits (SR-E27-05, KV-D01). A lane's `reserve()` never
refuses: it schedules the open and returns how long to wait for it, as `ConnectionRateGuard`
does. The venue counts per WebSocket domain; one window over every domain is the conservative
reading. The budget is per process, not per IP: two deployments behind one egress address
share the venue's count (OM-D07's residual). Pure bookkeeping on an injected monotonic clock.
"""

from __future__ import annotations

import bisect
import random
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Literal, Protocol

__all__ = ["BudgetLane", "ConnectionBudget", "ConnectionGuard", "ReconnectPolicy"]

type BudgetLane = Literal["public", "private"]

#: The venue's 500 new connections per 5 minutes, less headroom (24 §14.3 "Connections").
OPENS_LIMIT: Final = 480
WINDOW_S: Final = 300.0
#: Slots public opens leave for private ones (G-8b ruling 5).
PRIVATE_RESERVE: Final = 60
#: `testApiKey`'s key probes per window (SR-E27-05).
PROBE_CAP: Final = 10


class ReconnectPolicy:
    def __init__(
        self, *, base_s: float = 0.5, cap_s: float = 30.0, rng: random.Random | None = None
    ) -> None:
        self._base = base_s
        self._cap = cap_s
        self._rng = rng or random.Random()  # noqa: S311  (jitter, not crypto)

    def next_delay(self, attempt: int) -> float:
        ceiling = min(self._cap, self._base * (2 ** min(max(attempt, 0), 32)))
        return self._rng.uniform(0, ceiling)


class ConnectionGuard(Protocol):
    """What a connection lifecycle asks of its budget (B13's `connection_budget_exhausted`
    guard reads `remaining()`; `open_socket` waits out `reserve()`'s delay before it dials)."""

    def reserve(self) -> float:
        """Take one open slot; the delay in seconds before the open may be issued."""
        ...

    def remaining(self) -> int:
        """Opens this lane could make now without waiting."""
        ...


class _Lane:
    """One lane of a `ConnectionBudget`: a `ConnectionGuard` capped at `cap` opens a window."""

    __slots__ = ("_budget", "_cap")

    def __init__(self, budget: ConnectionBudget, cap: int) -> None:
        self._budget, self._cap = budget, cap

    def reserve(self) -> float:
        return self._budget._reserve(self._cap)

    def remaining(self) -> int:
        return self._budget._remaining(self._cap)


class ConnectionBudget:
    """One sliding window of WebSocket opens for public, private and probe sockets alike."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        limit: int = OPENS_LIMIT,
        window_s: float = WINDOW_S,
        private_reserve: int = PRIVATE_RESERVE,
        probe_cap: int = PROBE_CAP,
    ) -> None:
        if limit < 1 or not 0 <= private_reserve < limit:
            raise ValueError("a budget allows an open, and keeps a reserve smaller than its limit")
        if probe_cap < 1 or window_s <= 0:
            raise ValueError("the probe cap and the window must be positive")
        self._clock = clock
        self._limit = limit
        self._window = window_s
        self._public_cap = limit - private_reserve
        self._probe_cap = probe_cap
        #: Every open's time, sorted; one a lane scheduled ahead may lie in the future. Each is
        #: dropped once it can no longer share a window with a new open: what stays is the last
        #: window's opens and the ones its callers still wait for.
        self._opens: list[float] = []
        #: The probe's own opens in the window, oldest first; at most `probe_cap`.
        self._probes: deque[float] = deque()
        self._lanes: dict[BudgetLane, _Lane] = {
            "public": _Lane(self, self._public_cap),
            "private": _Lane(self, limit),
        }

    def lane(self, lane: BudgetLane) -> ConnectionGuard:
        """The `ConnectionGuard` of `lane`: `public` stops `private_reserve` short of the limit,
        `private` may take every slot. The same view each call."""
        return self._lanes[lane]

    def remaining(self, scope: Literal["public", "private", "probe"]) -> int:
        """Opens `scope` could make now without waiting."""
        if scope == "probe":
            left = self._remaining(self._public_cap)  # prunes the probes too
            return max(0, min(self._probe_cap - len(self._probes), left))
        return self._lanes[scope].remaining()

    def admit_probe(self) -> bool:
        """One probe open now, or `False` at once with nothing taken: never queued. Refused past
        `probe_cap` in the window, or when only the private reserve is left."""
        now = self._clock()
        self._prune(now)
        if len(self._probes) >= self._probe_cap or self._used() >= self._public_cap:
            return False
        bisect.insort(self._opens, now)
        self._probes.append(now)
        return True

    def _reserve(self, cap: int) -> float:
        """Schedule one open of a lane capped at `cap`: the earliest time at which, counting every
        open after it less one window (those scheduled ahead too), the lane stays within `cap`.
        Counting the scheduled ones keeps every window, earlier or later, within the limit."""
        now = self._clock()
        self._prune(now)
        start = now
        if len(self._opens) >= cap:
            start = max(now, self._opens[-cap] + self._window)
        bisect.insort(self._opens, start)
        return start - now

    def _remaining(self, cap: int) -> int:
        self._prune(self._clock())
        return max(0, cap - self._used())

    def _used(self) -> int:
        """Opens sharing a window with an open now: every one kept (`_prune` drops the rest)."""
        return len(self._opens)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        del self._opens[: bisect.bisect_right(self._opens, cutoff)]
        while self._probes and self._probes[0] <= cutoff:
            self._probes.popleft()


if TYPE_CHECKING:  # the lane views satisfy the protocol callers are checked against
    _GUARD: type[ConnectionGuard] = _Lane
