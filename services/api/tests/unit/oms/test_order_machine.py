"""The OMS facade (E29-T03 #847, slice 6): B1 built per order through the factory and driven
through the gateway, on the real binding with the in-memory stores. Legality from the chart's
static table (AC1), S5, S6 (AC5), S9, the outbox, the publish (OM-I02) and eviction (MUST-11)."""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms import ExecutionRepository
from candleviewer.oms.errors import (
    IllegalTransition,
    OrderBufferFull,
    OrderHistoryRefused,
    OrderMachinesFull,
    OrderNotLoaded,
    OrderStepRefused,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from candleviewer.oms.order_machine import (
    B1_AUDITS,
    COMMAND_EVENTS,
    MAX_HELD,
    PUSH_EVENTS,
    Actor,
    CommandEvent,
    Legality,
    OrderAuditRecord,
    Outcome,
    Severity,
)
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.gateway import GatewayOverloadedError
from candleviewer.statechart.persistence import DegradedLatchError
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import NewOrder, NewOrderEvent, OrderTransition
from tests.unit.oms.order_rig import (
    ACCOUNT,
    GATES,
    NOW_US,
    OTHER,
    READ_BACK,
    T0,
    Rig,
    build_rig,
    fill_of,
    gated,
    order_of,
)

CHART = Registry().get("order")
LEGALITY = Legality.of(CHART)
STATES = tuple(CHART["states"]["lifecycle"]["states"])
PLAN = Path(__file__).resolve().parents[5] / "docs" / "plan"


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = build_rig()
    yield out
    await out.facade.stop()


# --- AC1: the whole transition matrix, against 24 Sec.8.2 ----------------------------------------


def _diagram_pairs() -> set[tuple[str, str]]:
    """24 Sec.8.2's diagram: its drawn edges, and its note's KILL arms into `killed`."""
    text = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
    block = text[text.index("### 8.2 Order state machine") : text.index("**Binding transition")]
    camel = {"".join(w.capitalize() for w in s.split("_")): s for s in STATES}
    drawn = {(camel[a], camel[b]) for a, b in re.findall(r"^\s+(\w+) --> (\w+)\b", block, re.M)}
    finals = {camel[s] for s in re.findall(r"^\s+(\w+) --> \[\*\]$", block, re.M)}
    note = re.search(r"KILL from any non-terminal state but (.+)$", block, re.M)
    assert note is not None
    spared = {camel[name.strip()] for name in re.split(r",| and ", note[1])}
    return drawn | {(s, "killed") for s in STATES if s not in finals | spared}


@pytest.mark.parametrize("source", STATES)
def test_the_whole_transition_matrix_is_covered(source: str) -> None:
    """AC1: of every ordered pair of states, exactly the pairs 24 Sec.8.2 lists are steps B1's
    static table admits; every other pair raises IllegalTransition."""
    pairs = _diagram_pairs()
    for target in STATES:
        if (source, target) in pairs:
            LEGALITY.require_edge(source, target)
        else:
            with pytest.raises(IllegalTransition, match=f"{target} is not a transition"):
                LEGALITY.require_edge(source, target)


#: 24 Sec.8.2: the states each command leaves (and `untracked`, which records a reconciliation
#: finding it does not act on, INV-B1-l).
COMMANDS: dict[str, set[str]] = {
    "SEND": {"validated"},
    "CANCEL": {"submitted", "triggered", "partially_filled"},
    "AMEND": {"submitted", "partially_filled"},
    "OPERATOR_RESOLVED": {"held"},
    "ADOPT": {"untracked"},
    "TRANSPORT_FAULT": {"submitted"},
    "MISMATCH": {"submitted", "unknown", "quarantined"},
    **{
        f"RECON_FOUND_{found}": {"unknown", "quarantined", "untracked"}
        for found in ("LIVE", "PARTIAL", "FILLED", "CANCELLED")
    },
    "RECON_MISS": {"unknown", "untracked"},
}


@pytest.mark.parametrize(("command", "legal"), COMMANDS.items())
def test_a_command_is_legal_exactly_where_24_lists_it(command: str, legal: set[str]) -> None:
    for state in STATES:
        if state in legal:
            LEGALITY.require(state, command)
        else:
            with pytest.raises(IllegalTransition):
                LEGALITY.require(state, command)


async def test_an_illegal_command_is_refused_before_any_send(rig: Rig) -> None:
    """AC1 through the facade: refused synchronously and counted, with nothing sent, written or
    deferred, so a stray operator decision is never kept for a later hold (INV-B1-m)."""
    order = order_of()
    await rig.start(order)
    refused: tuple[tuple[CommandEvent, Actor], ...] = (
        ("CANCEL", "user"),
        ("OPERATOR_RESOLVED", "user"),
        ("RECON_MISS", "system"),
    )
    for event, actor in refused:
        with pytest.raises(IllegalTransition, match=f"{event} is not a transition of validated"):
            await rig.facade.command(ACCOUNT, order.id, event, actor=actor)
    assert rig.facade.state(order.id) == ("validated", "not_required")
    assert rig.commands.sent == [] and rig.count("oms_illegal_transitions_total") == 3
    assert rig.facade._orders[order.id].interp.deferred_count == 0
    assert rig.context(order)["rate_reservation"] == "rr-1"


async def test_a_step_outside_the_table_is_refused_before_its_row_is_written(rig: Rig) -> None:
    """S8, C-2.19: B1's persist port refuses a step the chart does not list, so nothing is written
    and the step rolls back; the refusal is counted."""
    step = b01.Step(str(UUID(int=1)), str(ACCOUNT), None, "submitted", "validated", "SEND", {}, {})
    with pytest.raises(IllegalTransition):
        await rig.facade._persist(step)
    assert await rig.orders.get(ACCOUNT, UUID(int=1)) is None
    assert rig.count("oms_illegal_transitions_total") == 1


# --- AC2 to AC5 -----------------------------------------------------------------------------------


async def test_cancel_loses_the_race_to_a_fill(rig: Rig) -> None:
    """AC2 (S3, INV-B1-d): a full execution in `cancel_pending` fills the order with no error to
    the caller; its row records the lost race (`pending_cancel` to `filled`) and the stop starts."""
    order = await rig.submitted()
    gate, rig.commands.on_cancel = gated({"ok": True})
    assert await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user") == "cancel_pending"
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.quiet()
    events = await rig.store.list_for_order(ACCOUNT, order.id)
    assert (events[-1].from_state, events[-1].to_state) == ("pending_cancel", "filled")
    assert sorted(rig.commands.kinds()) == ["attach_stop", "cancel", "place"]
    assert rig.facade.state(order.id) is None  # final, its stop confirmed: evicted (MUST-11)
    gate.set()


async def test_amend_rejection_does_not_move_the_stop(rig: Rig) -> None:
    """AC3 (S2): the exchange rejects the amend of an order at 63000, so it is `submitted` again
    at 63000 with its row unchanged, and the UI is told (`amend_rejected`)."""
    order = await rig.submitted()
    gate, rig.commands.on_amend = gated({"ok": True})
    await rig.facade.command(ACCOUNT, order.id, "AMEND", {"price": "64000"}, actor="user")
    reject = {"error_code": "PRICE_OUT_OF_BOUNDS"}
    await rig.facade.push(ACCOUNT, order.id, "AMEND_REJECTED", reject)
    await rig.quiet()
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert rig.context(order)["price"] == "63000"
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.price == Decimal(63000)
    assert (rig.notices.kinds(), rig.notices.got[-1].detail) == (["amend_rejected"], reject)
    gate.set()


async def test_duplicate_fill_never_double_counts(rig: Rig) -> None:
    """AC4 (S4): E1 for 0.4 delivered twice leaves `filled_qty` at 0.4 with one execution
    stored; a repeat is no anomaly (no FAULT, no record, no count)."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    published = len(rig.publish.calls)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    assert len(rig.publish.calls) == published  # an unchanged state is not published again
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.cum_exec_qty == Decimal("0.4")
    assert rig.context(order)["seen_exec_ids"] == ["e1"]
    assert len(rig.context(order)["outbox"]) == 1  # taken notices leave; the newest anchors seq
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert rig.audit.records == [] and rig.count("oms_reconcile_anomaly_total") == 0


async def test_terminal_state_is_immutable(rig: Rig) -> None:
    """AC5 (S6): a push for a filled order raises ReconcileAnomaly once `oms.reconcile_anomaly`
    is written; it is counted and changes nothing, and a late fill hands the position to B8."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.quiet()
    before = await rig.store.list_for_order(ACCOUNT, order.id)
    with pytest.raises(ReconcileAnomaly) as raised:
        await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 1})
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.1"))
    assert (raised.value.code, raised.value.state) == ("POST_TERMINAL_PUSH", "filled")
    s6 = ("oms.reconcile_anomaly", order.id, ACCOUNT, "denied", "error", "POST_TERMINAL_PUSH")
    assert rig.audit.records == [  # C-2.9 (codeB r1 Medium): each record in full
        OrderAuditRecord(*s6, {"state": "filled", "trigger": "TRIGGERED", "exec_id": None}),
        OrderAuditRecord(*s6, {"state": "filled", "trigger": "EXEC", "exec_id": "e2"}),
    ]
    assert rig.count("oms_reconcile_anomaly_total") == 2
    assert await rig.store.list_for_order(ACCOUNT, order.id) == before
    assert rig.notices.kinds() == ["request_fallback_sl"]
    assert rig.commands.kinds() == ["place", "attach_stop"]
    with pytest.raises(IllegalTransition, match="CANCEL is not a transition of filled"):
        await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")


