"""C-13.6 #2 repeated, a private reconnect storm (E29-Q04 #1148; E29-T06's driver, 24 Sec.8.5: "a
pass never overlaps itself: a trigger that finds a pass running is skipped, never queued"): an
order's create lands and its answer is lost, so it waits `unknown`, and the account's socket then
drops and comes back again and again, a burst at a time. The first reconnect's pass binds the
order by the full match; no pass opens while another is open; each reconnect starts a pass or is
skipped and logged while one runs, so none is queued; the venue counted one create; and the
storm pages nothing beyond B1's one `order_unknown`. On virtual time, the venue derived in-test:
derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import World, opened
from tests.chaos.oms.test_s5_post_send_timeout import lost_ack
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos

#: The storm: so many bursts, a second apart, of so many sockets lost and regained at once.
BURSTS, BURST = 3, 4


async def storm(world: World) -> UUID:
    """The scenario's faults: a lost acknowledgement (s5's), then the bursts, each socket's `down`
    and its successor's resync queued together. Answers the order's id."""
    order_id = await lost_ack(world, filled=False)
    epoch = 1
    for _ in range(BURSTS):
        for _ in range(BURST):
            world.exchange.status("down", "socket_closed", epoch)
            epoch += 1
            world.exchange.status("resyncing", "reconnected", epoch)
        await world.elapse(1)
    return order_id


@virtual
async def test_s8_a_reconnect_storm_runs_one_pass_at_a_time_and_sends_nothing_twice() -> None:
    async with opened(streamed=True) as world:
        passes = world.passes()
        began = asyncio.get_running_loop().time()
        with capture_logs() as logs:
            order_id = await storm(world)
        skipped = [e for e in logs if e["event"] == "reconcile_trigger_skipped"]
        ran = passes.of("reconnect")
        assert passes.peak == 1  # never two passes open at once
        reconnects = len(ran) + sum(e["trigger"] == "reconnect" for e in skipped)
        assert reconnects == BURSTS * BURST  # each a pass, or skipped while one ran: none queued
        assert skipped and all(e["reason"] == "running" for e in skipped)  # passes overlapped it
        assert len(passes.runs) == len(ran)  # and no pass but a reconnect's
        row = await world.row(order_id)
        assert row.lifecycle_state == "submitted" and row.exchange_order_id  # bound by the first
        print(f"s8: unknown bound {ran[0].at - began:.1f} s into the storm, by its first pass")
        assert world.raised("page") == ["order alert order_unknown"]  # one page, B1's
        assert world.exchange.creates() == {row.order_link_id: 1}
        await check(world)
