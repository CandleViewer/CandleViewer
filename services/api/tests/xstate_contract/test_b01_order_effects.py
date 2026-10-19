"""B1 `order` effects (E29-T03 #847 slice 5): the write-ahead step (S7, S8, INV-B1-g), the services
through the OMS's command port (S1, SR-E29-15), the outbox (CV-C25), the deadlines (A2), the guards
that read a lookup or a protection reading, and the closed event schemas."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs
from xstate_statemachine import PluginBase, SimulatedClock
from xstate_statemachine.exceptions import InvalidEventPayloadError

from candleviewer.oms import ExecutionRepository, OrderRepository
from candleviewer.oms.execution import apply_fields
from candleviewer.oms.fakes import InMemoryExecutionStore, InMemoryOrderStore
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.plugins import CvErrorHooks
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, LifecycleState, NewOrder
from tests.xstate_contract._harness import AuditTap, Charts, settle
from tests.xstate_contract.b01_ports import Commands, Store

CHART = Registry().get("order")
ACCOUNT, ORDER_ID = UUID(int=0xA1), UUID(int=0x01)
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # 24 Sec.8.3's example id
T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
ORDER = {"order_id": str(ORDER_ID), "order_link_id": LINK, "account_id": str(ACCOUNT)}
ORDER |= {"symbol": "BTCUSDT", "side": "buy", "qty": "1", "price": "63000", "stop_loss": "62000"}
VALIDATE: dict[str, Any] = {"gates": dict.fromkeys(b01.GATES, b01.PASSED), "order": ORDER}
VALIDATE["rate_reservation"] = "rr-1"


def _exec(exec_id: str, qty: str, **over: object) -> dict[str, Any]:
    """An `EXEC` payload: a 24 Sec.8.1 `Execution` of the order, bound as `x1`."""
    pairing = {k: ORDER[k] for k in ("order_id", "order_link_id", "account_id", "symbol", "side")}
    fill: dict[str, Any] = {"exec_id": exec_id, "exchange_order_id": "x1", "qty": qty}
    fill["exec_type"] = "trade"
    fill |= {"price": "63000", "fee": "0", "fee_rate": "0.0002", "ts_exec": 1_789_134_000_000_000}
    return pairing | fill | over


def _new_order() -> NewOrder:
    """The order E29-T04's pipeline builds and registers before it sends `VALIDATE`."""
    return NewOrder(
        id=ORDER_ID,
        exchange_account_id=ACCOUNT,
        order_link_id=LINK,
        symbol="BTCUSDT",
        side="Buy",
        intent="entry",
        order_type="Limit",
        qty=Decimal(1),
        price=Decimal(63000),
        stop_loss=Decimal(62000),
    )


class _Seen(PluginBase[Any]):
    """Records the lifecycle state each committed step makes observable."""

    def __init__(self, trail: list[tuple[str, str]]) -> None:
        self.trail = trail

    def on_transition(self, interpreter: Any, from_states: Any, to_states: Any, tr: Any) -> None:
        leaf = b01._leaf(interpreter)
        if leaf is not None and (not self.trail or self.trail[-1] != ("seen", leaf)):
            self.trail.append(("seen", leaf))


@dataclass
class Book:
    """The OMS side of one test: the in-memory stores behind the step writer, the command port,
    and the write and observe trail."""

    store: InMemoryOrderStore
    writer: OrderStepWriter
    commands: Commands
    trail: list[tuple[str, str]] = field(default_factory=list)

    async def persist(self, step: b01.Step) -> int:
        seq = await self.writer(step)
        self.trail.append(("written", step.to_state))
        return seq


