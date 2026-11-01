"""The SR-104 order budget and its circuit breaker (24 §11.7; E35-T10 slice 2f, BQ-6 to BQ-8).

`OrderBudget` counts, per rule, each order its actions hand to the OMS (one per OMS call per
resolved account, for the `counts_orders` types), checked and counted at check 7, before the
records written ahead: an order counts whatever the OMS then answers, and an order a check refuses
never counts. Two sliding windows, 60 s and 24 h, run on the wall clock. A rule's counts are
rebuilt at its first order action after a start, from the `action_start` events of its armed runs
(`BudgetRebuild`, ages on the database's clock); while that read fails or runs late, its order
actions are refused and the read runs again at its next one. Only a spent budget trips the breaker.

`CircuitBreaker.trip` stops the rule: its trip time, which blocks at dispatch any fire offered
before it, even after a re-arm; its waiting fires dropped from its lane; the page and the count;
B9 `KILL_SWITCH` through the manager; the drop again; and one `system_events` row. A move that
fails keeps the trip: the rule's order actions stay refused, and each sends the move again.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.rules.executor.gates import Halts
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.ports import AlertPort
from candleviewer.rules.executor.results import BlockedBy
from candleviewer.rules.limits import ORDER_BUDGET_DEFAULTS

#: The windows, in seconds: an order admitted at `t` is in the minute's while `now - t < MINUTE_S`.
MINUTE_S: Final = 60.0
DAY_S: Final = 86_400.0
#: The bound on a rule's rebuild read (BQ-7), a write ahead's.
REBUILD_TIMEOUT_S: Final = 2.0
#: The bound on the breaker's B9 move (`RulesManager.trip_breaker`).
TRIP_MOVE_TIMEOUT_S: Final = 2.0
#: What check 7 found for one order: counted, refused as spent (which trips the breaker), or
#: refused as not confirmed since a start (which never does).
Admission = Literal["ok", "spent", "unrebuilt"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BudgetRebuild(Protocol):
    """A rule's counted orders of the last 24 h, from the records written ahead (24 §11.7, BQ-7):
    the age in seconds, on the database's clock, of each counted `action_start` event of its armed
    runs, newest first, at most `limit`. `rules_oms_wiring` binds it over the rules repository."""

    async def order_ages(self, rule_id: str, *, limit: int) -> Sequence[float]: ...


class OrderBudget:
    """Each rule's admission times, in its two sliding windows (24 §11.7); `per_minute` and
    `per_day` are the deployment's, from its boot settings, held to `limits.ORDER_BUDGET_CAPS`."""

    def __init__(
        self,
        per_minute: int = ORDER_BUDGET_DEFAULTS["per_minute"],
        per_day: int = ORDER_BUDGET_DEFAULTS["per_day"],
        *,
        rebuild: BudgetRebuild | None = None,
    ) -> None:
        self.per_minute, self.per_day, self._rebuild = per_minute, per_day, rebuild
        self._times: dict[str, list[float]] = {}  # per rule rebuilt since the start

    async def admit(self, rule_id: str, now: float) -> Admission:
        """One order of `rule_id` at `now` (the wall clock): `ok`, counted; `spent` when a window
        already holds its limit (the eleventh in 60 s at the default, the 201st in 24 h), never
        counted; `unrebuilt` while its counts were not rebuilt since a start, never counted."""
        times = self._times.get(rule_id)
        if times is None:
            times = await self._rebuilt(rule_id, now)
            if times is None:
                return "unrebuilt"
        times[:] = [t for t in times if now - t < DAY_S]
        in_minute = sum(1 for t in times if now - t < MINUTE_S)
        if in_minute >= self.per_minute or len(times) >= self.per_day:
            return "spent"
        times.append(now)
        return "ok"

    async def _rebuilt(self, rule_id: str, now: float) -> list[float] | None:
        """The rule's admission times from its records, each event's age placed on this clock at
        `now`; `None` while unbound, or when the read fails or runs past `REBUILD_TIMEOUT_S`."""
        if self._rebuild is None:
            return None
        try:
            async with asyncio.timeout(REBUILD_TIMEOUT_S):
                ages = await self._rebuild.order_ages(rule_id, limit=self.per_day)
        except Exception as lost:  # never `CancelledError`, which is no `Exception`
            _log().warning("rules.budget_unrebuilt", rule_id=rule_id, error=type(lost).__name__)
            return None
        self._times[rule_id] = times = [now - float(age) for age in ages]
        return times


async def _unbound_move(_rule_id: str) -> bool:
    raise RuntimeError("the circuit breaker's move is not bound")


class CircuitBreaker:
    """The rule's breaker (24 §11.7; BQ-8), tripped by the first order its budget refuses as spent:
    `halts` keeps the trip time, `drop` takes a rule's waiting fires out of its lane (refused whole,
    `circuit_breaker`), `move` is `RulesManager.trip_breaker` (B9 `KILL_SWITCH`), and `alerts` pages
    and writes the `system_events` row. No count is reset: a re-arm keeps the rule's budget."""

    def __init__(
        self,
        halts: Halts,
        *,
        move: Callable[[str], Awaitable[bool]] | None = None,
        drop: Callable[[str, BlockedBy], None] | None = None,
        alerts: AlertPort | None = None,
        metrics: ExecutorMetrics | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._halts, self._move = halts, _unbound_move if move is None else move
        self._drop, self._alerts = drop, alerts
        self._metrics = ExecutorMetrics() if metrics is None else metrics
        self._clock = clock
        self._unmoved: set[str] = set()  # tripped, and their B9 move not landed yet

    def unmoved(self, rule_id: str) -> bool:
        """The rule tripped and its move has not landed: its order actions stay refused."""
        return rule_id in self._unmoved

    async def trip(self, rule_id: str, run_id: UUID, node_id: str) -> None:
        """Stop the rule, in this order: its trip time; its waiting fires dropped; the page and the
        count; B9 `KILL_SWITCH`, under its bound; the drop again, for fires offered during the
        move; and the `system_events` row saying whether the rule was moved."""
        self._halts.tripped[rule_id] = self._clock()
        self._dropped(rule_id)
        if self._alerts is not None:
            self._alerts.breaker_tripped(rule_id, run_id, node_id)
        self._metrics.tripped()
        moved = False
        try:
            async with asyncio.timeout(TRIP_MOVE_TIMEOUT_S):
                moved = await self._move(rule_id)
        except Exception as lost:  # never `CancelledError`, which is no `Exception`
            _log().error("rules.breaker_move_failed", rule_id=rule_id, error=type(lost).__name__)
        self._dropped(rule_id)
        if moved:
            self._unmoved.discard(rule_id)
        else:
            self._unmoved.add(rule_id)
        if self._alerts is not None:
            await self._alerts.breaker_moved(rule_id, run_id, node_id, moved=moved)

    def _dropped(self, rule_id: str) -> None:
        if self._drop is not None:
            self._drop(rule_id, "circuit_breaker")
