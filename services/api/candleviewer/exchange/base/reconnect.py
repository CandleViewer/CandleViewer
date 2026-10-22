"""Reconnect policy and the per-IP WebSocket connection budget (E08-T04; G-8b, #3963).

`ReconnectPolicy` is full-jitter exponential backoff (0.5 s to 30 s), moved here from
`ingestion/reconnect.py`, which re-exports it, so the private stream in the exchange adapter,
which may not import ingestion, backs off the same way (24 §14.2 rule 13).

`ConnectionBudget` is the one window of WebSocket opens every socket of the process draws on
(C-12.7, OM-D07; 24 §14.2 rule 13, G-8b ruling 5): at most `limit` opens in any `window_s` (the
venue allows 500 new connections per 5 minutes; 480 keeps headroom). Public opens stop
`private_reserve` short of it, so private streams can always reconnect; private opens may take
every slot; `testApiKey`'s key probe counts inside the window, at most `probe_cap` per window,
never in the private reserve, and never waits (SR-E27-05, KV-D01). An open counts only against
the windows that hold it, so one a lane booked ahead never takes a slot from an open now. A
lane's `reserve()` books the earliest slot at most one window ahead and returns how long to wait
for it; an open no such slot admits is refused (`RateBudgetExceededError`, nothing booked), so
the budget holds at most two windows of opens (C-2.18). The venue counts per WebSocket domain;
one window over every domain is the conservative reading. The budget is per process, not per
IP: two deployments behind one egress address share the venue's count (OM-D07's residual). Pure
bookkeeping on an injected monotonic clock.
"""

from __future__ import annotations

import bisect
import random
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Literal, Protocol

from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.observability.metrics import Counter, Gauge

__all__ = [
    "BudgetLane",
    "ConnectionBudget",
    "ConnectionGuard",
    "ReconnectPolicy",
    "ws_conn_budget_refused_total",
    "ws_conn_budget_remaining",
]

type BudgetLane = Literal["public", "private"]

#: The venue's 500 new connections per 5 minutes, less headroom (24 §14.3 "Connections").
OPENS_LIMIT: Final = 480
WINDOW_S: Final = 300.0
#: Slots public opens leave for private ones (G-8b ruling 5).
PRIVATE_RESERVE: Final = 60
#: `testApiKey`'s key probes per window (SR-E27-05).
PROBE_CAP: Final = 10

# Declared in the ingestion registry (`owner="exchange.base"`), built here: M3 may not import it.
ws_conn_budget_remaining = Gauge(
    "ws_conn_budget_remaining",
    "WebSocket opens a connection-budget scope could make now (public, private, probe).",
    ["scope"],
)

ws_conn_budget_refused_total = Counter(
    "ws_conn_budget_refused_total",
    "WebSocket opens the connection budget refused, by scope (a lane: no slot within one window; "
    "probe; streams: the cap).",
    ["scope"],
)


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
        """Take one open slot; the delay in seconds before the open may be issued. Raises
        `RateBudgetExceededError`, with nothing taken, when no slot within one window is free."""
        ...

    def remaining(self) -> int:
        """Opens this lane could make now without waiting."""
        ...