@pytest.fixture
def book(monkeypatch: pytest.MonkeyPatch) -> Book:
    store = InMemoryOrderStore(clock=lambda: T0)
    orders, executions = OrderRepository(store), ExecutionRepository(InMemoryExecutionStore(store))
    writer = OrderStepWriter(orders, executions, clock=lambda: T0)
    writer.expect(_new_order())
    out = Book(store=store, writer=writer, commands=Commands())
    ports = b01.OrderPorts(persist=out.persist, commands=out.commands, now_us=lambda: 1_000)
    monkeypatch.setattr(b01, "_ports", ports)
    monkeypatch.setattr(b01, "_core", apply_fields)
    return out


@asynccontextmanager
async def _machine(
    charts: Charts | Registry, source: str = "lifecycle.draft", *plugins: Any
) -> AsyncIterator[Any]:
    """B1 on the library with its real bindings, parked at *source*, through the factory."""
    registry = charts if isinstance(charts, Registry) else charts.registry("order", CHART, source)
    built = await build(
        "order", clock=SimulatedClock(), lane="order", registry=registry, plugins=plugins
    )
    try:
        yield built.interpreter
    finally:
        await built.interpreter.stop()


async def _send(interp: Any, event: str, **payload: Any) -> None:
    await interp.send(event, wait=True, **payload)
    await settle()


async def test_inv_b1_g_every_step_is_written_before_it_is_seen(book: Book, charts: Charts) -> None:
    """S8 on the library: each `lifecycle` step's row commits through the step writer and the
    in-memory stores before the step is observable, and the rows rebuild the order the machine
    holds (`state`, `lifecycle_state`, the fills and their events)."""
    async with _machine(charts, "lifecycle.draft", AuditTap(), _Seen(book.trail)) as interp:
        await _send(interp, "VALIDATE", **VALIDATE)
        await _send(interp, "SEND")
        for exec_id, qty in (("e1", "0.4"), ("e2", "0.6")):
            await _send(interp, "EXEC", **_exec(exec_id, qty))
        leaves: list[LifecycleState] = [
            "validated", "submitting", "submitted", "partially_filled", "filled"
        ]  # fmt: skip
        assert book.trail[0] == ("seen", "draft")  # the start: `draft` writes nothing
        assert book.trail[1:] == [(what, s) for s in leaves for what in ("written", "seen")]
        row = await book.store.get(ACCOUNT, ORDER_ID)
        events = await book.store.list_for_order(ACCOUNT, ORDER_ID)
        assert row is not None and (row.state, row.lifecycle_state) == ("filled", "filled")
        assert [e.to_state for e in events] == [ORDER_STATE_OF[s] for s in leaves]
        kinds = [(e.kind, e.source) for e in events]
        local = [("local_create", "local"), ("submit_attempt", "local")]
        fills = [("partial_fill", "ws_private"), ("fill", "ws_private")]
        assert kinds == [*local, ("ack", "rest"), *fills]
        cursor = interp.context["event_seq"]
        assert (row.cum_exec_qty, row.exchange_order_id, cursor) == (Decimal(1), "x1", 4)
        assert [n["kind"] for n in interp.context["outbox"]] == [
            "first_fill",
            "first_fill",
            "terminal",
        ]
        assert book.commands.kinds() == ["place"]


class _Pager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def raise_alert(self, severity: str, summary: str, **_labels: str) -> None:
        self.calls.append((severity, summary))


