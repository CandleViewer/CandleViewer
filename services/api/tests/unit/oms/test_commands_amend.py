"""The command port's amend (E29-T04 #913, slice 4 S4-B2; the orchestrator's Q2, Q3, Q4 and Q11
rulings; 24 Sec.8.8 rules 5 and 6, Sec.8.9; 21 Sec.3.3.11).

A TP/SL change re-pairs (both sides sent, the unchanged one at the order's value, a side the order
lacks left out), is checked against Q3's scope and Q4's ratchet before anything is recorded or
sent, records both sides ahead as one `entry_attach` insert with the order's id (audited
`sl.modified` / `tp.modified`, reason `amend`), sends, and settles the rows answered or refused; a
send that raises leaves them in flight. A held key answers `STOP_REQUEST_IN_FLIGHT` with the prior
order kept live. No `stopLoss` at or below zero is ever sent (C-2.6).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from candleviewer.exchange.base.errors import OmsErrorCode, RateBudgetExceededError, TransportError
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.exchange.base.models import AmendOrderRequest, OrderAck
from candleviewer.oms.commands import (
    AMEND_REASON,
    AMEND_REFUSED,
    STOP_LOOSENING_REFUSED,
    STOP_REQUEST_IN_FLIGHT,
)
from candleviewer.oms.order_machine import OrderAuditRecord
from candleviewer.oms.ports import KeyedRecord
from candleviewer.oms_wiring import STOP_REQUEST_BOUND_S
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow
from tests.unit.oms.command_rig import (
    ACCOUNT,
    EPOCH,
    STOP,
    SYMBOL,
    T0,
    T0_US,
    Rig,
    build_rig,
    command,
    exchange_order,
    new_order,
    ref,
)

_TP = Decimal("64000")


async def _live(rig: Rig, **over: Any) -> Any:
    """An entry resting at the venue, stored `submitted` as B1's `amend_pending` finds it."""
    order = new_order(**over)
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_order(exchange_order(order), uid="100001")
    return order


def _amend(order: Any, **terms: str | None) -> b01.Command:
    return command("amend", order, terms)


def _rows(rig: Rig) -> list[RecordedStopRow]:
    return sorted(rig.store._stops.values(), key=lambda row: row.kind)


def _sent(rig: Rig) -> list[AmendOrderRequest]:
    return [call.request for call in rig.demo.calls if isinstance(call.request, AmendOrderRequest)]


@pytest.fixture
def rows_at_send(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[RecordedStopRow]]:
    """The recorded stops the store holds when the venue call lands (the fake asserts them)."""
    seen: list[RecordedStopRow] = []
    real = rig.demo.amend_order

    async def amend_order(req: AmendOrderRequest) -> OrderAck:
        seen.extend(_rows(rig))
        return await real(req)

    monkeypatch.setattr(rig.demo, "amend_order", amend_order)
    yield seen


@pytest.fixture
def rig() -> Rig:
    return build_rig()


# --- terms only: no rows -------------------------------------------------------------------------


async def test_a_price_amend_sends_the_terms_alone_and_records_nothing(rig: Rig) -> None:
    order = await _live(rig)
    answer = await rig.port.amend(_amend(order, price="60500", qty="0.02"))
    assert answer["ok"] is True
    (call,) = rig.demo.calls
    assert (call.method, call.lane) == ("amend_order", "entry")
    assert call.request == AmendOrderRequest(
        account=ref(),
        symbol=SYMBOL,
        order_link_id=order.order_link_id,
        qty=Decimal("0.02"),
        price=Decimal("60500"),
    )
    assert _rows(rig) == [] and rig.audits.written == []


async def test_a_reduce_only_order_that_reduces_amends_in_the_critical_lane(rig: Rig) -> None:
    order = await _live(
        rig, reduce_only=True, intent="take_profit", stop_loss=None, take_profit=None
    )
    await rig.port.amend(_amend(order, qty="0.005"))
    assert [call.lane for call in rig.demo.calls] == ["critical"]


# --- the re-pairing rule -------------------------------------------------------------------------


