"""C-13.6 #4, its nearest row (E29-Q04 #1148; E29-T04's S1 path, E29-T06's pass; 24 Sec.8.5 step
3b, 28 B1's `second_consecutive_miss`): the create times out after it left, and the venue never
took it (the `place` door). The order waits `unknown`; the first periodic pass finds it nowhere,
open or in history, and records the miss; the second, one cycle later, rejects it with
`UNRESOLVED_AFTER_RECONCILE`, counted `abandoned`. One create reached the venue, which holds
nothing, and the oracle finds the book equal to the venue. On virtual time, the venue derived
in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

from uuid import UUID

import pytest

from candleviewer.oms.reconcile_job import INTERVAL_S, JITTER_S
from candleviewer.statechart.bindings.b01_order import UNRESOLVED_AFTER_RECONCILE
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import ACCOUNT, CORRECTIONS, UNKNOWN, World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos


async def never_landed(world: World) -> UUID:
    """The scenario's fault: the create leaves and never lands, so the request is answered 202
    `unknown`. Answers the order's id."""
    world.exchange.time_out()
    outcome = await world.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "unknown") and outcome.order_id
    return outcome.order_id


async def misses(world: World, order_id: UUID) -> int:
    """The order's `reconcile_diff` steps: each pass that found it nowhere."""
    events = await world.store.list_for_order(ACCOUNT, order_id)
    return sum(1 for event in events if event.kind == "reconcile_diff")


@virtual
async def test_s6_two_passes_that_find_nothing_reject_it_unresolved_after_reconcile() -> None:
    async with opened() as world:
        order_id = await never_landed(world)
        assert (await world.row(order_id)).lifecycle_state == "unknown"
        assert world.sample(UNKNOWN) == 1
        abandoned = world.sample(CORRECTIONS, kind="abandoned")
        await world.elapse(INTERVAL_S)  # the first pass: one miss, the order kept
        row = await world.row(order_id)
        assert (row.lifecycle_state, row.reject_code, await misses(world, order_id)) == (
            "unknown", None, 1,
        )  # fmt: skip

        async def rejected() -> bool:  # by the second pass, with no finding between the two
            return (await world.row(order_id)).lifecycle_state == "rejected"

        took = INTERVAL_S + await world.until(rejected, within_s=INTERVAL_S + JITTER_S)
        print(f"s6: rejected {took:.1f} s after the timeout, of virtual time")  # -rA shows it
        assert took <= 2 * INTERVAL_S  # within two reconciliation cycles
        row = await world.row(order_id)
        assert (row.reject_code, await misses(world, order_id)) == (UNRESOLVED_AFTER_RECONCILE, 2)
        assert world.sample(UNKNOWN) == 0
        assert world.sample(CORRECTIONS, kind="abandoned") == abandoned + 1
        assert world.exchange.creates() == {row.order_link_id: 1}
        await check(world)
