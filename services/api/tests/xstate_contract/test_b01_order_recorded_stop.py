"""B1 `order`, chart version 4 (#913, E29-T04's contract PR; CR-G6-R3-01 on #3972): the entry of a
recorded stop's row, the OMS-owned row of a TP/SL order that enters outside the placement path
(24-internal-schemas.md Sec.8.3 rule 7, Sec.8.8 rule 6; INV-B1-p). On the library with the real
binding, the step writer and the in-memory stores, and through the OMS facade, the five things
rule 7 asks of it: the entry sends nothing; the row takes `submitted`, a live state, whatever its
order's exchange status, so its fills apply as steps; each fill is committed as a live row's is
(`commit_fill`); KILL never cancels it, a CANCEL reaches it only through the cancel service, and
the facade refuses an AMEND of it; recovery replays it from its first row. Chart version 5 (#848,
E29-T05's contract-first PR) adds rule 7's sixth: the row's trigger price and quantity follow its
order's through `TERMS_CHANGED`, a written step (INV-B1-q)."""

from __future__ import annotations

import contextlib
import copy
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs
from xstate_statemachine import SimulatedClock
from xstate_statemachine.exceptions import InvalidEventPayloadError

from candleviewer.oms import ExecutionRepository, IllegalTransition, OrderRepository
from candleviewer.oms.execution import apply_fields
from candleviewer.oms.fakes import InMemoryExecutionStore, InMemoryOrderStore
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.recovery import RebuiltOrder, rebuild
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import DEFAULT_MACHINES_DIR, Registry
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrder
from tests.unit.oms.order_rig import ACCOUNT, NOW_US, build_rig, gated
from tests.xstate_contract._harness import Charts, exits, instrument, node_at, park, settle, walk
from tests.xstate_contract.b01_ports import Commands, Store

REGISTRY = Registry()
CHART = REGISTRY.get("order")
T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
STOP_ID = UUID(int=0x51)
LINK = "ext-" + "cd" * 16  # the id 24 Sec.8.3 "Adopted rows" gives such a row (`EXT_ID`)
EXCHANGE_ID = "x-sl-51"
#: The TP/SL order of a recorded stop-loss side of a long: Market on trigger, it only closes.
STOP: dict[str, Any] = {
    "order_id": str(STOP_ID), "order_link_id": LINK, "account_id": str(ACCOUNT),
    "symbol": "BTCUSDT", "side": "sell", "qty": "1", "price": None, "trigger_price": "62000",
    "take_profit": None, "stop_loss": None, "reduce_only": True, "exchange_order_id": EXCHANGE_ID,
}  # fmt: skip
#: The live states a recorded stop's row can reach from `submitted` (INV-B1-p); `held` audits.
LIVE = (
    "submitted", "triggered", "partially_filled", "cancel_pending", "amend_pending", "unknown",
    "quarantined",
)  # fmt: skip
SPARED = {"guard": "is_recorded_stop", "actions": ["audit_kill_spared_recorded_stop"]}
_DROP = object()


def _stop(**over: Any) -> NewOrder:
    """The row E29-T05 registers for the TP/SL order of a recorded stop (24 Sec.8.3 rule 7)."""
    fields: dict[str, Any] = {
        "id": STOP_ID, "exchange_account_id": ACCOUNT, "order_link_id": LINK,
        "symbol": "BTCUSDT", "side": "Sell", "intent": "stop_loss", "order_type": "Market",
        "qty": Decimal(1), "trigger_price": Decimal(62000), "reduce_only": True,
        "close_on_trigger": True, "tpsl_mode": "Partial", "exchange_order_id": EXCHANGE_ID,
    }  # fmt: skip
    return NewOrder(**fields | over)


def _fill(exec_id: str, qty: str) -> dict[str, Any]:
    """A trade of the stop's exchange order, every field it pairs on the row's (SR-E29-03)."""
    pairing = {key: STOP[key] for key in ("order_id", "order_link_id", "account_id", "symbol")}
    fill: dict[str, Any] = pairing | {"side": "sell", "exec_id": exec_id, "qty": qty}
    fill |= {"exchange_order_id": EXCHANGE_ID, "exec_type": "trade", "price": "62000"}
    return fill | {"fee": "0", "fee_rate": "0.00055", "ts_exec": NOW_US}


@dataclass
class Book:
    """The OMS side of one test: the in-memory stores behind the real step writer, the command
    port, and the names of B1's audit records."""

    store: InMemoryOrderStore
    fills: InMemoryExecutionStore
    commands: Commands
    records: list[str] = field(default_factory=list)

    async def audit(self, name: str, _context: dict[str, Any]) -> None:
        self.records.append(name)

    async def events(self) -> list[tuple[str, str, str | None, str | None]]:
        rows = await self.store.list_for_order(ACCOUNT, STOP_ID)
        return [(e.kind, e.source, e.from_state, e.to_state) for e in rows]


@contextlib.contextmanager
def _booked() -> Iterator[Book]:
    """B1's ports wired to the real step writer over fresh stores, the stop's row registered."""
    store = InMemoryOrderStore(clock=lambda: T0)
    fills = InMemoryExecutionStore(store)
    writer = OrderStepWriter(OrderRepository(store), ExecutionRepository(fills), clock=lambda: T0)
    writer.expect(_stop())
    book = Book(store, fills, Commands())
    ports = b01.OrderPorts(persist=writer, commands=book.commands, now_us=lambda: NOW_US)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ports", ports)
        mp.setattr(b01, "_core", apply_fields)
        mp.setattr(b01, "_hook", book.audit)
        yield book


@contextlib.asynccontextmanager
async def _machine() -> AsyncIterator[Any]:
    """B1 on the library with its real binding, in `draft`, through the factory."""
    built = await build("order", clock=SimulatedClock(), lane="order", registry=REGISTRY)
    try:
        yield built.interpreter
    finally:
        await built.interpreter.stop()