@pytest.mark.parametrize("outage", ["refused", "timed_out", "unwired"])
async def test_s7_a_write_that_fails_changes_nothing_and_pages(
    outage: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S7, S11: a refused, timed-out or unwired write raises in `persist_event`; the rollback
    leaves the configuration and context as they were, nothing reaches the exchange (the invoke
    the entry armed is torn down with it), and the order lane pages."""
    store, commands, pager = Store(), Commands(), _Pager()
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=store, commands=commands))
    hooks = CvErrorHooks(machine_kind="order", lane="order", pager=pager)
    async with _machine(charts, "lifecycle.draft", AuditTap(), hooks) as interp:
        await _send(interp, "VALIDATE", **VALIDATE)
        before = copy.deepcopy(interp.context)
        if outage == "refused":
            store.refuse = RuntimeError("the store refused the write")
        elif outage == "timed_out":
            store.hang = True
            monkeypatch.setattr(b01, "CV_PERSIST_TIMEOUT", 0.0)
        else:
            monkeypatch.setattr(b01, "_ports", b01.OrderPorts(commands=commands))
        await _send(interp, "SEND")
        assert "order.lifecycle.validated" in interp.current_state_ids
        assert (interp.context, commands.sent, len(store.steps)) == (before, [], 1)
        assert ("page", "transition failed: order") in pager.calls


async def test_a_store_outage_sends_nothing_twice_and_trips_the_chain(tmp_path: Path) -> None:
    """CV-C63: with the store down, the place result's step rolls back, which re-arms the invoke;
    the re-entered service answers the recorded result, so the exchange sees one create, and the
    bounded rollback storm trips the chain latch and pages. (`maxIterations` 20 here, so the
    storm stays inside the gate's time budget; the bound itself is the library's.)"""
    (tmp_path / "order.machine.json").write_text(json.dumps(CHART | {"maxIterations": 20}), "utf-8")
    small = Registry(machines_dir=tmp_path)
    gate, store, pager = asyncio.Event(), Store(), _Pager()

    async def _placed(_command: b01.Command) -> Mapping[str, Any]:
        await gate.wait()
        return {"ok": True, "exchange_order_id": "x1"}

    commands = Commands(on_place=_placed)
    hooks = CvErrorHooks(machine_kind="order", lane="order", pager=pager)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ports", b01.OrderPorts(persist=store, commands=commands))
        async with _machine(small, "lifecycle.draft", AuditTap(), hooks) as interp:
            await _send(interp, "VALIDATE", **VALIDATE)
            await _send(interp, "SEND")
            store.refuse = RuntimeError("the store is down")
            gate.set()
            for _ in range(100_000):
                if interp.chain_trips:
                    break
                await asyncio.sleep(0)
            assert interp.chain_trips >= 1 and commands.kinds() == ["place"]
            assert "order.lifecycle.submitting" in interp.current_state_ids
            assert any("runaway chain latched" in summary for _s, summary in pager.calls)


def _ctx(**over: object) -> dict[str, Any]:
    """A context B1 holds once `submitting` committed its row at `seq` 1."""
    base: dict[str, Any] = copy.deepcopy(CHART["context"])
    base |= ORDER | {"leaves_qty": "1", "event_seq": 1}
    return base | {"persisted_state": "submitting", "exchange_order_id": None} | over


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> Commands:
    port = Commands()
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=Store(), commands=port))
    monkeypatch.setattr(b01, "_ATTEMPTS", type(b01._ATTEMPTS)())
    return port


def _begun(context: Mapping[str, Any], kind: str) -> None:
    """The attempt a step this process committed began (`persist_event`)."""
    b01._remember((LINK, f"{kind}:{context['event_seq']}"))


async def test_a_place_is_sent_once_per_attempt(commands: Commands) -> None:
    """S1: a re-entered invoke answers the recorded result; a new attempt (a new step) sends."""
    ctx = _ctx()
    _begun(ctx, "place")
    first = await b01.place_order(None, ctx, None)
    again = await b01.place_order(None, ctx, None)
    assert first == again == {"ok": True, "exchange_order_id": "x1"}
    assert commands.kinds() == ["place"] and commands.sent[0].key == f"{LINK}:place:1"
    _begun(ctx := _ctx(event_seq=5), "place")
    await b01.place_order(None, ctx, None)
    assert commands.kinds() == ["place", "place"]


async def test_a_failed_command_fails_again_with_nothing_resent(commands: Commands) -> None:
    """S1: an ambiguous outcome is recorded; the re-entered invoke fails again (to `unknown`),
    never sending the create a second time."""

    async def _ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    commands.on_place = _ambiguous
    ctx = _ctx()
    _begun(ctx, "place")
    with pytest.raises(TimeoutError):
        await b01.place_order(None, ctx, None)
    with pytest.raises(b01.RecordedFailureError, match="TimeoutError"):
        await b01.place_order(None, ctx, None)
    assert commands.kinds() == ["place"]


FOUND: dict[str, Any] = {"exchange_order_id": "x9", "order_link_id": LINK}
FOUND["account_id"] = str(ACCOUNT)
FOUND |= {"symbol": "BTCUSDT", "side": "buy", "qty": "1", "price": "63000", "stop_loss": "62000"}
FOUND |= {"order_type": "limit", "reduce_only": False, "trigger_price": None}


@pytest.mark.parametrize(
    ("found", "want", "kinds"),
    [
        (FOUND, {"ok": False, "error_code": "DUPLICATE_CLIENT_ID", "lookup": FOUND}, ["lookup"]),
        ({}, {"ok": True, "exchange_order_id": "x1"}, ["lookup", "place"]),
    ],
)
async def test_a_place_this_process_did_not_begin_looks_the_id_up_first(
    found: dict[str, Any], want: dict[str, Any], kinds: list[str], commands: Commands
) -> None:
    """SR-E29-15: a resumed invoke with no recorded outcome looks the id up before any send; an
    order found under the id answers as success-after-lookup (24 Sec.8.3 rule 3)."""

    async def _found(_command: b01.Command) -> Mapping[str, Any]:
        return found

    commands.on_lookup = _found
    assert await b01.place_order(None, _ctx(), None) == want
    assert commands.kinds() == kinds


async def test_a_duplicate_id_is_looked_up_before_the_guards_read_it(commands: Commands) -> None:
    """24 Sec.8.3 rule 3: a duplicate-id reject comes back with the lookup's order attached."""

    async def _duplicate(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "DUPLICATE_CLIENT_ID"}

    async def _found(_command: b01.Command) -> Mapping[str, Any]:
        return FOUND

    commands.on_place, commands.on_lookup = _duplicate, _found
    ctx = _ctx()
    _begun(ctx, "place")
    result = await b01.place_order(None, ctx, None)
    assert result["lookup"] == FOUND and commands.kinds() == ["place", "lookup"]
    assert b01.is_duplicate_link_id_full_match(ctx, result)
    assert not b01.is_link_id_mismatch(ctx, result)


@pytest.mark.parametrize(
    ("staged", "sent"),
    [(None, []), ({}, []), ({"price": "64000"}, ["amend"])],
)
async def test_an_amend_sends_the_staged_terms_or_refuses_locally(
    staged: dict[str, str] | None, sent: list[str], commands: Commands
) -> None:
    """S2: without staged terms nothing is sent and the result is a refusal, so the prior order
    stays live; with them the result names the terms sent, for `adopt_amend`."""
    ctx = _ctx(amend_terms=staged)
    _begun(ctx, "amend")
    result = await b01.amend_order(None, ctx, None)
    assert commands.kinds() == sent
    assert result.get("ok") is bool(sent) and result.get("terms") == (staged if sent else None)


@pytest.mark.parametrize(("stop", "sent"), [(None, []), ("62000", ["attach_stop"])])
async def test_an_attach_sends_only_the_stop_the_oms_requested(
    stop: str | None, sent: list[str], commands: Commands
) -> None:
    """SR-E29-06: without a requested stop nothing is sent (`sl_missing` then hands the position
    to B8); with one the attach is keyed once per order."""
    result = await b01.attach_native_sl(None, _ctx(stop_loss=stop), None)
    assert commands.kinds() == sent
    if sent:
        assert (commands.sent[0].key, commands.sent[0].terms) == (
            f"{LINK}:attach_stop:once",
            {"stop_loss": "62000"},
        )
    else:
        assert result == {"ok": False, "error_code": "NATIVE_STOP_REQUIRED"}


async def test_a_command_with_no_port_wired_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1: an unwired order goes nowhere: the invoke fails, so the order waits in `unknown`."""
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts())
    with pytest.raises(b01.PortMissingError):
        await b01.cancel_order(None, _ctx(), None)


@pytest.mark.parametrize(
    ("over", "audits", "cancels"),
    [
        ({}, [], ["kill_cancel"]),
        ({"kill_skip_cancel": True}, ["kill_no_cancel_unsubmitted"], []),
        (
            {"kill_skip_cancel": True, "needs_lookup": True},
            ["kill_no_cancel_unverified_duplicate"],
            [],
        ),
    ],
)
async def test_a_kill_cancels_through_the_audited_cancel_service(
    over: dict[str, object], audits: list[str], cancels: list[str], commands: Commands
) -> None:
    """SR-E29-06: the KILL's cancel is the OMS's audited cancel (`kind` `kill_cancel`), never the
    binding's own service; a skipped one names why (lows-847s1: an unverified duplicate)."""
    seen: list[str] = []

    async def _hook(name: str, _ctx: dict[str, Any]) -> None:
        seen.append(name)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_hook", _hook)
        await b01.issue_kill_cancel(None, _ctx(**over), None, None)
    assert (seen, commands.kinds()) == (audits, cancels)
    assert not cancels or commands.sent[0].key == f"{LINK}:kill_cancel"


async def test_a_kill_with_no_command_port_is_audited_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kill proceeds unwired too; the cancel that could not go is audited (INV-B1-h)."""
    hook = []

    async def _hook(name: str, _ctx: dict[str, Any]) -> None:
        hook.append(name)

    monkeypatch.setattr(b01, "_ports", b01.OrderPorts())
    monkeypatch.setattr(b01, "_hook", _hook)
    await b01.issue_kill_cancel(None, _ctx(), None, None)
    assert hook == ["kill_cancel_failed"]


async def test_the_outbox_orders_and_bounds_its_notices() -> None:
    """CV-C25: notices queue in context with a `seq` for the facade's cursor; past `OUTBOX_MAX`
    the oldest is dropped and logged at ERROR (C-2.18)."""
    ctx: dict[str, Any] = {"outbox": "not a list", "order_link_id": LINK}
    b01._post(ctx, "first_fill")
    assert ctx["outbox"] == [{"seq": 0, "kind": "first_fill"}]
    with capture_logs() as logs:
        for _ in range(b01.OUTBOX_MAX):
            await b01.request_reconciliation(None, ctx, None, None)
    assert len(ctx["outbox"]) == b01.OUTBOX_MAX and ctx["outbox"][0]["seq"] == 1
    assert [(e["event"], e["log_level"], e["dropped"]) for e in logs] == [
        ("b01_outbox_overflow", "error", "first_fill")
    ]


class _Interp:
    def __init__(self, *leaves: str) -> None:
        self.current_state_ids = {f"order.{leaf}" for leaf in leaves}


@pytest.mark.parametrize(
    ("action", "interp", "event", "notice"),
    [
        ("notify_protection_region", None, {"type": "EXEC"}, {"kind": "first_fill"}),
        ("notify_amend_rejected", None, {"error_code": "RATE_LIMITED"}, {"kind": "amend_rejected"}),
        (
            "emit_terminal",
            _Interp("lifecycle.filled"),
            None,
            {"kind": "terminal", "state": "filled"},
        ),
        ("raise_unknown_alert", None, None, {"kind": "alert", "alert": "order_unknown"}),
        ("raise_critical_alert", _Interp("lifecycle.held"), None, {"alert": "order_held"}),
        ("raise_naked_position_alert", None, None, {"alert": "SL_ATTACH_FAILED"}),
        ("request_reconciliation", None, None, {"kind": "request_reconciliation"}),
        ("request_fallback_sl", None, None, {"kind": "request_fallback_sl"}),
    ],
)
async def test_each_notice_goes_to_the_outbox(
    action: str, interp: object, event: dict[str, Any] | None, notice: dict[str, Any]
) -> None:
    """No action sends to its own machine (CV-C25): each notice is a queued outbox entry."""
    fields = dict(event or {})
    trigger = _Event(str(fields.pop("type", "")), **fields)
    ctx = _ctx()
    await b01.ACTIONS[action](interp, ctx, trigger, None)
    assert notice.items() <= ctx["outbox"][-1].items()


class _Event:
    """An `Event`: its type, and its fields on `payload`."""

    def __init__(self, kind: str = "", **payload: object) -> None:
        self.type, self.payload = kind, payload


async def test_notify_protection_region_needs_a_fill() -> None:
    """INV-B1-o: no notice for an order that holds no fill and handles no EXEC (a cancel or an
    expiry of an unfilled order)."""
    unfilled, junk, filled = _ctx(), _ctx(filled_qty="junk"), _ctx(filled_qty="0.1")
    for ctx in (unfilled, junk, filled):
        await b01.notify_protection_region(None, ctx, _Event("REMOTE_CANCELLED"), None)
    assert (unfilled["outbox"], junk["outbox"]) == ([], [])
    assert filled["outbox"] == [{"seq": 0, "kind": "first_fill"}]


async def test_deadlines_are_absolute_microseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A2: the OMS's scheduler fires them; the clock is the facade's."""
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(now_us=lambda: 5_000_000))
    ctx = _ctx()
    await b01.arm_sl_deadline(None, ctx, None, None)
    await b01.arm_recon_deadline(None, ctx, None, None)
    assert (ctx["sl_deadline_us"], ctx["recon_deadline_us"]) == (7_000_000, 65_000_000)


