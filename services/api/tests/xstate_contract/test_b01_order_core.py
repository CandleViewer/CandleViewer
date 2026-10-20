"""B1 `order` binding core (E29-T03 #847): guards (A6), actions, INV-B1-a/b/h, S2-S4, native SL."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.oms.execution import apply_fields
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import Charts, _hang, park, settle
from tests.xstate_contract.b01_ports import Commands, Store

_CHART = Registry().get("order")
PAIRING = ("exchange_order_id", "order_id", "order_link_id", "account_id", "symbol", "side")
FACTS = dict(zip(PAIRING[1:], ("o1", "cvd-link-1", "a1", "BTCUSDT", "buy"), strict=True))
ORDER = FACTS | {"qty": "1", "price": "63000", "stop_loss": "62000"}
GATES = ("risk", "rate", "kill_switch", "live_gate", "native_stop")
REJECT_CODES = dict.fromkeys(GATES) | {"native_stop": "NATIVE_STOP_REQUIRED"}  # per failed verdict
HOSTILE: tuple[str, ...] = ("1" * 21, "0." + "0" * 18 + "1", "1E+100", "1E+100000", "1E+999999999")
HOSTILE += (" 1", "1_0", "\u0661")  # past numeric(38,18), or not C6 text: space, `_`, non-ASCII
MAX = "99999999999999999999.999999999999999999"  # numeric(38,18)'s largest value
MAX_LEAVES = "99999999999999999999.749999999999999999"  # MAX - 0.25
_STAMPED: dict[str, Any] = ORDER | {"trigger_price": None, "take_profit": None, "qty": "0.5"}
_STAMPED |= {"leaves_qty": "0.5", "reduce_only": False}
_X1 = {"ok": True, "exchange_order_id": "x1"}  # the place ack
_KEPT = ("63000", "1", "0.75", 1)  # price, qty, leaves_qty and one ERROR log: not adopted
_REJECT = [{"ok": False, "terms": {"stop_loss": "1", "price": "1"}}]  # ruling 3: a business reject
_CODE_ONLY = [{"ok": False, "error_code": "RATE_LIMITED"}]  # an `OrderAck` refusal, no terms
_RATES = st.sampled_from([Decimal("-0.0001"), Decimal("0.0002"), Decimal("0.00055")])
_FILL = st.tuples(st.decimals(1, 9, places=2), st.decimals(1, 99, places=1), _RATES)


class _Ev:  # an `Event`: its fields ride on `payload`
    def __init__(self, **payload: object) -> None:
        self.payload: dict[str, Any] = payload


class _Done:  # a `DoneEvent`: the service's result rides on `data`
    def __init__(self, data: object = None) -> None:
        self.data = data


class _Fault:  # an `ErrorEvent`: the service's exception rides on `error`
    def __init__(self, error: BaseException) -> None:
        self.error = error


class _Hostile(dict[str, Any]):
    def get(self, *_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def place(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """B1 as the OMS facade wires it (its fill core and a write-ahead store): an ok place ack,
    and a cancel in flight."""
    monkeypatch.setattr(b01, "_core", apply_fields)
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=Store()))
    monkeypatch.setitem(b01.SERVICES, "cancel_order", _hang)
    monkeypatch.setitem(b01.SERVICES, "place_order", placed := AsyncMock(return_value=_X1))
    return placed


def _ctx(**over: object) -> dict[str, Any]:
    c = FACTS | {"exchange_order_id": "x1", "qty": "1", "filled_qty": "0", "leaves_qty": "1"}
    return c | {"avg_price": None, "seen_exec_ids": [], "price": "63000"} | over


def _exec(exec_id: str, qty: object, price: str = "63000", **over: object) -> _Ev:
    fill = {"exchange_order_id": "x1", "exec_id": exec_id, "exec_type": "trade", "fee": "0"}
    return _Ev(**FACTS | fill | {"qty": qty, "price": price, "fee_rate": "0.0002"} | over)


def _validate(gates: dict[str, object] | None = None, /, **order: object) -> _Ev:
    return _Ev(gates=dict.fromkeys(GATES, "pass") | (gates or {}), order=ORDER | order)


async def _run(action: str, ctx: dict[str, Any], event: object) -> dict[str, Any]:
    await b01.ACTIONS[action](None, ctx, event, None)
    return ctx


@pytest.mark.parametrize(
    ("guard", "over", "event", "want"),
    [
        ("exec_new_and_closes", {}, _exec("e1", "1"), True),
        ("exec_new_and_partial", {}, _exec("e1", "1"), False),
        ("exec_new_and_closes", {}, _exec("e1", "0.4"), False),
        ("exec_new_and_partial", {}, _exec("e1", "0.4"), True),
        ("has_fills", {"filled_qty": "0.1"}, None, True),
        ("has_fills", {}, None, False),
        ("ret_code_ok", {}, _Done({"ok": True}), True),
        ("ret_code_ok", {}, _Done({"ok": "true"}), False),
        ("ret_code_ok", {}, _Done(), False),
        ("ret_code_ok_and_has_fills", {"filled_qty": "0.1"}, _Done({"ok": True}), True),
        ("ret_code_ok_and_has_fills", {}, _Done({"ok": True}), False),
        ("ret_code_ok_and_has_fills", {"filled_qty": "0.1"}, _Done({"ok": False}), False),
        ("is_duplicate_link_id", {}, _Done({"error_code": "DUPLICATE_CLIENT_ID"}), True),
        ("is_duplicate_link_id", {}, _Done({"error_code": "RATE_LIMITED"}), False),
    ],
)
def test_a_guard_reads_its_event_and_context(
    guard: str, over: dict[str, Any], event: object, want: bool
) -> None:
    assert b01.GUARDS[guard](_ctx(**over), event) is want


@pytest.mark.parametrize(
    ("over", "event"),
    [
        ({"seen_exec_ids": ["e1"]}, _exec("e1", "0.1")),  # a repeat (S4)
        ({}, _exec("e1", "1.1")),  # an overfill (INV-1, OM-T04)
        ({}, _exec("e1", "0.1", price="0")),
        ({}, _exec("e1", "0.1", fee="-100", fee_rate="-0.0001")),  # past MAX_FEE_RATE
        ({}, _exec("e1", 0.1)),  # a float
        *[({}, _exec("e1", qty)) for qty in HOSTILE],
        ({}, _exec("x" * 65, "0.1")),
        *[({}, _exec("e1", "0.1", **{key: "zz"})) for key in (*PAIRING, "exec_type")],
        ({"exchange_order_id": None}, _exec("e1", "0.1", exchange_order_id=None)),  # unbound
        ({"seen_exec_ids": [str(i) for i in range(b01.MAX_FILLS)]}, _exec("e1", "0.1")),
        ({"filled_qty": "junk"}, _exec("e1", "0.1")),
        ({}, _Done({"exec_id": "e1"})),
    ],
)
def test_exec_guards_deny_what_must_not_apply(over: dict[str, Any], event: object) -> None:
    ctx = _ctx(**over)
    assert not b01.exec_new_and_closes(ctx, event) and not b01.exec_new_and_partial(ctx, event)


def test_exec_guards_deny_every_fill_until_the_oms_sets_its_fill_core() -> None:
    b01.set_fill_core(None)
    with capture_logs() as logs:  # a denial, not a guard failure
        assert (b01.exec_new_and_partial(_ctx(), _exec("e1", "0.4")), logs) == (False, [])


@pytest.mark.parametrize(("seen", "level", "why"), [([], "error", "INV-1"), (["e1"], "info", "S4")])
async def test_a_denied_exec_is_logged_and_audited_once_with_its_exec_id_and_why(
    seen: list[str], level: str, why: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(b01, "_hook", hook := AsyncMock())
    ctx, event = _ctx(seen_exec_ids=seen), _exec("e1", "2")  # an overfill, or a repeat
    with capture_logs() as logs:
        assert not (b01.exec_new_and_closes(ctx, event) or b01.exec_new_and_partial(ctx, event))
        await _run("audit_guard_denied", ctx, event)
    ((name, audited),) = [call.args for call in hook.await_args_list]
    (log,) = logs
    assert (log["log_level"], log["exec_id"], why in log["reason"]) == (level, "e1", True)
    assert (name, audited["denied"]) == ("guard_denied", {"exec_id": "e1", "reason": log["reason"]})


def test_gates_identity_pairing_and_fill_bound_are_pinned_literally() -> None:
    assert (b01.GATES, b01.FACTS, b01.PAIRING, b01.MAX_FILLS) == (GATES, (*FACTS,), PAIRING, 10_000)


@pytest.mark.parametrize(
    ("event", "passes"),
    [
        (_validate(), True),
        *[(_validate({g: v}), False) for g in GATES for v in ("fail", None, True, 1)],
        *[(_Ev(gates={k: "pass" for k in GATES if k != g}, order=ORDER), False) for g in GATES],
        (_validate(qty="0"), False),
        *[(_validate(**{key: v}), False) for key in ("qty", "price") for v in HOSTILE],
        (_validate(stop_loss="-1"), False),
        (_validate(account_id=""), False),
        (_Ev(order=ORDER), False),
    ],
)
def test_passes_all_gates_needs_every_verdict_pass_and_a_well_formed_order(
    event: object, passes: bool
) -> None:
    assert b01.passes_all_gates({}, event) is passes


@pytest.mark.parametrize(("gate", "code"), REJECT_CODES.items())
async def test_native_sl_invariant_no_order_is_placed_unless_every_verdict_passes(
    gate: str, code: str | None, charts: Charts, place: AsyncMock
) -> None:
    """C-2.6 on the library: one verdict `fail` at VALIDATE rejects the order with nothing stamped,
    SEND then places nothing, and only the native-stop verdict records `NATIVE_STOP_REQUIRED`."""
    async with _sent(charts, {gate: "fail"}) as interp:
        assert "order.lifecycle.rejected" in interp.current_state_ids
        default = _CHART["context"] | {"reject_code": code}
        assert (place.await_count, _terms(interp.context)) == (0, _terms(default))
        assert [n["kind"] for n in interp.context["outbox"]] == ["terminal"]


def test_guards_are_total_and_deny_on_hostile_input() -> None:
    for name, guard in b01.GUARDS.items():
        for event in (None, _Ev(order=_Hostile(), gates=_Hostile()), _Done(_Hostile())):
            assert guard(_Hostile(), event) is False, name


@pytest.mark.parametrize(
    ("action", "event", "want"),
    [
        ("stamp_validated", _validate(qty="0.50", stop_loss="62000.0"), _STAMPED),
        ("stamp_validated", _validate({"risk": "fail"}), {}),
        ("apply_fill", _exec("e1", "0.4"), {}),  # refused: the order has no `seen_exec_ids`
        ("adopt_ack", _Done({"ok": True, "exchange_order_id": "x2"}), {}),  # never replaces x1
        ("adopt_cancel_ack", _Done(), {}),  # an ack without an id
        ("map_reject_code", _Done({"error_code": "RATE_LIMITED"}), {"reject_code": "RATE_LIMITED"}),
        ("map_reject_code", _Done({"error_code": "110007"}), {"reject_code": "EXCHANGE_UNKNOWN"}),
        ("map_reject_code", _Done(), {"reject_code": "EXCHANGE_UNKNOWN"}),
    ],
)
async def test_a_context_action_writes_only_its_fields(
    action: str, event: object, want: dict[str, Any]
) -> None:
    start = {"exchange_order_id": "x1"}
    assert await _run(action, dict(start), event) == start | want


@pytest.mark.parametrize(
    ("ack", "want"),
    [
        ({"ok": True, "terms": {"price": "64000", "qty": "0.8"}}, ("64000", "0.8", "0.55", 0)),
        ({"ok": True, "terms": {"qty": "0.25"}}, ("63000", "0.25", "0", 0)),  # qty == filled_qty
        ({"ok": True, "terms": {"qty": MAX}}, ("63000", MAX, MAX_LEAVES, 0)),  # exact at 38 digits
        ({"ok": False, "terms": {"price": "64000"}}, _KEPT),
        ({"ok": True, "terms": {"price": "0"}}, _KEPT),
        ({"ok": True, "terms": {"qty": "0.1"}}, _KEPT),  # under filled_qty (INV-1)
        *[({"ok": True, "terms": {key: v}}, _KEPT) for key in ("qty", "price") for v in HOSTILE],
        ({"ok": True}, _KEPT),
    ],
)
async def test_adopt_amend_adopts_only_an_accepted_well_formed_amend(
    ack: dict[str, Any], want: tuple[object, ...]
) -> None:
    with capture_logs() as logs:
        ctx = await _run("adopt_amend", _ctx(filled_qty="0.25", leaves_qty="0.75"), _Done(ack))
    assert (ctx["price"], ctx["qty"], ctx["leaves_qty"], len(logs)) == want


@settings(max_examples=40, deadline=None, derandomize=True)
@given(fills=st.lists(_FILL, min_size=1, max_size=5), data=st.data())
async def test_inv_b1_a_fills_in_any_order_give_the_same_totals(
    fills: list[tuple[Decimal, Decimal, Decimal]], data: st.DataObject
) -> None:
    events = [
        _exec(f"e{i}", str(q), str(p), fee=str(q * p * r), fee_rate=str(r))
        for i, (q, p, r) in enumerate(fills)
    ]
    totals = []
    for order in (events, data.draw(st.permutations(events * 2))):  # the second: each one twice
        ctx = _ctx(qty="50")
        for event in order:
            await _run("apply_fill", ctx, event)
        totals.append([ctx[k] for k in ("filled_qty", "avg_price", "cum_exec_value", "fee_paid")])
    assert totals[0] == totals[1] and Decimal(totals[0][0]) == sum(q for q, _, _ in fills)


@asynccontextmanager
async def _sent(charts: Charts, gates: dict[str, object] | None = None) -> AsyncIterator[Any]:
    """B1 on the library, real bindings, after VALIDATE (`pass` but *gates*), SEND and an ok ack."""
    interp = (await park("order", _CHART, "lifecycle.draft", charts)).interpreter
    try:
        await interp.send("VALIDATE", wait=True, **_validate(gates).payload)
        await interp.send("SEND", wait=True)
        await settle()
        yield interp
    finally:
        await interp.stop()


@pytest.mark.parametrize("applied", [["e1"], ["e0", "e1"]])  # E1 first, or after E0
async def test_duplicate_fill_never_double_counts(applied: list[str], charts: Charts) -> None:
    """Gherkin "Duplicate fill never double-counts" (INV-B1-b) on the library: E1 for 0.1 applied
    in `submitted` or `partially_filled`, then repeated, leaves the context and the state as is."""
    async with _sent(charts) as interp:
        for exec_id in applied:
            await interp.send("EXEC", wait=True, **_exec(exec_id, "0.1").payload)
        before = copy.deepcopy(interp.context)
        await interp.send("EXEC", wait=True, **_exec("e1", "0.1").payload)
        await settle()
        assert "order.lifecycle.partially_filled" in interp.current_state_ids
        assert (interp.context, before["seen_exec_ids"]) == (before, applied)


@pytest.mark.parametrize(
    ("exec_id", "qty", "state", "leaves", "seen"),
    [
        ("e3", "0.4", "filled", "0", ["e1", "e2", "e3"]),
        ("e3", "0.1", "partially_filled", "0.3", ["e1", "e2", "e3"]),
        ("e2", "0.2", "cancel_pending", "0.4", ["e1", "e2"]),  # a repeat: nothing changes
    ],
)
async def test_cancel_loses_the_race_to_a_fill_not_to_a_repeat(
    exec_id: str, qty: str, state: str, leaves: str, seen: list[str], charts: Charts
) -> None:
    """Gherkin "Cancel loses the race to a fill" (S3) on the library: a closing or a partial EXEC in
    `cancel_pending` applies, a repeat changes nothing (S4); the lost-race record is slice 6's."""
    async with _sent(charts) as interp:
        for event in (_exec("e1", "0.4"), _exec("e2", "0.2", "63100")):
            await interp.send("EXEC", wait=True, **event.payload)
        await interp.send("CANCEL", wait=True)
        await interp.send("EXEC", wait=True, **_exec(exec_id, qty, "63200").payload)
        await settle()
        assert f"order.lifecycle.{state}" in interp.current_state_ids
        assert (interp.context["leaves_qty"], interp.context["seen_exec_ids"]) == (leaves, seen)


