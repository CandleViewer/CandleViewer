"""B1 `order` binding core (E29-T03 #847), a member of the contract gate beside test_b01_order.py:
guards pure, total and deny-by-default (A6), each context action's effect on `context`, INV-B1-a
and INV-B1-b, and S2, S3 and S4 at the binding and on the library."""

from __future__ import annotations

import asyncio
import copy
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import Charts, park, settle

_CHART = Registry().get("order")
LINK = "cvd-link-1"
ORDER = {"order_id": "o1", "order_link_id": LINK, "account_id": "a1", "symbol": "BTCUSDT"}
ORDER |= {"side": "buy", "qty": "1", "price": "63000"}


class _Ev:  # an `Event`: its fields ride on `payload`
    def __init__(self, **payload: object) -> None:
        self.payload: dict[str, Any] = payload


class _Done:  # a `DoneEvent` (`data`) or an `ErrorEvent` (`error`)
    def __init__(self, data: object = None, error: object = None) -> None:
        self.data, self.error = data, error


class _Hostile(dict[str, Any]):
    def get(self, *_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("boom")


def _ctx(**over: object) -> dict[str, Any]:
    c = {"order_link_id": LINK, "qty": "1", "filled_qty": "0", "leaves_qty": "1"}
    return c | {"avg_price": None, "seen_exec_ids": [], "recon_misses": 0, "price": "63000"} | over


def _exec(
    exec_id: str, qty: object, price: str = "63000", fee: str = "0", link: object = LINK
) -> _Ev:
    return _Ev(exec_id=exec_id, order_link_id=link, qty=qty, price=price, fee=fee)


def _validate(gates: dict[str, object] | None = None, **order: object) -> _Ev:
    return _Ev(gates=dict.fromkeys(b01.GATES, True) | (gates or {}), order=ORDER | order)


async def _run(action: str, ctx: dict[str, Any], event: object) -> dict[str, Any]:
    await b01.ACTIONS[action](None, ctx, event, None)
    return ctx


@pytest.mark.parametrize(("qty", "closes"), [("0.4", False), ("1", True)])
def test_exec_guards_admit_a_new_fill_by_its_outcome(qty: str, closes: bool) -> None:
    assert b01.exec_new_and_closes(_ctx(), _exec("e1", qty)) is closes
    assert b01.exec_new_and_partial(_ctx(), _exec("e1", qty)) is not closes


@pytest.mark.parametrize(
    ("over", "event"),
    [
        ({"seen_exec_ids": ["e1"]}, _exec("e1", "0.1")),  # a repeat (S4)
        ({}, _exec("e1", "0.1", link="cvd-other")),
        ({}, _exec("e1", "1.1")),  # an overfill (INV-1, OM-T04)
        ({}, _exec("e1", "0.1", price="0")),
        ({}, _exec("e1", 0.1)),  # a float
        ({}, _exec("x" * 65, "0.1")),
        ({"order_link_id": None}, _exec("e1", "0.1", link=None)),
        ({"seen_exec_ids": [str(i) for i in range(b01.MAX_FILLS)]}, _exec("e1", "0.1")),
        ({"filled_qty": "junk"}, _exec("e1", "0.1")),
        ({}, _Done({"exec_id": "e1"})),
    ],
)
def test_exec_guards_deny_what_must_not_apply(over: dict[str, Any], event: object) -> None:
    ctx = _ctx(**over)
    assert not b01.exec_new_and_closes(ctx, event) and not b01.exec_new_and_partial(ctx, event)


@pytest.mark.parametrize(
    ("guard", "over", "event", "expected"),
    [
        ("has_fills", {"filled_qty": "0.1"}, None, True),
        ("has_fills", {}, None, False),
        ("ret_code_ok", {}, _Done({"ok": True}), True),
        ("ret_code_ok", {}, _Done({"ok": "true"}), False),
        ("ret_code_ok", {}, _Done(), False),
        ("is_duplicate_link_id", {}, _Done({"error_code": "DUPLICATE_CLIENT_ID"}), True),
        ("is_duplicate_link_id", {}, _Done({"error_code": "RATE_LIMITED"}), False),
        ("second_consecutive_miss", {"recon_misses": 1}, None, True),
        ("second_consecutive_miss", {"recon_misses": 0}, None, False),
        ("second_consecutive_miss", {"recon_misses": True}, None, False),
    ],
)
def test_result_and_count_guards(
    guard: str, over: dict[str, Any], event: object, expected: bool
) -> None:
    assert b01.GUARDS[guard](_ctx(**over), event) is expected


@pytest.mark.parametrize(
    ("event", "passes"),
    [
        (_validate(), True),
        (_validate({"native_stop": False}), False),
        (_validate({"risk": None}), False),
        (_validate({"live_gate": "yes"}), False),
        (_validate(qty="0"), False),
        (_validate(stop_loss="-1"), False),
        (_validate(account_id=""), False),
        (_Ev(order=ORDER), False),
    ],
)
def test_passes_all_gates_needs_every_verdict_and_a_well_formed_order(
    event: object, passes: bool
) -> None:
    assert b01.passes_all_gates({}, event) is passes


def test_guards_are_total_and_deny_on_hostile_input() -> None:
    for name, guard in b01.GUARDS.items():
        for event in (None, _Ev(order=_Hostile(), gates=_Hostile()), _Done(_Hostile())):
            assert guard(_Hostile(), event) is False, name


async def test_stamp_validated_pins_the_order_and_set_local_reject_names_the_reason() -> None:
    ctx = await _run("stamp_validated", {}, _validate(qty="0.50", stop_loss="62E3"))
    terms = {"price": "63000", "trigger_price": None, "take_profit": None, "stop_loss": "62000"}
    assert ctx == ORDER | terms | {"qty": "0.5", "leaves_qty": "0.5"}
    assert await _run("stamp_validated", {}, _validate(qty="0")) == {}  # behind the guard
    native = await _run("set_local_reject", {}, _validate({"native_stop": False}))
    other = await _run("set_local_reject", {}, _validate({"risk": False}))
    assert native["reject_code"] == "NATIVE_STOP_REQUIRED" and other["reject_code"] is None


_FILL = st.tuples(
    *(st.decimals(lo, hi, places=n) for lo, hi, n in ((1, 9, 2), (1, 99, 1), (-1, 1, 4)))
)


@settings(max_examples=40, deadline=None, derandomize=True)
@given(fills=st.lists(_FILL, min_size=1, max_size=5), data=st.data())
async def test_inv_b1_a_fills_in_any_order_give_the_same_totals(
    fills: list[tuple[Decimal, Decimal, Decimal]], data: st.DataObject
) -> None:
    events = [_exec(f"e{i}", str(q), str(p), str(f)) for i, (q, p, f) in enumerate(fills)]
    totals = []
    for order in (events, data.draw(st.permutations(events))):
        ctx = _ctx(qty="50")
        for event in order:
            await _run("apply_fill", ctx, event)
        totals.append([ctx[k] for k in ("filled_qty", "avg_price", "cum_exec_value", "fee_paid")])
    assert totals[0] == totals[1] and Decimal(totals[0][0]) == sum(q for q, _, _ in fills)


async def test_apply_fill_changes_nothing_for_an_exec_the_guards_deny() -> None:
    ctx = _ctx(seen_exec_ids=["e1"])
    assert await _run("apply_fill", copy.deepcopy(ctx), _exec("e1", "0.4")) == ctx  # INV-B1-b


async def _submitted(charts: Charts, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A B1 machine on the library with the real guards and context actions: VALIDATE, SEND and
    an ok place ack take it to `submitted`; a cancel stays in flight."""

    async def _ack(*_a: object) -> dict[str, object]:
        return {"ok": True, "exchange_order_id": "x1"}

    async def _hang(*_a: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setitem(b01.SERVICES, "place_order", _ack)
    monkeypatch.setitem(b01.SERVICES, "cancel_order", _hang)
    interp = (await park("order", _CHART, "lifecycle.draft", charts)).interpreter
    await interp.send("VALIDATE", wait=True, **_validate().payload)
    await interp.send("SEND", wait=True)
    await settle()
    assert "order.lifecycle.submitted" in interp.current_state_ids
    return interp


async def test_inv_b1_b_a_repeated_exec_id_changes_nothing(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp = await _submitted(charts, monkeypatch)
    try:
        await interp.send("EXEC", wait=True, **_exec("e1", "0.4").payload)
        before = copy.deepcopy(interp.context)
        await interp.send("EXEC", wait=True, **_exec("e1", "0.4").payload)
        assert interp.context == before and before["filled_qty"] == "0.4"
        assert "order.lifecycle.partially_filled" in interp.current_state_ids
    finally:
        await interp.stop()


async def test_cancel_loses_the_race_to_a_fill(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "Cancel loses the race to a fill" (S3), partial, partial then full, on the library:
    the closing EXEC in `cancel_pending` fills the order."""
    interp = await _submitted(charts, monkeypatch)
    try:
        for event in (_exec("e1", "0.4"), _exec("e2", "0.2", "63100")):
            await interp.send("EXEC", wait=True, **event.payload)
        await interp.send("CANCEL", wait=True)
        await settle()
        assert "order.lifecycle.cancel_pending" in interp.current_state_ids
        await interp.send("EXEC", wait=True, **_exec("e3", "0.4", "63200").payload)
        await settle()
        assert "order.lifecycle.filled" in interp.current_state_ids
        ctx = interp.context
        assert (ctx["filled_qty"], ctx["leaves_qty"], ctx["avg_price"]) == ("1", "0", "63100")
        assert (ctx["seen_exec_ids"], ctx["exchange_order_id"]) == (["e1", "e2", "e3"], "x1")
    finally:
        await interp.stop()


async def test_adopt_records_the_exchange_order_id_once_and_recon_ends_the_misses() -> None:
    ctx = await _run("adopt_ack", _ctx(recon_misses=1), _Done({"exchange_order_id": "x1"}))
    await _run("adopt_cancel_ack", ctx, _Done({"ok": True, "exchange_order_id": "x2"}))
    await _run("adopt_recon", ctx, _Ev(exchange_order_id=None))
    assert (ctx["exchange_order_id"], ctx["recon_misses"]) == ("x1", 0)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"ok": True, "terms": {"price": "64000", "qty": "0.8"}}, ("64000", "0.8", "0.55")),
        ({"ok": False, "terms": {"price": "64000"}}, ("63000", "1", "0.75")),
        ({"ok": True, "terms": {"price": "0"}}, ("63000", "1", "0.75")),
        ({"ok": True, "terms": {"qty": "0.1"}}, ("63000", "1", "0.75")),  # under filled_qty
        ({"ok": True}, ("63000", "1", "0.75")),
    ],
)
async def test_adopt_amend_adopts_only_an_accepted_well_formed_amend(
    result: dict[str, Any], expected: tuple[str, str, str]
) -> None:
    ctx = await _run("adopt_amend", _ctx(filled_qty="0.25", leaves_qty="0.75"), _Done(result))
    assert (ctx["price"], ctx["qty"], ctx["leaves_qty"]) == expected