async def test_a_take_profit_change_sends_both_sides(rig: Rig) -> None:
    order = await _live(rig)
    await rig.port.amend(_amend(order, take_profit="65000"))
    (sent,) = _sent(rig)
    assert (sent.take_profit, sent.stop_loss) == (Decimal("65000"), STOP)


async def test_a_stop_change_sends_both_sides(rig: Rig) -> None:
    order = await _live(rig)
    await rig.port.amend(_amend(order, stop_loss="58500"))
    (sent,) = _sent(rig)
    assert (sent.take_profit, sent.stop_loss) == (_TP, Decimal("58500"))


async def test_a_side_the_order_lacks_is_left_out(rig: Rig) -> None:
    order = await _live(rig, take_profit=None)
    await rig.port.amend(_amend(order, stop_loss="58500"))
    (sent,) = _sent(rig)
    assert (sent.take_profit, sent.stop_loss) == (None, Decimal("58500"))
    assert [row.kind for row in _rows(rig)] == ["stop_loss"]


# --- the rows: written ahead, settled -------------------------------------------------------------


async def test_the_rows_exist_when_the_venue_call_lands(
    rig: Rig, rows_at_send: list[RecordedStopRow]
) -> None:
    """Q2: one request's rows, `entry_attach` with the order's id, in flight when the call lands,
    each audited in the insert's transaction (`sl.modified` / `tp.modified`, reason `amend`)."""
    order = await _live(rig)
    await rig.port.amend(_amend(order, stop_loss="58500", take_profit="65000"))
    assert [(r.kind, r.source, r.order_id, r.status) for r in rows_at_send] == [
        ("stop_loss", "entry_attach", order.id, "pending"),
        ("take_profit", "entry_attach", order.id, "pending"),
    ]
    assert all(r.answered_at is None and r.tpsl_mode == "Full" for r in rows_at_send)
    assert [r.trigger_price for r in rows_at_send] == [Decimal("58500"), Decimal("65000")]
    assert [(r.action, r.reason, sent) for r, sent in rig.audits.written] == [
        ("sl.modified", AMEND_REASON, 0),
        ("tp.modified", AMEND_REASON, 0),
    ]
    for (record, _), row in zip(rig.audits.written, rows_at_send, strict=True):
        assert isinstance(record, KeyedRecord) and record.object_id == row.id
        assert row.audit_record_id == rig.audits.record_id(record.action, str(row.id))


async def test_an_accepted_amend_answers_its_rows(rig: Rig) -> None:
    order = await _live(rig)
    rig.now.us = T0_US + 3_000_000
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer["ok"] is True
    at = EPOCH + timedelta(microseconds=T0_US + 3_000_000)
    assert [(r.status, r.answered_at) for r in _rows(rig)] == [("pending", at), ("pending", at)]


