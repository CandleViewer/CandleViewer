"""C-13.6 #4 and #7 (E29-Q04 #1148, "A lost acknowledgement never duplicates"; E29-T04's S1 path,
E29-T06's pass): the venue takes the create and its answer is lost (the `place` door: a post-send
timeout, 24 Sec.8.6 "Order creates"). The order waits `unknown` (S1, INV-B1-e), nothing is sent
again, and the account's next periodic pass, within one 30 s cycle, binds it by the full match to
the venue's truth: the order resting (24 Sec.8.5 step 3a), or filled meanwhile with its fill
withheld from the stream (step 3b, its fill and its position with the native stop adopted). The
venue counted one create, and the oracle finds the book equal to the venue. On virtual time, the
venue derived in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

from uuid import UUID

import pytest

from candleviewer.oms.reconcile_job import INTERVAL_S
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import CORRECTIONS, PRICE, UNKNOWN, World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos


async def lost_ack(world: World, *, filled: bool) -> UUID:
    """The scenario's faults: the create lands and its answer is lost, so the request is
    answered 202 `unknown`; with `filled`, the venue then fills all of it, its push withheld.
    Answers the order's id."""
    world.exchange.lose_ack()
    outcome = await world.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "unknown") and outcome.order_id
    if filled:
        row = await world.row(outcome.order_id)
        await world.exchange.fill(row.order_link_id, row.qty, PRICE, push=False)
    return outcome.order_id


@pytest.mark.parametrize(
    ("filled", "listed"), [(False, "corrected"), (True, "resolved_from_history")],
    ids=["resting", "filled"],
)  # fmt: skip
@virtual
async def test_s5_a_lost_ack_is_resolved_by_the_next_pass_and_never_sent_again(
    filled: bool, listed: str
) -> None:
    async with opened() as world:
        order_id = await lost_ack(world, filled=filled)
        row = await world.row(order_id)
        assert (row.lifecycle_state, row.exchange_order_id) == ("unknown", None)
        assert world.sample(UNKNOWN) == 1
        assert world.exchange.creates() == {row.order_link_id: 1}
        corrections = world.sample(CORRECTIONS, kind=listed)

        async def resolved() -> bool:
            return (await world.row(order_id)).lifecycle_state != "unknown"

        took = await world.until(resolved, within_s=2 * INTERVAL_S)
        print(f"s5 ({listed}): unknown resolved in {took:.1f} s of virtual time")  # -rA shows it
        assert took <= INTERVAL_S  # within one reconciliation cycle (#1148, Performance notes)
        venue = await world.exchange.order(row.order_link_id)
        row = await world.row(order_id)
        state = "filled" if filled else "submitted"
        assert (row.lifecycle_state, row.exchange_order_id) == (state, venue.exchange_order_id)
        assert world.sample(UNKNOWN) == 0
        assert world.sample(CORRECTIONS, kind=listed) == corrections + 1
        assert world.exchange.creates() == {row.order_link_id: 1}  # sent once, never again
        await check(world)