class _Done:
    """A `DoneEvent`: the service's result rides on `data`."""

    def __init__(self, data: object) -> None:
        self.data = data


def _dup(found: object) -> _Done:
    return _Done({"ok": False, "error_code": "DUPLICATE_CLIENT_ID", "lookup": found})


#: One field of the found order unlike the row's, each (SR-E29-03).
_OTHERS: tuple[tuple[str, object], ...] = (
    ("account_id", "a-2"),
    ("symbol", "ETHUSDT"),
    ("side", "sell"),
    ("qty", "2"),
    ("order_type", "market"),
    ("price", "63001"),
    ("trigger_price", "1"),
    ("reduce_only", True),
    ("stop_loss", None),
    ("order_link_id", "cvl-other"),
)


@pytest.mark.parametrize(
    ("found", "full", "mismatch"),
    [
        (FOUND, True, False),
        *[({**FOUND, key: value}, False, True) for key, value in _OTHERS],
        ({}, False, False),  # an empty lookup: the order parks in `unknown`
        (None, False, False),  # a failed lookup
        (FOUND | {"exchange_order_id": None}, False, True),  # nothing to bind
        (FOUND | {"qty": "1E+3"}, False, False),  # malformed: A6 denies both
    ],
)
def test_a_duplicate_result_binds_only_on_a_full_match(
    found: object, full: bool, mismatch: bool
) -> None:
    """SR-E29-03, INV-B1-m: every field the row and the found order share must agree (the order
    type is `limit` exactly when the row has a price); a different order under our id is held,
    and a failed, empty or malformed lookup binds nothing."""
    ctx, result = _ctx(), _dup(found)
    assert b01.is_duplicate_link_id_full_match(ctx, result) is full
    assert b01.is_link_id_mismatch(ctx, result) is mismatch
    assert b01.is_duplicate_link_id(ctx, result)