class _Lane:
    """One lane of a `ConnectionBudget`: a `ConnectionGuard` capped at `cap` opens a window."""

    __slots__ = ("_budget", "_cap", "_name")

    def __init__(self, budget: ConnectionBudget, cap: int, name: BudgetLane) -> None:
        self._budget, self._cap, self._name = budget, cap, name

    def reserve(self) -> float:
        return self._budget._reserve(self._cap, self._name)

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
        #: Every open's time, sorted; one a lane booked ahead lies at most one window ahead
        #: (`_slot`). `_prune` drops an open once no window holding a new one can hold it, so
        #: those kept lie within one window either side of now, and as no window holds more
        #: than `limit`, at most `2 * limit` are kept (C-2.18).
        self._opens: list[float] = []
        #: When each kept open leaves the window (its time plus `window_s`, in `_opens`' order).
        #: Every window edge is reckoned from this one sum, so a slot found where an open leaves
        #: never counts that open, whatever the float rounding.
        self._leaves: list[float] = []
        #: The probe's own opens in the window, oldest first; at most `probe_cap`.
        self._probes: deque[float] = deque()
        self._lanes: dict[BudgetLane, _Lane] = {
            "public": _Lane(self, self._public_cap, "public"),
            "private": _Lane(self, limit, "private"),
        }

    def lane(self, lane: BudgetLane) -> ConnectionGuard:
        """The `ConnectionGuard` of `lane`: `public` stops `private_reserve` short of the limit,
        `private` may take every slot. The same view each call."""
        return self._lanes[lane]

    def remaining(self, scope: Literal["public", "private", "probe"]) -> int:
        """Opens `scope` could make now without waiting."""
        if scope == "probe":
            return self._probes_left(self._read())
        return self._lanes[scope].remaining()

    def admit_probe(self) -> bool:
        """One probe open now, or `False` at once with nothing taken: never queued. Refused past
        `probe_cap` in the window, or when only the private reserve is left."""
        now = self._clock()
        self._prune(now)
        load = self._load(now)
        if len(self._probes) >= self._probe_cap or load >= self._public_cap:
            ws_conn_budget_refused_total.labels(scope="probe").inc()
            self._publish(load)
            return False
        self._book(now)
        self._probes.append(now)
        self._publish(load + 1)  # every window holding now holds this open too
        return True

    def _reserve(self, cap: int, lane: BudgetLane) -> float:
        """Book one open of `lane`, capped at `cap`, at its earliest slot (`_slot`) and return
        how long to wait for it; with no slot within one window, refuse with nothing booked,
        counted under the lane. A slot is booked when scheduled, so an open cancelled while it
        waits (a KILL, a SHUTDOWN) keeps it for one window: under-used, never exceeded."""
        now = self._clock()
        self._prune(now)
        start = self._slot(cap, now)
        if start is None:
            ws_conn_budget_refused_total.labels(scope=lane).inc()
            raise RateBudgetExceededError(
                "no WebSocket open is free within one window; nothing was booked"
            )
        self._book(start)
        self._publish(self._load(now))
        return start - now

    def _book(self, at: float) -> None:
        i = bisect.bisect_right(self._opens, at)
        self._opens.insert(i, at)
        self._leaves.insert(i, at + self._window)  # sorted too: the sum keeps the order

    def _remaining(self, cap: int) -> int:
        return max(0, cap - self._read())

    def _read(self) -> int:
        """The load now (`_load`), the gauges refreshed with it."""
        now = self._clock()
        self._prune(now)
        load = self._load(now)
        self._publish(load)
        return load

    def _slot(self, cap: int, now: float) -> float | None:
        """The earliest time from `now` to one window ahead at which one more open leaves every
        window that holds it within `cap`, else `None`. Only `now` and the times kept opens leave
        the window can be it: past any other time, the windows holding a later one hold no fewer
        opens. When the window ending one window ahead is full, every later time lies in it and
        only `now` can be; else each kept open's count enters a falling deque once (O(n log n))."""
        opens, window, held = self._opens, self._window, self._held
        if held(now + window) >= cap:  # every later time, to one window ahead, lies in it
            return now if self._fits(now, cap) else None
        ahead: deque[tuple[int, int]] = deque()  # (index, held) of opens in range, held falling
        nxt = 0
        last: float | None = None
        for start in (now, *self._leaves[: bisect.bisect_right(opens, now)]):
            if start == last:
                continue
            last = start
            lo = bisect.bisect_right(opens, start)  # the opens after `start` ...
            hi = bisect.bisect_left(opens, start + window)  # ... less than a window after it
            for i in range(max(nxt, lo), hi):
                count = held(opens[i])
                while ahead and ahead[-1][1] <= count:
                    ahead.pop()
                ahead.append((i, count))
            nxt = max(nxt, hi)
            while ahead and ahead[0][0] < lo:
                ahead.popleft()
            if max(held(start), ahead[0][1] if ahead else 0) < cap:
                return start
        return None

    def _fits(self, at: float, cap: int) -> bool:
        """Whether `_load(at) < cap`, stopping at the first full window, the latest first (where
        opens booked ahead gather)."""
        opens, held = self._opens, self._held
        lo = bisect.bisect_right(opens, at)
        hi = bisect.bisect_left(opens, at + self._window)
        return held(at) < cap and all(held(opens[i]) < cap for i in range(hi - 1, lo - 1, -1))

    def _load(self, at: float) -> int:
        """The most opens any window holding `at` holds: the window ending at `at`, or at a kept
        open less than one window after it (a window's count rises only where an open lies)."""
        opens = self._opens
        lo = bisect.bisect_right(opens, at)
        hi = bisect.bisect_left(opens, at + self._window)
        return max([self._held(at), *map(self._held, opens[lo:hi])])

    def _held(self, end: float) -> int:
        """The opens in the window that ends at `end`: made by then, and not yet left."""
        return bisect.bisect_right(self._opens, end) - bisect.bisect_right(self._leaves, end)

    def _probes_left(self, load: int) -> int:
        return max(0, min(self._probe_cap - len(self._probes), self._public_cap - load))

    def _publish(self, load: int) -> None:
        """`ws_conn_budget_remaining{scope}`, `load` being the most opens a window holding now
        holds: refreshed on every open and every reading of `remaining`."""
        ws_conn_budget_remaining.labels(scope="public").set(max(0, self._public_cap - load))
        ws_conn_budget_remaining.labels(scope="private").set(max(0, self._limit - load))
        ws_conn_budget_remaining.labels(scope="probe").set(self._probes_left(load))

    def _prune(self, now: float) -> None:
        gone = bisect.bisect_right(self._leaves, now)  # the opens that have left the window
        del self._opens[:gone], self._leaves[:gone]
        while self._probes and self._probes[0] + self._window <= now:
            self._probes.popleft()


if TYPE_CHECKING:  # the lane views satisfy the protocol callers are checked against
    _GUARD: type[ConnectionGuard] = _Lane
