"""The private stream's per-push core (E29-T05 #848, S4b; 24-internal-schemas.md Sec.8.12): every
row of the contract's decision table, the one 5 s deadline, the facade's answers, cancellation. On a
fake clock the reads advance; no sleeps, no network."""

from __future__ import annotations

import asyncio
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.models import Execution, Order, PrivateEvent
from candleviewer.oms import stream_push
from candleviewer.oms.errors import (
    HandoverUnavailable,
    IllegalTransition,
    OrderBufferFull,
    OrderNotLoaded,
    OrderStepRefused,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from candleviewer.oms.push_mapping import push_time_ms, route
from candleviewer.oms.stream_push import NoRecordedStopStream
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopNotBindable,
    RecordedStopRow,
)
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, link
from tests.unit.oms.stream_rig import GUARD_S, XID, Rig, event, order_row

STOP = {
    "stopOrderType": "PartialStopLoss", "tpslMode": "Partial", "triggerPrice": "94000",
    "qty": "0.5", "side": "Sell", "reduceOnly": True, "orderStatus": "Untriggered",
    "timeInForce": "GTC",
}  # fmt: skip
OURS = {"orderLinkId": link()}
CANCELLED = {"orderId": XID, "orderStatus": "Cancelled", "timeInForce": "GTC"} | OURS


def _exec_id(fill: PrivateEvent) -> str:
    assert isinstance(fill.payload, Execution)
    return fill.payload.exec_id


def _record(**over: Any) -> RecordedStopRow:
    values: dict[str, Any] = {f.name: None for f in fields(RecordedStopRow)}
    values |= {"id": UUID(int=1), "exchange_account_id": ACCOUNT_A}
    values |= {"created_at": datetime(2026, 10, 24, tzinfo=UTC), "symbol": "BTCUSDT"}
    values |= {"position_idx": 0, "position_side": "Buy", "status": "pending", "kind": "stop_loss"}
    values |= {"tpsl_mode": "Partial", "trigger_price": Decimal(94000), "size": Decimal("0.5")}
    return RecordedStopRow(**(values | over))


HANDED_OVER = "handover:False"
NOT_BOUND = RecordedStopNotBindable()


def _stop_rig(**kw: Any) -> Rig:
    """A stop-claiming push whose recorded-stop write is refused; the refusal clears the live
    record, so what the stores hold after it is no record."""
    rig = Rig(raises={"take": NOT_BOUND} | kw.pop("raises", {}), answers={"stops": (_record(),)})
    rig.answers["on_take"] = lambda: rig.answers.update(stops=())
    rig.answers |= kw
    return rig


def _fill_of_a_stop(rig: Rig) -> PrivateEvent:
    rig.answers["order"] = event("order", orderId=XID, **STOP).payload
    return event("execution", orderId=XID)


async def _stalled(rig: Rig) -> None:
    async with asyncio.timeout(GUARD_S):
        await rig.stalled.wait()


async def test_handle_fill_reads_in_the_contracts_order_each_once() -> None:
    rig = Rig(answers={"order": event("order", orderId=XID, **STOP).payload})
    await rig.run(event("execution"))
    assert [c for c in rig.calls if c in {"bound", "named", "order", "stops"}] == [
        "bound", "named", "order", "stops",
    ]  # fmt: skip


async def test_handle_reads_under_one_deadline_not_one_per_read() -> None:
    """Three reads of 2 s would leave 1 s of the 5 s: use 3 s, so the third is spent, not called."""
    rig = Rig(cost=3.0)
    await rig.run(event("execution"))
    assert rig.calls[:3] == ["bound", "named", HANDED_OVER] and rig.opened == []


async def test_handle_zero_bound_cuts_a_never_answering_read_short_without_a_sleep() -> None:
    rig = Rig(hang={"bound", "named", "order"})
    await rig.run(event("execution"), handover_bound_s=0.0)
    assert "bound" not in rig.calls and HANDED_OVER in rig.calls


async def test_handle_raising_read_hands_the_fill_over_undecided() -> None:
    rig = Rig(raises={"order": RuntimeError("x")})
    await rig.run(event("execution"))
    assert HANDED_OVER in rig.calls


async def test_handle_none_order_read_hands_the_fill_over_as_an_empty_read() -> None:
    rig = Rig()
    await rig.run(event("execution"))
    assert "handover:True" in rig.calls


async def test_handle_bound_fill_sends_exec_under_the_rows_ids() -> None:
    rig = Rig(answers={"bound": order_row()})
    await rig.run(event("execution", orderId=XID))
    [(oid, name, body)] = rig.pushed
    assert (oid, name) == (UUID(int=1), "EXEC") and body["order_link_id"] == link()
    assert body["order_id"] == str(UUID(int=1)) and rig.counts == ["paired"]