async def test_amend_rejection_does_not_move_the_stop() -> None:
    """Gherkin "Amend rejection does not move the stop" (S2) at the binding: price 63000 stays."""
    ctx = _ctx(stop_loss="62000")
    before = copy.deepcopy(ctx)
    await _run("keep_prior_order_live", ctx, _Ev(error_code="INSUFFICIENT_MARGIN"))
    assert ctx == before and ctx["price"] == "63000"


@pytest.mark.parametrize(
    ("code", "expected"),
    [("RATE_LIMITED", "RATE_LIMITED"), ("110007", "EXCHANGE_UNKNOWN"), (None, "EXCHANGE_UNKNOWN")],
)
async def test_map_reject_code_keeps_a_taxonomy_code(code: object, expected: str) -> None:
    ctx = await _run("map_reject_code", {}, _Done({"ok": False, "error_code": code}))
    assert ctx["reject_code"] == expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("echoed signed request"), "TimeoutError"),
        (None, "unknown"),
        (type("bad name", (Exception,), {})(), "unknown"),
    ],
)
async def test_record_transport_fault_keeps_the_class_name(error: object, expected: str) -> None:
    ctx = await _run("record_transport_fault", {}, _Done(error=error))
    assert ctx == {"transport_fault": expected}


async def test_recon_misses_count_up_and_the_second_rejects_the_order_unresolvable() -> None:
    ctx = await _run("bump_recon_misses", {"recon_misses": 0}, None)
    await _run("set_reject_unresolvable", ctx, None)
    assert ctx == {"recon_misses": 2, "reject_code": "UNRESOLVED_AFTER_RECONCILE"}
