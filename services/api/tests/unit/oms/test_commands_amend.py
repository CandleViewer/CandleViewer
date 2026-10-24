"""The command port's amend (E29-T04 #913, S4-B2; the orchestrator's Q2 to Q4 and Q11 rulings; 24
Sec.8.8 rules 5 and 6, Sec.8.9; 21 Sec.3.3.11): re-pairing, Q3's scope and Q4's ratchet before any
record or send, both sides recorded ahead as one `entry_attach` insert, settled or left in flight,
a held key answered in flight; no stop at or below zero is ever sent (C-2.6)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.exchange.base.errors import OmsErrorCode, RateBudgetExceededError, TransportError
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.exchange.base.models import AmendOrderRequest, OrderAck
from candleviewer.oms import commands as oc
from candleviewer.oms.order_machine import OrderAuditRecord
from candleviewer.oms.ports import KeyedRecord
from candleviewer.oms_wiring import STOP_REQUEST_BOUND_S
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms.command_rig import T0, T0_US, Rig
from tests.unit.oms.test_commands import _earlier_request

_TP, _SL2 = Decimal("64000"), Decimal("58500")
_NO: dict[str, Any] = {"ok": False}
_REDUCE = {"reduce_only": True, "intent": "take_profit", "stop_loss": None, "take_profit": None}


async def _live(rig: Rig, **over: Any) -> Any:
    """An entry resting at the venue, stored `submitted` as B1's `amend_pending` finds it."""
    order = cr.new_order(**over)
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_order(cr.exchange_order(order), uid="100001")
    return order


def _amend(order: Any, **terms: str | None) -> b01.Command:
    return cr.command("amend", order, terms)


def _rows(rig: Rig) -> list[RecordedStopRow]:
    return sorted(rig.store._stops.values(), key=lambda row: row.kind)


def _sent(rig: Rig) -> list[AmendOrderRequest]:
    return [call.request for call in rig.demo.calls if isinstance(call.request, AmendOrderRequest)]


@pytest.fixture
def rig() -> Rig:
    return cr.build_rig()


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


async def test_a_price_amend_sends_the_terms_alone_and_records_nothing(rig: Rig) -> None:
    """The amend's exit watch gets B1's answer, as the cancel's does; a cancel watch is unspent."""
    order = await _live(rig)
    watch, other = (rig.port.expect_exit(order.id, kind) for kind in ("amend", "cancel"))
    answer = await rig.port.amend(_amend(order, price="60500", qty="0.02"))
    assert answer["ok"] is True and watch.answered and await watch.answer() == answer
    assert not other.answered
    (call,) = rig.demo.calls
    assert call.lane == "entry" and call.request == AmendOrderRequest(
        account=cr.ref(), symbol=cr.SYMBOL, order_link_id=order.order_link_id,
        qty=Decimal("0.02"), price=Decimal("60500"),
    )  # fmt: skip
    assert _rows(rig) == [] and rig.audits.written == []


async def test_a_reduce_only_order_that_reduces_amends_in_the_critical_lane(rig: Rig) -> None:
    order = await _live(rig, **_REDUCE)
    await rig.port.amend(_amend(order, qty="0.005"))
    assert [call.lane for call in rig.demo.calls] == ["critical"]


@pytest.mark.parametrize(
    ("over", "terms", "sent", "kinds"),
    [
        ({}, {"take_profit": "65000"}, (Decimal("65000"), cr.STOP), 2),
        ({}, {"stop_loss": "58500"}, (_TP, _SL2), 2),
        ({"take_profit": None}, {"stop_loss": "58500"}, (None, _SL2), 1),
    ],
    ids=["tp_only_sends_both", "sl_only_sends_both", "a_side_the_order_lacks_is_left_out"],
)
async def test_the_re_pairing_rule(
    rig: Rig, over: dict[str, Any], terms: dict[str, str], sent: tuple[Any, Any], kinds: int
) -> None:
    order = await _live(rig, **over)
    await rig.port.amend(_amend(order, **terms))
    (request,) = _sent(rig)
    assert (request.take_profit, request.stop_loss) == sent and len(_rows(rig)) == kinds


