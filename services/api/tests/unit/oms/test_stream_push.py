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
from candleviewer.oms.errors import (
    HandoverUnavailable,
    OrderBufferFull,
    OrderStepRefused,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from candleviewer.oms.push_mapping import push_time_ms
from candleviewer.oms.stream_push import NoRecordedStopStream
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopNotBindable,
    RecordedStopRow,
)
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, link
from tests.unit.oms.stream_rig import XID, Rig, event, order_row

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


def _record() -> RecordedStopRow:
    values: dict[str, Any] = {f.name: None for f in fields(RecordedStopRow)}
    values |= {"id": UUID(int=1), "exchange_account_id": ACCOUNT_A}
    values |= {"created_at": datetime(2026, 10, 24, tzinfo=UTC), "symbol": "BTCUSDT"}
    values |= {"position_idx": 0, "position_side": "Buy", "status": "pending", "kind": "stop_loss"}
    return RecordedStopRow(
        **(
            values
            | {"tpsl_mode": "Partial", "trigger_price": Decimal(94000), "size": Decimal("0.5")}
        )
    )


async def test_reads_come_in_the_contracts_order_each_once() -> None:
    rig = Rig(answers={"order": event("order", orderId=XID, **STOP).payload})
    await rig.run(event("execution"))
    assert rig.calls[:4] == ["bound", "named", "order", "stops"]
    assert [c for c in rig.calls if c in {"bound", "named", "order", "stops"}] == rig.calls[:4]
    assert rig.counts == ["no_intent"] and rig.calls.count("order") == 1


async def test_one_deadline_spans_all_reads_not_one_per_read() -> None:
    """Three reads of 2 s would leave 1 s of the 5 s: use 3 s, so the third is spent, not called."""
    rig = Rig(cost=3.0)
    await rig.run(event("execution"))
    assert rig.calls[:3] == ["bound", "named", "handover:False"]
    assert rig.opened == []  # the hand-over kept it


async def test_zero_bound_cuts_a_never_answering_read_short_without_a_sleep() -> None:
    rig = Rig(hang={"bound", "named", "order"})
    await rig.run(event("execution"), handover_bound_s=0.0)
    assert "bound" not in rig.calls and "handover:False" in rig.calls


async def test_raising_read_is_failed_and_a_none_order_read_is_an_empty_read() -> None:
    failed = Rig(raises={"order": RuntimeError("x")})
    await failed.run(event("execution"))
    assert "handover:False" in failed.calls
    empty = Rig()
    await empty.run(event("execution"))
    assert "handover:True" in empty.calls


async def test_to_row_sends_exec_and_an_order_row_event_under_the_rows_ids() -> None:
    rig = Rig(answers={"bound": order_row()})
    fill, ended = event("execution", orderId=XID), event("order", **CANCELLED)
    await rig.run(fill)
    await rig.run(ended)
    [(oid, name, exec_), (_, end, body)] = rig.pushed
    assert (oid, name) == (UUID(int=1), "EXEC") and exec_["order_link_id"] == link()
    assert exec_["order_id"] == str(UUID(int=1)) and end == "REMOTE_CANCELLED"
    assert isinstance(ended.payload, Order)
    assert body["updated_time"] == push_time_ms(ended.payload, ended.ts_event)
    assert body["exchange_order_id"] == XID and rig.counts == ["paired", "paired"]


async def test_a_row_with_no_event_sends_nothing() -> None:
    rig = Rig(answers={"bound": order_row()})
    await rig.run(event("order", orderId=XID, orderStatus="New"))
    assert rig.pushed == []


async def test_wait_on_row_delivers_and_a_full_buffer_pages_once_with_no_lockout() -> None:
    rig = Rig(answers={"named": order_row(exchange_order_id=None, state="submitted")})
    rig.push_errors = [OrderBufferFull("full"), OrderBufferFull("full")]
    await rig.run(event("order", **CANCELLED))
    await rig.run(event("order", **CANCELLED))
    assert rig.counts == ["buffer_full", "buffer_full"] and len(rig.pages) == 1
    assert rig.opened == [] and len(rig.pushed) == 2
    await rig.run(event("order", **CANCELLED))
    assert rig.counts[-1] == "held"


async def test_no_intent_opens_the_lockout_before_the_handover_and_survives_its_failure() -> None:
    rig = Rig(raises={"handover": HandoverUnavailable("none")})
    fill = event("execution", orderId=XID)
    rig.answers["order"] = event("order", orderId=XID).payload
    await rig.run(fill)
    assert rig.calls.index("lockout") < rig.calls.index("handover:False")
    assert rig.opened == [("execution", _exec_id(fill))]
    assert rig.counts == ["no_intent", "handover_unavailable"]


async def test_exchange_placed_audits_and_pages_and_never_opens_the_lockout() -> None:
    rig = Rig(answers={"order": event("order", orderId=XID).payload.model_copy(
        update={"exchange_placed": True})})  # fmt: skip
    await rig.run(event("execution", orderId=XID))
    assert "exchange_placed" in rig.calls and rig.opened == []
    assert rig.counts[0] == "exchange_placed"


