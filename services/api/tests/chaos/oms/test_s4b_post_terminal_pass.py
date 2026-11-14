"""E29-Q04's "Post-terminal push" criterion (#1148), the pass's leg (E29-T06's 24 Sec.8.5 step
3c, as S6), E29-T05's s4 being the stream's; no C-13.6 row of its own, #2 the nearest. The venue's
stream ends an order while its reads, behind its stream, still show it open: the row ends
`cancelled`, final. Each pass then reads an open order bound to a final row, a `ReconcileAnomaly`:
it changes nothing (the row and its steps; nothing adopted, nothing sent), the pass audits it in
its own `oms.reconcile` record (`anomalies`) and alerts it once for its episode however many passes
list it, and the job waits in `divergent`. Once the venue's reads catch up, the next pass lists
nothing and the oracle finds the book equal to the venue. On virtual time, the venue derived
in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

from uuid import UUID

import pytest

from candleviewer.exchange.base.models import Order
from candleviewer.oms.reconcile_job import INTERVAL_S, JITTER_S
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import ACCOUNT, World, opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos

#: The pass's alert for an anomaly (`reconciler.py`'s `_ALERTS`), raised once an episode.
ANOMALY = "Reconciliation met an anomaly."


async def ended_unread(world: World) -> tuple[UUID, Order]:
    """The scenario's fault: an order submitted, then cancelled on the account's stream while the
    venue's reads still show it open (`Venue.end_unread`). Answers its id and the end pushed."""
    outcome = await world.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
    ended = await world.exchange.end_unread((await world.row(outcome.order_id)).order_link_id)
    await world.settle()
    return outcome.order_id, ended


@virtual
async def test_s4b_an_open_order_bound_to_a_final_row_is_an_anomaly_that_changes_nothing() -> None:
    async with opened(streamed=True) as world:
        order_id, ended = await ended_unread(world)
        link = ended.order_link_id
        before = (await world.row(order_id), await world.store.list_for_order(ACCOUNT, order_id))
        assert before[0].lifecycle_state == "cancelled" and before[0].exchange_order_id
        await world.elapse(2 * INTERVAL_S + JITTER_S)  # two passes meet it
        after = (await world.row(order_id), await world.store.list_for_order(ACCOUNT, order_id))
        assert after == before  # S6: the row and its steps as they were
        assert [r["anomalies"] for r in world.reports()[-2:]] == [[link], [link]]  # each pass's
        assert world.raised("alert").count(ANOMALY) == 1  # alerted once for its episode
        assert world.job() == "divergent"
        assert len((await world.book()).orders) == 1  # nothing adopted beside it
        assert world.exchange.creates() == {link: 1}
        assert "cancel_order" not in {call.method for call in world.port.calls}  # nothing sent
        world.exchange.settle(ended)  # the venue's reads catch up with its stream

        async def over() -> bool:
            return world.job() == "idle" and world.reports()[-1]["anomalies"] == []

        took = await world.until(over, within_s=INTERVAL_S + JITTER_S)
        print(f"s4b: the anomaly's episode over {took:.1f} s after the venue caught up")  # -rA
        assert took <= INTERVAL_S  # the next periodic pass
        await check(world)