async def test_the_rows_exist_when_the_venue_call_lands(
    rig: Rig, rows_at_send: list[RecordedStopRow]
) -> None:
    """Q2: one request's rows, `entry_attach` with the order's id, in flight when the call lands,
    each audited in the insert's transaction (`sl.modified` / `tp.modified`, reason `amend`)."""
    order = await _live(rig)
    rig.now.us = T0_US + 3_000_000
    answer = await rig.port.amend(_amend(order, stop_loss="58500", take_profit="65000"))
    seen = [(r.kind, r.source, r.order_id, r.answered_at, r.trigger_price) for r in rows_at_send]
    assert seen == [
        ("stop_loss", "entry_attach", order.id, None, _SL2),
        ("take_profit", "entry_attach", order.id, None, Decimal("65000")),
    ]
    assert {(r.status, r.tpsl_mode) for r in rows_at_send} == {("pending", "Full")}
    assert [(r.action, r.reason, sent) for r, sent in rig.audits.written] == [
        ("sl.modified", oc.AMEND_REASON, 0),
        ("tp.modified", oc.AMEND_REASON, 0),
    ]
    for (record, _), row in zip(rig.audits.written, rows_at_send, strict=True):
        assert isinstance(record, KeyedRecord) and record.object_id == row.id
        assert row.audit_record_id == rig.audits.record_id(record.action, str(row.id))
    at = cr.EPOCH + timedelta(microseconds=T0_US + 3_000_000)  # accepted: the rows answered
    assert (
        answer["ok"] is True
        and [(r.status, r.answered_at) for r in _rows(rig)] == [("pending", at)] * 2
    )