async def test_a_fill_for_a_final_machine_still_alive_is_b1s_anomaly(rig: Rig) -> None:
    """INV-B1-o: while the stop of a filled order is attached its machine lives, and a later fill
    reaches it: B1 consumes it under its own S6 record, and the caller gets ReconcileAnomaly."""
    order = await rig.submitted()
    gate, rig.commands.on_attach = gated(READ_BACK)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    assert rig.facade.state(order.id) == ("filled", "sl_pending")
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.5"))
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", {"updated_time": 9})
    anomaly = ("oms.reconcile_anomaly", order.id, ACCOUNT, "denied", "error")
    b1 = {"order_link_id": order.order_link_id, "state": "filled", "exec_id": "e2"}
    s6 = {"state": "filled", "trigger": "REMOTE_CANCELLED", "exec_id": None}
    assert rig.audit.records == [  # C-2.9 (codeB r1 Medium): B1's record, then the facade's
        OrderAuditRecord(*anomaly, "reconcile_anomaly", b1 | {"trigger": "EXEC"}),
        OrderAuditRecord(*anomaly, "POST_TERMINAL_PUSH", s6),
    ]
    assert rig.count("oms_reconcile_anomaly_total") == 2
    assert rig.context(order)["filled_qty"] == "1"
    gate.set()
    await rig.quiet()
    assert rig.facade.state(order.id) is None


# --- S5: order, staleness and the reorder buffer --------------------------------------------------


async def test_s5_an_older_push_is_ignored_and_a_fill_never_is(rig: Rig) -> None:
    """S5: a push older than the last `orders` push the order took, or one its state has no arm
    for, is ignored; a fill applies whenever it arrives."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 200})
    await rig.facade.push(ACCOUNT, order.id, "EXPIRE", {"updated_time": 150})
    assert rig.facade.state(order.id) == ("triggered", "not_required")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4", ts_exec=1))
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 300})
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert rig.facade._orders[order.id].interp.deferred_count == 0  # ignored, never kept


async def _unknown(rig: Rig) -> NewOrder:
    """An order whose place had an ambiguous outcome: `unknown` and unbound (S1)."""

    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    return order


async def test_a_fill_before_the_bind_waits_then_applies_in_exec_order(rig: Rig) -> None:
    """SR-E29-03 (slice 4's SL2): the fills of an unbound order wait in the reorder buffer, and
    apply in `(ts_exec, seq)` order once reconciliation binds it; `unknown` paged meanwhile."""
    order = await _unknown(rig)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.2", ts_exec=2))
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.2", ts_exec=1))
    assert rig.context(order)["seen_exec_ids"] == []
    assert rig.facade._tasks == set()  # a held push waits; no turn spins on it
    found = {"exchange_order_id": "x1"}
    await rig.facade.command(ACCOUNT, order.id, "RECON_FOUND_LIVE", found, actor="system")
    await rig.quiet()
    assert rig.context(order)["seen_exec_ids"] == ["e1", "e2"]
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert rig.notices.got[0].detail == {"alert": "order_unknown"}


async def test_the_reorder_buffer_is_bounded(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.18: past `MAX_HELD` a push is refused, for its sender to resync (24 Sec.8.5 step 2)."""
    monkeypatch.setattr("candleviewer.oms.order_machine.MAX_HELD", 1)
    order = await _unknown(rig)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.2"))
    with pytest.raises(OrderBufferFull):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.2"))
    assert MAX_HELD == 256


async def test_an_exchange_end_waits_for_the_fills_it_reports(rig: Rig) -> None:
    """INV-B1-k: a cancel the exchange reports with 0.4 filled, ahead of that fill, waits; the
    fill applies first, then the end, so the final row carries every fill."""
    order = await rig.submitted()
    end = {"cum_exec_qty": "0.4", "updated_time": 10}
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", end)
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    events = await rig.store.list_for_order(ACCOUNT, order.id)
    assert [e.to_state for e in events][-2:] == ["partially_filled", "cancelled"]
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and (row.state, row.cum_exec_qty) == ("cancelled", Decimal("0.4"))


# --- S9, OM-I02, MUST-11 ------------------------------------------------------------------------


async def test_s9_no_rule_algo_or_group_acts_on_an_untracked_order(rig: Rig) -> None:
    """S9, SR-E29-12: a rule, an algo or a group is refused on an `untracked` order, only a user
    may ask to adopt it (D6 denies every adoption until E45-S01), and reconciliation's finding is
    recorded."""
    found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
    assert await rig.facade.discover(found, environment="demo") == "untracked"
    managers: tuple[Actor, ...] = ("rule", "algo", "group")
    events: tuple[CommandEvent, ...] = ("CANCEL", "ADOPT", "RECON_FOUND_LIVE")
    for actor in managers:
        for event in events:
            with pytest.raises(IllegalTransition):
                await rig.facade.command(ACCOUNT, found.id, event, actor=actor)
    with pytest.raises(IllegalTransition):  # only a user adopts (D6), not the reconciler either
        await rig.facade.command(ACCOUNT, found.id, "ADOPT", actor="system")
    assert await rig.facade.command(ACCOUNT, found.id, "ADOPT", actor="user") == "untracked"
    finding = await rig.facade.command(ACCOUNT, found.id, "RECON_FOUND_LIVE", actor="system")
    assert finding == "untracked" and rig.commands.sent == []
    assert rig.count("oms_illegal_transitions_total") == 10


async def test_each_step_is_published_scoped_to_the_orders_account(rig: Rig) -> None:
    """OM-I02, 23 Sec.6.4: every committed step publishes the order's `MachineStateUpdate` with
    the stored order's account as its scope; an unchanged payload is not published again, and the
    one the order ends with is the entity's last once its machine is evicted."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.quiet()
    assert {(o, a) for o, a, _p, _l in rig.publish.calls} == {(order.id, ACCOUNT)}
    seen = [(p["state"], p["regions"]["protection"], last) for _o, _a, p, last in rig.publish.calls]
    assert seen == [
        ("draft", "not_required", False),
        ("validated", "not_required", False),
        ("submitting", "not_required", False),
        ("submitted", "not_required", False),
        ("filled", "not_required", False),
        ("filled", "sl_pending", False),
        ("filled", "sl_present", False),
        ("filled", "sl_present", True),
    ]
    assert rig.publish.calls[-1][2] == {
        "machine_kind": "order",
        "state": "filled",
        "regions": {"lifecycle": "filled", "protection": "sl_present"},
        "tags": ["protected", "terminal"],
        "degraded": False,
        "machine_hash": Registry().hash("order"),
        "environment": "demo",
        "context_summary": {"symbol": "BTCUSDT", "halted_by_kill": False, "recon_misses": 0},
        "updated_at_ms": NOW_US // 1_000,
    }
    assert rig.publish.calls[0][2]["context_summary"] == {
        "halted_by_kill": False,
        "recon_misses": 0,
    }


async def test_a_full_registry_refuses_a_new_order_and_keeps_every_live_one(rig: Rig) -> None:
    """C-2.18: at its bound the facade refuses a new order before anything is written; a live
    machine is never evicted, and a final one is (MUST-11)."""
    rig.facade._max = 1
    order = await rig.submitted()
    with pytest.raises(OrderMachinesFull):
        await rig.start(order_of(2))
    assert await rig.orders.get(ACCOUNT, UUID(int=2)) is None
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    with pytest.raises(IllegalTransition):
        await rig.start(order)  # the order's machine already runs: VALIDATE is no step of it


async def test_another_accounts_order_is_not_found(rig: Rig) -> None:
    """C-12.4: another account's order id finds nothing, as an unknown one does (no oracle)."""
    order = await rig.submitted()
    with pytest.raises(OrderNotLoaded):
        await rig.facade.command(OTHER, order.id, "CANCEL", actor="user")
    with pytest.raises(OrderNotLoaded):
        await rig.facade.push(OTHER, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.facade.push(OTHER, order.id, "SL_LOST", {"updated_time": 1, "size": "1"})
    assert rig.commands.kinds() == ["place"] and rig.context(order)["seen_exec_ids"] == []


# --- The outbox: a lost KILL, hostile fills, notices ----------------------------------------------


async def test_a_kill_whose_cancel_a_fill_outran_is_sent_again(rig: Rig) -> None:
    """Slice 4's SL4 (INV-B1-h, C-2.21): KILL reused the in-flight cancel, then a partial fill
    took the order to `partially_filled`, still halted, and its cancel with it. The facade sends
    KILL again: the order is `killed` with one cancel through the audited cancel service
    (SR-E29-06), and the loss is audited and logged at ERROR."""
    order = await rig.submitted()
    gate, rig.commands.on_cancel = gated({"ok": True})
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    assert await rig.facade.kill("kill switch engaged") == ()
    assert rig.facade.state(order.id) == ("cancel_pending", "not_required")
    with capture_logs() as logs:
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
        await rig.quiet()
    assert sorted(rig.commands.kinds()) == ["attach_stop", "cancel", "kill_cancel", "place"]
    assert "kill_cancel_lost" in rig.audit.reasons("orders.cancel")
    assert any(e["event"] == "oms_kill_resent" and e["log_level"] == "error" for e in logs)
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "killed"
    gate.set()


async def test_a_hostile_execution_quarantines_the_order(rig: Rig) -> None:
    """OM-T04 (#3804's deviation 8): an EXEC of another exchange order is refused by B1, and as it
    is neither a repeat nor early, answered with FAULT: quarantined, audited and counted."""
    order = await rig.submitted()
    hostile = fill_of(order, "e1", "0.4", exchange_order_id="x-foreign")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", hostile)
    await rig.quiet()
    assert rig.facade.state(order.id) == ("quarantined", "not_required")
    assert len(rig.context(order)["outbox"]) == 1  # both notices taken; the newest anchors seq
    refusal = "the execution is not a trade of this order's bound exchange order"
    detail = {"order_link_id": order.order_link_id, "state": "submitted", "exec_id": "e1"}
    assert rig.audit.records == [  # C-2.9 (codeB r1 Medium): the record in full
        OrderAuditRecord(
            "oms.reconcile_anomaly",
            order.id,
            ACCOUNT,
            "denied",
            "error",
            "guard_denied",
            detail | {"trigger": None, "refusal": refusal},
        )
    ]
    assert rig.count("oms_reconcile_anomaly_total") == 1
    assert rig.notices.kinds() == ["alert", "request_reconciliation"]


async def test_a_hostile_execution_pages_where_its_state_cannot_quarantine(rig: Rig) -> None:
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 1})
    hostile = fill_of(order, "e1", "0.4", exchange_order_id="x-foreign")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", hostile)
    assert rig.facade.state(order.id) == ("triggered", "not_required")
    assert rig.pager.calls == ["oms_hostile_exec_not_quarantined"]