async def _send(interp: Any, event: str, **payload: Any) -> Any:
    receipt = await interp.send(event, wait=True, **payload)
    await settle()
    return receipt


def _leaf(interp: Any, region: str = "lifecycle") -> str:
    head = f"order.{region}."
    return str(next(s for s in interp.current_state_ids if s.startswith(head)))[len(head) :]


def _arms(node: Mapping[str, Any], event: str) -> list[Mapping[str, Any]]:
    spec = (node.get("on") or {}).get(event)
    return [] if spec is None else spec if isinstance(spec, list) else [spec]


# --- (1) The entry sends nothing ------------------------------------------------------------------


def test_the_entry_is_taken_only_in_draft_and_invokes_no_service() -> None:
    """Rule 7 (1): `MATERIALISED` is taken only in `draft`, as `VALIDATE` and `DISCOVERED` are, and
    its one arm enters `submitted`, which invokes no service, so the entry sends nothing."""
    taking = [path for path, node in walk(CHART) if _arms(node, "MATERIALISED")]
    assert taking == ["lifecycle.draft"]
    [arm] = _arms(node_at(CHART, "lifecycle.draft"), "MATERIALISED")
    assert arm == {"target": "#order.lifecycle.submitted", "actions": ["record_materialised"]}
    submitted = node_at(CHART, "lifecycle.submitted")
    assert "invoke" not in submitted and submitted["entry"] == ["persist_event"]
    assert (CHART["version"], CHART["context"]["recorded_stop"]) == (7, False)  # 7: #914


@pytest.mark.parametrize(
    ("extra", "source"),
    [({}, "ws_private"), ({"pass_id": "p1", "source": "reconcile"}, "reconcile")],
    ids=["private_stream", "reconciliation"],
)
async def test_a_materialised_stop_is_written_submitted_and_bound_with_nothing_sent(
    extra: dict[str, str], source: str
) -> None:
    """Rule 7 (1) and (2): the row's first `order_events` row is `submitted`'s, bound at entry to
    its order's exchange id, from the path that met it; nothing is sent and no notice is posted."""
    with _booked() as book:
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP, **extra)
            context = interp.context
            assert _leaf(interp) == "submitted" and context["recorded_stop"] is True
            assert (context["exchange_order_id"], context["reduce_only"]) == (EXCHANGE_ID, True)
            assert (context["persisted_state"], context["event_seq"]) == ("submitted", 0)
            assert (book.commands.sent, context["outbox"]) == ([], [])
        row = await book.store.get(ACCOUNT, STOP_ID)
        assert row is not None and (row.state, row.lifecycle_state) == ("accepted", "submitted")
        assert (row.exchange_order_id, row.reduce_only, row.close_on_trigger) == (
            EXCHANGE_ID,
            True,
            True,
        )
        assert row.trade_group_leg_id is None
        assert await book.events() == [("exchange_push", source, None, "accepted")]


@pytest.mark.parametrize(
    "change",
    [
        {"reduce_only": False},
        {"reduce_only": _DROP},
        {"exchange_order_id": _DROP},
        {"exchange_order_id": "x\x01y"},
    ],
    ids=["not_reduce_only", "no_reduce_only", "no_exchange_id", "control_char_id"],
)
async def test_a_stop_order_b1_cannot_keep_is_refused_with_nothing_written(
    change: dict[str, Any],
) -> None:
    """A TP/SL order only closes its position and is bound at entry: one that is not reduce-only,
    or names no exchange order id B1 can keep (`text_id`), is stamped nothing by
    `record_materialised`, so its first row write refuses it and the machine stays in `draft`
    (S7), with nothing written or sent."""
    order = {key: value for key, value in (STOP | change).items() if value is not _DROP}
    with _booked() as book, capture_logs() as logs:
        async with _machine() as interp:
            receipt = await _send(interp, "MATERIALISED", order=order)
            assert _leaf(interp) == "draft" and receipt.error is not None
            assert (interp.context["recorded_stop"], book.commands.sent) == (False, [])
        assert await book.store.get(ACCOUNT, STOP_ID) is None
    assert "b01_recorded_stop_refused" in [entry["event"] for entry in logs]


@pytest.mark.parametrize("bad", [{"exchange_order_id": "x" * 65}, {"surprise": 1}])
async def test_a_payload_the_closed_schema_refuses_never_reaches_the_machine(
    bad: dict[str, Any],
) -> None:
    """28 B1.8 version 3 (g): `MATERIALISED`'s payload is closed and typed, so an id longer than
    B1 keeps or an unknown key is refused at `send()`, before any action."""
    with _booked():
        async with _machine() as interp:
            before = copy.deepcopy(interp.context)
            with pytest.raises(InvalidEventPayloadError):
                await interp.send("MATERIALISED", wait=True, order=STOP | bad)
            assert interp.context == before


@pytest.mark.parametrize("source", ["rest", "paper"])
async def test_a_recorded_stop_is_met_only_on_the_private_stream_or_by_reconciliation(
    source: str,
) -> None:
    """24 Sec.8.2: `MATERIALISED` is the exchange fact of the TP/SL order, `exchange_push` from
    `ws_private`, or from `reconcile` as its payload names, so its closed schema admits only those
    two sources and refuses any other at `send()`, before any action."""
    assert b01.SCHEMAS["MATERIALISED"]["properties"]["source"] == {
        "enum": ["ws_private", "reconcile"]
    }
    with _booked():
        async with _machine() as interp:
            before = copy.deepcopy(interp.context)
            with pytest.raises(InvalidEventPayloadError):
                await interp.send("MATERIALISED", wait=True, order=STOP, source=source)
            assert interp.context == before


# --- (2), (3) A live state whatever its order's status, and each fill committed -----------------