async def test_a_refused_amend_voids_its_rows_audited_ahead(rig: Rig) -> None:
    order = await _live(rig)
    rig.demo.script("amend_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "hidden"))
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert {k: answer[k] for k in ("ok", "error_code", "exchange_ret_code")} == {
        "ok": False,
        "error_code": "INSTRUMENT_FILTER",
        "exchange_ret_code": 110003,
    }
    assert "hidden" not in repr(answer)
    assert [r.status for r in _rows(rig)] == ["void", "void"]
    assert rig.audits.actions()[2:] == [
        ("sl.modified", AMEND_REFUSED),
        ("tp.modified", AMEND_REFUSED),
    ]


async def test_an_amend_whose_send_raises_leaves_its_rows_in_flight(rig: Rig) -> None:
    """Q11: the order goes `unknown` (S1) and is never re-sent; the complete read ends the rows."""
    order = await _live(rig)
    rig.demo.script("amend_order", TransportError("cut off"))
    with pytest.raises(TransportError):
        await rig.port.amend(_amend(order, stop_loss="58500"))
    assert [(r.status, r.answered_at) for r in _rows(rig)] == [("pending", None)] * 2


async def test_a_refused_rate_token_voids_the_rows_with_nothing_sent(rig: Rig) -> None:
    order = await _live(rig)
    rig.demo.script("amend_order", RateBudgetExceededError("no token", retry_after_s=2.0))
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer == {"ok": False, "error_code": "RATE_BUDGET_EXCEEDED", "retry_after_s": 2}
    assert [r.status for r in _rows(rig)] == ["void", "void"]


async def test_one_insert_shares_one_created_at() -> None:
    ticks = iter(T0 + timedelta(seconds=n) for n in range(100))
    rig = build_rig(created_at=lambda: next(ticks))
    order = await _live(rig)
    await rig.port.amend(_amend(order, stop_loss="58500"))
    stamps = {row.created_at for row in _rows(rig) if row.source == "entry_attach"}
    assert len(stamps) == 1


# --- a held key ----------------------------------------------------------------------------------


async def _earlier_request(rig: Rig) -> None:
    earlier = NewRecordedStop(
        id=uuid5(NAMESPACE_URL, "earlier"),
        exchange_account_id=ACCOUNT,
        symbol=SYMBOL,
        position_idx=0,
        position_side="Buy",
        kind="stop_loss",
        source="trading_stop",
        order_id=None,
        tpsl_mode="Full",
        trigger_price=Decimal("57000"),
        size=None,
        audit_record_id=uuid5(NAMESPACE_URL, "earlier-record"),
        actor_user_id=None,
    )

    async def audited(_rows: Any) -> None:
        return None

    await rig.stops.record([earlier], write_ahead=audited)


@pytest.mark.parametrize("past_bound", [True, False], ids=["waiting", "in_flight"])
async def test_a_held_key_answers_in_flight_and_keeps_the_prior_order(
    rig: Rig, past_bound: bool
) -> None:
    """409 `stop_request_in_flight` at the route: nothing recorded or sent, never a raise."""
    order = await _live(rig)
    await _earlier_request(rig)
    bound_us = round(STOP_REQUEST_BOUND_S * 1_000_000)
    rig.now.us = T0_US + (bound_us if past_bound else 1_000_000)
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer["ok"] is False and answer["error_code"] == STOP_REQUEST_IN_FLIGHT
    assert answer["retry_after_s"] == 5
    assert rig.demo.calls == [] and len(_rows(rig)) == 1


# --- a restart ------------------------------------------------------------------------------------


async def test_an_amend_resumed_after_a_raise_meets_its_rows_and_keeps_the_prior_order(
    rig: Rig,
) -> None:
    """The rows the first attempt left in flight hold the key (23505 on `ux_rs_in_flight`): the
    resumed attempt answers in flight, nothing sent again, so B1 keeps the prior order live."""
    order = await _live(rig)
    rig.demo.script("amend_order", TransportError("cut off"))
    with pytest.raises(TransportError):
        await rig.port.amend(_amend(order, stop_loss="58500"))
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer["error_code"] == STOP_REQUEST_IN_FLIGHT
    assert len(_sent(rig)) == 1 and len(_rows(rig)) == 2


async def test_an_amend_resumed_with_nothing_recorded_records_and_sends(rig: Rig) -> None:
    order = await _live(rig)
    rig.audits.refuse = RuntimeError("the audit did not land")
    with pytest.raises(RuntimeError):
        await rig.port.amend(_amend(order, stop_loss="58500"))
    assert _rows(rig) == [] and rig.demo.calls == []
    rig.audits.refuse = None
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer["ok"] is True and len(_rows(rig)) == 2 and len(_sent(rig)) == 1


# --- native-SL assertions -------------------------------------------------------------------------


@pytest.mark.parametrize("stop", ["0", "-1", "0E-18"])
async def test_no_stop_at_or_below_zero_is_ever_sent(rig: Rig, stop: str) -> None:
    order = await _live(rig)
    answer = await rig.port.amend(_amend(order, stop_loss=stop))
    assert answer == {"ok": False, "error_code": b01.NATIVE_STOP_REQUIRED}
    assert rig.demo.calls == [] and _rows(rig) == []


async def test_a_looser_stop_is_refused_in_the_writer_before_any_record_or_send(rig: Rig) -> None:
    """Q4: audited `orders.amend` denied, never `sl.loosen_refused`; nothing recorded or sent."""
    order = await _live(rig)
    answer = await rig.port.amend(_amend(order, stop_loss="57999"))
    assert answer == {"ok": False, "error_code": STOP_LOOSENING_REFUSED}
    assert rig.demo.calls == [] and _rows(rig) == []
    ((record, _),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord)
    assert (record.action, record.outcome, record.reason) == (
        "orders.amend",
        "denied",
        "looser_than_order",
    )


async def test_a_stop_looser_than_the_record_in_force_is_refused(rig: Rig) -> None:
    order = await _live(rig)
    await _earlier_request(rig)
    (earlier,) = _rows(rig)
    rig.store._stops[earlier.id] = replace(
        earlier, trigger_price=Decimal("58800"), status="in_force", answered_at=T0, in_force_at=T0
    )
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer == {"ok": False, "error_code": STOP_LOOSENING_REFUSED}
    assert rig.demo.calls == [] and rig.audits.actions() == [("orders.amend", "looser_than_record")]


async def test_a_tighter_stop_on_a_short_is_sent(rig: Rig) -> None:
    order = await _live(rig, side="Sell", stop_loss=Decimal("62000"), take_profit=Decimal("57000"))
    answer = await rig.port.amend(_amend(order, stop_loss="61500"))
    assert answer["ok"] is True
    (sent,) = _sent(rig)
    assert sent.stop_loss == Decimal("61500")
    assert {row.position_side for row in _rows(rig)} == {"Sell"}


# --- Q3: the scope of a TP/SL amend ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "terms", "code"),
    [
        ({"cum_exec_qty": Decimal("0.004")}, {"stop_loss": "58500"}, "TPSL_AFTER_FILL"),
        ({"tpsl_mode": "Partial"}, {"take_profit": "65000"}, "TPSL_PARTIAL_MODE"),
        (
            {"reduce_only": True, "intent": "take_profit", "stop_loss": None, "take_profit": None},
            {"take_profit": "65000"},
            "REDUCE_ONLY_TPSL",
        ),
        ({}, {"take_profit": None}, "TPSL_CLEAR_UNSUPPORTED"),
        ({}, {"stop_loss": None}, "NATIVE_STOP_REQUIRED"),
    ],
    ids=["filled", "partial", "reduce_only", "tp_null", "sl_null"],
)
async def test_q3_refusals_answer_their_code_audited_with_nothing_sent(
    rig: Rig, over: dict[str, Any], terms: dict[str, str | None], code: str
) -> None:
    order = await _live(rig, **over)
    answer = await rig.port.amend(_amend(order, **terms))
    assert answer == {"ok": False, "error_code": code}
    assert rig.demo.calls == [] and _rows(rig) == []
    assert rig.audits.actions() == [("orders.amend", code.lower())]