@pytest.mark.parametrize(("misses", "second"), [(0, False), (1, True), (3, True), ("x", False)])
def test_second_consecutive_miss_counts_the_earlier_misses(misses: object, second: bool) -> None:
    assert b01.second_consecutive_miss(_ctx(recon_misses=misses), None) is second


READ = {"updated_time": 100, "stop_loss": "62000", "size": "1"}


@pytest.mark.parametrize(
    ("position", "last", "ok"),
    [
        (READ, None, True),
        (READ | {"stop_loss": "62000.0"}, None, True),  # the same amount
        (READ | {"stop_loss": "61000"}, None, False),  # another stop (SR-E29-06)
        (READ | {"stop_loss": None}, None, False),
        (READ | {"size": "0"}, None, False),  # a flat position
        (READ | {"updated_time": -1}, None, False),
        (None, None, False),  # the call's ack alone, no read-back
        (READ, {"kind": "SL_LOST", "updated_time": 101}, False),  # lost after the read-back
        (READ, {"kind": "SL_LOST", "updated_time": 99}, True),  # a stale loss
        (READ, {"kind": "SL_OBSERVED", "updated_time": 101}, True),
    ],
)
def test_sl_attach_ok_needs_a_read_back_no_later_loss_superseded(
    position: object, last: object, ok: bool
) -> None:
    """INV-B1-f (version 3): the read-back of the open position shows the stop the OMS
    requested, and no `SL_LOST` stamped after it was recorded during the attach."""
    ctx = _ctx(sl_reading=last)
    assert b01.sl_attach_ok(ctx, _Done({"ok": True, "position": position})) is ok
    observed = ok or (last is not None and position == READ)  # no supersede check on a read
    reading = position if isinstance(position, dict) else {}
    assert b01.sl_observed_ok(ctx, _Event("SL_OBSERVED", **reading)) is observed


