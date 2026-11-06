"""C-13.6 #6 (E29-Q04 #1148; E29-T04's clock halt, 24 Sec.8.6 `10002`): a create the venue refuses
`10002`, its timestamp outside `recv_window` after the adapter's one re-signed retry, is rejected
(502 `exchange_error` with the venue's code), counted in `oms_clock_halt_trips_total`, and halts
order entry: the next submit is refused `503 clock_drift` with `Retry-After` before anything is
recorded or sent, and so is one after the resync the trip asked for, which measured at the trip's
own moment. A measurement taken after the trip clears the halt, and the next submit is sent once.
The oracle finds the book equal to the venue. On virtual time, the venue derived in-test: derived,
not evidence (E29-K01, #843)."""

from __future__ import annotations

import pytest

from candleviewer.oms.clock_halt import TRIPS_METRIC
from candleviewer.oms.errors import ClockDriftBlocked, problem_for
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos


async def drifted(world: World) -> None:
    """The scenario's fault: the venue refuses the next create `10002`; the request is answered
    502 with the venue's code, the order `rejected`."""
    world.exchange.drift()
    outcome = await world.submit()
    assert (outcome.status, outcome.lifecycle, outcome.ret_code) == (502, "rejected", 10002)


@virtual
async def test_s10_a_10002_halts_order_entry_until_a_fresh_clock_measurement() -> None:
    async with opened() as world:
        await drifted(world)
        assert world.sample(TRIPS_METRIC) == 1 and world.health.resyncs == ["order_10002"]
        sent, tripped_at = world.exchange.creates(), world.clock.s
        for _ in range(2):  # at once, and after the trip's resync, measured at its moment
            with pytest.raises(ClockDriftBlocked) as halted:
                await world.submit()
            problem = problem_for(halted.value)
            assert (problem.status, problem.code) == (503, "clock_drift")
            assert halted.value.retry_after_s == 5  # `Retry-After`
            assert world.exchange.creates() == sent  # nothing recorded or sent
            await world.settle()
        world.clock.s += 1  # the process's monotonic clock moves on, and the guard measures
        world.health.measure()
        halted_s = world.clock.s - tripped_at
        print(f"s10: halted until a measurement {halted_s:.1f} s after the trip, monotonic")
        outcome = await world.submit()
        assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
        assert sorted(world.exchange.creates().values()) == [1, 1]
        assert world.sample(TRIPS_METRIC) == 1
        await check(world)