async def test_a_lost_notice_or_audit_record_pages_and_the_step_stands(rig: Rig) -> None:
    """The step that posted a notice, or called B1's audit hook, stands; the loss pages (C-2.9)."""
    rig.notices.refuse = True
    order = await _unknown(rig)  # its `order_unknown` alert is lost
    assert "order notice lost: alert" in rig.pager.calls
    rig.audit.refuse = True
    assert await rig.facade.kill("kill switch engaged") == ()
    assert rig.facade.state(order.id) is None  # killed, nothing filled: evicted
    assert "oms_audit_record_lost" in rig.pager.calls
    assert sorted(rig.commands.kinds()) == ["kill_cancel", "place"]


# --- Gates and failures ---------------------------------------------------------------------------


async def test_a_chain_trip_latched_order_refuses_order_path_commands(rig: Rig) -> None:
    """CV-C63: a machine whose chain tripped refuses SEND, CANCEL, AMEND and ADOPT until an
    operator acknowledges it; the reconciler's facts still pass, and the publish says degraded."""
    order = await rig.submitted()
    rig.facade._orders[order.id].interp.chain_trips = 1
    with pytest.raises(DegradedLatchError):
        await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    fault = {"reason": "socket closed"}
    state = await rig.facade.command(ACCOUNT, order.id, "TRANSPORT_FAULT", fault, actor="system")
    assert state == "unknown" and rig.commands.kinds() == ["place"]
    assert rig.publish.calls[-1][2]["degraded"] is True


async def test_s7_an_order_whose_first_row_is_refused_leaves_nothing(rig: Rig) -> None:
    """S7: the store refuses the order's first row, so `start` raises, nothing is written and no
    machine is left behind."""
    rig.store.fail_next(RuntimeError("Postgres is down"))
    with pytest.raises(OrderStepRefused, match="VALIDATE"):
        await rig.start()
    assert rig.facade.state(UUID(int=1)) is None
    assert await rig.orders.get(ACCOUNT, UUID(int=1)) is None


async def test_a_push_for_an_order_with_no_machine_and_no_final_row_is_not_loaded(
    rig: Rig,
) -> None:
    with pytest.raises(OrderNotLoaded):
        await rig.facade.push(ACCOUNT, UUID(int=9), "TRIGGERED", {"updated_time": 1})
    with pytest.raises(OrderNotLoaded):
        await rig.facade.command(ACCOUNT, UUID(int=9), "CANCEL", actor="user")


def test_every_b1_record_is_written_under_a_registered_action() -> None:
    """C-2.9, SR-E29-17: the writer never refuses one of the facade's records."""
    assert {action for action, _o, _s in B1_AUDITS.values()} <= AUDIT_ACTIONS
    assert "oms.reconcile_anomaly" in AUDIT_ACTIONS


async def test_stop_unwires_the_binding(rig: Rig) -> None:
    await rig.submitted()
    await rig.facade.stop()
    assert (b01._ports, b01._core) == (b01.OrderPorts(), None)
    assert rig.facade.state(UUID(int=1)) is None


async def test_an_end_that_reports_no_fill_is_taken_at_once(rig: Rig) -> None:
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXPIRE", {"updated_time": 5})
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "expired" and rig.facade.state(order.id) is None


async def test_a_lost_stop_pages_and_hands_the_position_to_b8(rig: Rig) -> None:
    """C-2.6: a protection fact reaches the live machine; a lost stop alerts and hands the
    position to B8 (`request_fallback_sl`)."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    lost = {"updated_time": 200, "stop_loss": None, "size": "0.4"}
    await rig.facade.push(ACCOUNT, order.id, "SL_LOST", lost)
    assert rig.facade.state(order.id) == ("partially_filled", "sl_missing")
    assert rig.notices.kinds() == ["alert", "request_fallback_sl"]
    assert rig.notices.got[0].detail == {"alert": "SL_ATTACH_FAILED"}


async def test_a_kill_that_does_not_commit_is_reported_and_pages(rig: Rig) -> None:
    """INV-B1-h: an order whose KILL rolled back is answered and paged (the receipt can read clean,
    CV-C06)."""
    order = await rig.submitted()
    rig.store.fail_next(RuntimeError("Postgres is down"))
    assert await rig.facade.kill("kill switch engaged") == (order.id,)
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert "oms_kill_not_recorded" in rig.pager.calls


@pytest.mark.parametrize(("reason", "recorded"), [("", "kill"), ("x" * 65, "x" * 64)])
async def test_a_malformed_kill_reason_still_kills_every_live_order(
    rig: Rig, reason: str, recorded: str
) -> None:
    """codeA r1 Low (C-2.21): a reason B1's closed `KILL` schema would refuse (empty, or past
    `MAX_TEXT`) is normalised, never refused, so a malformed reason stops no order's KILL."""
    orders = [await rig.submitted(order_of(n)) for n in (1, 2)]
    assert await rig.facade.kill(reason) == ()
    for order in orders:
        row = await rig.orders.get(ACCOUNT, order.id)
        assert row is not None and row.state == "killed"
        events = await rig.store.list_for_order(ACCOUNT, order.id)
        assert events[-1].payload == {"reason": recorded}
    assert sorted(rig.commands.kinds()) == ["kill_cancel", "kill_cancel", "place", "place"]


async def test_a_turn_stops_at_a_failure_and_the_next_step_retries(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release whose step is refused waits in the buffer again, and the turn stops, logged;
    the order's next step releases it (S7: nothing was applied meanwhile)."""
    order = await _unknown(rig)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.2"))
    real = rig.fills.commit_fill

    async def refused_once(fill: Any) -> Any:
        monkeypatch.setattr(rig.fills, "commit_fill", real)
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(rig.fills, "commit_fill", refused_once)
    found = {"exchange_order_id": "x1"}
    with capture_logs() as logs:
        await rig.facade.command(ACCOUNT, order.id, "RECON_FOUND_LIVE", found, actor="system")
    assert "oms_settle_stopped" in [e["event"] for e in logs]
    assert rig.context(order)["seen_exec_ids"] == []
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 1})
    assert rig.context(order)["seen_exec_ids"] == ["e1"]


async def test_a_hostile_fill_whose_fault_is_refused_leaves_the_order_as_it_was(rig: Rig) -> None:
    order = await rig.submitted()
    rig.store.fail_next(RuntimeError("Postgres is down"))
    hostile = fill_of(order, "e1", "0.4", exchange_order_id="x-foreign")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", hostile)
    assert rig.facade.state(order.id) == ("submitted", "not_required")


async def test_a_caller_that_waited_out_an_eviction_takes_the_evicted_path(rig: Rig) -> None:
    """Every send runs under the order's lock. A push, a command, a KILL and a turn that waited
    while the machine was evicted find it gone; one turn is ever pending per order."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    async with o.lock:
        trigger = {"updated_time": 1}
        push = asyncio.create_task(rig.facade.push(ACCOUNT, order.id, "TRIGGERED", trigger))
        cancel = asyncio.create_task(rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user"))
        kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
        rig.facade._schedule(o)
        rig.facade._schedule(o)
        assert len(rig.facade._tasks) == 1
        await asyncio.sleep(0)
        await rig.facade._close(o, publish=False)
    for waited in (push, cancel):
        with pytest.raises(OrderNotLoaded):  # its row is live: `hydrate` brings it back
            await waited
    assert await kill == ()
    await rig.facade.idle()
    await rig.facade._close(o, publish=False)  # closing twice is harmless
    assert rig.commands.kinds() == ["place"]


async def test_idle_waits_for_a_turn_and_stop_cancels_one(rig: Rig) -> None:
    order = await rig.submitted()
    gate, rig.commands.on_attach = gated(READ_BACK)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    gate.set()
    for _ in range(1_000):
        if rig.facade._tasks:
            break
        await asyncio.sleep(0)
    await rig.facade.idle()
    assert rig.facade.state(order.id) is None
    second = order_of(2)
    await rig.submitted(second)
    gate, rig.commands.on_attach = gated(READ_BACK)
    await rig.facade.push(ACCOUNT, second.id, "EXEC", fill_of(second, "e2", "1"))
    gate.set()
    for _ in range(1_000):
        if rig.facade._tasks:
            break
        await asyncio.sleep(0)
    await rig.facade.stop()
    assert rig.facade._tasks == set() and rig.facade.state(second.id) is None


async def test_an_order_whose_machine_cannot_be_built_is_not_kept(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise TimeoutError("start() did not settle")

    monkeypatch.setattr("candleviewer.oms.order_machine.build", broken)
    with pytest.raises(TimeoutError):
        await rig.start()
    assert rig.facade.state(UUID(int=1)) is None


async def test_a_refused_publish_is_logged_and_the_step_stands(rig: Rig) -> None:
    rig.publish.refuse = True
    with capture_logs() as logs:
        await rig.start()
    assert rig.facade.state(UUID(int=1)) == ("validated", "not_required")
    assert "oms_publish_failed" in [e["event"] for e in logs]


async def test_the_refusals_kept_for_an_answer_are_bounded(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18; a record for an order the facade does not hold is not written."""
    monkeypatch.setattr("candleviewer.oms.order_machine.MAX_HELD", 1)
    order = await rig.submitted()
    for exec_id in ("e1", "e2"):
        denied = {"exec_id": exec_id, "reason": b01.REPEAT}
        await rig.facade._audited("guard_denied", {"order_id": str(order.id), "denied": denied})
    assert list(rig.facade._orders[order.id].denied) == ["e2"]
    await rig.facade._audited("halted_by_kill", {"order_id": "not an order id"})
    assert rig.audit.records == []