@pytest.mark.parametrize(
    "fills", [[("e1", "1")], [("e1", "0.4"), ("e2", "0.6")]], ids=["fired", "in_parts"]
)
async def test_a_recorded_stops_fills_are_committed_as_a_live_rows(
    fills: list[tuple[str, str]],
) -> None:
    """Rule 7 (2) and (3): whatever its order's status when first seen (a stop that fired before
    then included), every fill takes `submitted`'s or `partially_filled`'s `EXEC` arm and is
    committed by `commit_fill`, its `executions` row with a fill event, to `partially_filled` and
    `filled`, never as an S6 anomaly. A TP/SL only closes its position, so no fill starts the
    `protection` region (INV-B1-o) and nothing is sent."""
    with _booked() as book:
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            for n, (exec_id, qty) in enumerate(fills, start=1):
                await _send(interp, "EXEC", **_fill(exec_id, qty))
                assert _leaf(interp) == ("filled" if n == len(fills) else "partially_filled")
                stored = await book.fills.get(ACCOUNT, exec_id)
                assert stored is not None and stored.order_id == STOP_ID
                assert stored.exec_qty == Decimal(qty)
            assert _leaf(interp, "protection") == "not_required"
            assert [notice["kind"] for notice in interp.context["outbox"]] == ["terminal"]
            assert (book.records, book.commands.sent) == ([], [])
        row = await book.store.get(ACCOUNT, STOP_ID)
        assert row is not None and (row.state, row.cum_exec_qty) == ("filled", Decimal(1))
        kinds = [kind for kind, _source, _from, _to in await book.events()]
        assert kinds == ["exchange_push", *["partial_fill"] * (len(fills) - 1), "fill"]


# --- (4) KILL never cancels it; a CANCEL only through the cancel service -------------------------


def _reach(start: str) -> set[str]:
    """The `lifecycle` states a row in *start* reaches through the states' own arms, KILL's
    into `killed` aside, finals included."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        state = todo.pop()
        if state not in seen:
            seen.add(state)
            leaves = (str(t).rsplit(".", 1)[-1] for _e, _g, t in exits(CHART, f"lifecycle.{state}"))
            todo.extend(leaf for leaf in leaves if leaf != "killed")
    return seen


def test_kill_meets_the_guarded_arm_first_in_every_live_state_the_row_reaches() -> None:
    """Rule 7 (4), INV-B1-p: from `submitted` a recorded stop's row can rest in exactly these live
    states and `held`. In each live one the `KILL` group opens with the guarded `is_recorded_stop`
    arm, which only audits, before the arm that cancels (into `killed`) or reuses an in-flight
    cancel, the ordered unguarded fall-through (C-07b); `held` only audits a KILL (INV-B1-n), and
    no other state guards one."""
    states = node_at(CHART, "lifecycle")["states"]
    finals = {name for name, node in states.items() if node.get("type") == "final"}
    assert _reach("submitted") - finals == {*LIVE, "held"}
    for state in LIVE:
        first, rest = _arms(states[state], "KILL")
        assert first == SPARED and "guard" not in rest, state
    assert _arms(states["held"], "KILL") == [{"actions": ["audit_kill_ignored_unowned"]}]
    guarded = {path for path, node in walk(CHART) if any("guard" in a for a in _arms(node, "KILL"))}
    assert guarded == {f"lifecycle.{state}" for state in LIVE}


@pytest.mark.parametrize("state", LIVE)
async def test_kill_spares_a_recorded_stop_in_each_live_state(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 7 (4): with `is_recorded_stop` true, a KILL in each live state is consumed by its
    guarded arm, which only audits: the state stays, nothing is deferred, and no kill action runs,
    neither the cancel nor `mark_halted_by_kill` (C-2.6, INV-B1-i)."""
    rec = instrument("order", monkeypatch, "async_def", guards={"is_recorded_stop": True})
    interp = (await park("order", CHART, f"lifecycle.{state}", charts)).interpreter
    try:
        await settle()
        mark = len(rec.actions)
        await interp.send("KILL", wait=True)
        await settle()
        assert (_leaf(interp), interp.deferred_count) == (state, 0)
        assert sorted(rec.actions[mark:]) == [
            "audit_kill_protection_retained",
            "audit_kill_spared_recorded_stop",
        ]
        assert ("is_recorded_stop", True) in rec.guards
    finally:
        await interp.stop()


async def test_kill_spares_a_materialised_stop_which_still_takes_its_fills() -> None:
    """On the real binding: the KILL is audited (`kill_spared_recorded_stop`), writes no
    `order_events` row (an internal arm, INV-B1-g), sends nothing and leaves `halted_by_kill`
    unset; the row stays live, so the stop's fill still applies."""
    with _booked() as book:
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            await _send(interp, "KILL", reason="kill switch")
            assert (_leaf(interp), interp.context["halted_by_kill"]) == ("submitted", False)
            assert sorted(book.records) == ["kill_protection_retained", "kill_spared_recorded_stop"]
            assert (len(await book.events()), book.commands.sent) == (1, [])
            await _send(interp, "EXEC", **_fill("e1", "1"))
            assert (_leaf(interp), book.commands.sent) == ("filled", [])


async def test_the_kill_switch_spares_a_recorded_stop_through_the_facade() -> None:
    """`OrderMachines.kill` counts a recorded stop's audited KILL as recorded: it answers no
    failure and pages nothing, and the `orders.cancel` record says the cancel was refused
    (`denied`): it was never the KILL's to send."""
    rig = build_rig()
    try:
        assert await rig.facade.materialise(_stop(), environment="demo") == "submitted"
        assert await rig.facade.kill("kill switch") == ()
        assert rig.facade.state(STOP_ID) == ("submitted", "not_required")
        assert (rig.commands.sent, rig.pager.calls) == ([], [])
        spared = [r for r in rig.audit.records if r.reason == "kill_spared_recorded_stop"]
        assert [(r.action, r.outcome, r.severity) for r in spared] == [
            ("orders.cancel", "denied", "info")
        ]
    finally:
        await rig.facade.stop()