async def test_record_sl_fact_ignored_keeps_the_latest_reading() -> None:
    """INV-B1-f: by exchange time, so a reading delivered late never undoes a newer one; a
    malformed one is logged and dropped; a fact that is no reading is consumed silently."""
    ctx = _ctx()
    for kind, when in (("SL_LOST", 50), ("SL_OBSERVED", 70), ("SL_LOST", 60)):
        await b01.record_sl_fact_ignored(
            None, ctx, _Event(kind, **READ | {"updated_time": when}), None
        )
    assert ctx["sl_reading"] == READ | {"updated_time": 70, "kind": "SL_OBSERVED"}
    with capture_logs() as logs:
        await b01.record_sl_fact_ignored(None, ctx, _Event("SL_LOST", updated_time=90), None)
        await b01.record_sl_fact_ignored(None, ctx, _Event("SL_DEADLINE"), None)
    assert [e["event"] for e in logs] == ["b01_sl_reading_refused"]
    assert ctx["sl_reading"]["updated_time"] == 70


async def test_a_loss_during_the_attach_ends_in_sl_missing(charts: Charts) -> None:
    """lows-847s1b security Low 1, on the library with the real guards: an `SL_LOST` the
    exchange stamped after the attach's read-back, delivered while the attach was in flight, is
    kept, and the confirmed result then goes to `sl_missing`, never `protected`."""
    gate, commands = asyncio.Event(), Commands()

    async def _attached(_command: b01.Command) -> Mapping[str, Any]:
        await gate.wait()
        return {"ok": True, "position": READ}

    commands.on_attach = _attached
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ports", b01.OrderPorts(persist=Store(), commands=commands))
        async with _machine(charts, "protection.not_required", AuditTap()) as interp:
            interp.context.update(stop_loss="62000", order_link_id=LINK)
            await _send(interp, "FIRST_FILL")
            await _send(interp, "SL_LOST", updated_time=150, stop_loss=None, size="1")
            gate.set()
            await settle()
            assert "order.protection.sl_missing" in interp.current_state_ids
            assert not interp.has_tag("protected") and interp.deferred_count == 0


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("EXEC", {"exec_id": "e1", "surprise": 1}),  # a key the schema does not name
        ("EXEC", {"qty": 0.4}),  # a float, never money
        ("VALIDATE", {"gates": {"risk": True}}),  # a verdict is `pass` or `fail`, never a bool
        ("SL_OBSERVED", {"updated_time": "100"}),
        ("CANCEL", {"anything": "at all"}),
        ("KILL", {"reason": ""}),
    ],
)
async def test_a_payload_its_closed_schema_refuses_never_reaches_the_machine(
    event: str, payload: dict[str, Any], charts: Charts
) -> None:
    """The E29 threat model's T03 row: every B1 event's schema is closed, so a payload with an
    unknown key or a wrong type is refused at `send()` (CV-C-strict), before any guard."""
    async with _machine(charts, "lifecycle.submitted", AuditTap()) as interp:
        before = copy.deepcopy(interp.context)
        with pytest.raises(InvalidEventPayloadError):
            await interp.send(event, wait=True, **payload)
        assert interp.context == before


