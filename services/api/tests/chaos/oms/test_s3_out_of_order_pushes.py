"""C-13.6 #3's analogue on the private stream (E29-T05 #848; 24 Sec.8.12, 28 INV-B1-a, S5): fills
delivered in reverse `seq` before their order's bind wait in its reorder buffer and apply in `seq`
order once it binds, giving the in-order totals, and an end older than the order's last push,
arriving after it, is stale: ignored, no anomaly. On virtual time (`stream_world`), its rows
derived in-test: derived, not evidence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.audit.audit_waits import virtual
from tests.unit.oms.stream_world import A, opened
from tests.unit.oms.test_e29_t05_acceptance import FILLS, ORDERS, fill_row, order_row, parsed

pytestmark = pytest.mark.chaos

PRICES = {1: "63000", 2: "63100", 3: "63200"}  # each fill's own price, by its `seq`
FILL_KINDS = ("partial_fill", "fill")  # a fill's `order_events` row


@virtual
async def test_s3_fills_in_reverse_seq_before_the_bind_apply_in_seq_order() -> None:
    async with opened(parsed) as w:
        order, ack = await w.unacked(qty=Decimal(3))
        for n in (3, 2, 1):  # the order is not bound yet: each waits in its reorder buffer
            w.send(FILLS, fill_row(order, f"e{n}", "1", seq=n, execPrice=PRICES[n]))
        await w.settle()
        assert w.count("push", "held") == 3 and await w.fills("e1", "e2", "e3") == []
        ack.set()
        await w.settle()
        events = await w.out.events.list_for_order(A, order.id)
        applied = [e.payload.get("exec_id") for e in events if e.kind in FILL_KINDS]
        assert applied == ["e1", "e2", "e3"]  # by `(ts_exec, seq)`, never in arrival order
        row = await w.row(order.id)
        value = sum(Decimal(price) for price in PRICES.values())  # the in-order totals
        assert (row.cum_exec_qty, row.cum_exec_value) == (Decimal(3), value)
        assert row.avg_price == Decimal(63100) and row.lifecycle_state == "filled"


@virtual
async def test_s3_an_end_older_than_the_orders_last_push_is_stale_and_no_anomaly() -> None:
    async with opened(parsed) as w:
        order = await w.submitted()
        now_ms = w.now_us() // 1_000
        w.send(ORDERS, order_row(order, "Triggered", updatedTime=str(now_ms + 2_000)))
        w.send(ORDERS, order_row(order, "Cancelled", updatedTime=str(now_ms + 1_000)))  # late
        await w.settle()
        assert (await w.row(order.id)).lifecycle_state == "triggered"
        assert [r for r in w.out.audit.records if r.action == "oms.reconcile_anomaly"] == []
        assert w.out.pager.calls == [] and w.count("push", "anomaly") == 0