async def test_a_refused_validation_writes_nothing_and_ends_at_once(rig: Rig) -> None:
    """24 Sec.8.4: a verdict that refused the order (here E32-T01's native stop) ends it
    `rejected` with no row; the machine is evicted and its last payload published."""
    refused = GATES | {"native_stop": b01.FAILED}
    state = await rig.facade.start(order_of(), environment="demo", gates=refused)
    assert state == "rejected" and rig.facade.state(UUID(int=1)) is None
    assert await rig.orders.get(ACCOUNT, UUID(int=1)) is None
    assert rig.publish.calls[-1][3] is True and rig.commands.sent == []


async def test_a_turn_past_its_rounds_hands_the_rest_to_the_next(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18: a turn takes at most `SETTLE_ROUNDS` rounds, and schedules a turn for the rest."""
    monkeypatch.setattr("candleviewer.oms.order_machine.SETTLE_ROUNDS", 1)
    order = await _unknown(rig)
    for exec_id, ts in (("e1", 1), ("e2", 2)):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, exec_id, "0.2", ts_exec=ts))
    found = {"exchange_order_id": "x1"}
    await rig.facade.command(ACCOUNT, order.id, "RECON_FOUND_LIVE", found, actor="system")
    assert rig.context(order)["seen_exec_ids"] == ["e1"]
    await rig.quiet()
    assert rig.context(order)["seen_exec_ids"] == ["e1", "e2"]


async def test_each_committed_step_is_counted_by_state_and_source(rig: Rig) -> None:
    """`oms_state_transitions_total{from,to,source}`: one per written row, by chart state and the
    event's source (24 Sec.8.2), the first row from `draft`."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    steps = (
        ("draft", "validated", "local"),
        ("validated", "submitting", "local"),
        ("submitting", "submitted", "rest"),
        ("submitted", "filled", "ws_private"),
    )
    name = "oms_state_transitions_total"
    for source, target, origin in steps:
        assert rig.count(name, **{"from": source, "to": target, "source": origin}) == 1
    assert rig.count(name) == 4


# --- S7, an unknown outcome: the row decides (codeA r1 Medium, codeB r1 Low) ---------------------

_CUT_OFF = "the commit's answer was cut off"


async def test_a_fill_whose_write_outcome_is_unknown_is_rebuilt_from_its_row(rig: Rig) -> None:
    """24 Sec.8.2 S7: a fill's row commits but its answer is lost (the binding's timeout cut the
    write off). B1 rolls the step back, so the caller is told the outcome is unknown, and the
    facade pages and rebuilds the machine from the order's events, where the row decides: the
    machine holds the fill, its stop is attached (24 Sec.8.8 rule 2), and the next fill applies."""
    order = await rig.submitted()
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    with pytest.raises(OrderStepUnknown, match="EXEC"):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    rebuilt = {("partially_filled", "sl_pending"), ("partially_filled", "sl_present")}
    assert rig.facade.state(order.id) in rebuilt  # before push() answered (codeB r2 Low)
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and (row.state, row.cum_exec_qty) == ("partially_filled", Decimal("0.4"))
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert (rig.context(order)["seen_exec_ids"], rig.context(order)["filled_qty"]) == (
        ["e1"],
        "0.4",
    )
    assert rig.commands.kinds() == ["place", "attach_stop"]
    assert "oms_step_outcome_unknown" in rig.pager.calls
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.6"))
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and (row.state, row.cum_exec_qty) == ("filled", Decimal(1))
    assert rig.facade.state(order.id) is None  # final, its stop confirmed: evicted


async def test_a_place_ack_whose_write_outcome_is_unknown_converges_with_one_create(
    rig: Rig,
) -> None:
    """S7 for a step no caller drove: the place ack's row commits but its answer is lost. The
    re-armed invoke answers its recorded result (one create), its write meets a row that moved
    on, and a turn rebuilds the machine from the row: bound, and a fill that came before the bind
    and waited in the reorder buffer is carried over and applies."""
    order = order_of()
    gate, rig.commands.on_place = gated({"ok": True, "exchange_order_id": "x1"})
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))  # held: unbound
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    gate.set()
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert rig.context(order)["seen_exec_ids"] == ["e1"]
    assert rig.commands.kinds() == ["place", "attach_stop"]
    assert rig.pager.calls.count("oms_step_outcome_unknown") == 1


async def test_a_row_another_writer_moved_is_read_again(rig: Rig) -> None:
    """S7: a step that meets a row which moved on under the machine (`StaleOrderState`) rolls
    back; the machine was behind its row, so it is rebuilt from the order's events, and the order
    takes the next command from where the row is."""
    order = await rig.submitted()
    pushed = NewOrderEvent(
        kind="exchange_push", source="ws_private", event_ts=T0, payload={"updated_time": 5}
    )
    moved = OrderTransition(
        account_id=ACCOUNT,
        order_id=order.id,
        from_state="accepted",
        to_state="triggered",
        event=pushed,
        lifecycle_state="triggered",
    )
    await rig.store.transition(moved)
    with pytest.raises(OrderStepUnknown, match="CANCEL is not known: StaleOrderState"):
        await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    assert rig.facade.state(order.id) == ("triggered", "not_required")
    assert await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user") == "cancel_pending"
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "cancelled"
    assert rig.commands.kinds() == ["place", "cancel"]


async def test_an_order_whose_first_row_outcome_is_unknown_is_rebuilt_if_it_landed(
    rig: Rig,
) -> None:
    """S7 at the first row: it committed, but its answer was lost, so the caller is told the
    outcome is unknown and the facade rebuilds the order from that row: `validated`, and sent."""
    order = order_of()
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    with pytest.raises(OrderStepUnknown, match="VALIDATE"):
        await rig.start(order)
    assert rig.facade.state(order.id) == ("validated", "not_required")
    assert await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user") == "submitting"
    await rig.quiet()
    assert rig.facade.state(order.id) == ("submitted", "not_required")


async def test_an_order_whose_first_row_did_not_land_leaves_nothing(rig: Rig) -> None:
    """S7: the store timed out before the first row committed: the outcome is unknown to the
    caller, the facade finds no row to rebuild, and nothing is kept."""
    rig.store.fail_next(TimeoutError(_CUT_OFF))
    with pytest.raises(OrderStepUnknown):
        await rig.start()
    assert rig.facade.state(UUID(int=1)) is None
    assert await rig.orders.get(ACCOUNT, UUID(int=1)) is None


async def test_a_final_fill_whose_outcome_is_unknown_hands_the_position_to_b8(rig: Rig) -> None:
    """S7, C-2.6: the fill that filled the order committed while its machine rolled it back. The
    row is final, so no machine is rebuilt (MUST-11), and as none can start the stop, the position
    goes to B8 (`request_fallback_sl`); an exchange end that waited for that fill is recorded as
    an S6 anomaly, as for any final order, never lost."""
    order = await rig.submitted()
    end = {"cum_exec_qty": "1", "updated_time": 10}
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", end)  # waits for its fill
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    with pytest.raises(OrderStepUnknown):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.quiet()
    assert rig.facade.state(order.id) is None
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "filled"
    assert rig.notices.kinds() == ["request_fallback_sl"]
    assert rig.commands.kinds() == ["place"]
    s6 = {"state": "filled", "trigger": "REMOTE_CANCELLED", "exec_id": None}
    assert [dict(r.detail) for r in rig.audit.records] == [s6]


# --- The synchronous gates hold for every caller (codeB r1 Medium, C-2.21) -----------------------


async def test_a_payload_cannot_rename_the_event_the_gates_checked(rig: Rig) -> None:
    """A rule's SEND whose payload names `type: KILL` is refused before any send: the gates
    checked SEND, and the payload never replaces the event."""
    order = order_of()
    await rig.start(order)
    with pytest.raises(IllegalTransition):
        await rig.facade.command(ACCOUNT, order.id, "SEND", {"type": "KILL"}, actor="rule")
    with pytest.raises(IllegalTransition):
        await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"type": "KILL", "updated_time": 1})
    assert rig.facade.state(order.id) == ("validated", "not_required")
    assert rig.commands.sent == [] and rig.count("oms_illegal_transitions_total") == 2
    _gate, rig.commands.on_place = gated({"ok": True, "exchange_order_id": "x1"})
    await rig.facade._send_order(rig.facade._orders[order.id], "SEND", {"type": "KILL"})
    assert rig.facade.state(order.id) == ("submitting", "not_required")  # never a KILL