async def test_a_take_profit_change_on_an_order_with_no_stop_is_never_sent_bare(rig: Rig) -> None:
    order = await _live(rig, stop_loss=None)
    answer = await rig.port.amend(_amend(order, take_profit="65000"))
    assert answer == {"ok": False, "error_code": b01.NATIVE_STOP_REQUIRED}
    assert rig.demo.calls == [] and _rows(rig) == []


async def test_a_recorded_stops_row_is_never_amended_here(rig: Rig) -> None:
    order = await _live(rig, provenance="recorded_stop")
    answer = await rig.port.amend(_amend(order, price="60500"))
    assert answer == {"ok": False, "error_code": "ORDER_NOT_AMENDABLE"}
    assert rig.demo.calls == []


@pytest.mark.parametrize(
    "terms",
    [{}, {"qty": "0"}, {"price": "abc"}, {"price": None}, {"leverage": "5"}],
    ids=["none", "zero_qty", "not_decimal", "null_price", "unknown"],
)
async def test_terms_b1_would_not_stage_are_refused_locally(
    rig: Rig, terms: dict[str, str | None]
) -> None:
    order = await _live(rig)
    answer = await rig.port.amend(_amend(order, **terms))
    assert answer == {"ok": False, "error_code": OmsErrorCode.INSTRUMENT_FILTER.value}
    assert rig.demo.calls == []


async def test_a_command_naming_another_order_sends_nothing(rig: Rig) -> None:
    order = await _live(rig)
    with pytest.raises(ValueError, match="another order"):
        await rig.port.amend(command("amend", order, {"price": "1"}, order_link_id="x"))
    assert rig.demo.calls == []
