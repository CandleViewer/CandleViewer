"""The meta-test (E29-Q04 #1148, "Test plan": the suite has teeth). Each scenario that depends on
the reconciliation pass runs over the composed pass, where the oracle finds the book equal to the
venue, and over the stand-ins the runtime composes without E29-T06's stores
(`World(handover_store=None, reconcile_reads=None)`: `NoReconciliation`, `NoHandoverStore`), where
the oracle must fail it, naming the fields that differ, two cycles on: neither run passes
vacuously. Without the pass, s5's order stays `unknown` and unbound beside the venue's order (and
its fill and position, once filled); s6's stays `unknown` with no order at the venue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest

from candleviewer.oms.reconcile_job import INTERVAL_S, JITTER_S
from tests.chaos.oms._oracle import OracleMismatch, check
from tests.chaos.oms._world import World, opened
from tests.chaos.oms.test_s5_post_send_timeout import lost_ack
from tests.chaos.oms.test_s6_unresolved_after_reconcile import never_landed
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos


async def resting(world: World) -> UUID:
    return await lost_ack(world, filled=False)


async def filled(world: World) -> UUID:
    return await lost_ack(world, filled=True)


#: Each scenario's faults, and the (item, field) pairs the oracle names without the pass.
SCENARIOS: dict[str, tuple[Callable[[World], Awaitable[UUID]], set[tuple[str, str]]]] = {
    "s5-resting": (resting, {("order", "exchange_order_id"), ("order", "lifecycle_state")}),
    "s5-filled": (filled, {
        ("order", "exchange_order_id"), ("order", "lifecycle_state"), ("order", "filled_qty"),
        ("execution", "exec_id"), ("position", "open"),
    }),
    "s6": (never_landed, {("order", "venue order")}),
}  # fmt: skip
STAND_INS: dict[str, Any] = {"handover_store": None, "reconcile_reads": None}


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("composed", [True, False], ids=["pass", "stand-ins"])
@virtual
async def test_the_oracle_fails_a_scenario_only_without_the_pass(name: str, composed: bool) -> None:
    drive, named = SCENARIOS[name]
    async with opened(**({} if composed else STAND_INS)) as world:
        await drive(world)
        await world.elapse(2 * INTERVAL_S + JITTER_S)
        if composed:
            await check(world)
            return
        with pytest.raises(OracleMismatch) as raised:
            await check(world)
        assert named <= {(d.item.split()[0], d.field) for d in raised.value.diffs}
