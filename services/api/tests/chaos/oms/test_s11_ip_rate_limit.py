"""C-13.6 #5, the half that exists before E34-T02 (E29-Q04 #1148; the ruling's BQ-7; 24 Sec.8.6
`10018`): the venue answers a pass's read `10018`, and the adapter's governor holds every caller
for 10 minutes (`TokenBucketGovernor.hold_ip`, `bybit_ip_hold_remaining_seconds`). A submit then
meets the hold at its rate point, its headroom the governor's: `429 exchange_rate_limited` with
`Retry-After`, nothing recorded or sent, counted in `oms_rate_reject_total`. The position the
account holds keeps the native stop its create attached (C-2.6): nothing changes it while every
REST path is held. The hold outlasts reconciliation's 2-minute stale window, so the account locks
for new orders (`stale_lockout`, paged) until the Owner resolves it; once the hold has ended and
the Owner has, order entry resumes, its create taking a token again. "The reserve protects stop
and cancel" is E34-T02's, its chaos E34-Q04's. On virtual time, the venue derived in-test: derived,
not evidence (E29-K01, #843)."""

from __future__ import annotations

import asyncio

import pytest
from prometheus_client import REGISTRY

from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.oms.errors import RateBudgetExceeded, problem_for
from candleviewer.oms.reconcile_job import INTERVAL_S, JITTER_S
from candleviewer.oms.routing import MAX_RETRY_AFTER_S
from tests.chaos.oms._oracle import check
from tests.chaos.oms._venue import IP_HOLD_S
from tests.chaos.oms._world import ACCOUNT, PRICE, Exchange, World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos

#: The governor's gauge, in the process-wide registry: order-independent, as this test reads it
#: only once its own governor has set it (600 at the hold, 0.0 once a create found the hold
#: over), and leaves it at 0.0.
HELD = "bybit_ip_hold_remaining_seconds"
#: The stale page (`reconcile_phases.py`): reconciliation failed for the stale window.
STALE = "Reconciliation has failed for 2 minutes: order entry on an account is refused."


def governed() -> Exchange:
    """The venue with the adapter's rate governor, on the loop's clock."""
    return Exchange(governor=TokenBucketGovernor(clock=asyncio.get_running_loop().time))


async def held(world: World) -> str:
    """The scenario's fault, once an entry has filled and its position holds its native stop: the
    next pass's first read is answered `10018`. Answers the entry's link."""
    outcome = await world.submit()
    assert outcome.order_id
    row = await world.row(outcome.order_id)
    await world.exchange.fill(row.order_link_id, row.qty, PRICE, push=True)
    await world.settle()
    world.exchange.ip_limit("open_orders")
    await world.elapse(INTERVAL_S + JITTER_S)
    return row.order_link_id


async def noted(_state: str) -> None:
    """`resolveReconciliation`'s record of the Owner's decision: the route's, not this suite's."""


@virtual
async def test_s11_the_ip_hold_refuses_a_create_with_nothing_sent_and_the_stops_stay() -> None:
    async with opened(streamed=True, venue=governed()) as world:
        link = await held(world)
        governor, reconcile = world.port.governor, world.oms._composed().reconcile
        assert governor is not None and reconcile is not None
        assert governor.ip_hold_remaining_s() > IP_HOLD_S - INTERVAL_S - JITTER_S  # it engaged
        loop = asyncio.get_running_loop()
        hit = loop.time() + governor.ip_hold_remaining_s() - IP_HOLD_S  # the 10018's moment
        assert REGISTRY.get_sample_value(HELD) == IP_HOLD_S
        rejected, sent = world.sample("oms_rate_reject_total"), world.exchange.creates()
        with pytest.raises(RateBudgetExceeded) as refused:
            await world.submit()
        problem = problem_for(refused.value)
        assert (problem.status, problem.code) == (429, "exchange_rate_limited")
        assert refused.value.retry_after_s == MAX_RETRY_AFTER_S  # the hold's, capped
        assert world.exchange.creates() == sent and len((await world.book()).orders) == 1
        assert world.sample("oms_rate_reject_total") == rejected + 1
        [position] = await world.port.positions(world.exchange.account)
        venue = await world.exchange.order(link)
        assert position.stop_loss == venue.stop_loss is not None  # the stop its create attached
        await world.elapse(IP_HOLD_S)  # the hold ends; its failed passes locked the account
        assert (world.job(), governor.ip_hold_remaining_s()) == ("stale_lockout", 0.0)
        assert world.raised("page") == [STALE]
        await reconcile.jobs.resolve(ACCOUNT, decided_by="owner", write_ahead=noted)
        await world.settle()
        outcome = await world.submit()
        assert (outcome.status, outcome.lifecycle) == (202, "submitted")
        assert REGISTRY.get_sample_value(HELD) == 0.0  # its create found the hold over
        took = loop.time() - hit
        print(f"s11: entry back {took:.1f} s after the 10018: the hold ended, the Owner resolved")
        await check(world)