async def test_handle_bound_order_push_sends_its_event_with_the_exchange_order_id() -> None:
    rig = Rig(answers={"bound": order_row()})
    ended = event("order", **CANCELLED)
    await rig.run(ended)
    [(_, name, body)] = rig.pushed
    assert isinstance(ended.payload, Order) and name == "REMOTE_CANCELLED"
    assert body["updated_time"] == push_time_ms(ended.payload, ended.ts_event)
    assert body["exchange_order_id"] == XID and rig.counts == ["paired"]


async def test_handle_row_with_no_event_sends_nothing() -> None:
    rig = Rig(answers={"bound": order_row()})
    await rig.run(event("order", orderId=XID, orderStatus="New"))
    assert rig.pushed == []


async def test_handle_unmapped_status_is_counted_and_sends_nothing() -> None:
    rig = Rig(answers={"bound": order_row()})
    odd = event("order", orderId=XID)
    assert isinstance(odd.payload, Order)
    unmapped = odd.model_copy(update={"payload": odd.payload.model_copy(update={"state": "odd"})})
    assert (routed := route(unmapped)) is not None and getattr(routed, "unmapped", False)
    await rig.run(unmapped)
    assert rig.counts == ["unmapped"] and rig.pushed == []


async def test_handle_unbound_live_row_its_link_names_takes_the_push_counted_held() -> None:
    rig = Rig(answers={"named": order_row(exchange_order_id=None, state="submitted")})
    await rig.run(event("order", **CANCELLED))
    assert rig.counts == ["held"] and len(rig.pushed) == 1


async def test_handle_full_buffer_pages_once_per_order_and_opens_no_lockout() -> None:
    rig = Rig(answers={"bound": order_row()})
    rig.push_errors = [OrderBufferFull("full"), OrderBufferFull("full")]
    await rig.run(event("order", **CANCELLED))
    await rig.run(event("order", **CANCELLED))
    assert rig.counts == ["buffer_full", "buffer_full"] and len(rig.pages) == 1
    assert rig.opened == [] and len(rig.pushed) == 2


async def test_handle_full_buffers_forgets_the_oldest_paged_order_at_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_push, "PAGED_ORDERS", 2)
    rig = Rig()
    rig.push_errors = [OrderBufferFull("full")] * 4
    for n in (1, 2, 3, 1):  # the third evicts the first, so the first pages again
        rig.answers["bound"] = order_row(id=UUID(int=n))
        await rig.run(event("order", **CANCELLED))
    assert len(rig.pages) == 4


async def test_handle_no_intent_fill_opens_the_lockout_before_the_handover() -> None:
    rig = Rig(answers={"order": event("order", orderId=XID).payload})
    fill = event("execution", orderId=XID)
    await rig.run(fill)
    assert rig.calls.index("lockout") < rig.calls.index(HANDED_OVER)
    assert rig.opened == [("execution", _exec_id(fill))] and rig.counts == ["no_intent"]


async def test_handle_failed_handover_of_a_no_intent_fill_is_counted_after_the_lockout() -> None:
    rig = Rig(
        answers={"order": event("order", orderId=XID).payload},
        raises={"handover": HandoverUnavailable("none")},
    )
    await rig.run(event("execution", orderId=XID))
    assert rig.counts == ["no_intent", "handover_unavailable"]


async def test_handle_no_intent_order_push_hands_over_no_fill() -> None:
    rig = Rig()
    await rig.run(event("order", orderId=XID))
    assert rig.opened == [("order", XID)] and not any(c.startswith("handover") for c in rig.calls)


async def test_handle_exchange_placed_order_is_audited_and_opens_no_lockout() -> None:
    placed = event("order", orderId=XID).payload.model_copy(update={"exchange_placed": True})
    rig = Rig(answers={"order": placed})
    await rig.run(event("execution", orderId=XID))
    assert "exchange_placed" in rig.calls and rig.opened == []
    assert rig.counts[0] == "exchange_placed"


async def test_handle_failed_lockout_pages_and_counts() -> None:
    rig = Rig(raises={"lockout": RuntimeError("x")})
    await rig.run(event("order", orderId=XID))
    assert rig.counts == ["lockout_failed"] and len(rig.pages) == 1


async def test_handle_undecided_fill_that_cannot_be_kept_opens_the_undecided_lockout() -> None:
    fill = event("execution", orderId=XID)
    rig = Rig(raises={"handover": HandoverUnavailable("none"), "order": RuntimeError("x")})
    await rig.run(fill)
    assert rig.opened == [("undecided", _exec_id(fill))]


