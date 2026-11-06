"""C-13.6 #7, its duplicate-ack half (E29-Q04 #1148; E29-T04's resumed create, SR-E29-15 and 24
Sec.8.3 rules 3 and 6; E29-T05's s2 is the redelivered fills'). A restart finds an order
`submitting` whose create the venue already holds (the process went down after the send), its
create a request this process did not begin. The restart's sweep resumes it: the id is
looked up first, whatever else, and the order found is bound by the full match, audited
`adopted_after_lookup`, nothing sent again: the venue counted one create. Were the lookup skipped,
the re-send would meet the venue's refusal of a reused id, and the lookup and full match after it
would still bind the one order, but the venue would count two creates, which the oracle fails
(`test_teeth`). The restart is in process, the store and the venue handed over as they stood
(the SIGKILL leg is slice 3's s14). And an acknowledgement row maps to no B1 event (24
Sec.8.12): its redelivery, the order's `new` row twice, is read and changes nothing. On virtual
time, the venue derived in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import NoReturn

import pytest

from candleviewer.oms.commands import place_request
from candleviewer.statechart.bindings import b01_order as b01
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import ACCOUNT, REF, World, opened
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms import command_rig as cr
from tests.unit.oms import order_rig
from tests.unit.oms.test_oms_runtime import until

pytestmark = pytest.mark.chaos

#: The order the process before this one was sending when it went down.
SENDING = cr.new_order(seq=9)


async def crashed(world: World) -> None:
    """The process before this one, over the same store and venue (`opened(before=)`): the order
    `submitting` and its create taken by the venue, then down, its attempts gone with its memory,
    as `test_oms_runtime.crashed` leaves its `SENDING`."""
    rig = order_rig.build_rig(world.store)

    async def landed(_command: b01.Command) -> NoReturn:
        await world.port.place_order(place_request(SENDING, REF))
        await asyncio.Event().wait()  # the answer never comes back: the process goes down
        raise AssertionError("unreachable")

    rig.commands.on_place = landed
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        await rig.facade.start(SENDING, environment="demo", gates=order_rig.GATES)
        await rig.facade.command(ACCOUNT, SENDING.id, "SEND", actor="user")
        await until(lambda: bool(world.exchange.creates()))
    finally:
        b01._ATTEMPTS = saved  # first: a `stop()` that raises leaves no swapped table behind
        await rig.facade.stop()


@virtual
async def test_s9_a_resumed_create_the_venue_holds_is_looked_up_and_bound_not_sent_again() -> None:
    async with opened(before=crashed) as world:
        row = await world.row(SENDING.id)
        venue = await world.exchange.order(SENDING.order_link_id)
        assert (row.lifecycle_state, row.exchange_order_id) == (
            "submitted",
            venue.exchange_order_id,
        )
        assert ("orders.submit", "adopted_after_lookup") in world.writer.actions
        assert world.exchange.creates() == {SENDING.order_link_id: 1}  # the first process's only
        await check(world)


@virtual
async def test_s9_the_venues_acknowledgement_on_the_stream_twice_changes_nothing() -> None:
    async with opened(streamed=True) as world:
        outcome = await world.submit()
        assert outcome.order_id
        row = await world.row(outcome.order_id)
        before = (row, await world.store.list_for_order(ACCOUNT, row.id))
        for _ in range(2):  # the stream's acknowledgement, redelivered
            await world.exchange.ack(row.order_link_id)
        await world.settle()
        assert world.sample("oms_stream_event_lag_seconds_count") == 2  # both read: a count
        assert (
            await world.row(row.id),
            await world.store.list_for_order(ACCOUNT, row.id),
        ) == before
        assert "oms.reconcile_anomaly" not in {action for action, _ in world.writer.actions}
        assert world.exchange.creates() == {row.order_link_id: 1}
        await check(world)
