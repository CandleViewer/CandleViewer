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

from candleviewer.domain.primitives import AccountId
from candleviewer.oms.errors import (
    IllegalTransition,
    OrderBufferFull,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from candleviewer.oms.order_machine import MAX_HELD, _Held
from candleviewer.oms.ports import PositionKey
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.orders import NewOrder
from tests.unit.oms.order_rig import (
    ACCOUNT,
    OTHER,
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
    await rig.quiet()


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


async def test_a_fresh_end_naming_another_order_than_the_bound_one_changes_nothing(
    rig: Rig,
) -> None:
    """SR-E29-03: after the bind, a push naming a foreign exchange order is an anomaly."""
    order = await rig.submitted()  # bound as `x1`
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", _end("y9"))
    assert rig.audit.reasons(_ANOMALY) == ["POST_TERMINAL_PUSH"]
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "accepted" and row.exchange_order_id == "x1"


async def test_a_held_push_naming_no_order_is_an_anomaly_after_the_bind(rig: Rig) -> None:
    """A push held for the bind that names no exchange order cannot be shown to be ours."""
    order, gate = await _unbound(rig)
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", {"updated_time": 9})
    assert _held(rig, order) == 1
    gate.set()
    await rig.quiet()
    assert rig.audit.reasons(_ANOMALY) == ["POST_TERMINAL_PUSH"]
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "accepted"


async def test_a_held_rows_push_is_not_held_for_a_bind(rig: Rig) -> None:
    """A row in lifecycle `held` never gets a bind from the stream: the push is not held."""
    order = await rig.submitted()
    await rig.facade.command(
        ACCOUNT, order.id, "MISMATCH", {"exchange_order_id": "x9"}, actor="system"
    )
    assert rig.facade.state(order.id) == ("held", "not_required")
    rig.facade._orders[order.id].view["exchange_order_id"] = None
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", _end("y9"))
    assert _held(rig, order) == 0


async def test_an_unbound_final_rows_push_is_the_s6_anomaly_not_held(rig: Rig) -> None:
    order = await rig.submitted()
    _gate, rig.commands.on_attach = gated(READ_BACK)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    assert rig.facade.state(order.id) == ("filled", "sl_pending")
    rig.facade._orders[order.id].view["exchange_order_id"] = None
    async with asyncio.timeout(10):  # a hold above the final-row anomaly would wait for ever
        with pytest.raises(ReconcileAnomaly):
            await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", _end("y9"))
    assert rig.audit.reasons(_ANOMALY) == ["POST_TERMINAL_PUSH"]
    assert _held(rig, order) == 0


async def test_a_store_failure_re_hold_keeps_the_unbound_flag(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = await rig.submitted()
    machine = rig.facade._orders[order.id]
    held = _Held((9_000, 0), "REMOTE_CANCELLED", _end("x1"), 0, True)

    async def doubtful(*_args: Any) -> bool:
        raise OrderStepUnknown("REMOTE_CANCELLED", "StepOutcomeUnknown")

    monkeypatch.setattr(rig.facade, "_take", doubtful)
    with pytest.raises(OrderStepUnknown):
        await rig.facade._release(machine, held)
    assert [(h.refused, h.unbound) for h in machine.held] == [(1, True)]


# --- The positions path's surface (E29-T05 S5a; 24 Sec.8.12 "Protection readings") --------------

_LOST = {"updated_time": 200, "stop_loss": None, "size": "0.4"}
_KEY = PositionKey(AccountId(ACCOUNT), "BTCUSDT", 0)
_ETH = PositionKey(AccountId(ACCOUNT), "ETHUSDT", 0)


async def _protected(rig: Rig, order: NewOrder) -> None:
    """The order sent and part-filled: its stop attached, `sl_present`."""
    await rig.submitted(order)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, f"f{order.id.int}", "0.4"))
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")


async def test_protecting_lists_an_order_by_its_account_symbol_and_position_idx_only(
    rig: Rig,
) -> None:
    mine, hedge = order_of(1), order_of(2, position_idx=2)
    other_symbol = order_of(3, symbol="ETHUSDT")
    for order in (mine, hedge, other_symbol):
        await _protected(rig, order)
    assert rig.facade.protecting(_KEY) == (mine.id,)
    assert rig.facade.protecting(PositionKey(AccountId(ACCOUNT), "BTCUSDT", 2)) == (hedge.id,)
    assert rig.facade.protecting(_ETH) == (other_symbol.id,)
    assert rig.facade.protecting(PositionKey(AccountId(OTHER), "BTCUSDT", 0)) == ()


async def test_protecting_leaves_out_an_order_whose_protection_is_not_required(rig: Rig) -> None:
    order = await rig.submitted()
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert rig.facade.protecting(_KEY) == ()


async def test_a_hydrated_order_keeps_its_position_idx(rig: Rig) -> None:
    order = order_of(position_idx=2)
    await _protected(rig, order)
    again = await rig.restart()
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert again.facade.protecting(PositionKey(AccountId(ACCOUNT), "BTCUSDT", 2)) == (order.id,)
        assert again.facade.protecting(_KEY) == ()
    finally:
        await again.facade.stop()


async def test_push_protection_records_the_reading_on_the_live_machine(rig: Rig) -> None:
    """C-2.6: a lost stop reaches the order's own machine, which leaves `sl_present`."""
    order = order_of()
    await _protected(rig, order)
    assert await rig.facade.push_protection(ACCOUNT, order.id, "SL_LOST", _LOST) is True
    assert rig.facade.state(order.id) == ("partially_filled", "sl_missing")


async def test_push_protection_for_no_machine_answers_false_and_records_nothing(
    rig: Rig,
) -> None:
    order = order_of()
    assert await rig.facade.push_protection(ACCOUNT, order.id, "SL_LOST", _LOST) is False
    assert rig.notices.got == [] and rig.audit.records == []


async def test_push_protection_for_an_unprotected_order_answers_false(rig: Rig) -> None:
    order = await rig.submitted()
    assert await rig.facade.push_protection(ACCOUNT, order.id, "SL_LOST", _LOST) is False
    assert rig.facade.state(order.id) == ("submitted", "not_required")


@pytest.mark.parametrize("event", ["SL_DEADLINE", "EXEC", "nope"])
async def test_push_protection_refuses_any_other_event_before_a_read(rig: Rig, event: str) -> None:
    order = order_of()
    await _protected(rig, order)
    with pytest.raises(IllegalTransition):
        await rig.facade.push_protection(ACCOUNT, order.id, event, _LOST)
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")


async def test_a_reading_pushed_during_a_resync_is_taken_by_the_successor(rig: Rig) -> None:
    order = order_of()
    await _protected(rig, order)
    old = rig.facade._orders[order.id]
    async with rig.facade._holding(old):
        waiting = asyncio.create_task(
            rig.facade.push_protection(ACCOUNT, order.id, "SL_LOST", _LOST)
        )
        for _ in range(8):
            await asyncio.sleep(0)
        await rig.facade._resync(old)
    assert await asyncio.wait_for(waiting, 5) is True
    assert rig.facade._orders[order.id] is not old
    assert rig.facade.state(order.id) == ("partially_filled", "sl_missing")