async def test_handle_undecided_fill_that_is_kept_opens_no_lockout() -> None:
    rig = Rig(raises={"order": RuntimeError("x")})
    await rig.run(event("execution", orderId=XID))
    assert rig.opened == [] and rig.counts == []


async def test_handle_undecided_order_push_opens_nothing() -> None:
    rig = Rig(raises={"bound": RuntimeError("x")})
    await rig.run(event("order", orderId=XID))
    assert rig.opened == [] and rig.counts == ["undecided"]


async def test_handle_refused_fill_is_undecided_never_no_intent() -> None:
    fill = event("execution", orderId=XID)
    rig = Rig(
        answers={"bound": order_row(exchange_account_id=ACCOUNT_B)},
        raises={"handover": HandoverUnavailable("n")},
    )
    await rig.run(fill)
    assert rig.counts[0] == "pairing_refused" and rig.pushed == []
    assert rig.opened == [("undecided", _exec_id(fill))]


async def test_handle_refused_order_push_does_nothing_but_count_it() -> None:
    rig = Rig(answers={"bound": order_row(exchange_account_id=ACCOUNT_B)})
    await rig.run(event("order", orderId=XID))
    assert rig.counts == ["pairing_refused"] and rig.pushed == [] and rig.opened == []
    assert not any(c.startswith("handover") or c == "exchange_placed" for c in rig.calls)


async def test_handle_logs_name_no_foreign_account_or_row_value() -> None:
    other = order_row(exchange_account_id=ACCOUNT_B)
    with capture_logs() as logs:
        await Rig(answers={"bound": other}).run(event("execution", orderId=XID))
    assert logs and str(ACCOUNT_B) not in str(logs) and other.order_link_id not in str(logs)


async def test_handle_logs_name_neither_the_pushes_link_id_nor_its_trigger_price() -> None:
    rig = Rig(answers={"bound": order_row()}, push_errors=[OrderBufferFull("full")])
    with capture_logs() as logs:
        await rig.run(event("order", **(STOP | CANCELLED)))
    assert any(e["event"] == "stream_buffer_full" for e in logs)
    assert link() not in str(logs) and "94000" not in str(logs)


async def test_handle_stand_in_counts_pending_and_opens_nothing() -> None:
    rig = Rig(answers={"stops": (_record(),)})
    await rig.run(event("order", orderId=XID, **STOP), stops=NoRecordedStopStream(rig))
    assert rig.counts == ["stop_pending_s6"] and rig.opened == [] and rig.taken == []


async def test_handle_recorded_stop_decision_reaches_the_seam() -> None:
    rig = Rig(answers={"stops": (_record(),)})
    await rig.run(event("order", orderId=XID, **STOP), stops=rig)
    assert len(rig.taken) == 1 and rig.taken[0].record == _record()


@pytest.mark.parametrize("failure", [RecordedStopNotBindable(), StorageQueryFailed("23505")])
async def test_handle_refused_stop_write_rereads_and_acts_on_what_is_found(
    failure: Exception,
) -> None:
    rig = Rig(raises={"take": failure}, answers={"stops": (_record(),)})
    rig.answers["on_take"] = lambda: rig.answers.update(bound=order_row())
    await rig.run(event("order", orderId=XID, **(STOP | {"orderStatus": "Cancelled"})))
    assert "for_exchange_order" in rig.calls and rig.pushed[0][0] == UUID(int=1)
    assert rig.counts == ["paired"] and rig.taken[0].record == _record()


async def test_handle_second_recorded_stop_decision_is_not_retried() -> None:
    rig = Rig(raises={"take": NOT_BOUND}, answers={"stops": (_record(),)})
    await rig.run(event("order", orderId=XID, **STOP))
    assert len(rig.taken) == 1 and rig.counts == ["stop_unbindable"] and rig.opened == []


async def test_handle_reread_finding_a_record_of_the_order_is_intent_not_a_foreign_order() -> None:
    rig = _stop_rig(for_exchange_order=(_record(exchange_order_id=XID),))
    await rig.run(event("order", orderId=XID, **STOP))
    assert rig.opened == [] and rig.counts == ["stop_unbindable"]


@pytest.mark.parametrize(
    "stray",
    [
        {"exchange_account_id": ACCOUNT_B},
        {"exchange_order_id": "other"},
        {"exchange_order_id": None},
    ],
    ids=["another-account", "another-order", "no-order"],
)
async def test_handle_reread_answering_a_record_that_is_not_the_orders_still_locks(
    stray: dict[str, Any],
) -> None:
    rig = _stop_rig(for_exchange_order=(_record(**({"exchange_order_id": XID} | stray)),))
    await rig.run(event("order", orderId=XID, **STOP))
    assert rig.opened == [("order", XID)] and rig.counts == ["no_intent"]