async def test_a_latched_order_cannot_be_cancelled_through_a_smuggled_type(rig: Rig) -> None:
    """CV-C63: with the chain tripped, a TRANSPORT_FAULT carrying `type: CANCEL` is refused, so
    the cancel the latch refuses never reaches the exchange."""
    order = await rig.submitted()
    rig.facade._orders[order.id].interp.chain_trips = 1
    smuggled = {"type": "CANCEL", "reason": "socket closed"}
    with pytest.raises(IllegalTransition):
        await rig.facade.command(ACCOUNT, order.id, "TRANSPORT_FAULT", smuggled, actor="system")
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert rig.commands.kinds() == ["place"]


@pytest.mark.parametrize(
    ("via", "event", "actor"),
    [("push", "OPERATOR_RESOLVED", "user"), ("command", "KILL", "rule"), ("push", "FAULT", "user")],
)
async def test_an_event_outside_the_methods_set_is_refused(
    rig: Rig, via: str, event: Any, actor: Any
) -> None:
    """`command` takes only `COMMAND_EVENTS` and `push` only `PUSH_EVENTS`, whatever the static
    types said: a push cannot resolve a hold (only a user does, D6), a rule cannot KILL, and no
    push can quarantine an order (OM-T04 is the facade's answer)."""
    order = await rig.submitted()
    mismatch = {"exchange_order_id": "x9"}
    await rig.facade.command(ACCOUNT, order.id, "MISMATCH", mismatch, actor="system")
    assert rig.facade.state(order.id) == ("held", "not_required")
    with pytest.raises(IllegalTransition, match=f"{event} is not a transition of order"):
        if via == "push":  # an untyped caller: `event` is `Any`, as a mapped request's would be
            await rig.facade.push(ACCOUNT, order.id, event, {"decided_by": "owner"})
        else:
            await rig.facade.command(ACCOUNT, order.id, event, actor=actor)
    assert rig.facade.state(order.id) == ("held", "not_required")
    assert "OPERATOR_RESOLVED" not in PUSH_EVENTS and "KILL" not in COMMAND_EVENTS


# --- C-2.6 on the place path, C-2.9 records, C-12.4 scope (codeB r1 Mediums) --------------------


async def test_every_place_carries_the_native_stop(rig: Rig) -> None:
    """C-2.6 (AGENTS.md Sec.6 rule 9): the `place` command the exchange receives carries the stop
    the validated order requested, with the order's identity and terms."""
    order = await rig.submitted()
    place = rig.commands.sent[0]
    assert (place.kind, place.order["stop_loss"]) == ("place", "62000")
    assert (place.order["order_link_id"], place.order["qty"], place.order["price"]) == (
        order.order_link_id,
        "1",
        "63000",
    )


async def test_a_kill_record_names_the_order_its_account_and_state(rig: Rig) -> None:
    """C-2.9: the KILL's records in full, the order's cancel (`orders.cancel`, OM-R01), written
    for the order and its account: the lifecycle's, with the state the KILL found, then the
    `protection` region's, which keeps the stop (INV-B1-i), once the order is `killed`."""
    order = await rig.submitted()
    assert await rig.facade.kill("kill switch engaged") == ()
    cancel = ("orders.cancel", order.id, ACCOUNT, "success")
    detail = {"order_link_id": order.order_link_id, "exec_id": None, "trigger": None}
    assert rig.audit.records == [
        OrderAuditRecord(*cancel, "warning", "halted_by_kill", detail | {"state": "submitted"}),
        OrderAuditRecord(*cancel, "info", "kill_protection_retained", detail | {"state": "killed"}),
    ]


async def test_a_kill_for_one_account_leaves_another_accounts_orders_live(rig: Rig) -> None:
    """C-12.4, OM-I02: `kill(account_id=...)` records KILL on that account's orders only."""
    mine = await rig.submitted()
    theirs = order_of(2, exchange_account_id=OTHER)
    await rig.start(theirs)
    await rig.facade.command(OTHER, theirs.id, "SEND", actor="user")
    await rig.quiet()
    assert await rig.facade.kill("account kill", account_id=ACCOUNT) == ()
    row = await rig.orders.get(ACCOUNT, mine.id)
    assert row is not None and row.state == "killed" and rig.facade.state(mine.id) is None
    assert rig.facade.state(theirs.id) == ("submitted", "not_required")
    assert [c.order["order_id"] for c in rig.commands.sent if c.kind == "kill_cancel"] == [
        str(mine.id)
    ]


def test_the_transition_labels_serve_only_the_b1_step_counter() -> None:
    """codeB r1 Low: the allow-list's `from`, `to` and `source` (.semgrep, #847) are bounded only
    for `oms_state_transitions_total` (B1's states and `OrderEventSource`, `max_series` 256); a
    new metric using them must bring its own bound to review, so this pin then fails."""
    users = {spec.name for spec in CATALOGUE if {"from", "to", "source"} & set(spec.labels)}
    assert users == {"oms_state_transitions_total"}
    spec = next(spec for spec in CATALOGUE if spec.name == "oms_state_transitions_total")
    assert (spec.labels, spec.max_series) == (("from", "to", "source"), 256)


# --- The outbox keeps a notice until it is acted on (codeA r1 Low, codeB r1 Low) -----------------


async def test_a_first_fill_that_could_not_start_the_stop_pages_and_is_tried_again(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.6: a one-shot full fill's FIRST_FILL is refused once (an overloaded inbox). The notice
    stays, the order is paged, and its machine is not evicted: the next push the order takes
    tries it again, and the stop is attached."""
    order = await rig.submitted()
    send, refused = rig.facade._gateway.send, []

    async def overloaded_once(key: str, event: Any, *, wait: bool = False) -> Any:
        if isinstance(event, Mapping) and event.get("type") == "FIRST_FILL" and not refused:
            refused.append(key)
            raise GatewayOverloadedError(key, "order")
        return await send(key, event, wait=wait)

    monkeypatch.setattr(rig.facade._gateway, "send", overloaded_once)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.quiet()
    assert rig.facade.state(order.id) == ("filled", "not_required")
    assert "oms_first_fill_not_delivered" in rig.pager.calls
    assert rig.commands.kinds() == ["place"]
    seen = {"updated_time": 50, "stop_loss": None, "size": "1"}
    await rig.facade.push(ACCOUNT, order.id, "SL_OBSERVED", seen)
    await rig.quiet()
    assert rig.commands.kinds() == ["place", "attach_stop"]
    assert rig.facade.state(order.id) is None  # its stop confirmed: evicted (MUST-11)


async def test_a_refused_quarantine_is_tried_again_at_the_next_turn(rig: Rig) -> None:
    """OM-T04: the FAULT that answers a hostile fill is refused once (the store is down); the
    refusal stays queued, so the next push's settle (one the order ignores) quarantines it."""
    order = await rig.submitted()
    hostile = fill_of(order, "e1", "0.4", exchange_order_id="x-foreign")
    rig.store.fail_next(RuntimeError("Postgres is down"))
    await rig.facade.push(ACCOUNT, order.id, "EXEC", hostile)
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    await rig.facade.push(ACCOUNT, order.id, "AMEND_REJECTED", {"error_code": "X"})  # ignored
    assert rig.facade.state(order.id) == ("quarantined", "not_required")


# --- Stalled ports and a concurrent KILL (codeB r1 Low, C-2.18) -------------------------------


async def test_a_stalled_audit_sink_neither_holds_the_order_nor_stops_the_kill(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit port is awaited within `PORT_TIMEOUT`: a sink that never answers loses its
    record, which pages, and the KILL of every order goes on."""
    orders = [await rig.submitted(order_of(n)) for n in (1, 2)]
    monkeypatch.setattr("candleviewer.oms.order_machine.PORT_TIMEOUT", 0.0)

    async def stalled(_record: OrderAuditRecord) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(rig.audit, "write", stalled)
    async with asyncio.timeout(10):  # a backstop only: a regression would hang here
        assert await rig.facade.kill("kill switch engaged") == ()
    for order in orders:
        row = await rig.orders.get(ACCOUNT, order.id)
        assert row is not None and row.state == "killed"
    assert "oms_audit_record_lost" in rig.pager.calls


async def test_a_slow_kill_cancel_delays_no_other_orders_kill(rig: Rig) -> None:
    """The orders are killed concurrently: while the first order's cancel hangs, the second order
    is already `killed`."""
    first, second = await rig.submitted(order_of(1)), await rig.submitted(order_of(2))
    gate = asyncio.Event()

    async def cancel(command: b01.Command) -> Mapping[str, Any]:
        if command.order["order_id"] == str(first.id):
            await gate.wait()
        return {"ok": True}

    rig.commands.on_cancel = cancel
    kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
    for _ in range(200):
        await asyncio.sleep(0)
    row = await rig.orders.get(ACCOUNT, second.id)
    assert row is not None and row.state == "killed" and not kill.done()
    gate.set()
    assert await kill == ()
    row = await rig.orders.get(ACCOUNT, first.id)
    assert row is not None and row.state == "killed"


@pytest.mark.parametrize("exec_id", ["e" * 100_000, 123, ""])
async def test_an_s6_record_keeps_no_exec_id_b1_would_not_keep(rig: Rig, exec_id: object) -> None:
    """C-12.6: a push for an evicted final order never met B1's closed schema; its `exec_id`
    enters the record and the log only as B1 keeps one (text of 1 to `MAX_TEXT` characters)."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXPIRE", {"updated_time": 5})
    await rig.quiet()
    late = fill_of(order, "e1", "0.1") | {"exec_id": exec_id}
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", late)
    assert [dict(r.detail) for r in rig.audit.records] == [
        {"state": "expired", "trigger": "EXEC", "exec_id": None}
    ]


# --- Whose stop the protection region manages (codeA r1 Medium and Lows, C-2.6) ----------------


async def test_a_discovered_order_found_filled_never_has_its_stop_managed(rig: Rig) -> None:
    """B1.8(b), INV-B1-l, SR-E29-06, SR-E29-12: an order reconciliation discovered, with a stop on
    it, is found filled. Its fill starts the protection region, but that stop is the exchange's,
    not one the OMS requested: no attach is sent (it could loosen a stop the user tightened, 24
    Sec.8.8 rule 5), and the region goes to `sl_missing`, whose alert pages and whose fallback
    request hands the position to B8."""
    found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
    assert await rig.facade.discover(found, environment="demo") == "untracked"
    finding = {"exchange_order_id": "x7", "execution": fill_of(found, "e7", "1"), "pass_id": "p1"}
    state = await rig.facade.command(
        ACCOUNT, found.id, "RECON_FOUND_FILLED", finding, actor="system"
    )
    assert state == "filled"
    await rig.quiet()
    assert rig.commands.sent == []
    assert [(n.kind, dict(n.detail)) for n in rig.notices.got] == [
        ("alert", {"alert": "SL_ATTACH_FAILED"}),
        ("request_fallback_sl", {}),
    ]
    last = rig.publish.calls[-1]
    assert (last[2]["regions"]["protection"], last[3]) == ("sl_missing", True)
    assert rig.facade.state(found.id) is None  # final, its region settled: evicted, B8's now


async def test_a_partial_fill_found_without_its_execution_starts_the_stop(rig: Rig) -> None:
    """INV-B1-o: reconciliation finds the unknown order partly filled, with no execution to apply
    yet: `partially_filled` starts the protection region all the same, so the stop is attached."""
    order = await _unknown(rig)
    found = {"exchange_order_id": "x1", "pass_id": "p1"}
    await rig.facade.command(ACCOUNT, order.id, "RECON_FOUND_PARTIAL", found, actor="system")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert rig.context(order)["filled_qty"] == "0"
    assert rig.commands.kinds() == ["place", "attach_stop"]


async def test_a_reduce_only_exit_starts_no_stop_and_pages_nothing(rig: Rig) -> None:
    """C-2.6 covers position-opening orders: a reduce-only exit, which carries no stop, opens no
    position, so its fills start no protection region (no attach, no `SL_ATTACH_FAILED` page, no
    hand-off to B8), and neither does its hydration after a restart."""
    order = order_of(reduce_only=True, stop_loss=None, intent="flatten")
    await rig.submitted(order)
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "not_required")
    assert (rig.commands.kinds(), rig.notices.got, rig.pager.calls) == (["place"], [], [])
    again = await rig.restart()
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert again.facade.state(order.id) == ("partially_filled", "not_required")
        assert again.commands.sent == []
    finally:
        await again.facade.stop()


