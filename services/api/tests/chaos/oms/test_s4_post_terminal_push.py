"""E29-Q04's "Post-terminal push" criterion (#1148), E29-T05's half (#848; 24 Sec.8.12, S6); no
C-13.6 row of its own, #2 the nearest: a burst of ending statuses for an order the stream filled
leaves the order as it was, and each push is audited `oms.reconcile_anomaly` and alerted. On
virtual time (`stream_world`), its rows derived in-test: derived, not evidence."""

from __future__ import annotations

import pytest

from candleviewer.oms.errors import POST_TERMINAL_PUSH
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms.stream_world import FILLS, ORDERS, opened
from tests.unit.oms.test_e29_t05_acceptance import fill_row, order_row, parsed

pytestmark = pytest.mark.chaos

ENDS = ("Cancelled", "Deactivated", "Rejected", "PartiallyFilledCanceled")


@virtual
async def test_s4_a_burst_of_ends_after_filled_is_each_audited_and_changes_nothing() -> None:
    async with opened(parsed) as w:
        order = await w.submitted()
        w.send(FILLS, fill_row(order, "e1", "1", seq=1))
        await w.settle()
        before = (await w.row(order.id), await w.events(order.id))
        assert before[0].lifecycle_state == "filled"
        for status in ENDS:
            w.send(ORDERS, order_row(order, status, "1"))
        await w.settle()
        assert (await w.row(order.id), await w.events(order.id)) == before
        anomalies = [r for r in w.out.audit.records if r.action == "oms.reconcile_anomaly"]
        assert [r.reason for r in anomalies] == [POST_TERMINAL_PUSH] * len(ENDS)
        assert w.out.pager.severities == ["alert"] * len(ENDS)
        assert w.count("push", "anomaly") == len(ENDS)