class _Fault:
    """An `ErrorEvent`: the service's exception rides on `error`, never on data (CV-C21)."""

    def __init__(self, error: BaseException) -> None:
        self.error = error


def test_a_failed_service_is_recorded_by_its_class_only() -> None:
    """CV-C21: the row records the exception's class, never its message; it carries no data."""
    fault = _Fault(TimeoutError("a message that may hold anything"))
    assert (b01._fields(fault), b01._step_payload(fault)) == ({}, {"error": "TimeoutError"})


def test_set_ports_unwires_on_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(persist=Store()))
    b01.set_ports(None)
    assert b01._ports == b01.OrderPorts()


def test_recorded_attempts_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.18: the oldest recorded outcome goes first."""
    monkeypatch.setattr(b01, "_ATTEMPTS", type(b01._ATTEMPTS)())
    monkeypatch.setattr(b01, "MAX_ATTEMPTS", 2)
    for n in range(3):
        b01._remember((LINK, f"place:{n}"))
    assert list(b01._ATTEMPTS) == [(LINK, "place:1"), (LINK, "place:2")]


async def test_a_malformed_validated_order_stamps_nothing() -> None:
    """A1: behind `passes_all_gates` it cannot happen; called anyway, it logs and stamps nothing."""
    ctx = _ctx()
    before = copy.deepcopy(ctx)
    malformed = _Event("VALIDATE", gates=VALIDATE["gates"], order=ORDER | {"qty": "0"})
    with capture_logs() as logs:
        await b01.stamp_validated(None, ctx, malformed, None)
    assert ctx == before and [e["event"] for e in logs] == ["b01_stamp_refused"]


async def test_a_full_match_binds_the_id_its_lookup_found() -> None:
    """SR-E29-03: the duplicate-id result has no id of its own; the matched lookup's is bound."""
    ctx = _ctx()
    await b01.adopt_ack(None, ctx, _dup(FOUND), None)
    assert ctx["exchange_order_id"] == "x9"


