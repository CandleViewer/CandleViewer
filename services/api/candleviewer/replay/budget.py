"""`ReplayLoopBudget`: the share of the event loop replay may take (#2668 G1, C-2.17).

Replay shares the API process's event loop with order entry, the gateway and ingestion. Each
replay turn already yields after `ClockConfig.yield_slice_s` of work, so no single turn holds the
loop long; this budget caps what all replay turns *together* take. It is plain code on the hot
path, never a statechart (C-2.20), and it has no off value (C-4.14): the settings bound the share
to 0.05..0.75 and the burst to 5..250 ms.

**Bucket.** A token bucket in loop seconds: it refills lazily at `share` loop seconds per wall
second, capped at `burst_s`, and every lane's work is charged against it. A lane that breathes
while the bucket is in debt, or while other lanes wait, queues; waiters are admitted first in,
first out, each once the debt is paid, so N busy lanes split the share evenly and together never
take more than the share plus the burst and about one turn each.

**Lanes.** `budget.lane(key)` is one replay session's account (`key` names it). Its tasks call
`start()` whenever they resume, `charge()` before a natural wait and `await breathe()` where they
used to yield. `breathe` charges, then yields once if the bucket is not in debt and nobody
waits, else holds the lane in the queue until it is admitted, and returns the seconds held. A
hold waits through the injected `MonotonicTime` (`LoopTime` in production); setting `wake` ends it
early (a pause), and a cancelled hold leaves the queue on the way out, so the next waiter is
admitted on time. One lane may serve several tasks of a session: since only one task runs at a
time, charging since the last `start()` or `charge()` of any of them never double counts.

**Wall time, not thread time.** Work is measured with `measure` (`time.perf_counter`), not
`time.thread_time`: garbage collection, page faults and syscalls inside a turn hold the loop
just as much as Python code does, and thread time would not see them. A turn that suspends
inside a sink without charging first is charged the suspension too. That overcharge only makes
replay yield more, which is the safe direction for the loop's other work; one charge adds at most
`MAX_CHARGE_S` of debt, so one long suspension cannot hold every session for long.

**Metrics** (served by `replay.metrics`): `replay_loop_seconds_total` is the loop time charged to
replay, `replay_budget_held_seconds_total` the wall time lanes were held, and
`replay_budget_waiters` the lanes waiting now.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from time import perf_counter
from typing import Final

from candleviewer.observability.metrics import Counter, Gauge
from candleviewer.replay.errors import ReplayConfigInvalid
from candleviewer.replay.playback import MonotonicTime

#: Bounds of the share and the burst; `settings.py` (M1, which may not import this module)
#: repeats them on `CV_REPLAY_LOOP_SHARE` and `CV_REPLAY_LOOP_BURST_MS`.
MIN_SHARE: Final = 0.05
MAX_SHARE: Final = 0.75
MIN_BURST_S: Final = 0.005
MAX_BURST_S: Final = 0.25
#: The most one charge adds to the debt. Real loop work between two breathes is a few ms (the
#: clock yields after `yield_slice_s`); a charge past this is a suspension inside a sink, or a
#: whole-loop pause that already cost every task. Charging it in full would hold every replay
#: session (the bucket is process-wide) for charge / share; capped, the hold is at most
#: MAX_CHARGE_S / share (1 s at the default share). The full charge still reaches
#: `replay_loop_seconds_total`, so the overrun stays visible.
MAX_CHARGE_S: Final = 0.25
#: Debt below this counts as paid, so float rounding never schedules a needless hold.
_EPS: Final = 1e-9

replay_loop_seconds_total = Counter(
    "replay_loop_seconds_total", "Event-loop wall time charged to replay lanes."
)
replay_budget_held_seconds_total = Counter(
    "replay_budget_held_seconds_total", "Wall time replay lanes were held by the loop budget."
)
replay_budget_waiters = Gauge(
    "replay_budget_waiters", "Replay lanes waiting for the loop budget now."
)


class ReplayLoopBudget:
    """One per process: the token bucket every replay lane charges (see the module docstring)."""

    def __init__(
        self,
        share: float,
        burst_s: float,
        time: MonotonicTime,
        measure: Callable[[], float] = perf_counter,
    ) -> None:
        if not MIN_SHARE <= share <= MAX_SHARE:  # also refuses NaN
            raise ReplayConfigInvalid(f"the replay loop share must be {MIN_SHARE}..{MAX_SHARE}")
        if not MIN_BURST_S <= burst_s <= MAX_BURST_S:
            raise ReplayConfigInvalid(
                f"the replay loop burst must be {MIN_BURST_S}..{MAX_BURST_S} s"
            )
        self._share, self._burst = float(share), float(burst_s)
        self._time, self._measure = time, measure
        self._tokens = self._burst
        self._stamp: float | None = None  # taken on the first refill: no running loop needed here
        self._waiters: deque[object] = deque()
        self._never = asyncio.Event()  # a hold's wake when the caller passes none

    @property
    def share(self) -> float:
        return self._share

    @property
    def burst_s(self) -> float:
        return self._burst

    def lane(self, key: str) -> BudgetLane:
        """A new lane named `key` (one per replay session)."""
        return BudgetLane(self, key)

    def _refill(self) -> None:
        now = self._time.now()
        elapsed = 0.0 if self._stamp is None else now - self._stamp
        if elapsed > 0.0:
            self._tokens = min(self._burst, self._tokens + elapsed * self._share)
        self._stamp = now

    def _charge(self, seconds: float) -> None:
        self._refill()
        self._tokens -= min(seconds, MAX_CHARGE_S)
        replay_loop_seconds_total.inc(seconds)

    def _free(self) -> bool:
        """Whether a lane may run on without queueing: no debt and nobody waiting."""
        self._refill()
        return not self._waiters and self._tokens >= -_EPS

    async def _hold(self, wake: asyncio.Event | None) -> float:
        """Queue, then wait until first in line with the debt paid, or until `wake` is set."""
        time, ticket = self._time, object()
        signal = wake if wake is not None else self._never
        self._waiters.append(ticket)
        replay_budget_waiters.inc()
        began, waited = time.now(), False
        try:
            while not signal.is_set():
                self._refill()
                debt = -self._tokens
                if debt > _EPS:  # every waiter, first or not, sleeps until the debt is paid
                    waited = True
                    await time.wait_until(time.now() + debt / self._share, signal)
                elif self._waiters[0] is ticket:
                    break
                else:  # paid, and the waiter ahead is about to run: let it
                    waited = True
                    await asyncio.sleep(0)
        finally:
            self._waiters.remove(ticket)
            replay_budget_waiters.dec()
            held = max(time.now() - began, 0.0)
            replay_budget_held_seconds_total.inc(held)
        if not waited:  # a wake set already (or a debt just paid): still one yield (C-2.17)
            await asyncio.sleep(0)
        return held


class BudgetLane:
    """One replay session's account with the budget: `start()`, `charge()`, `breathe()`."""

    __slots__ = ("_budget", "_key", "_mark")

    def __init__(self, budget: ReplayLoopBudget, key: str) -> None:
        self._budget, self._key = budget, key
        self._mark: float | None = None

    @property
    def key(self) -> str:
        return self._key

    def start(self) -> None:
        """The lane's task resumed: its loop time counts from now."""
        self._mark = self._budget._measure()

    def charge(self) -> float:
        """Charge the loop time since the last `start()` or `charge()`; returns it (seconds). The
        lane stays started, so a second charge in a row charges nothing."""
        now = self._budget._measure()
        mark, self._mark = self._mark, now
        spent = 0.0 if mark is None else max(now - mark, 0.0)
        if spent > 0.0:
            self._budget._charge(spent)
        return spent

    async def breathe(self, wake: asyncio.Event | None = None) -> float:
        """Charge, then yield once, or hold while the budget is in debt or others wait. Returns
        the seconds held (0.0 for a plain yield); `wake` ends a hold early. Every call suspends at
        least once, even with `wake` already set. The lane is started again on return, so neither
        the yield nor the hold is charged to it."""
        budget = self._budget
        self.charge()
        try:
            if budget._free():
                await asyncio.sleep(0)
                return 0.0
            return await budget._hold(wake)
        finally:
            self.start()
