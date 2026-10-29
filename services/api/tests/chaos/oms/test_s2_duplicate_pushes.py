"""C-13.6 #7's idempotency half, and #3's analogue on the private stream (E29-T05 #848; 24
Sec.8.12 S4): fills redelivered across a reconnect, one of them again in the next bundle, are each
stored and counted once. The restart half of #7 is E29-Q04's (#1148). On virtual time
(`stream_world`), its rows derived in-test: derived, not evidence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.audit.audit_waits import virtual
from tests.unit.oms.stream_world import opened
from tests.unit.oms.test_e29_t05_acceptance import FILLS, fill_row, parsed

pytestmark = pytest.mark.chaos


@virtual
async def test_s2_fills_redelivered_across_a_reconnect_are_each_counted_once() -> None:
    async with opened(parsed) as w:
        order = await w.submitted(qty=Decimal(3))
        e1, e2, e3 = (fill_row(order, f"e{n}", "1", seq=n) for n in (1, 2, 3))
        w.send(FILLS, e1)
        w.status("down", "socket_closed", 1)
        w.status("resyncing", "reconnected", 2)
        w.send(FILLS, e1, e2)  # the venue's replay after the reconnect: e1 again, then e2
        w.send(FILLS, e2, e3)  # e2 once more, in the next bundle
        await w.settle()
        assert await w.fills("e1", "e2", "e3") == [(f"e{n}", Decimal(1)) for n in (1, 2, 3)]
        row = await w.row(order.id)
        assert (row.cum_exec_qty, row.lifecycle_state) == (Decimal(3), "filled")
        fills = [kind for kind, source, _ in await w.events(order.id) if source == "ws_private"]
        assert len(fills) == 3 and w.emitted == [] and w.out.pager.calls == []