def test_cancel_and_amend_carry_no_guard() -> None:
    """28 B1.8 version 4 (d): 24 Sec.8.8 rule 6 is enforced by synchronous code, the OMS's cancel
    and amend services, before anything is sent (C-2.21), so no `CANCEL` or `AMEND` arm is
    guarded."""
    arms = [arm for _p, node in walk(CHART) for e in ("CANCEL", "AMEND") for arm in _arms(node, e)]
    assert arms and [arm for arm in arms if "guard" in arm] == []


@pytest.mark.parametrize(
    ("answer", "leaf"),
    [({"ok": False}, "submitted"), ({"ok": True, "exchange_order_id": EXCHANGE_ID}, "cancelled")],
    ids=["position_open", "position_flat"],
)
async def test_a_cancel_reaches_a_recorded_stop_only_through_the_cancel_service(
    answer: dict[str, Any], leaf: str
) -> None:
    """A CANCEL that reaches the row goes once to the command port's cancel, the OMS's audited
    cancel service (SR-E29-06): its refusal, as while the position is open (24 Sec.8.8 rule 6),
    sends nothing and leaves the row live (INV-B1-j); a cancel the position allows (it is flat)
    ends it `cancelled`. Neither touches `halted_by_kill`."""

    async def cancel(_command: b01.Command) -> Mapping[str, Any]:
        return answer

    with _booked() as book:
        book.commands.on_cancel = cancel
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            await _send(interp, "CANCEL")
            assert (_leaf(interp), book.commands.kinds()) == (leaf, ["cancel"])
            assert interp.context["halted_by_kill"] is False
        row = await book.store.get(ACCOUNT, STOP_ID)
        assert row is not None and row.lifecycle_state == leaf


async def test_the_facade_refuses_an_amend_of_a_recorded_stop_but_not_a_cancel() -> None:
    """24 Sec.8.8 rule 6, 28 B1.8 version 4 (d): a recorded stop changes only through its record,
    so the facade refuses every AMEND of its row, whatever the position, before anything is sent
    or written (`IllegalTransition`, counted); a CANCEL it admits, to the command port's cancel,
    the cancel service, which alone reads the position: refused there, the row stays live."""

    async def refused(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False}

    rig = build_rig()
    rig.commands.on_cancel = refused
    try:
        assert await rig.facade.materialise(_stop(), environment="demo") == "submitted"
        history = await rig.events.list_for_order(ACCOUNT, STOP_ID)
        with pytest.raises(IllegalTransition, match="AMEND is not a transition of submitted"):
            await rig.facade.command(ACCOUNT, STOP_ID, "AMEND", {"qty": "2"}, actor="user")
        assert (rig.commands.sent, rig.count("oms_illegal_transitions_total")) == ([], 1)
        assert await rig.events.list_for_order(ACCOUNT, STOP_ID) == history
        await rig.facade.command(ACCOUNT, STOP_ID, "CANCEL", actor="user")
        await rig.quiet()
        assert (rig.commands.kinds(), rig.facade.state(STOP_ID)) == (
            ["cancel"],
            ("submitted", "not_required"),
        )
    finally:
        await rig.facade.stop()


# --- (5) Recovery replays it from its first row ---------------------------------------------------


@pytest.mark.parametrize(
    ("fills", "pass_id"),
    [((), None), (("0.4",), "p1")],
    ids=["submitted", "partially_filled_by_reconciliation"],
)
async def test_a_recorded_stop_replays_from_its_first_row(
    fills: tuple[str, ...], pass_id: str | None
) -> None:
    """Rule 7 (5), 24 Sec.8.2 Recovery: the fold of a recorded stop's events, from its first row
    (`exchange_push` into `submitted`, bound), equals its row, and after a crash the facade
    hydrates it from that first row: the replayed machine is the one that crashed, configuration
    and context, `recorded_stop` included. Nothing is written, audited, notified or sent (it is
    reduce-only, so no stop is attached again), and a KILL still spares it."""
    rig = build_rig()
    order = _stop()
    assert await rig.facade.materialise(order, environment="demo", pass_id=pass_id) == "submitted"
    for n, qty in enumerate(fills, start=1):
        await rig.facade.push(ACCOUNT, STOP_ID, "EXEC", _fill(f"e{n}", qty))
    await rig.quiet()
    history = await rig.events.list_for_order(ACCOUNT, STOP_ID)
    first = history[0]
    assert (first.seq, first.kind, first.from_state, first.to_state) == (
        0,
        "exchange_push",
        None,
        "accepted",
    )
    assert first.source == ("ws_private" if pass_id is None else "reconcile")
    row = await rig.orders.get(ACCOUNT, STOP_ID)
    assert row is not None and rebuild(history) == RebuiltOrder.of_row(row)
    assert rebuild(history).exchange_order_id == EXCHANGE_ID
    state, context = rig.facade.state(STOP_ID), dict(rig.context(order))
    again = await rig.restart()
    try:
        assert state is not None
        assert await again.facade.hydrate(ACCOUNT, STOP_ID, environment="demo") == state[0]
        await again.quiet()
        assert (again.facade.state(STOP_ID), again.context(order)) == (state, context)
        assert again.context(order)["recorded_stop"] is True
        assert await again.events.list_for_order(ACCOUNT, STOP_ID) == history
        assert (again.audit.records, again.notices.got, again.commands.sent) == ([], [], [])
        assert await again.facade.kill("kill switch") == ()
        assert (again.facade.state(STOP_ID), again.commands.sent) == (state, [])
    finally:
        await again.facade.stop()


# --- INV-B1-p, as a property --------------------------------------------------------------------


