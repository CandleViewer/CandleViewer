"""C-13.6 #10, its audit half (E29-Q04 #1148; the ruling's BQ-8 (a); threat-model rows AC-20 and
OM-D04; C-2.9): the lane's audit writer's write-ahead log fills while Postgres is down, so every
append is refused `AuditUnavailable` and the writer's fail-closed alarm fires, which the runtime
pages (`oms_lane_audit_alarm`, once a window). A submit is refused `503 audit_unavailable` before
anything is recorded or sent. An entry's first fill finds its position without the create's stop,
so its attach is due (24 Sec.8.8 rule 2), and the stop write is withheld: its `sl.attached`
record cannot land, so no `set_trading_stop` goes out, and B1 lands the order's protection in
`sl_missing` and pages `SL_ATTACH_FAILED`. Once the log drains, a submit is accepted and sent
once, and its own first fill, which finds the position still without a stop, has its due attach
write the stop: the position holds it, nothing more is paged, and the oracle finds the book equal
to the venue. The log here is the writer's double (`_world.Wal`); the writer's own refusal is
pinned by its unit test, `test_writer_wal_full_with_postgres_down_refuses_never_drops`. On
virtual time, the venue derived in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

from uuid import UUID

import pytest

from candleviewer.oms.errors import AuditNotDurable, problem_for
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import PRICE, Wal, World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos

#: The runtime's page for the writer's alarm, in the writer's own words (`AuditWriter._accept`).
ALARM = "oms_lane_audit_alarm: audit WAL unavailable: AuditWalFull"
#: B1's page for a stop it could not confirm (C-2.6), as the notice route words it.
NAKED = "order alert SL_ATTACH_FAILED"


async def full(world: World) -> UUID:
    """The scenario's fault: an entry accepted, then the lane's audit log full (the world's writer
    a `Wal`, its alarm the runtime's). Answers the entry's id."""
    wal = world.writer
    assert isinstance(wal, Wal)
    wal.alarm = world.alarms[-1]
    outcome = await world.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
    wal.full = True
    return outcome.order_id


async def filled_bare(world: World, order_id: UUID) -> None:
    """The order filled whole, its position shown without the create's stop (`attached` off), so
    its attach is due; settled."""
    row = await world.row(order_id)
    await world.exchange.fill(row.order_link_id, row.qty, PRICE, push=True, attached=False)
    await world.settle()


def stop_writes(world: World) -> int:
    """The `set_trading_stop` calls that reached the venue."""
    return [call.method for call in world.port.calls].count("set_trading_stop")


@virtual
async def test_s13_a_full_audit_log_refuses_a_submit_and_a_due_attach_before_any_send() -> None:
    async with opened(streamed=True, writer=Wal()) as world:
        order_id = await full(world)
        sent = world.exchange.creates()
        with pytest.raises(AuditNotDurable) as refused:
            await world.submit()
        problem = problem_for(refused.value)
        assert (problem.status, problem.code) == (503, "audit_unavailable")
        assert world.exchange.creates() == sent and len((await world.book()).orders) == 1
        assert world.raised("page").count(ALARM) == 1  # the writer's alarm, paged
        await filled_bare(world, order_id)  # its attach due, its record refused
        assert (world.raised("page").count(NAKED), stop_writes(world)) == (1, 0)  # withheld
        assert isinstance(world.writer, Wal)
        world.writer.full = False  # Postgres back: the log drains
        paged = world.raised("page")
        outcome = await world.submit()
        assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
        link = (await world.row(outcome.order_id)).order_link_id
        assert world.exchange.creates() == {**sent, link: 1}  # one more create
        await filled_bare(world, outcome.order_id)  # due again, and its record lands
        assert (stop_writes(world), world.raised("page")) == (1, paged)  # written, no more paged
        await check(world)  # the position holds the stop written, at the venue and in the book
