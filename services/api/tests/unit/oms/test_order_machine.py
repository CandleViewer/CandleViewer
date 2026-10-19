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
from candleviewer.oms.errors import (
    IllegalTransition,
    OrderBufferFull,
    OrderMachinesFull,
    OrderNotLoaded,
    OrderStepRefused,
    ReconcileAnomaly,
)
from candleviewer.oms.order_machine import (
    B1_AUDITS,
    MAX_HELD,
    Actor,
    CommandEvent,
    Legality,
)
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import DegradedLatchError
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import NewOrder
from tests.unit.oms.order_rig import (
    ACCOUNT,
    GATES,
    NOW_US,
    OTHER,
    READ_BACK,
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
    assert rig.audit.reasons("oms.reconcile_anomaly") == ["POST_TERMINAL_PUSH"] * 2
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
    reasons = rig.audit.reasons("oms.reconcile_anomaly")
    assert reasons == ["reconcile_anomaly", "POST_TERMINAL_PUSH"]
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
    assert rig.audit.reasons("oms.reconcile_anomaly") == ["guard_denied"]
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
    CV-C06); a reason B1 would refuse is refused before any order is touched."""
    order = await rig.submitted()
    for reason in ("", "x" * 65):
        with pytest.raises(ValueError, match="KILL reason"):
            await rig.facade.kill(reason)
    rig.store.fail_next(RuntimeError("Postgres is down"))
    assert await rig.facade.kill("kill switch engaged") == (order.id,)
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert "oms_kill_not_recorded" in rig.pager.calls


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