async def test_handle_reread_finding_no_record_leaves_no_intent_and_opens_the_lockout() -> None:
    rig = _stop_rig()
    await rig.run(event("order", orderId=XID, **STOP))
    assert rig.opened == [("order", XID)] and rig.counts == ["no_intent"]


async def test_handle_failed_reread_hands_the_fill_over_undecided_with_no_re_pair_reads() -> None:
    rig = _stop_rig(raises={"for_exchange_order": RuntimeError("x")})
    await rig.run(_fill_of_a_stop(rig))
    after = rig.calls[rig.calls.index("take") + 1 :]
    assert after == ["for_exchange_order", HANDED_OVER] and rig.opened == []


async def test_handle_reread_runs_under_the_pushs_deadline_not_a_fresh_one() -> None:
    rig = _stop_rig()
    rig.answers["on_take"] = lambda: setattr(rig, "now", rig.now + 100.0)  # the write spent it
    await rig.run(_fill_of_a_stop(rig))
    after = rig.calls[rig.calls.index("take") + 1 :]
    assert after == [HANDED_OVER] and rig.opened == []


async def test_handle_unknown_outcome_is_delivered_once_more() -> None:
    rig = Rig(answers={"bound": order_row()})
    rig.push_errors = [OrderStepUnknown("EXEC", "x")]
    await rig.run(event("execution", orderId=XID))
    assert rig.counts == ["paired"] and rig.pushed[0] == rig.pushed[1]


async def test_handle_unknown_outcome_twice_is_counted_and_never_a_third_delivery() -> None:
    rig = Rig(answers={"bound": order_row()})
    rig.push_errors = [OrderStepUnknown("EXEC", "x")] * 3
    await rig.run(event("execution", orderId=XID))
    assert len(rig.pushed) == 2 and rig.counts == ["unknown_twice"] and rig.opened == []


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (ReconcileAnomaly("filled", "EXEC"), "anomaly"),
        (OrderStepRefused("EXEC", "x"), "refused"),
        (IllegalTransition("filled", "EXEC"), "refused"),
        (OrderNotLoaded("x"), "not_loaded"),
        (TimeoutError(), "unknown"),
        (OSError("x"), "unknown"),
    ],
    ids=lambda p: type(p).__name__ if isinstance(p, Exception) else p,
)
async def test_handle_other_facade_answers_are_counted_and_not_redelivered(
    error: Exception, outcome: str
) -> None:
    rig = Rig(answers={"bound": order_row()}, push_errors=[error])
    await rig.run(event("execution", orderId=XID))
    assert rig.counts == [outcome] and len(rig.pushed) == 1


async def test_handle_cancel_during_a_read_propagates_with_no_lockout_and_no_handover() -> None:
    rig = Rig(hang={"bound"})
    task = asyncio.create_task(rig.run(event("execution", orderId=XID)))
    await _stalled(rig)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rig.opened == [] and not any(c.startswith("handover") for c in rig.calls)


async def test_handle_cancel_during_the_push_propagates_with_no_second_delivery() -> None:
    rig = Rig(answers={"bound": order_row()}, hang={"push"})
    task = asyncio.create_task(rig.run(event("execution", orderId=XID)))
    await _stalled(rig)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(rig.pushed) == 1 and rig.counts == []


async def test_handle_hung_lockout_is_cut_by_its_bound_and_paged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_push, "PORT_TIMEOUT_S", 0.0)
    rig = Rig(hang={"lockout"})
    await rig.run(event("order", orderId=XID))
    assert rig.counts == ["lockout_failed"] and len(rig.pages) == 1


async def test_handle_hung_push_is_cut_by_its_bound_counted_unknown_and_not_redelivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_push, "PUSH_TIMEOUT_S", 0.0)
    rig = Rig(answers={"bound": order_row()}, hang={"push"})
    await rig.run(event("execution", orderId=XID))
    assert rig.counts == ["unknown"] and len(rig.pushed) == 1


async def test_handle_hung_handover_is_cut_by_its_bound_and_the_lockout_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_push, "PORT_TIMEOUT_S", 0.0)
    rig = Rig(raises={"order": RuntimeError("x")}, hang={"handover"})
    fill = event("execution", orderId=XID)
    await rig.run(fill)
    assert rig.counts[0] == "handover_unavailable"
    assert rig.opened == [("undecided", _exec_id(fill))]


async def test_handle_hung_recorded_stop_take_is_cut_by_its_bound_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_push, "PORT_TIMEOUT_S", 0.0)
    rig = Rig(answers={"stops": (_record(),)}, hang={"take"})
    await rig.run(event("order", orderId=XID, **STOP))
    assert rig.counts == ["stop_unbindable"] and rig.opened == []