async def test_failed_lockout_pages_and_counts() -> None:
    rig = Rig(raises={"lockout": RuntimeError("x")})
    await rig.run(event("order", orderId=XID))
    assert rig.counts == ["lockout_failed"] and len(rig.pages) == 1


async def test_undecided_fill_opens_the_undecided_lockout_only_when_it_cannot_be_kept() -> None:
    fill = event("execution", orderId=XID)
    lost = Rig(raises={"handover": HandoverUnavailable("none"), "order": RuntimeError("x")})
    await lost.run(fill)
    assert lost.opened == [("undecided", _exec_id(fill))]
    kept = Rig(raises={"order": RuntimeError("x")})
    await kept.run(fill)
    assert kept.opened == [] and kept.counts == []


async def test_undecided_order_push_opens_nothing() -> None:
    rig = Rig(raises={"bound": RuntimeError("x")})
    await rig.run(event("order", orderId=XID))
    assert rig.opened == [] and rig.counts == ["undecided"]


async def test_refused_fill_is_undecided_never_no_intent_and_the_log_names_no_value() -> None:
    other = order_row(exchange_account_id=ACCOUNT_B)
    fill = event("execution", orderId=XID)
    with capture_logs() as logs:
        refused = Rig(answers={"bound": other}, raises={"handover": HandoverUnavailable("n")})
        await refused.run(fill)
        await Rig(answers={"bound": other}).run(event("order", orderId=XID))
    assert refused.counts[0] == "pairing_refused" and refused.pushed == []
    assert refused.opened == [("undecided", _exec_id(fill))]
    assert str(ACCOUNT_B) not in str(logs) and other.order_link_id not in str(logs)


async def test_stand_in_counts_and_opens_nothing_and_the_seam_receives_a_recorded_stop() -> None:
    stop = event("order", orderId=XID, **STOP)
    rig = Rig(answers={"stops": (_record(),)})
    await rig.run(stop, stops=NoRecordedStopStream(rig))
    assert rig.counts == ["stop_pending_s6"] and rig.opened == [] and rig.taken == []
    await rig.run(stop, stops=rig)
    assert len(rig.taken) == 1 and rig.taken[0].record == _record()


@pytest.mark.parametrize("failure", [RecordedStopNotBindable(), StorageQueryFailed("23505")])
async def test_refused_stop_write_rereads_and_acts_on_what_is_found(failure: Exception) -> None:
    rig = Rig(raises={"take": failure}, answers={"stops": (_record(),)})
    rig.answers["on_take"] = lambda: rig.answers.update(bound=order_row())
    await rig.run(event("order", orderId=XID, **(STOP | {"orderStatus": "Cancelled"})))
    assert "for_exchange_order" in rig.calls and rig.pushed[0][0] == UUID(int=1)
    assert rig.counts == ["paired"] and rig.taken[0].record == _record()


async def test_second_recorded_stop_decision_is_not_retried() -> None:
    rig = Rig(raises={"take": RecordedStopNotBindable()}, answers={"stops": (_record(),)})
    await rig.run(event("order", orderId=XID, **STOP))
    assert len(rig.taken) == 1 and rig.counts == ["stop_unbindable"] and rig.opened == []


async def test_a_record_of_the_order_found_on_the_reread_is_intent_not_a_foreign_order() -> None:
    rig = Rig(raises={"take": RecordedStopNotBindable()}, answers={"stops": (_record(),)})
    rig.answers["on_take"] = lambda: rig.answers.update(stops=())
    rig.answers["for_exchange_order"] = (_record(),)
    await rig.run(event("order", orderId=XID, **STOP))
    assert rig.opened == [] and rig.counts == ["stop_unbindable"]


async def test_unknown_outcome_is_delivered_once_more_and_never_a_third_time() -> None:
    rig = Rig(answers={"bound": order_row()})
    rig.push_errors = [OrderStepUnknown("EXEC", "x")]
    await rig.run(event("execution", orderId=XID))
    assert rig.counts == ["paired"] and rig.pushed[0] == rig.pushed[1]
    twice = Rig(answers={"bound": order_row()})
    twice.push_errors = [OrderStepUnknown("EXEC", "x")] * 3
    await twice.run(event("execution", orderId=XID))
    assert len(twice.pushed) == 2 and twice.counts == ["unknown_twice"] and twice.opened == []


async def test_other_facade_answers_are_counted_and_a_timeout_is_not_redelivered() -> None:
    answers = [
        (ReconcileAnomaly("filled", "EXEC"), "anomaly"),
        (OrderStepRefused("EXEC", "x"), "refused"),
        (TimeoutError(), "unknown"),
    ]
    for error, outcome in answers:
        rig = Rig(answers={"bound": order_row()}, push_errors=[error])
        await rig.run(event("execution", orderId=XID))
        assert rig.counts == [outcome] and len(rig.pushed) == 1


async def test_cancellation_propagates_with_no_lockout_and_no_handover() -> None:
    rig = Rig(hang={"bound"})
    task = asyncio.create_task(rig.run(event("execution", orderId=XID)))
    await asyncio.sleep(0)  # let the read start: the event loop, not a wall clock
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rig.opened == [] and not any(c.startswith("handover") for c in rig.calls)