_ACKED_UNUSABLE = [{"ok": True, "terms": {"qty": "1E+80"}}]


def _terms(context: dict[str, Any]) -> dict[str, Any]:
    """The order as the context holds it, without the write-ahead cursor and the outbox."""
    return {k: v for k, v in context.items() if k not in ("event_seq", "outbox")}


@pytest.mark.parametrize(("fills", "state"), [(["e1"], "partially_filled"), ([], "submitted")])
@pytest.mark.parametrize("amend", [_hang, _ACKED_UNUSABLE, _REJECT, _CODE_ONLY])
async def test_amend_rejection_does_not_move_the_stop(
    amend: object, fills: list[str], state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "Amend rejection does not move the stop" (S2) on the library, with fills or none:
    an amend rejected (`AMEND_REJECTED`, or a result that is not ok), or acked ok with terms it
    cannot use, is sent once and changes no term of the order; a rejection tells the UI through
    the outbox (`amend_rejected`). Only the write-ahead cursor and the outbox move."""
    monkeypatch.setitem(b01.SERVICES, "amend_order", sent := AsyncMock(side_effect=amend))
    async with _sent(charts) as interp:
        for exec_id in fills:
            await interp.send("EXEC", wait=True, **_exec(exec_id, "0.25").payload)
        before = copy.deepcopy(interp.context)
        for event in ("AMEND", "AMEND_REJECTED"):  # unhandled once the ack has landed: deferred
            await interp.send(event, wait=True)
            await settle()
        assert f"order.lifecycle.{state}" in interp.current_state_ids
        assert (sent.await_count, interp.context["stop_loss"]) == (1, "62000")
        assert _terms(interp.context) == _terms(before)
        notices = [n["kind"] for n in interp.context["outbox"][len(before["outbox"]) :]]
        notices = [kind for kind in notices if kind != "first_fill"]  # a repeat, consumed
        assert notices == ([] if amend is _ACKED_UNUSABLE else ["amend_rejected"])


@pytest.mark.parametrize("recon", ["RECON_FOUND_LIVE", "RECON_FOUND_PARTIAL"])
async def test_inv_b1_h_kill_cancels_a_reconciled_duplicate(
    recon: str, charts: Charts, place: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-B1-h on the library: a duplicate-id place result parks in `unknown`, where a KILL skips
    the cancel; reconciliation finding the order live binds it (`adopt_recon` clears the skip), so
    a KILL then audits ahead of exactly one cancel (#847 slice 4)."""
    trail: list[str] = []

    async def _cancel(*_a: object) -> None:
        trail.append("cancel_order")

    async def _audit(name: str, _ctx: object) -> None:
        trail.append(name)

    place.return_value = {"ok": False, "error_code": "DUPLICATE_CLIENT_ID"}
    ports = b01.OrderPorts(persist=Store(), commands=Commands(on_cancel=_cancel))
    monkeypatch.setattr(b01, "_ports", ports)
    monkeypatch.setattr(b01, "_hook", _audit)
    async with _sent(charts) as interp:
        assert "order.lifecycle.unknown" in interp.current_state_ids
        assert interp.context["kill_skip_cancel"] is True
        for event in (recon, "KILL"):
            await interp.send(event, wait=True)
        await settle()
        assert "order.lifecycle.killed" in interp.current_state_ids
        assert trail == ["halted_by_kill", "cancel_order", "kill_protection_retained"]


# --- #847 slice 5: the context actions' bodies ----------------------------------------------------


@pytest.mark.parametrize(
    ("action", "over", "event", "want"),
    [
        ("bump_recon_misses", {"recon_misses": 1}, None, {"recon_misses": 2}),
        ("bump_recon_misses", {"recon_misses": "junk"}, None, {"recon_misses": 1}),
        ("set_reject_unresolvable", {}, None, {"reject_code": "UNRESOLVED_AFTER_RECONCILE"}),
        ("mark_needs_lookup", {}, None, {"needs_lookup": True}),
        ("record_remote_state", {"recon_misses": 1}, _Ev(), {"recon_misses": 0}),
        ("reserve_rate_token", {}, _Ev(rate_reservation="rr-1"), {"rate_reservation": "rr-1"}),
        ("reserve_rate_token", {}, _Ev(rate_reservation="x" * 65), {"rate_reservation": None}),
        (
            "stage_amend",
            {},
            _Ev(price="64000.10", qty="0.5"),
            {"amend_terms": {"price": "64000.1", "qty": "0.5"}},
        ),
        ("stage_amend", {}, _Ev(price="-1"), {"amend_terms": None}),
        (
            "keep_prior_order_live",
            {"amend_terms": {"price": "1"}},
            _Done({}),
            {"amend_terms": None},
        ),
        (
            "adopt_untracked",
            {"needs_lookup": True, "discovered": True},
            _Ev(),
            {"needs_lookup": False, "discovered": False},
        ),
        ("set_cancel_missing_remote", {}, None, {}),
        ("record_cancel_refused", {}, _Done({"error_code": "ORDER_NOT_FOUND"}), {}),
        ("record_mismatch", {}, _Done({"lookup": {"exchange_order_id": "x9"}}), {}),
        (
            "adopt_remote_cancel",
            {"filled_qty": "0"},
            _Ev(exchange_order_id="x1", cum_exec_qty="0"),
            {},
        ),
    ],
)
async def test_a_slice_5_action_writes_only_its_fields(
    action: str, over: dict[str, Any], event: object, want: dict[str, Any]
) -> None:
    ctx = _ctx(**over)
    before = copy.deepcopy(ctx)
    await _run(action, ctx, event)
    assert ctx == before | want


@pytest.mark.parametrize(
    ("action", "over", "event", "logged"),
    [
        (
            "adopt_remote_cancel",
            {},
            _Ev(exchange_order_id="x9"),
            ["b01_exchange_order_id_mismatch"],
        ),
        ("adopt_remote_cancel", {}, _Ev(cum_exec_qty="0.4"), ["b01_remote_cancel_outran_fills"]),
        ("adopt_remote_cancel", {}, _Ev(cum_exec_qty="junk"), ["b01_remote_cancel_outran_fills"]),
        ("record_mismatch", {}, _Ev(exchange_order_id="x9"), ["b01_link_id_mismatch"]),
        ("record_transport_fault", {}, _Fault(TimeoutError()), ["b01_transport_fault"]),
        ("stage_amend", {}, _Ev(), ["b01_amend_not_staged"]),
        (
            "adopt_cancel_ack",
            {"exchange_order_id": None},
            _Done({"ok": True}),
            ["b01_cancel_ack_unbound"],
        ),
        (
            "adopt_cancel_ack",
            {},
            _Done({"exchange_order_id": "x9"}),
            ["b01_exchange_order_id_mismatch"],
        ),
        ("adopt_cancel_ack", {}, _Done({"exchange_order_id": "x1"}), []),
        (
            "adopt_ack",
            {},
            _Done({"ok": True, "exchange_order_id": "x2"}),
            ["b01_exchange_order_id_mismatch"],
        ),
        ("adopt_ack", {}, _Done({"ok": True, "exchange_order_id": "x1"}), []),
        *[
            (
                "map_reject_code",
                {},
                _Done({"error_code": c}),
                ["b01_ambiguous_outcome_recorded_as_reject"],
            )
            for c in ("TRANSPORT_ERROR", "SERVICE_UNAVAILABLE", "UNKNOWN_STATE")
        ],
        ("map_reject_code", {}, _Done({"error_code": "RATE_LIMITED"}), []),
    ],
)
async def test_a_disagreement_is_logged_at_error_never_adopted(
    action: str, over: dict[str, Any], event: object, logged: list[str]
) -> None:
    """SR-E29-03, OM-S05: an id the order is not bound to is never taken,
    a cancel ack binds nothing, and a code 24 Sec.8.6 routes to reconciliation is flagged."""
    ctx = _ctx(**over)
    with capture_logs() as logs:
        await _run(action, ctx, event)
    assert [(e["event"], e["log_level"]) for e in logs] == [(name, "error") for name in logged]
    assert ctx["exchange_order_id"] == _ctx(**over)["exchange_order_id"]


async def test_a_cancel_ack_never_binds_on_the_library(charts: Charts) -> None:
    """SR-E29-03: a duplicate-id place leaves the order unbound in `unknown`; reconciliation
    finds it live under `x1`; a cancel ack naming a foreign id then binds nothing."""
    ctx = _ctx(exchange_order_id=None)
    await _run("adopt_cancel_ack", ctx, _Done({"ok": True, "exchange_order_id": "x-foreign"}))
    assert ctx["exchange_order_id"] is None


@pytest.mark.parametrize(
    ("payload", "want"),
    [
        ({"exchange_order_id": "x1"}, {"exchange_order_id": "x1"}),
        (
            {"exchange_order_id": "x1", "execution": _exec("e1", "0.4").payload},
            {
                "exchange_order_id": "x1",
                "filled_qty": "0.4",
                "leaves_qty": "0.6",
                "seen_exec_ids": ["e1"],
                "avg_price": "63000",
                "cum_exec_value": "25200",
                "fee_paid": "0",
            },
        ),
    ],
)
async def test_adopt_recon_binds_and_applies_what_it_carries(
    payload: dict[str, Any], want: dict[str, Any]
) -> None:
    """INV-B1-m, OM-R02: the reconciled id binds, an execution the finding carries is applied as an
    EXEC would be, and the KILL cancel and the miss count are re-armed."""
    ctx = _ctx(exchange_order_id=None, kill_skip_cancel=True, needs_lookup=True, recon_misses=1)
    await _run("adopt_recon", ctx, _Ev(**payload))
    flags = {"kill_skip_cancel": False, "needs_lookup": False, "recon_misses": 0}
    assert {k: ctx[k] for k in (*want, *flags)} == want | flags


async def test_record_discovered_records_the_found_order_or_nothing() -> None:
    """S9: an untracked order keeps the identity, terms and id reconciliation found, marked as
    discovered: its stop is the exchange's, not one the OMS requested."""
    ctx: dict[str, Any] = {}
    await _run("record_discovered", ctx, _Ev(order=ORDER | {"exchange_order_id": "x7"}))
    assert ctx == _STAMPED | {
        "qty": "1",
        "leaves_qty": "1",
        "stop_loss": "62000",
        "exchange_order_id": "x7",
        "discovered": True,
    }
    fresh: dict[str, Any] = {}
    with capture_logs() as logs:
        await _run("record_discovered", fresh, _Ev(order=ORDER))  # no exchange id
    assert fresh == {} and [e["event"] for e in logs] == ["b01_discovered_order_refused"]


@pytest.mark.parametrize("hook_name", ["reconcile_anomaly", "operator_command_refused"])
async def test_an_anomaly_or_a_stray_operator_command_is_audited(
    hook_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: each is audited with what was refused, where; the context is unchanged (S6)."""
    monkeypatch.setattr(b01, "_hook", hook := AsyncMock())
    ctx = _ctx()
    await b01.ACTIONS[f"audit_{hook_name}"](None, ctx, _Ev(exec_id="e9"), None)
    ((name, audited),) = [call.args for call in hook.await_args_list]
    assert name == hook_name and audited.items() >= ctx.items()


def test_a_failing_guard_denies_and_logs_once() -> None:
    """A6: a guard that cannot decide denies, with one ERROR naming it."""
    with capture_logs() as logs:
        assert b01.has_fills(_ctx(filled_qty="junk"), None) is False
    assert [(e["event"], e["log_level"], e["guard"]) for e in logs] == [
        ("b01_guard_failed", "error", "has_fills")
    ]


def test_text_and_id_bounds_are_pinned() -> None:
    """A negative zero renders as `0`; an id of 1 and of `MAX_TEXT` characters is
    taken, 0 and `MAX_TEXT + 1` are not."""
    assert b01._text(Decimal("-0")) == "0" and b01._text(Decimal("-0.000")) == "0"
    assert [b01._id("x" * n) is not None for n in (0, 1, 64, 65)] == [False, True, True, False]


async def test_an_exec_before_the_bind_waits_and_is_logged_below_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-E29-03: an EXEC for an order with no bound id is refused as `UNBOUND`, at
    INFO, for the facade's reorder buffer, never answered with `FAULT`."""
    monkeypatch.setattr(b01, "_hook", AsyncMock())
    ctx = _ctx(exchange_order_id=None)
    with capture_logs() as logs:
        await _run("audit_guard_denied", ctx, _exec("e1", "0.1"))
    assert [(e["log_level"], e["reason"]) for e in logs] == [("info", b01.UNBOUND)]


@pytest.mark.parametrize("term", ["price", "stop_loss", "take_profit", "trigger_price"])
async def test_an_amend_of_one_term_changes_that_term_alone(term: str) -> None:
    """S2: `qty` absent, the order's own `qty` and `leaves_qty` stand."""
    ctx = _ctx(filled_qty="0.25", leaves_qty="0.75")
    before = copy.deepcopy(ctx)
    await _run("adopt_amend", ctx, _Done({"ok": True, "terms": {term: "61000"}}))
    assert ctx == before | {term: "61000", "amend_terms": None}


@pytest.mark.parametrize(("fills", "state"), [(["e1"], "partially_filled"), ([], "submitted")])
async def test_an_accepted_amend_moves_the_terms_on_the_library(
    fills: list[str], state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2's positive twin: an ok amend through the real result arms adopts its terms
    into the live state it came from, with fills (`ret_code_ok_and_has_fills`) and without."""
    terms = {"price": "64000", "stop_loss": "62500"}
    monkeypatch.setitem(
        b01.SERVICES, "amend_order", AsyncMock(return_value={"ok": True, "terms": terms})
    )
    async with _sent(charts) as interp:
        for exec_id in fills:
            await interp.send("EXEC", wait=True, **_exec(exec_id, "0.25").payload)
        await interp.send("AMEND", wait=True, **terms)
        await settle()
        assert f"order.lifecycle.{state}" in interp.current_state_ids
        assert (interp.context["price"], interp.context["stop_loss"]) == ("64000", "62500")
        assert interp.context["amend_terms"] is None


async def test_inv_b1_h_kill_cancels_nothing_under_an_unverified_duplicate(
    charts: Charts, place: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-B1-h: a KILL straight after a duplicate-id place result, with no
    reconciliation between, cancels nothing and audits why: the id may not be ours."""
    trail: list[str] = []

    async def _audit(name: str, _ctx: object) -> None:
        trail.append(name)

    commands = Commands()
    place.return_value = {"ok": False, "error_code": "DUPLICATE_CLIENT_ID"}
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=Store(), commands=commands))
    monkeypatch.setattr(b01, "_hook", _audit)
    async with _sent(charts) as interp:
        assert "order.lifecycle.unknown" in interp.current_state_ids
        await interp.send("KILL", wait=True)
        await settle()
        assert "order.lifecycle.killed" in interp.current_state_ids
        assert commands.sent == []
        assert trail == [
            "halted_by_kill",
            "kill_no_cancel_unverified_duplicate",
            "kill_protection_retained",
        ]