@pytest.mark.parametrize("fills", [[], ["e1"]])
async def test_an_amend_sends_the_terms_its_event_staged(
    fills: list[str], book: Book, charts: Charts
) -> None:
    """S2's positive path on the library, through the real amend service and the command port:
    AMEND's terms are staged in context (an invoke reads the context, not the event), sent once,
    and adopted from the ack into the live state the order came from."""
    async with _machine(charts, "lifecycle.draft", AuditTap()) as interp:
        await _send(interp, "VALIDATE", **VALIDATE)
        await _send(interp, "SEND")
        for exec_id in fills:
            await _send(interp, "EXEC", **_exec(exec_id, "0.4"))
        await _send(interp, "AMEND", price="64000", stop_loss="62500")
        amend = book.commands.sent[-1]
        assert (amend.kind, amend.terms) == ("amend", {"price": "64000", "stop_loss": "62500"})
        assert (interp.context["price"], interp.context["stop_loss"]) == ("64000", "62500")
        live = "partially_filled" if fills else "submitted"
        assert f"order.lifecycle.{live}" in interp.current_state_ids
        assert interp.context["amend_terms"] is None
        row = await book.store.get(ACCOUNT, ORDER_ID)  # the row holds what the exchange accepted
        assert row is not None and (row.price, row.stop_loss) == (Decimal(64000), Decimal(62500))
