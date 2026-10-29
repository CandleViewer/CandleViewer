"""C-13.6 #3's analogue on the private stream (E29-T05 #848; 24 Sec.8.12, 28 INV-B1-a, S5): fills
delivered in reverse `seq` give the totals they give in order, and an end older than the order's
last push, arriving after it, is stale: ignored, no anomaly. On virtual time (`stream_world`), its
rows derived in-test: derived, not evidence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.audit.audit_waits import virtual
from tests.unit.oms.stream_world import FILLS, ORDERS, opened
from tests.unit.oms.test_e29_t05_acceptance import fill_row, order_row, parsed

pytestmark = pytest.mark.chaos

PRICES = {1: "63000", 2: "63100", 3: "63200"}  # each fill's own price, by its `seq`


@virtual
async def test_s3_fills_in_reverse_seq_give_the_in_order_totals() -> None:
    async with opened(parsed) as w:
        order = await w.submitted(qty=Decimal(3))
        for n in (3, 2, 1):
            w.send(FILLS, fill_row(order, f"e{n}", "1", seq=n, execPrice=PRICES[n]))
        await w.settle()
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