@settings(max_examples=25, deadline=None)
@given(triggered=st.booleans(), events=st.lists(st.sampled_from(("KILL", "EXEC")), max_size=8))
async def test_inv_b1_p_a_recorded_stop_is_never_killed_and_keeps_every_fill_property(
    triggered: bool, events: list[str]
) -> None:
    """INV-B1-p: whatever KILLs and fills interleave, after a trigger push or not, a recorded
    stop's row is never `killed`, `halted_by_kill` stays unset and nothing is sent; every KILL
    while it is live is the spared one's record, a KILL once it is filled the final state's; each
    fill is committed with its execution and an order event; no fill starts the `protection`
    region; and only its first row and its steps write `order_events`, never a KILL."""
    b01._ATTEMPTS.clear()  # per example: the autouse reset runs once per test
    with _booked() as book:
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            if triggered:
                await _send(interp, "TRIGGERED", updated_time=1)
            filled, applied, spared, ignored = Decimal(0), 0, 0, 0
            for event in events:
                if event == "KILL":
                    final = filled == 1
                    spared, ignored = spared + (not final), ignored + final
                    await _send(interp, "KILL", reason="kill switch")
                elif filled < 1:
                    applied += 1
                    await _send(interp, "EXEC", **_fill(f"e{applied}", "0.25"))
                    filled += Decimal("0.25")
                assert _leaf(interp) != "killed" and interp.context["halted_by_kill"] is False
            live = "triggered" if triggered else "submitted"
            want = "filled" if filled == 1 else "partially_filled" if filled else live
            assert (_leaf(interp), _leaf(interp, "protection")) == (want, "not_required")
            assert (Decimal(interp.context["filled_qty"]), book.commands.sent) == (filled, [])
            assert book.records.count("kill_spared_recorded_stop") == spared
            assert book.records.count("kill_ignored_terminal") == ignored
        for n in range(1, applied + 1):
            stored = await book.fills.get(ACCOUNT, f"e{n}")
            assert stored is not None and stored.order_id == STOP_ID
        kinds = [kind for kind, _source, _from, _to in await book.events()]
        steps = ["exchange_push"] * (1 + triggered)
        fills = ["partial_fill"] * applied
        if filled == 1:
            fills[-1] = "fill"
        assert kinds == [*steps, *fills]


# --- (6) The terms step (version 5): rule 7's sixth item, INV-B1-q -------------------------------

#: The stop's order on the exchange with another trigger price and quantity, changed in place.
TERMS: dict[str, Any] = {"exchange_order_id": EXCHANGE_ID, "trigger_price": "61000", "qty": "2"}
GROUPED = ("submitted", "triggered", "partially_filled")


async def _to(interp: Any, state: str) -> None:
    """The materialised row moved to *state*: by a trigger push, or by a fill of 0.4."""
    await _send(interp, "MATERIALISED", order=STOP)
    if state == "triggered":
        await _send(interp, "TRIGGERED", updated_time=1)
    elif state == "partially_filled":
        await _send(interp, "EXEC", **_fill("e1", "0.4"))
    assert _leaf(interp) == state


def test_terms_changed_arms_three_live_states_reenter_with_audited_fall_through() -> None:
    """INV-B1-q: only `submitted`, `triggered` and `partially_filled` take `TERMS_CHANGED`, each
    with exactly the guarded arm that re-enters it and the ordered unguarded fall-through (C-07b);
    no region or root names it. The `reenter: true` of each arm is pinned here: without it the arm
    is internal and writes no row, and CV-LINT-REENTER cannot see an absolute self-target
    (#4267)."""
    taking = {path: _arms(node, "TERMS_CHANGED") for path, node in walk(CHART)}
    assert {path for path, arms in taking.items() if arms} == {f"lifecycle.{s}" for s in GROUPED}
    for state in GROUPED:
        guarded: dict[str, Any] = {"target": f"#order.lifecycle.{state}"}
        guarded |= {"guard": "recorded_terms_changed", "reenter": True, "actions": ["adopt_terms"]}
        assert taking[f"lifecycle.{state}"] == [guarded, {"actions": ["audit_terms_refused"]}]
        assert taking[f"lifecycle.{state}"][0]["reenter"] is True
    assert (_arms(CHART, "TERMS_CHANGED"), CHART["version"]) == ([], 7)  # 7: #914


@pytest.mark.parametrize(
    ("extra", "source"),
    [({}, "ws_private"), ({"pass_id": "p1", "source": "reconcile"}, "reconcile")],
    ids=["private_stream", "reconciliation"],
)
@pytest.mark.parametrize("state", GROUPED)
async def test_terms_changed_in_a_live_state_writes_one_step_and_moves_the_terms(
    state: str, extra: dict[str, str], source: str
) -> None:
    """INV-B1-q, INV-B1-g: the push re-enters the row's live state, so its `order_events` row
    (`exchange_push` from the path that met it, the state kept) and the row's `qty`,
    `trigger_price` and generated `leaves_qty` are written with the step; nothing is sent, no
    notice is posted, and the reduce-only row starts no `protection` region (INV-B1-o)."""
    with _booked() as book:
        async with _machine() as interp:
            await _to(interp, state)
            seq, outbox = interp.context["event_seq"], list(interp.context["outbox"])
            await _send(interp, "TERMS_CHANGED", **TERMS, updated_time=2, **extra)
            context = interp.context
            leaves = 2 - Decimal(context["filled_qty"])
            assert (_leaf(interp), context["event_seq"]) == (state, seq + 1)
            assert (context["qty"], context["trigger_price"]) == ("2", "61000")
            assert Decimal(context["leaves_qty"]) == leaves
            assert (book.commands.sent, context["outbox"]) == ([], outbox)
            assert _leaf(interp, "protection") == "not_required"
        row = await book.store.get(ACCOUNT, STOP_ID)
        assert row is not None
        assert (row.qty, row.trigger_price, row.leaves_qty) == (Decimal(2), Decimal(61000), leaves)
        stored = ORDER_STATE_OF[cast(Any, state)]
        assert (await book.events())[-1] == ("exchange_push", source, stored, stored)


