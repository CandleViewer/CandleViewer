"""C-13.6 #2, E29-T05's half (#848; 24-internal-schemas.md Sec.8.12): the private stream killed for
60 s during an open order. The account is shown resyncing once; the silence bound ends the dead
session and the refresh subscribes again; each reconnect asks one reconciliation and the episode
pages once; the order is untouched; the fill after the reconnect applies once; `/readyz` stays
ready. The pass's correctness, the rest of #2, is E29-T06's and E29-Q04's (#1148). On virtual time
(`stream_world`), its rows derived in-test: derived, not evidence."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from tests.unit.audit.audit_waits import virtual
from tests.unit.oms.stream_world import FILLS, REFUSED, RESYNCING, A, opened
from tests.unit.oms.test_e29_t05_acceptance import fill_row, parsed

pytestmark = pytest.mark.chaos


@virtual
async def test_s1_a_60_s_kill_mid_order_is_one_notice_one_page_and_one_fill() -> None:
    async with opened(parsed) as w:
        order = await w.submitted()
        before = (await w.row(order.id), await w.events(order.id))
        await asyncio.sleep(1)
        w.status("down", "socket_closed", 1)  # killed: nothing more for 60 s
        await asyncio.sleep(60)
        assert (await w.row(order.id), await w.events(order.id)) == before
        assert w.trace.count(f"subscribe:{A}") == 2 and w.count("consumer", "silence") == 1
        w.status("resyncing", "connected", 1)  # the venue is back: the new socket
        w.status("resyncing", "rejected_frame", 1)  # and a resync of that socket's own
        w.send(FILLS, fill_row(order, "e1", "1", seq=1))
        await w.settle()
        assert [(f["reason"], f["exchange_account_ids"]) for f in w.frames] == [
            (RESYNCING, [str(A)])
        ]
        assert w.requests.asked == [(A, "connected"), (A, "rejected_frame")]
        assert w.pages == [REFUSED]  # once per episode
        assert await w.fills("e1") == [("e1", Decimal(1))]
        assert (await w.row(order.id)).lifecycle_state == "filled"
        assert w.consumer.fault is None and w.wiring is not None
        assert w.wiring.readiness.degraded() is None