async def test_what_a_resync_leaves_without_a_machine_is_sent_on_or_paged(rig: Rig) -> None:
    """S7, C-2.6 (`_orphaned`): with no machine rebuilt, a held push goes as an evicted order's
    would (here the row is live, so it is dropped, logged, for reconciliation to apply again),
    each notice but `first_fill` and `terminal` goes to the notice port, and a hostile fill no
    machine can quarantine pages; a row holding no fill needs no hand-off to B8."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    await rig.facade._close(o, publish=False)  # as `_resync` does before it hydrates
    o.held.append(((1, 0), "EXEC", fill_of(order, "e1", "0.1")))
    o.notices.extend(
        [
            {"seq": 7, "kind": "alert", "alert": "order_unknown"},
            {"seq": 8, "kind": "first_fill"},
            {"seq": 9, "kind": "terminal", "state": "filled"},
        ]
    )
    o.denied["e9"] = "the execution is not a trade of this order's bound exchange order"
    with capture_logs() as logs:
        await rig.facade._orphaned(o)
    dropped = [e for e in logs if e["event"] == "oms_held_push_dropped"]
    assert [(e["trigger"], e["error"]) for e in dropped] == [("EXEC", "OrderNotLoaded")]
    assert [(n.kind, dict(n.detail)) for n in rig.notices.got] == [
        ("alert", {"alert": "order_unknown"})
    ]
    assert rig.pager.calls == ["oms_hostile_exec_not_quarantined"]


async def test_a_resync_that_cannot_read_the_row_pages(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.6: whether the position needs B8 is unknown when the row cannot be read, so the
    operator is paged rather than told nothing."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    await rig.facade._close(o, publish=False)

    async def unreadable(_account: UUID, _order: UUID) -> Any:
        raise TimeoutError

    monkeypatch.setattr(rig.orders, "get", unreadable)
    await rig.facade._orphaned(o)
    assert rig.pager.calls == ["oms_resync_row_unread"] and rig.notices.got == []


async def test_a_kill_that_fails_unexpectedly_is_reported_and_pages(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-B1-h: an order whose KILL raised something unforeseen is answered and paged; the other
    orders' KILLs are not held up by it."""
    first, second = await rig.submitted(order_of(1)), await rig.submitted(order_of(2))
    real = rig.facade._kill

    async def broken(o: Any, reason: str) -> None:
        if o.order_id == first.id:
            raise RuntimeError("unforeseen")
        await real(o, reason)

    monkeypatch.setattr(rig.facade, "_kill", broken)
    assert await rig.facade.kill("kill switch engaged") == (first.id,)
    assert rig.pager.calls == ["oms_kill_not_recorded"]
    row = await rig.orders.get(ACCOUNT, second.id)
    assert row is not None and row.state == "killed"


# --- A resync resumes as a restart does (codeA r2 Medium, codeB r2 Medium) ---------------------


async def _no_stop(_command: b01.Command) -> Mapping[str, Any]:
    """The attach's read-back finds the position with no stop on it."""
    return {"ok": True, "position": {"updated_time": 300, "stop_loss": None, "size": "0.6"}}


async def test_a_resync_confirms_the_stop_from_a_fresh_exchange_read(rig: Rig) -> None:
    """INV-B1-f, C-2.6, 24 Sec.8.8 rule 2: the exchange lost the stop (`SL_LOST`: `sl_missing`,
    alerted, handed to B8), then a fill's write is in doubt. The rebuilt machine forgets the old
    one's attach, as a restarted process does, so its first fill attaches and reads the position
    back again: no stop, so the region is `sl_missing` again, B8 is asked again, and no publish
    calls the order `protected`."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    lost = {"updated_time": 200, "stop_loss": None, "size": "0.4"}
    await rig.facade.push(ACCOUNT, order.id, "SL_LOST", lost)
    assert rig.facade.state(order.id) == ("partially_filled", "sl_missing")
    rig.commands.on_attach = _no_stop
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    with pytest.raises(OrderStepUnknown):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.2"))
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_missing")
    assert rig.commands.kinds() == ["place", "attach_stop", "attach_stop"]
    assert rig.notices.kinds() == ["alert", "request_fallback_sl"] * 2
    assert "protected" not in rig.publish.calls[-1][2]["tags"]


async def test_a_resync_looks_up_the_place_the_old_machine_left_in_flight(rig: Rig) -> None:
    """SR-E29-15, S1: the place is in flight when the order's KILL is written in doubt, with
    nothing landed, so the machine is rebuilt in `submitting` and the old one's place is cut off
    unanswered. Its attempt went with it: the rebuilt machine's place is one this process did not
    begin, so it looks the id up before it sends, as after a restart; the KILL then reaches the
    rebuilt machine, which cancels once (INV-B1-h)."""
    order = order_of()
    gate, rig.commands.on_place = gated({"ok": True, "exchange_order_id": "x1"})
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    rig.store.fail_next(TimeoutError(_CUT_OFF))
    assert await rig.facade.kill("kill switch engaged") == ()
    assert rig.commands.kinds() == ["place", "lookup", "place", "kill_cancel"]
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "killed"
    gate.set()


# --- A KILL reaches the machine a resync rebuilds (codeA r2 Medium, INV-B1-h) ------------------


#: The pages of a step rolled back (`CvErrorHooks`) and of a KILL that did not commit.
_ROLLED_BACK, _NOT_KILLED = "transition failed: order", "oms_kill_not_recorded"


async def _resync_held(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, order: NewOrder
) -> tuple[asyncio.Event, asyncio.Task[None]]:
    """A fill whose write is in doubt with nothing landed, its resync held at the re-read of the
    row: the old machine is closed and the new one not yet built."""
    gate, read = asyncio.Event(), rig.orders.get

    async def held(account_id: UUID, order_id: UUID) -> Any:
        await gate.wait()
        return await read(account_id, order_id)

    monkeypatch.setattr(rig.orders, "get", held)
    rig.store.fail_next(TimeoutError(_CUT_OFF))
    fill = fill_of(order, "e1", "0.4")
    push = asyncio.create_task(rig.facade.push(ACCOUNT, order.id, "EXEC", fill))
    for _ in range(1_000):
        if order.id not in rig.facade._orders:
            break
        await asyncio.sleep(0)
    assert order.id not in rig.facade._orders and not push.done()
    return gate, push


@pytest.mark.parametrize(
    ("landed", "unkilled", "sent", "paged"),
    [
        (False, (), ["kill_cancel"], [_ROLLED_BACK, "oms_step_outcome_unknown"]),
        (True, (UUID(int=1),), [], [_ROLLED_BACK, "oms_step_outcome_unknown", _NOT_KILLED]),
    ],
)
async def test_an_in_doubt_kill_is_sent_to_the_rebuilt_machine_unless_its_row_landed(
    rig: Rig, landed: bool, unkilled: tuple[UUID, ...], sent: list[str], paged: list[str]
) -> None:
    """INV-B1-h, 24 Sec.8.2 "An unknown outcome": a KILL whose write is in doubt rebuilds the
    machine from the row. With nothing landed, the rebuilt machine is killed in turn, its cancel
    sent once. A `killed` row that landed gets no machine and its cancel was never sent, so the
    order is answered and paged (the residual: B18's cancel-all and reconciliation settle it)."""
    order = await rig.submitted()
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=landed)
    assert await rig.facade.kill("kill switch engaged") == unkilled
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "killed" and rig.facade.state(order.id) is None
    assert rig.commands.kinds() == ["place", *sent]
    assert rig.pager.calls == paged