async def test_a_refused_amend_voids_its_rows_audited_ahead(rig: Rig) -> None:
    order = await _live(rig)
    rig.demo.script("amend_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "hidden"))
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    codes = {key: answer[key] for key in ("ok", "error_code", "exchange_ret_code")}
    assert codes == _NO | {"error_code": "INSTRUMENT_FILTER", "exchange_ret_code": 110003}
    assert "hidden" not in repr(answer) and [r.status for r in _rows(rig)] == ["void"] * 2
    assert rig.audits.actions()[2:] == [
        ("sl.modified", oc.AMEND_REFUSED),
        ("tp.modified", oc.AMEND_REFUSED),
    ]


async def test_an_amend_whose_send_raises_leaves_its_rows_in_flight(rig: Rig) -> None:
    """Q11: B1 lands the order in `unknown`, never re-sent; the complete read ends the rows, and
    the exit service's watch reads None."""
    order = await _live(rig)
    watch = rig.port.expect_exit(order.id, "amend", request_id=uuid4())
    rig.demo.script("amend_order", TransportError("cut off"))
    with pytest.raises(TransportError):
        await rig.port.amend(_amend(order, stop_loss="58500"))
    assert [(r.status, r.answered_at) for r in _rows(rig)] == [("pending", None)] * 2
    assert watch.answered and await watch.answer() is None


async def test_a_refused_rate_token_voids_the_rows_with_nothing_sent(rig: Rig) -> None:
    order = await _live(rig)
    rig.demo.script("amend_order", RateBudgetExceededError("no token", retry_after_s=2.0))
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer == _NO | {"error_code": "RATE_BUDGET_EXCEEDED", "retry_after_s": 2}
    assert [r.status for r in _rows(rig)] == ["void", "void"]


async def test_one_insert_shares_one_created_at() -> None:
    ticks = iter(T0 + timedelta(seconds=n) for n in range(100))
    rig = cr.build_rig(created_at=lambda: next(ticks))
    order = await _live(rig)
    await rig.port.amend(_amend(order, stop_loss="58500"))
    assert len({row.created_at for row in _rows(rig) if row.source == "entry_attach"}) == 1


@pytest.mark.parametrize("past_bound", [True, False], ids=["waiting", "in_flight"])
async def test_a_held_key_answers_in_flight_and_keeps_the_prior_order(
    rig: Rig, past_bound: bool
) -> None:
    """409 `stop_request_in_flight` at the route: nothing recorded or sent, never a raise."""
    order = await _live(rig)
    await _earlier_request(rig)
    rig.now.us = T0_US + (round(STOP_REQUEST_BOUND_S * 1_000_000) if past_bound else 1_000_000)
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer == _NO | {"error_code": oc.STOP_REQUEST_IN_FLIGHT, "retry_after_s": 5}
    assert rig.demo.calls == [] and len(_rows(rig)) == 1


async def test_an_amend_resumed_after_a_raise_meets_its_rows_and_keeps_the_prior_order(
    rig: Rig,
) -> None:
    """The first attempt's rows hold the key (23505 on `ux_rs_in_flight`): the resumed attempt
    answers in flight with nothing sent again, so B1 keeps the prior order live."""
    order = await _live(rig)
    rig.demo.script("amend_order", TransportError("cut off"))
    with pytest.raises(TransportError):
        await rig.port.amend(_amend(order, stop_loss="58500"))
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer["error_code"] == oc.STOP_REQUEST_IN_FLIGHT
    assert len(_sent(rig)) == 1 and len(_rows(rig)) == 2


async def test_an_amend_resumed_with_nothing_recorded_records_and_sends(rig: Rig) -> None:
    order = await _live(rig)
    rig.audits.refuse = RuntimeError("the audit did not land")
    with pytest.raises(RuntimeError):
        await rig.port.amend(_amend(order, stop_loss="58500"))
    assert _rows(rig) == [] and rig.demo.calls == []
    rig.audits.refuse = None
    assert (await rig.port.amend(_amend(order, stop_loss="58500")))["ok"] is True
    assert len(_rows(rig)) == 2 and len(_sent(rig)) == 1


async def test_a_looser_stop_is_refused_in_the_writer_before_any_record_or_send(rig: Rig) -> None:
    """Q4: audited `orders.amend` denied, never `sl.loosen_refused`; nothing recorded or sent."""
    order = await _live(rig)
    answer = await rig.port.amend(_amend(order, stop_loss="57999"))
    assert answer == _NO | {"error_code": oc.STOP_LOOSENING_REFUSED}
    assert rig.demo.calls == [] and _rows(rig) == []
    ((record, _),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord) and record.outcome == "denied"
    assert (record.action, record.reason) == ("orders.amend", "looser_than_order")


async def test_a_stop_looser_than_the_record_in_force_is_refused(rig: Rig) -> None:
    order = await _live(rig)
    await _earlier_request(rig)
    (row,) = _rows(rig)
    in_force: dict[str, Any] = {"status": "in_force", "answered_at": T0, "in_force_at": T0}
    rig.store._stops[row.id] = replace(row, trigger_price=Decimal("58800"), **in_force)
    answer = await rig.port.amend(_amend(order, stop_loss="58500"))
    assert answer == _NO | {"error_code": oc.STOP_LOOSENING_REFUSED}
    assert rig.demo.calls == [] and rig.audits.actions() == [("orders.amend", "looser_than_record")]


@pytest.mark.parametrize(
    ("over", "terms", "code"),
    [
        ({"cum_exec_qty": Decimal("0.004")}, {"stop_loss": "58500"}, "TPSL_AFTER_FILL"),
        ({"tpsl_mode": "Partial"}, {"take_profit": "65000"}, "TPSL_PARTIAL_MODE"),
        (_REDUCE, {"take_profit": "65000"}, "REDUCE_ONLY_TPSL"),
        ({}, {"take_profit": None}, "TPSL_CLEAR_UNSUPPORTED"),
        ({}, {"stop_loss": None}, "NATIVE_STOP_REQUIRED"),
        ({}, {"stop_loss": "0"}, "NATIVE_STOP_REQUIRED"),  # C-2.6: no stop at or below zero sent
        ({}, {"stop_loss": "-1"}, "NATIVE_STOP_REQUIRED"),
        ({"stop_loss": None}, {"take_profit": "65000"}, "NATIVE_STOP_REQUIRED"),
        ({"provenance": "recorded_stop"}, {"price": "60500"}, "ORDER_NOT_AMENDABLE"),
    ],
)
async def test_refusals_answer_their_code_audited_with_nothing_sent(
    rig: Rig, over: dict[str, Any], terms: dict[str, str | None], code: str
) -> None:
    """Q3's scope, an order with no stop never sent bare, and a recorded stop's row."""
    order = await _live(rig, **over)
    answer = await rig.port.amend(_amend(order, **terms))
    assert answer == _NO | {"error_code": code}
    assert rig.demo.calls == [] and _rows(rig) == []
    assert [action for action, _ in rig.audits.actions()] == ["orders.amend"]


@pytest.mark.parametrize(
    "terms", [{}, {"qty": "0"}, {"price": "abc"}, {"price": None}, {"leverage": "5"}]
)
async def test_terms_b1_would_not_stage_are_refused_locally(
    rig: Rig, terms: dict[str, Any]
) -> None:
    order = await _live(rig)
    answer = await rig.port.amend(_amend(order, **terms))
    assert answer == _NO | {"error_code": OmsErrorCode.INSTRUMENT_FILTER.value}
    assert rig.demo.calls == []
