"""C-13.6 #2, E29-Q04's half (#1148; E29-T06's pass, 24 Sec.8.5 "on every private-WS reconnect";
03 Sec.9.1's sequence, asserted under this name): the private stream killed while an order is
open and part filled; during the outage the venue fills the rest, its pushes lost with the
socket. The new socket's resync asks a pass, which reads the venue over REST, applies the gap's
fill to the bound row and corrects the position, so the book is usable again within 5 s of the
reconnect (#1148's Performance notes, C-14.2). 03 Sec.9.1's assertions: no order is created twice
for any id seen before or after the gap, the position keeps its native stop (step 5 and the
oracle), and every fill of the gap window is in the book. The UI half (the account shown
resyncing, never stale as live) is E29-S07's server notices, slice 4's. The periodic pass inside
the outage runs before the gap's fill, so the reconnect's pass is the one that corrects it. On
virtual time, the venue derived in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest

from candleviewer.oms.reconcile_job import INTERVAL_S
from tests.chaos.oms._oracle import check, compare
from tests.chaos.oms._world import PRICE, World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos

#: The outage: the socket lost, and the new one's resync this long after, inside the consumer's
#: 30 s silence bound (`STREAM_SILENCE_S`), as the adapter's own reconnect delivers it.
OUTAGE_S = INTERVAL_S - 0.5
BEFORE, GAP = Decimal("0.004"), Decimal("0.006")


async def at(world: World, t: float) -> None:
    """On to `t` on the loop's clock."""
    await world.elapse(max(0.0, t - asyncio.get_running_loop().time()))


async def gap(world: World) -> UUID:
    """The scenario's faults, from the world's opening (`t0`, after the job's start): an order
    submitted and part filled, pushed; the socket lost at `t0 + 1`; the rest filled once the
    job's periodic pass at its start + 30 s has run, its pushes lost; the new socket's resync at
    `t0 + 1 + OUTAGE_S`, before the next. Answers the order's id."""
    t0 = asyncio.get_running_loop().time()
    outcome = await world.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
    link = (await world.row(outcome.order_id)).order_link_id
    await world.exchange.fill(link, BEFORE, PRICE, push=True)
    await at(world, t0 + 1)
    world.exchange.status("down", "socket_closed", 1)
    await at(world, t0 + INTERVAL_S + 0.25)
    await world.exchange.fill(link, GAP, PRICE, push=False)
    await at(world, t0 + 1 + OUTAGE_S)
    row = await world.row(outcome.order_id)
    assert (row.lifecycle_state, row.cum_exec_qty) == ("partially_filled", BEFORE)  # stale
    world.exchange.status("resyncing", "reconnected", 2)
    return outcome.order_id


@virtual
async def test_s7_a_kill_with_fills_in_the_gap_is_corrected_by_the_reconnects_pass() -> None:
    async with opened(streamed=True) as world:
        order_id = await gap(world)
        loop = asyncio.get_running_loop()
        began = loop.time()

        async def usable() -> bool:
            return not compare(await world.book(), await world.truth())

        await world.settle()
        took = loop.time() - began + await world.until(usable, within_s=5.0)
        print(f"s7: the book usable {took:.1f} s after the reconnect, of virtual time")  # -rA
        assert took <= 5.0  # #1148's figure, C-14.2's reconnect recovery
        row = await world.row(order_id)
        assert (row.lifecycle_state, row.cum_exec_qty) == ("filled", BEFORE + GAP)
        resynced = [r for r in world.reports() if r["trigger"] == "reconnect"]
        assert [r["corrected"] for r in resynced] == [[row.order_link_id]]  # the reconnect's pass
        assert world.exchange.creates() == {row.order_link_id: 1}  # never created twice
        await check(world)  # the gap's fills, the position and its native stop
