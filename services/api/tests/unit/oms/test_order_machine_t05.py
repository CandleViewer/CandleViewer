"""The B1 facade's hold of an order push for an unbound row (E29-T05 #848 slice S4a; SR-E29-03,
24-internal-schemas.md Sec.8.12 step 2): a push of the exchange's order row waits for the bind,
and is taken only if it names the order the bind names."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.oms.errors import OrderBufferFull, ReconcileAnomaly
from candleviewer.oms.order_machine import MAX_HELD
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms.order_rig import (
    ACCOUNT,
    READ_BACK,
    Rig,
    build_rig,
    fill_of,
    gated,
    order_of,
)

_ANOMALY = "oms.reconcile_anomaly"


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = build_rig()
    yield out
    await out.facade.stop()


async def _unbound(rig: Rig) -> tuple[Any, Any]:
    """An order sent, its place in flight until the gate is set, then acked as `x1`."""
    order = order_of()
    gate, rig.commands.on_place = gated({"ok": True, "exchange_order_id": "x1"})
    await rig.start(order)
    assert await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user") == "submitting"
    return order, gate


def _held(rig: Rig, order: Any) -> int:
    return len(rig.facade._orders[order.id].held)


def _end(venue_id: str, **over: Any) -> dict[str, Any]:
    return {"exchange_order_id": venue_id, "updated_time": 9} | over


async def test_a_squatters_cancel_under_our_link_id_waits_and_is_an_anomaly_after_the_bind(
    rig: Rig,
) -> None:
    order, gate = await _unbound(rig)
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", _end("y9"))
    assert rig.facade.state(order.id) == ("submitting", "not_required")  # held, not applied
    assert _held(rig, order) == 1 and rig.audit.records == []
    assert rig.facade._tasks == set()  # a held push waits for the bind; no turn spins on it
    gate.set()
    await rig.quiet()
    assert rig.facade.state(order.id) == ("submitted", "not_required")  # still ours, still live
    assert _held(rig, order) == 0
    assert rig.audit.reasons(_ANOMALY) == ["POST_TERMINAL_PUSH"]
    assert rig.count("oms_reconcile_anomaly_total") == 1
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "accepted" and row.exchange_order_id == "x1"


async def test_an_end_naming_the_bound_order_ends_the_row_after_the_ack(rig: Rig) -> None:
    order, gate = await _unbound(rig)
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", _end("x1"))
    assert rig.facade.state(order.id) == ("submitting", "not_required")
    gate.set()
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "cancelled"
    assert rig.audit.reasons(_ANOMALY) == []


async def test_an_end_that_outruns_the_fills_still_waits_for_them_after_the_bind(
    rig: Rig,
) -> None:
    """INV-B1-k: the bind does not release an end that reports fills the order does not hold."""
    order, gate = await _unbound(rig)
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", _end("x1", cum_exec_qty="0.4"))
    gate.set()
    async with asyncio.timeout(10):  # a release that re-holds the end would turn the settling over
        await rig.quiet()
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert _held(rig, order) == 1
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and (row.state, row.cum_exec_qty) == ("cancelled", Decimal("0.4"))


async def test_the_unbound_hold_is_bounded_at_max_held(rig: Rig) -> None:
    """C-2.18: the 257th push waiting for the bind is refused, and nothing it carried is applied."""
    order, gate = await _unbound(rig)
    for n in range(MAX_HELD):
        await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", _end("x1", updated_time=n))
    assert _held(rig, order) == MAX_HELD == 256
    with pytest.raises(OrderBufferFull):
        await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", _end("x1", updated_time=999))
    assert _held(rig, order) == MAX_HELD
    assert rig.facade.state(order.id) == ("submitting", "not_required")
    gate.set()


async def test_an_untracked_row_takes_the_push_at_once(rig: Rig) -> None:
    """An `untracked` row has no bind to wait for: the push is not held."""
    found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
    assert await rig.facade.discover(found, environment="demo") == "untracked"
    # discovery always names the exchange order; unbind the plain view to pin the rule alone
    rig.facade._orders[found.id].view["exchange_order_id"] = None
    await rig.facade.push(ACCOUNT, found.id, "TRIGGERED", _end("y9"))
    assert _held(rig, found) == 0


async def test_a_final_rows_push_is_still_the_s6_anomaly(rig: Rig) -> None:
    """S6 is unchanged: a push for a final order is audited, raised and never held."""
    order = await rig.submitted()
    _gate, rig.commands.on_attach = gated(READ_BACK)  # the stop stays pending: the machine lives
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    assert rig.facade.state(order.id) == ("filled", "sl_pending")
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", _end("y9"))
    assert rig.audit.reasons(_ANOMALY) == ["POST_TERMINAL_PUSH"]
    assert _held(rig, order) == 0
