"""Scenario 7 - reconnect-storm guard (SR-039). C-13.6 #1.

200 induced disconnects inside 5 minutes (TCP resets plus refused dials).
Declared: the public lane of the adapter's connection budget (`ConnectionBudget`, 24 §14.2
rule 13), which the composition root gives the public stream, keeps dials under the lane's cap
in every sliding 300 s window - well under Bybit's 500/5 min/IP - and when the lane is spent
the B13 chart enters `budget_blocked` (feed `degraded`, never a tight loop). A burst of book
resubscribes that books the lane ahead never takes the opens the budget keeps for private
streams (CR-G8B-A-01). Exceeding a bound is an assertion failure, not a warning.
"""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.exchange.base.reconnect import (
    OPENS_LIMIT,
    PRIVATE_RESERVE,
    ws_conn_budget_refused_total,
)
from candleviewer.observability.context import spawn
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._rig import Rig, metric
from tests.chaos.ingestion._stub_exchange import EXCHANGE_CONN_LIMIT

pytestmark = pytest.mark.chaos

WINDOW_S = 300.0
DISCONNECTS = 200
PUBLIC_CAP = OPENS_LIMIT - PRIVATE_RESERVE


async def _storm(rig: Rig, *, disconnects: int, over_s: float) -> None:
    every = over_s / disconnects
    for i in range(disconnects):
        if i % 4 == 3:
            rig.ex.inject(Fault(FaultKind.REFUSE))  # a refused dial still counts
        rig.ex.inject(Fault(FaultKind.RESET))
        await rig.clock.advance(every)


async def test_s07_200_disconnects_in_5_min_stay_within_the_attempt_budget() -> None:
    budget = 120  # a deliberately tight public lane so the budget, not luck, bounds the dials
    rig = Rig(seed=7, conn_limit=budget + PRIVATE_RESERVE)
    await rig.start()
    try:
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        await _storm(rig, disconnects=DISCONNECTS, over_s=WINDOW_S)
        await rig.clock.advance(WINDOW_S)  # let any parked reconnects drain
        peak = rig.ex.conn_attempts_in_any_window(WINDOW_S)
        assert peak <= budget, f"{peak} dials in a 300 s window > budget {budget}"
        assert peak < EXCHANGE_CONN_LIMIT
        degraded = [f for f in rig.observe().feed if f.state == "degraded"]
        assert degraded, "budget exhaustion must be visible (feed degraded)"
    finally:
        await rig.stop()


async def test_s07_default_budget_stays_well_under_the_exchange_cap() -> None:
    """Production defaults (480 opens per 300 s, the public lane 420): the storm never
    approaches 500."""
    rig = Rig(seed=8)
    await rig.start()
    try:
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        await _storm(rig, disconnects=DISCONNECTS, over_s=WINDOW_S)
        peak = rig.ex.conn_attempts_in_any_window(WINDOW_S)
        assert peak < EXCHANGE_CONN_LIMIT
        assert peak <= PUBLIC_CAP
    finally:
        await rig.stop()


async def test_s07_a_resubscribe_burst_never_takes_the_private_reserve() -> None:
    """CR-G8B-A-01: 1,000 book resubscribes at once ask the public lane for more opens than two
    windows hold. The lane books them at most one window ahead and refuses the rest, counted,
    so the budget keeps two windows at most; an open counts only against the windows that hold
    it, so the private lane still has its 60 and a private dial goes at once."""
    rig = Rig(seed=9)
    await rig.start()
    burst: list[asyncio.Task[None]] = []
    try:
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        [socket] = rig.ex.live_sockets()
        topic = next(t for t in sorted(socket.topics) if t.startswith("orderbook."))
        held = len(rig.budget._opens)
        refused = metric(ws_conn_budget_refused_total, scope="public")
        burst = [spawn(rig.ws.resubscribe_topic(topic), name="chaos-resub") for _ in range(1_000)]
        await rig.clock.settle()
        booked = len(rig.budget._opens) - held
        turned_away = metric(ws_conn_budget_refused_total, scope="public") - refused
        assert booked + turned_away == 1_000 and turned_away > 0
        assert len(rig.budget._opens) <= 2 * PUBLIC_CAP < 2 * OPENS_LIMIT
        private = rig.budget.lane("private")
        assert private.remaining() == PRIVATE_RESERVE, "public bookings took the private reserve"
        assert private.reserve() == 0.0, "a private dial must go at once"
    finally:
        for task in burst:
            task.cancel()
        await asyncio.gather(*burst, return_exceptions=True)
        await rig.stop()