async def test_a_kill_during_a_resync_waits_for_the_rebuilt_machine(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.21, INV-B1-h: KILL arrives while a resync rebuilds the order's machine, the old one
    closed and the new one not yet built. It waits for the resync and kills the rebuilt machine,
    which sends its cancel; it never answers the order as killed while nothing recorded it."""
    order = await rig.submitted()
    gate, push = await _resync_held(rig, monkeypatch, order)
    kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
    for _ in range(64):
        await asyncio.sleep(0)
    assert not kill.done()
    gate.set()
    with pytest.raises(OrderStepUnknown):
        await push
    assert await kill == ()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "killed"
    assert rig.commands.kinds() == ["place", "kill_cancel"]


async def test_a_kill_that_waited_out_a_resync_kills_the_rebuilt_machine(rig: Rig) -> None:
    """KILL found the order's machine and waited on its lock while a resync replaced it: it
    follows the order to the rebuilt machine and kills that, never counting the closed one."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    async with o.lock:  # as a caller's settle holds it while it resyncs
        kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
        await asyncio.sleep(0)
        o.resync = True
        await rig.facade._resync(o)
    assert await kill == ()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "killed" and rig.facade.state(order.id) is None
    assert rig.commands.kinds() == ["place", "kill_cancel"]


async def test_a_kill_whose_order_a_resync_left_without_a_machine_reports_it(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resync a KILL waited out rebuilt no machine (the order's history did not hydrate), so
    nothing recorded the KILL: the order is answered and paged, never counted as killed."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]

    async def refused(*_args: Any) -> str:
        raise OrderHistoryRefused("the order's events do not rebuild its row (OM-T03)")

    monkeypatch.setattr(rig.facade, "_hydrate", refused)
    async with o.lock:
        kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
        await asyncio.sleep(0)
        o.resync = True
        await rig.facade._resync(o)
    assert await kill == (order.id,)
    assert rig.pager.calls == ["oms_step_outcome_unknown", "oms_kill_not_recorded"]
    assert rig.commands.kinds() == ["place"]


async def test_a_kill_while_a_first_row_is_in_doubt_kills_the_rebuilt_machine(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KILL waits on a new order whose first row is being written; the row commits but its answer
    is lost, so the order is rebuilt from it under the same lock, and KILL kills the rebuilt
    machine (never sent, so no cancel)."""
    gate, create = asyncio.Event(), rig.store.create

    async def held(order: NewOrder, first_event: Any) -> Any:
        await gate.wait()
        return await create(order, first_event)

    monkeypatch.setattr(rig.store, "create", held)
    start = asyncio.create_task(rig.start(order_of()))
    for _ in range(1_000):
        if UUID(int=1) in rig.facade._orders and rig.facade._orders[UUID(int=1)].busy:
            break
        await asyncio.sleep(0)
    assert rig.facade._orders[UUID(int=1)].busy  # its first row's write is under way
    kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
    for _ in range(64):
        await asyncio.sleep(0)
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    gate.set()
    with pytest.raises(OrderStepUnknown, match="VALIDATE"):
        await start
    assert await kill == ()
    row = await rig.orders.get(ACCOUNT, UUID(int=1))
    assert row is not None and row.state == "killed" and rig.commands.sent == []


async def test_a_kill_reports_an_order_whose_machine_is_still_being_built(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A KILL that meets an order whose machine is still being built cannot record it there: the
    order is answered and paged, never counted as killed (the synchronous kill switch still
    refuses its sends, C-2.21)."""
    gate = asyncio.Event()

    async def held(*args: Any, **kwargs: Any) -> Any:
        await gate.wait()
        return await build(*args, **kwargs)

    monkeypatch.setattr("candleviewer.oms.order_machine.build", held)
    start = asyncio.create_task(rig.start(order_of()))
    for _ in range(64):
        await asyncio.sleep(0)
    assert UUID(int=1) in rig.facade._orders and rig.facade.state(UUID(int=1)) is not None
    assert await rig.facade.kill("kill switch engaged") == (UUID(int=1),)
    assert rig.pager.calls == ["oms_kill_not_recorded"]
    gate.set()
    assert await start == "validated"


# --- Callers that waited out a resync reach the rebuilt machine (codeB r2 Low) -----------------


async def test_callers_that_waited_out_a_resync_reach_the_rebuilt_machine(rig: Rig) -> None:
    """A push and a command queued on the order's lock while an unknown-outcome write rebuilt its
    machine are taken by the rebuilt machine, never answered as if no machine held the order."""
    order = await rig.submitted()
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    first = fill_of(order, "e1", "0.4")
    pushed = asyncio.create_task(rig.facade.push(ACCOUNT, order.id, "EXEC", first))
    second = fill_of(order, "e2", "0.2")
    waited = asyncio.create_task(rig.facade.push(ACCOUNT, order.id, "EXEC", second))
    cancel = asyncio.create_task(rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user"))
    with pytest.raises(OrderStepUnknown):
        await pushed
    await waited  # taken: no OrderNotLoaded
    assert await cancel == "cancel_pending"
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and (row.state, row.cum_exec_qty) == ("cancelled", Decimal("0.6"))


async def test_a_push_during_a_resync_waits_for_the_rebuilt_machine(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A push that arrives while a resync rebuilds the order's machine, the old one closed and
    the new one not yet built, waits for it and is taken by it."""
    order = await rig.submitted()
    gate, push = await _resync_held(rig, monkeypatch, order)
    later = asyncio.create_task(
        rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.2"))
    )
    for _ in range(64):
        await asyncio.sleep(0)
    assert not later.done()
    gate.set()
    with pytest.raises(OrderStepUnknown):
        await push
    await later  # taken: no OrderNotLoaded
    await rig.quiet()
    assert rig.context(order)["seen_exec_ids"] == ["e2"]


async def test_a_hydration_during_a_resync_answers_the_rebuilt_machine(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: hydrating an order a resync is rebuilding waits for the rebuilt machine and answers
    its state, never building a second machine for the order."""
    order = await rig.submitted()
    gate, push = await _resync_held(rig, monkeypatch, order)
    hydrated = asyncio.create_task(rig.facade.hydrate(ACCOUNT, order.id, environment="demo"))
    for _ in range(64):
        await asyncio.sleep(0)
    assert not hydrated.done()
    gate.set()
    with pytest.raises(OrderStepUnknown):
        await push
    assert await hydrated == "submitted"
    assert rig.pager.calls == [_ROLLED_BACK, "oms_step_outcome_unknown"]


async def test_a_second_hydration_racing_the_first_leaves_its_replay_alone(rig: Rig) -> None:
    """L3, SR-E29-15: two hydrations of an order race after a restart. The second is refused
    before it touches the binding's record of the first machine's replay, so the place the crash
    cut off resumes once, after the replay, looking its id up first."""
    order = order_of()
    _gate, rig.commands.on_place = gated({"ok": True, "exchange_order_id": "x1"})
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    again = await rig.restart()
    try:
        both = await asyncio.gather(
            again.facade.hydrate(ACCOUNT, order.id, environment="demo"),
            again.facade.hydrate(ACCOUNT, order.id, environment="demo"),
            return_exceptions=True,
        )
        await again.quiet()
        assert both[0] == "submitting" and isinstance(both[1], IllegalTransition)
        assert again.commands.kinds() == ["lookup", "place"]
        assert again.facade.state(order.id) == ("submitted", "not_required")
    finally:
        await again.facade.stop()


async def test_a_caller_follows_an_order_through_at_most_follows_machines(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18: a caller follows the order through at most `FOLLOWS` machines, then is answered as
    if none held it: here `FOLLOWS` is 1, so the machine one resync rebuilt is past it."""
    monkeypatch.setattr("candleviewer.oms.order_machine.FOLLOWS", 1)
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    async with o.lock:
        cancel = asyncio.create_task(rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user"))
        trigger = {"updated_time": 1}
        push = asyncio.create_task(rig.facade.push(ACCOUNT, order.id, "TRIGGERED", trigger))
        hydrated = asyncio.create_task(rig.facade.hydrate(ACCOUNT, order.id, environment="demo"))
        kill = asyncio.create_task(rig.facade.kill("kill switch engaged"))
        await asyncio.sleep(0)
        o.resync = True
        await rig.facade._resync(o)
    for waited in (cancel, push):
        with pytest.raises(OrderNotLoaded):
            await waited
    with pytest.raises(IllegalTransition):  # a second machine for the order is refused (L3)
        await hydrated
    assert await kill == (order.id,)
    assert rig.facade.state(order.id) == ("submitted", "not_required")


# --- What a resync hands over, and what it leaves (codeB r2 Low) -------------------------------


async def test_a_resync_hands_the_old_machines_work_to_the_rebuilt_one(rig: Rig) -> None:
    """S5, S7: the rebuilt machine takes over what the old one had not done: its pending notice
    reaches the notice port and its held fill applies; and its S5 watermark stays, so an `orders`
    push older than the last one the order took is still ignored."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 500})
    o = rig.facade._orders[order.id]
    async with o.lock:
        o.notices.append({"seq": 90, "kind": "request_fallback_sl"})
        o.held.append(((1, 0), "EXEC", fill_of(order, "e1", "0.4")))
        o.resync = True
        await rig.facade._resync(o)
    await rig.quiet()
    assert rig.notices.kinds() == ["request_fallback_sl"] and rig.facade._resyncing == {}
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    stale = {"updated_time": 400, "cum_exec_qty": "0.4"}
    await rig.facade.push(ACCOUNT, order.id, "REMOTE_CANCELLED", stale)
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")


async def test_a_refusal_the_old_machine_kept_is_answered_by_the_rebuilt_one(rig: Rig) -> None:
    """OM-T04: a hostile fill's refusal the old machine kept for its answer passes to the rebuilt
    machine, which quarantines the order."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    async with o.lock:
        o.denied["e9"] = "the execution is not a trade of this order's bound exchange order"
        o.resync = True
        await rig.facade._resync(o)
    assert rig.facade.state(order.id) == ("quarantined", "not_required")


async def test_a_reduce_only_exit_left_without_a_machine_hands_nothing_to_b8(rig: Rig) -> None:
    """C-2.6 covers position-opening orders: the fill that ends a reduce-only exit commits while
    its machine rolls it back, so no machine is rebuilt for the final row, and as the exit opens
    no position, nothing is handed to B8."""
    order = order_of(reduce_only=True, stop_loss=None, intent="flatten")
    await rig.submitted(order)
    rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    with pytest.raises(OrderStepUnknown):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "1"))
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "filled" and rig.facade.state(order.id) is None
    assert rig.notices.got == [] and rig.commands.kinds() == ["place"]


# --- Each port await is bounded by PORT_TIMEOUT (codeB r2 Low, C-2.18) -------------------------


async def _stalled(*_args: Any, **_kwargs: Any) -> Any:
    await asyncio.Event().wait()


def _answering(row: Any) -> Any:
    """A read port that answers *row* at once, so a zero `PORT_TIMEOUT` passes it."""

    async def answer(*_args: Any, **_kwargs: Any) -> Any:
        return row

    return answer


async def test_a_hydration_gives_up_a_row_read_that_stalls(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("candleviewer.oms.order_machine.PORT_TIMEOUT", 0.0)
    monkeypatch.setattr(rig.orders, "get", _stalled)
    async with asyncio.timeout(10):  # a backstop only: a regression would hang here
        with pytest.raises(TimeoutError):
            await rig.facade.hydrate(ACCOUNT, UUID(int=9), environment="demo")


async def test_a_hydration_gives_up_a_history_read_that_stalls(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = await rig.submitted()
    await rig.facade._close(rig.facade._orders[order.id], publish=False)
    row = await rig.orders.get(ACCOUNT, order.id)
    monkeypatch.setattr("candleviewer.oms.order_machine.PORT_TIMEOUT", 0.0)
    monkeypatch.setattr(rig.orders, "get", _answering(row))
    monkeypatch.setattr(rig.events, "list_for_order", _stalled)
    async with asyncio.timeout(10):
        with pytest.raises(TimeoutError):
            await rig.facade.hydrate(ACCOUNT, order.id, environment="demo")


async def test_a_command_for_an_unloaded_order_gives_up_a_row_read_that_stalls(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("candleviewer.oms.order_machine.PORT_TIMEOUT", 0.0)
    monkeypatch.setattr(rig.orders, "get", _stalled)
    async with asyncio.timeout(10):
        with pytest.raises(TimeoutError):
            await rig.facade.command(ACCOUNT, UUID(int=9), "CANCEL", actor="user")


async def test_an_s6_record_that_stalls_is_given_up_never_the_refusal(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: a record that cannot be written in time raises; the push is not refused as recorded
    (`ReconcileAnomaly` is raised only once its record is written)."""
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXPIRE", {"updated_time": 5})
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    monkeypatch.setattr("candleviewer.oms.order_machine.PORT_TIMEOUT", 0.0)
    monkeypatch.setattr(rig.orders, "get", _answering(row))
    monkeypatch.setattr(rig.audit, "write", _stalled)
    async with asyncio.timeout(10):
        with pytest.raises(TimeoutError):
            await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.1"))


async def test_a_notice_route_that_stalls_pages_and_the_step_stands(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("candleviewer.oms.order_machine.PORT_TIMEOUT", 0.0)
    monkeypatch.setattr(rig.notices, "notify", _stalled)
    async with asyncio.timeout(10):
        await _unknown(rig)  # its `order_unknown` alert is given up
    assert "order notice lost: alert" in rig.pager.calls


# --- A caller's event name reaches the log and the error only bounded (codeB r2 Low) -----------


@pytest.mark.parametrize(
    ("event", "shown"),
    [("X" * 100_000, "X" * 64), ("TRIGGERED\n\x00", "TRIGGERED??"), (42, "int")],
)
async def test_an_unknown_event_name_is_logged_and_raised_only_bounded(
    rig: Rig, event: Any, shown: str
) -> None:
    """C-12.6, C-2.18: an event name outside the method's set is an untyped caller's raw value;
    the refusal logs and raises at most `MAX_TEXT` printable characters of it, or a non-text
    value's type name."""
    order = await rig.submitted()
    with capture_logs() as logs, pytest.raises(IllegalTransition) as raised:
        await rig.facade.push(ACCOUNT, order.id, event, {"updated_time": 1})
    assert raised.value.attempted == shown and len(str(raised.value)) < 120
    assert [e["attempted"] for e in logs if e["event"] == "oms_illegal_transition"] == [shown]


# --- Every B1 record, in full (codeB r2 Low, C-2.9) --------------------------------------------

#: Each B1 record as the audit writer must receive it: its action, outcome and severity, written
#: out here rather than read from `B1_AUDITS`, so a record rewritten there fails this table.
B1_RECORDS: dict[str, tuple[str, Outcome, Severity]] = {
    "halted_by_kill": ("orders.cancel", "success", "warning"),
    "kill_cancel_in_flight": ("orders.cancel", "success", "warning"),
    "kill_protection_retained": ("orders.cancel", "success", "info"),
    "kill_no_cancel_unsubmitted": ("orders.cancel", "denied", "info"),
    "kill_no_cancel_unverified_duplicate": ("orders.cancel", "denied", "warning"),
    "kill_ignored_terminal": ("orders.cancel", "denied", "info"),
    "kill_ignored_unowned": ("orders.cancel", "denied", "warning"),
    "kill_cancel_timeout": ("orders.cancel", "failure", "error"),
    "kill_cancel_failed": ("orders.cancel", "failure", "error"),
    "kill_cancel_lost": ("orders.cancel", "failure", "error"),
    "guard_denied": ("oms.reconcile_anomaly", "denied", "error"),
    "reconcile_anomaly": ("oms.reconcile_anomaly", "denied", "error"),
}


async def test_each_b1_record_is_written_in_full(rig: Rig) -> None:
    """C-2.9: every record B1's hook names reaches the audit writer with the action, order,
    account, outcome, severity, reason and detail this table gives it; a failed or timed-out
    KILL cancel is never written as a success."""
    order = await rig.submitted()
    for name in B1_RECORDS:
        await rig.facade._audited(name, {"order_id": str(order.id)})
    detail: dict[str, str | None] = {"order_link_id": order.order_link_id, "state": "submitted"}
    detail |= {"exec_id": None, "trigger": None}
    assert set(B1_RECORDS) == set(B1_AUDITS)
    assert rig.audit.records == [
        OrderAuditRecord(action, order.id, ACCOUNT, outcome, severity, name, detail)
        for name, (action, outcome, severity) in B1_RECORDS.items()
    ]


# --- A fill the row holds already is the row moving on (codeA r2 Low, S4, S7) -------------------


async def test_a_fill_the_row_holds_already_rebuilds_the_machine(rig: Rig) -> None:
    """S7: a fill's COMMIT landed after the machine was rebuilt, so the machine is behind its row.
    The fill delivered again finds its execution stored: the row moved on under the machine, not
    a double count, so the machine is rebuilt from the row, holds the fill once, and its stop is
    attached."""
    order = await rig.submitted()
    late_commit = OrderStepWriter(rig.orders, ExecutionRepository(rig.fills), clock=lambda: T0)
    totals = {"filled_qty": "0.4", "cum_exec_value": "25200", "avg_price": "63000"}
    context = rig.context(order) | totals | {"fee_paid": "0"}
    fill = fill_of(order, "e1", "0.4")
    ids = (str(order.id), str(ACCOUNT), order.order_link_id)
    await late_commit(b01.Step(*ids, "submitted", "partially_filled", "EXEC", fill, context))
    with pytest.raises(OrderStepUnknown, match="StaleOrderState"):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill)
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    assert rig.context(order)["seen_exec_ids"] == ["e1"]
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.cum_exec_qty == Decimal("0.4")
    assert rig.commands.kinds() == ["place", "attach_stop"]