async def test_terms_changed_write_refused_rolls_back_keeping_the_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S7, S11: a terms step whose write the store refuses rolls back: the row stays `submitted`
    with its terms, the context is as it was, and no step is stored."""
    store = Store()
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=store, commands=Commands()))
    async with _machine() as interp:
        await _send(interp, "MATERIALISED", order=STOP)
        store.refuse = ValueError("the store refused the step")
        before = copy.deepcopy(interp.context)
        receipt = await _send(interp, "TERMS_CHANGED", **TERMS, updated_time=2)
        assert receipt.error is not None
        assert (_leaf(interp), interp.context) == ("submitted", before)
        assert [step.event for step in store.steps] == ["MATERIALISED"]


@pytest.mark.parametrize(
    ("state", "push"),
    [
        ("submitted", TERMS | {"exchange_order_id": "x-other"}),
        ("submitted", {"exchange_order_id": EXCHANGE_ID, "updated_time": 2}),
        ("submitted", TERMS | {"trigger_price": "0"}),
        ("partially_filled", TERMS | {"qty": "0.3"}),
        ("partially_filled", TERMS | {"qty": "0.4"}),
    ],
    ids=["other_order", "no_term", "zero_term", "under_filled", "equal_filled"],
)
@pytest.mark.parametrize("triggered", [False, True], ids=["untriggered", "triggered"])
async def test_terms_changed_not_taken_changes_nothing_and_records_terms_refused(
    state: str, push: dict[str, Any], triggered: bool
) -> None:
    """INV-B1-q, C-07b: a push the guard denies is consumed by the ordered unguarded arm, never
    deferred: the row, its context and its events stay as they were; it is logged at ERROR and
    recorded as `terms_refused`, never as `guard_denied`, which the OMS answers with `FAULT`. A
    quantity equal to the filled one is refused too (the 2026-10-25 ruling Q1): the row would be
    left with nothing to fill. The same after a trigger push (S1's CODE-2)."""
    with _booked() as book, capture_logs() as logs:
        async with _machine() as interp:
            if triggered:
                await _send(interp, "MATERIALISED", order=STOP)
                await _send(interp, "TRIGGERED", updated_time=1)
                if state == "partially_filled":
                    await _send(interp, "EXEC", **_fill("e1", "0.4"))
                state = _leaf(interp)
            else:
                await _to(interp, state)
            before, events = copy.deepcopy(interp.context), await book.events()
            await _send(interp, "TERMS_CHANGED", **push)
            assert (_leaf(interp), interp.context, interp.deferred_count) == (state, before, 0)
            assert (await book.events(), book.records[-1:]) == (events, ["terms_refused"])
    assert "guard_denied" not in book.records
    assert ("b01_terms_refused", "error") in [(e["event"], e["log_level"]) for e in logs]


async def test_terms_changed_unchanged_repeat_writes_nothing_and_records_nothing() -> None:
    """S4, S5: a redelivered push naming the terms the row now holds is no step and no anomaly:
    the second delivery writes no event and no record, and is logged at INFO only."""
    with _booked() as book, capture_logs() as logs:
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            await _send(interp, "TERMS_CHANGED", **TERMS, updated_time=2)
            events, context = await book.events(), copy.deepcopy(interp.context)
            await _send(interp, "TERMS_CHANGED", **TERMS, updated_time=2)
            assert (await book.events(), interp.context, book.records) == (events, context, [])
    said = [(e["event"], e["log_level"]) for e in logs if e["event"].startswith("b01_terms")]
    assert said == [("b01_terms_unchanged", "info")]


class _Unreadable(Mapping[str, Any]):
    """A push whose every read fails in a way the terms' checks do not foresee."""

    def __getitem__(self, key: str) -> Any:
        raise LookupError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


async def test_terms_refused_on_a_push_it_cannot_read_records_its_class_and_never_raises() -> None:
    """A1, INV-B1-q: the refusal arm is total. A push it cannot read at all is recorded as
    `terms_refused` with the failure's class as its reason and logged at ERROR; the action never
    raises into the machine. Called on the binding's own API (E29-T05's test plan)."""
    seen: list[tuple[str, dict[str, Any]]] = []

    async def hook(name: str, context: dict[str, Any]) -> None:
        seen.append((name, context))

    context = {"recorded_stop": True, "exchange_order_id": EXCHANGE_ID, "order_link_id": LINK}
    event = SimpleNamespace(type="TERMS_CHANGED", payload=_Unreadable())
    b01.set_audit_hook(hook)
    try:
        with capture_logs() as logs:
            await b01.audit_terms_refused(SimpleNamespace(), context, event, None)
    finally:
        b01.set_audit_hook(None)
    [(name, recorded)] = seen
    assert name == "terms_refused"
    assert recorded["denied"] == {"reason": "LookupError", "trigger": "TERMS_CHANGED"}
    said = [(e["event"], e["log_level"], e["reason"]) for e in logs]
    assert said == [("b01_terms_refused", "error", "LookupError")]


@pytest.mark.parametrize(
    "bad",
    [{"surprise": 1}, {"source": "rest"}, {"qty": 2}, {"trigger_price": None}],
    ids=["unknown_key", "rest_source", "int_qty", "null_trigger"],
)
async def test_terms_changed_payload_outside_schema_refused_at_send(bad: dict[str, Any]) -> None:
    """`TERMS_CHANGED`'s payload is closed and typed: money only as decimal text, met only on the
    private stream or by reconciliation; anything else is refused at `send()`, before any
    action."""
    with _booked():
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            before = copy.deepcopy(interp.context)
            with pytest.raises(InvalidEventPayloadError):
                await interp.send("TERMS_CHANGED", wait=True, **(TERMS | bad))
            assert interp.context == before


async def test_terms_changed_during_a_cancel_waits_then_applies_after_the_refusal() -> None:
    """S10: `cancel_pending` has no arm, so the root defers the push while the cancel is in
    flight; the cancel service refuses (the position is open, 24 Sec.8.8 rule 6), the row is live
    again, and the deferred push is taken there as a written step."""
    gate, held = gated({"ok": False})
    with _booked() as book:
        book.commands.on_cancel = held
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            await _send(interp, "CANCEL")
            await _send(interp, "TERMS_CHANGED", **TERMS, updated_time=2)
            assert (_leaf(interp), interp.deferred_count) == ("cancel_pending", 1)
            gate.set()
            await settle()
            assert (_leaf(interp), interp.context["trigger_price"]) == ("submitted", "61000")
        assert (await book.events())[-2:] == [
            ("cancel_ack", "rest", "pending_cancel", "accepted"),
            ("exchange_push", "ws_private", "accepted", "accepted"),
        ]


_TERMS_STEPS = st.lists(
    st.one_of(
        st.tuples(
            st.just("TERMS"),
            st.sampled_from(("0", "0.25", "0.5", "1", "2")),
            st.sampled_from((None, "61000", "62000")),
            st.booleans(),  # foreign: a push of another exchange order
        ),
        st.tuples(st.just("EXEC"), st.sampled_from(("0.25", "0.5")), st.none(), st.just(False)),
    ),
    max_size=8,
)


@settings(max_examples=25, deadline=None)
@given(triggered=st.booleans(), steps=_TERMS_STEPS)
async def test_inv_b1_q_terms_move_only_by_a_written_step_property(
    triggered: bool, steps: list[tuple[str, str, str | None, bool]]
) -> None:
    """INV-B1-q: whatever terms pushes and fills interleave, after a trigger push or not, the row's
    trigger price and quantity are the context's after every event; they change exactly when one
    `exchange_push` step that keeps its state is written, and never for a foreign push, a quantity
    not above zero or one under the filled quantity; INV-1 holds, the row is never killed, nothing
    is sent and its `protection` region stays `not_required`."""
    b01._ATTEMPTS.clear()  # per example: the autouse reset runs once per test
    with _booked() as book:
        async with _machine() as interp:
            await _send(interp, "MATERIALISED", order=STOP)
            if triggered:
                await _send(interp, "TRIGGERED", updated_time=1)
            for n, (kind, qty, trigger, foreign) in enumerate(steps, start=2):
                before, events = dict(interp.context), await book.events()
                if kind == "EXEC":
                    await _send(interp, "EXEC", **_fill(f"e{n}", qty))
                else:
                    push = {"exchange_order_id": "x-foreign" if foreign else EXCHANGE_ID}
                    push |= {"qty": qty} | ({} if trigger is None else {"trigger_price": trigger})
                    await _send(interp, "TERMS_CHANGED", **push, updated_time=n)
                context, written = interp.context, (await book.events())[len(events) :]
                terms = (context["qty"], context["trigger_price"])
                assert 0 <= Decimal(context["filled_qty"]) <= Decimal(context["qty"])
                row = await book.store.get(ACCOUNT, STOP_ID)
                assert row is not None and (row.qty, row.trigger_price) == tuple(
                    map(Decimal, terms)
                )
                moved = terms != (before["qty"], before["trigger_price"])
                steps_kept = [e for e in written if e[0] == "exchange_push" and e[2] == e[3]]
                assert moved == (len(steps_kept) == 1) and (kind == "TERMS" or not moved)
                under = Decimal(qty) <= 0 or Decimal(qty) <= Decimal(before["filled_qty"])
                assert not (moved and (foreign or under))
                assert _leaf(interp) != "killed"
            assert (book.commands.sent, _leaf(interp, "protection")) == ([], "not_required")


async def test_terms_changed_to_a_placed_order_via_facade_audited_anomaly_never_fault() -> None:
    """S6, OM-T04: a `TERMS_CHANGED` the facade delivers to an order that is not a recorded stop's
    is no step: B1's fall-through records `terms_refused`, which the facade writes as
    `oms.reconcile_anomaly` (denied, error) with the refusal and trigger, and the order stays as
    it was, never answered with `FAULT` or quarantined."""
    rig = build_rig()
    try:
        order = await rig.submitted()
        history = await rig.events.list_for_order(ACCOUNT, order.id)
        push = {"exchange_order_id": "x1", "trigger_price": "61000", "qty": "2", "updated_time": 2}
        await rig.facade.push(ACCOUNT, order.id, "TERMS_CHANGED", push)
        await rig.quiet()
        [record] = [r for r in rig.audit.records if r.reason == "terms_refused"]
        assert (record.action, record.outcome, record.severity) == (
            "oms.reconcile_anomaly",
            "denied",
            "error",
        )
        refusal = "the row is not a recorded stop's (24 Sec.8.3 rule 7)"
        assert (record.detail["refusal"], record.detail["trigger"]) == (refusal, "TERMS_CHANGED")
        assert rig.facade.state(order.id) == ("submitted", "not_required")
        assert await rig.events.list_for_order(ACCOUNT, order.id) == history
    finally:
        await rig.facade.stop()


@pytest.mark.parametrize(
    ("lead", "extra"),
    [
        ((), {}),
        (("TRIGGERED", {"updated_time": 1}), {"pass_id": "p1", "source": "reconcile"}),
        (("EXEC", _fill("e1", "0.4")), {}),
    ],
    ids=["submitted", "triggered_by_reconciliation", "partially_filled"],
)
async def test_terms_changed_hydration_replays_the_written_step(
    lead: tuple[Any, ...], extra: dict[str, str]
) -> None:
    """24 Sec.8.2 Recovery: the fold of a history holding the terms step equals the row, its new
    terms included, and after a crash the facade hydrates the machine that crashed, configuration
    and context, replaying the step off B1's table; nothing is written, audited, notified or
    sent."""
    rig, order = build_rig(), _stop()
    try:
        assert await rig.facade.materialise(order, environment="demo") == "submitted"
        if lead:
            await rig.facade.push(ACCOUNT, STOP_ID, *lead)
        terms = TERMS | {"updated_time": 2} | extra
        await rig.facade.push(ACCOUNT, STOP_ID, "TERMS_CHANGED", terms)
        await rig.quiet()
        history = await rig.events.list_for_order(ACCOUNT, STOP_ID)
        last = history[-1]
        assert (last.kind, last.from_state) == ("exchange_push", last.to_state)
        row = await rig.orders.get(ACCOUNT, STOP_ID)
        assert row is not None and rebuild(history) == RebuiltOrder.of_row(row)
        assert (row.qty, row.trigger_price) == (Decimal(2), Decimal(61000))
        state, context = rig.facade.state(STOP_ID), dict(rig.context(order))
    except BaseException:
        await rig.facade.stop()  # B1's ports are process-wide: never left wired (C-2.11)
        raise
    again = await rig.restart()
    try:
        assert state is not None
        assert await again.facade.hydrate(ACCOUNT, STOP_ID, environment="demo") == state[0]
        await again.quiet()
        assert (again.facade.state(STOP_ID), again.context(order)) == (state, context)
        assert await again.events.list_for_order(ACCOUNT, STOP_ID) == history
        assert (again.audit.records, again.notices.got, again.commands.sent) == ([], [], [])
    finally:
        await again.facade.stop()


def test_recorded_terms_changed_guard_total_denies_by_default() -> None:
    """A6: pure and total. An empty context or event is a denial, a context it cannot read is a
    denial logged once at ERROR, and a push of the row's order with new terms is taken."""
    context = copy.deepcopy(CHART["context"]) | {"recorded_stop": True, "qty": "1"}
    context |= {"exchange_order_id": EXCHANGE_ID, "trigger_price": "62000"}
    push = SimpleNamespace(payload=TERMS)
    assert b01.recorded_terms_changed({}, None) is False
    assert b01.recorded_terms_changed(context, None) is False
    with capture_logs() as logs:
        assert b01.recorded_terms_changed(cast(Any, object()), push) is False
    assert [(e["event"], e["guard"]) for e in logs] == [
        ("b01_guard_failed", "recorded_terms_changed")
    ]
    assert b01.recorded_terms_changed(context, push) is True


async def test_adopt_terms_unreadable_push_changes_nothing_and_logs() -> None:
    """A1: the action is total; a push it cannot take, only reachable past the guard, changes
    nothing and is logged at ERROR."""
    context = copy.deepcopy(CHART["context"]) | {"recorded_stop": True}
    context |= {"exchange_order_id": EXCHANGE_ID, "qty": "1", "trigger_price": "62000"}
    before = copy.deepcopy(context)
    with capture_logs() as logs:
        await b01.adopt_terms(None, context, SimpleNamespace(payload={"qty": "2"}), None)
    assert context == before
    assert [entry["event"] for entry in logs] == ["b01_terms_not_adopted"]


# --- The binding: the guard, the action and the first-row rule (A1, A6) -------------------------


def test_is_recorded_stop_is_total_and_true_only_for_the_flag() -> None:
    """A6: pure and total; only `recorded_stop is True` makes it true, and a context it cannot
    read is a denial, logged at ERROR."""
    assert b01.is_recorded_stop({"recorded_stop": True}, None) is True
    for context in ({}, {"recorded_stop": False}, {"recorded_stop": 1}, {"recorded_stop": "true"}):
        assert b01.is_recorded_stop(context, None) is False
    with capture_logs() as logs:
        assert b01.is_recorded_stop(cast(Any, object()), None) is False
    assert [entry.get("guard") for entry in logs] == ["is_recorded_stop"]


async def test_record_materialised_stamps_the_order_bound_and_marks_the_row() -> None:
    context = copy.deepcopy(CHART["context"])
    await b01.record_materialised(None, context, SimpleNamespace(payload={"order": STOP}), None)
    stamped = {key: context[key] for key in ("qty", "leaves_qty", "trigger_price", "price")}
    assert stamped == {"qty": "1", "leaves_qty": "1", "trigger_price": "62000", "price": None}
    assert (context["recorded_stop"], context["reduce_only"]) == (True, True)
    assert (context["exchange_order_id"], context["side"]) == (EXCHANGE_ID, "sell")


@pytest.mark.parametrize(
    "payload",
    [{}, {"order": "x"}, {"order": STOP | {"reduce_only": False}}, {"order": STOP | {"qty": "0"}}],
    ids=["no_order", "not_a_mapping", "not_reduce_only", "no_qty"],
)
async def test_record_materialised_never_raises_and_stamps_nothing_it_cannot_read(
    payload: dict[str, Any],
) -> None:
    """A1: the action is total; an order it cannot read stays unstamped, logged at ERROR, and the
    first row write refuses it."""
    context = copy.deepcopy(CHART["context"])
    with capture_logs() as logs:
        await b01.record_materialised(None, context, SimpleNamespace(payload=payload), None)
    assert context == CHART["context"]
    assert [entry["event"] for entry in logs] == ["b01_recorded_stop_refused"]


@pytest.mark.parametrize(
    ("state", "event", "writes"),
    [
        ("validated", "VALIDATE", True),
        ("untracked", "DISCOVERED", True),
        ("submitted", "MATERIALISED", True),
        ("submitted", "SEND", False),
        ("validated", "MATERIALISED", False),
    ],
)
async def test_only_its_own_event_writes_a_rows_first_step(
    state: str, event: str, writes: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-B1-g: the row's first `order_events` row is the step of `VALIDATE` into `validated`,
    `DISCOVERED` into `untracked` or `MATERIALISED` into `submitted` (`FIRST_ROWS`); no other
    entry of a state writes a first row."""
    store = Store()
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=store))
    interp = SimpleNamespace(current_state_ids=(f"order.lifecycle.{state}",))
    context = copy.deepcopy(CHART["context"]) | {"order_id": str(STOP_ID)}
    await b01.persist_event(interp, context, SimpleNamespace(type=event, payload={}), None)
    assert [step.to_state for step in store.steps] == ([state] if writes else [])


def test_every_chart_keeps_the_layout_prettier_is_told_to_leave_alone() -> None:
    """`.prettierignore` lists the charts because each is `json.dumps(indent=2)` plus a final LF,
    as 28's B<n>.1 blocks hold them; a reflowed chart fails here, not in review."""
    charts = sorted(DEFAULT_MACHINES_DIR.glob("*.machine.json"))
    assert len(charts) == 20
    for path in charts:
        raw = path.read_text(encoding="utf-8")
        assert raw == json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n", path.name
