"""#4808: an exit the order chart refuses is recorded as a denied order action and refused.

The OMS facade's static table refuses an exit (`CANCEL`, `AMEND`) the order's state does not take,
before any send (C-2.21, 24 Sec.8.4 step 11), and B1's chart denies and records one all the same
(INV-B1-r; `untracked`'s own arm, INV-B1-l). The facade writes that refusal ahead as one M19 row
(21 Sec.3.10.1): the exit's own action, `orders.cancel` or `orders.amend`, outcome `denied`,
severity `warning`, its reason the B1 record (`operator_command_refused`, or `untracked`'s
`command_refused_unowned`), by `system:oms` with the order as its object and the state and the
exit in its detail (C-2.9). The exit is then refused as the table refuses one
(`IllegalTransition`): nothing moves, no event row is written and nothing is sent. As the table
refuses each such exit first, one the chart refuses is a defect: logged at ERROR, counted and
paged, its record lost or not. On the exit routes it is answered as the table's refusal is (an
amend's `422`, a cancel's `409 conflict`), the request's refusal recorded beside its intent,
and no exit registration is left behind. B1's refusal of the operator's resolution, of an
adoption or of `untracked`'s other commands stays logged only. Each test widens the facade's
table for itself alone (and the exit service's state check, on the exit routes), so the chart's
own refusal is what it tests.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.writer import AuditWriter
from candleviewer.oms import exits as ex
from candleviewer.oms.errors import IllegalTransition
from candleviewer.oms.exits import AmendTerms, ExitCaller
from candleviewer.oms.order_machine import CommandEvent, OrderAuditRecord, OrderMachines
from candleviewer.oms.ports import RequestRecord
from candleviewer.oms_wiring import SYSTEM_ACTOR, OmsAudit
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, ScopedOrder
from tests.unit.oms import command_rig as cr
from tests.unit.oms import order_rig as orig
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.test_exits import OWNER, REQUEST, actor, exits_of, placed

_EXITS: Final = frozenset({"AMEND", "CANCEL"})
_TERMS: Final = {"price": "64000"}
_TAKEN: Final = {"CANCEL": "cancel_pending", "AMEND": "amend_pending"}
#: The M19 action each exit's refusal is written under, written out here rather than read from the
#: facade's table, so a mapping rewritten there fails these tests.
_ACTION: Final = {"CANCEL": "orders.cancel", "AMEND": "orders.amend"}
#: The refusal's outcome and severity, and who writes it: the facade, no user and no request.
_OUTCOME: Final = "denied"
_SEVERITY: Final = "warning"
_ACTOR: Final = "system:oms"
#: The B1 record each refusal is written with as its reason: the `lifecycle` region's refusal
#: arm's (INV-B1-r), and `untracked`'s own (INV-B1-l).
_REFUSED: Final = "operator_command_refused"
_UNOWNED: Final = "command_refused_unowned"
#: What the facade logs and pages for an exit the chart refused, and its counter.
_SAID: Final = "oms_exit_chart_denied"
_COUNTED: Final = "oms_exit_chart_denied_total"
_LOST: Final = "oms_audit_record_lost"
_DOC: Final = Path(__file__).resolve().parents[5] / "docs" / "plan" / "24-internal-schemas.md"


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[orig.Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = orig.build_rig()
    yield built
    await built.facade.stop()


class _Rows:
    """The M19 writer behind the composition root's audit port (`OmsAudit`): each row the real
    writer's `build` accepts (a registered action, its columns and values, SR-E29-17), kept as the
    port hands it over."""

    def __init__(self, tmp_path: Path) -> None:
        self._real = AuditWriter(cast(Any, object()), str(tmp_path / "audit.wal"))
        self.written: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self._real.build(action, **fields)
        self.written.append((action, fields))

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        self._real.build(action, **fields)
        self.written.append((action, fields | {"name": name}))


def _rows(rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Rows:
    """From here on the facade writes its records through the composition root's audit port."""
    rows = _Rows(tmp_path)
    ports = replace(rig.facade._ports, audit=OmsAudit(rows, environment="demo"))
    monkeypatch.setattr(rig.facade, "_ports", ports)
    return rows


def _widen(facade: OrderMachines, monkeypatch: pytest.MonkeyPatch, events: frozenset[str]) -> None:
    """The facade's static table, widened in this test alone: every state lists `events`, so the
    facade sends them and B1's chart alone decides."""
    table = facade.legality
    handled = {state: listed | events for state, listed in table.handled.items()}
    monkeypatch.setattr(facade, "legality", replace(table, handled=MappingProxyType(handled)))


async def _exit(rig: orig.Rig, order: NewOrder, event: CommandEvent) -> str:
    payload = _TERMS if event == "AMEND" else None
    return await rig.facade.command(orig.ACCOUNT, order.id, event, payload, actor="user")


def _holds(rig: orig.Rig, order: NewOrder) -> int:
    """The events B1 holds for later (S10)."""
    held: int = rig.facade._orders[order.id].interp.deferred_count
    return held


def _reason(state: str) -> str:
    """B1's record of a command `state` refuses: `untracked`'s own, else the region's."""
    return _UNOWNED if state == "untracked" else _REFUSED


def _row(order: NewOrder, state: str, event: str) -> dict[str, Any]:
    """The refusal's M19 row (21 Sec.3.10.1), as the audit port hands it to the writer."""
    detail = {"order_link_id": order.order_link_id, "state": state, "exec_id": None}
    return {
        "outcome": _OUTCOME,
        "severity": _SEVERITY,
        "reason": _reason(state),
        "after_state": detail | {"trigger": event, "account_id": str(orig.ACCOUNT)},
        "request_id": None,
        "env": "demo",
        "actor_label": _ACTOR,
        "actor_user_id": None,
        "object_kind": "order",
        "object_id": str(order.id),
    }


# --- The states an order is left in whose chart arm refuses an exit (INV-B1-r) --------------------

Reach = Callable[[orig.Rig, list[asyncio.Event]], Awaitable[NewOrder]]


async def _validated(rig: orig.Rig, _gates: list[asyncio.Event]) -> NewOrder:
    order = orig.order_of()
    await rig.start(order)
    return order


async def _submitting(rig: orig.Rig, gates: list[asyncio.Event]) -> NewOrder:
    """The order sent, its place in flight."""
    gate, rig.commands.on_place = orig.gated({"ok": True, "exchange_order_id": "x1"})
    gates.append(gate)
    order = orig.order_of()
    await rig.start(order)
    await rig.facade.command(orig.ACCOUNT, order.id, "SEND", actor="user")
    return order


async def _triggered(rig: orig.Rig, _gates: list[asyncio.Event]) -> NewOrder:
    order = await rig.submitted()
    await rig.facade.push(orig.ACCOUNT, order.id, "TRIGGERED", {"updated_time": 5})
    return order


async def _cancel_pending(rig: orig.Rig, gates: list[asyncio.Event]) -> NewOrder:
    """The order's cancel in flight."""
    order = await rig.submitted()
    gate, rig.commands.on_cancel = orig.gated({"ok": True})
    gates.append(gate)
    await rig.facade.command(orig.ACCOUNT, order.id, "CANCEL", actor="user")
    return order


async def _amend_pending(rig: orig.Rig, gates: list[asyncio.Event]) -> NewOrder:
    """The order's amend in flight."""
    order = await rig.submitted()
    gate, rig.commands.on_amend = orig.gated({"ok": True})
    gates.append(gate)
    await rig.facade.command(orig.ACCOUNT, order.id, "AMEND", _TERMS, actor="user")
    return order


async def _unknown(rig: orig.Rig, _gates: list[asyncio.Event]) -> NewOrder:
    """The order's place with an ambiguous outcome (S1)."""

    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = orig.order_of()
    await rig.start(order)
    await rig.facade.command(orig.ACCOUNT, order.id, "SEND", actor="user")
    return order


async def _quarantined(rig: orig.Rig, _gates: list[asyncio.Event]) -> NewOrder:
    """A fill of another exchange order, refused as hostile (OM-T04)."""
    order = await rig.submitted()
    hostile = orig.fill_of(order, "e1", "0.4", exchange_order_id="x-foreign")
    await rig.facade.push(orig.ACCOUNT, order.id, "EXEC", hostile)
    return order


async def _held(rig: orig.Rig, _gates: list[asyncio.Event], n: int = 1) -> NewOrder:
    """Order *n*, whose id reconciliation found on another exchange order (SR-E29-03)."""
    order = await rig.submitted(orig.order_of(n))
    mismatch = {"exchange_order_id": "x9"}
    await rig.facade.command(orig.ACCOUNT, order.id, "MISMATCH", mismatch, actor="system")
    return order


async def _untracked(rig: orig.Rig, _gates: list[asyncio.Event]) -> NewOrder:
    """An exchange order reconciliation found with no local row (S9)."""
    found = orig.order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
    assert await rig.facade.discover(found, environment="demo") == "untracked"
    return found


_REACH: Final[Mapping[str, Reach]] = {
    "validated": _validated,
    "submitting": _submitting,
    "triggered": _triggered,
    "cancel_pending": _cancel_pending,
    "amend_pending": _amend_pending,
    "unknown": _unknown,
    "quarantined": _quarantined,
    "held": _held,
    "untracked": _untracked,
}
#: Each of those states with each exit its chart arm refuses: `triggered` takes a `CANCEL`.
_REFUSING: Final = [
    (state, event)
    for state in _REACH
    for event in ("CANCEL", "AMEND")
    if (state, event) != ("triggered", "CANCEL")
]


@pytest.mark.parametrize(("state", "event"), _REFUSING)
async def test_an_exit_the_chart_refuses_is_recorded_as_a_denied_order_action_and_refused(
    rig: orig.Rig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    state: str,
    event: CommandEvent,
) -> None:
    """C-2.9, INV-B1-r, INV-B1-l: an exit the chart refuses is one M19 row, the exit's own action,
    denied, at `warning`, by `system:oms` (no user, no request) with the order as its object, its
    account, the B1 record that refused it as its reason, and the state the chart refused it in
    and the exit in its detail. The command is refused in that state, as the table refuses one
    (`IllegalTransition`): no step, no version moved, no event row, nothing held, none sent."""
    gates: list[asyncio.Event] = []
    try:
        order = await _REACH[state](rig, gates)
        await rig.quiet()
        before = (rig.facade.state(order.id), rig.facade.version(order.id))
        assert before[0] is not None and before[0][0] == state
        events = await rig.events.list_for_order(orig.ACCOUNT, order.id)
        sent = rig.commands.kinds()
        rows = _rows(rig, monkeypatch, tmp_path)
        _widen(rig.facade, monkeypatch, _EXITS)
        with pytest.raises(IllegalTransition) as refused:
            await _exit(rig, order, event)
        assert (refused.value.state, refused.value.attempted) == (state, event)
        await rig.quiet()
        assert rows.written == [(_ACTION[event], _row(order, state, event))]
        assert (rig.facade.state(order.id), rig.facade.version(order.id)) == before
        assert await rig.events.list_for_order(orig.ACCOUNT, order.id) == events
        assert (rig.commands.kinds(), _holds(rig, order)) == (sent, 0)
    finally:
        for gate in gates:
            gate.set()


@pytest.mark.parametrize("event", ["CANCEL", "AMEND"])
async def test_an_exit_the_chart_refuses_is_logged_counted_and_paged(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """The facade's table refuses each exit the chart would refuse, before any send, so one the
    chart refuses is a defect: once its record is written it is logged at ERROR
    (`oms_exit_chart_denied`, with the order's id and the exit's kind), counted in
    `oms_exit_chart_denied_total` and paged. An exit B1 takes is logged, counted and paged for
    none of it, and is answered with the state it took the order to."""
    taken, held = await rig.submitted(), await _held(rig, [], 2)
    await rig.quiet()
    _widen(rig.facade, monkeypatch, _EXITS)
    paged = len(rig.pager.calls)
    with capture_logs() as logs:
        assert await _exit(rig, taken, event) == _TAKEN[event]
        await rig.quiet()
        assert (_said(logs), rig.count(_COUNTED), rig.pager.calls[paged:]) == ([], 0, [])
        with pytest.raises(IllegalTransition):
            await _exit(rig, held, event)
        await rig.quiet()
    assert _said(logs) == [("error", str(held.id), event)]
    assert rig.count(_COUNTED) == 1
    assert (rig.pager.calls[paged:], rig.pager.severities[paged:]) == ([_SAID], ["page"])


@pytest.mark.parametrize("event", ["CANCEL", "AMEND"])
async def test_a_refused_exit_whose_record_is_lost_is_still_refused_counted_and_paged(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """C-2.9: B1's audit hook never raises, so a record the audit port refuses is lost and paged
    (`oms_audit_record_lost`). The exit is refused all the same, as the table refuses one, and
    is still logged at ERROR, counted and paged as a defect, with nothing sent or moved."""
    held = await _held(rig, [])
    await rig.quiet()
    _widen(rig.facade, monkeypatch, _EXITS)
    written, paged, sent = len(rig.audit.records), len(rig.pager.calls), rig.commands.kinds()
    rig.audit.refuse = True
    with capture_logs() as logs, pytest.raises(IllegalTransition):
        await _exit(rig, held, event)
    await rig.quiet()
    assert rig.audit.records[written:] == [] and rig.commands.kinds() == sent
    assert (_said(logs), rig.count(_COUNTED)) == ([("error", str(held.id), event)], 1)
    assert (rig.pager.calls[paged:], rig.pager.severities[paged:]) == (
        [_LOST, _SAID], ["page", "page"],
    )  # fmt: skip
    assert rig.facade.state(held.id) == ("held", "not_required")


def _said(logs: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """What the facade logged of an exit the chart refused: level, order and kind."""
    said = [log for log in logs if log["event"] == _SAID]
    return [(log["log_level"], log["order_id"], log["kind"]) for log in said]


@pytest.mark.parametrize(
    ("state", "event"),
    [("submitted", "OPERATOR_RESOLVED"), ("submitted", "ADOPT"), ("untracked", "SEND")],
)
async def test_a_command_the_chart_refuses_that_is_no_exit_is_still_logged_only(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, state: str, event: CommandEvent
) -> None:
    """B1's refusal of the operator's resolution outside `held`, or of an adoption outside
    `untracked`, keeps its mapping: those are their routes' records (E45-T03, E45-S01), so the
    facade writes none of its own, logs it at INFO (`oms_b1_record`), and counts and pages none of
    it; so does `untracked`'s refusal of a command that is no exit (INV-B1-l). The order stays as
    it was, with nothing sent, and the command is answered with the state it holds."""
    order = await (_untracked(rig, []) if state == "untracked" else rig.submitted())
    _widen(rig.facade, monkeypatch, frozenset({event}))
    written, paged, sent = len(rig.audit.records), len(rig.pager.calls), rig.commands.kinds()
    with capture_logs() as logs:
        assert await rig.facade.command(orig.ACCOUNT, order.id, event, actor="user") == state
        await rig.quiet()
    logged = [(log["log_level"], log["record"]) for log in logs if log["event"] == "oms_b1_record"]
    assert logged == [("info", _reason(state))]
    assert rig.audit.records[written:] == [] and rig.pager.calls[paged:] == []
    assert rig.count(_COUNTED) == 0 and rig.commands.kinds() == sent
    assert rig.facade.state(order.id) == (state, "not_required")


# --- On the exit routes: answered as the table's refusal is (SEC-4808-02) ----------------------

#: The Owner, asking with its request's correlation id, as the route's caller does.
_CALLER: Final = ExitCaller(OwnerScope(OWNER), actor(OWNER), REQUEST)
type Written = tuple[str, str, str, object]


@pytest.fixture
async def exit_rig() -> AsyncIterator[sr.SubmitRig]:
    """The exit service over the real B1 facade, command port and fake venue (`submit_rig`)."""
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


async def _held_row(rig: sr.SubmitRig, monkeypatch: pytest.MonkeyPatch) -> OrderRow:
    """The rig's entry, sent and then held (SR-E29-03), so its chart refuses both exits. The exit
    service's own state check and the facade's table let both through, in this test alone, so
    B1's chart decides."""
    row = await placed(rig)
    mismatch = {"exchange_order_id": "x9"}
    await rig.machines.command(cr.ACCOUNT, row.id, "MISMATCH", mismatch, actor="system")
    await rig.quiet()
    assert rig.machines.state(row.id) == ("held", "not_required")
    monkeypatch.setattr(ex, "_CANCELLABLE", ex._CANCELLABLE | {"held"})
    monkeypatch.setattr(ex, "_AMENDABLE", ex._AMENDABLE | {"held"})
    _widen(rig.machines, monkeypatch, _EXITS)
    held = await rig.port.orders.get(cr.ACCOUNT, row.id)
    assert held is not None and held.lifecycle_state == "held"
    return held


def _written(rig: sr.SubmitRig, action: str, mark: int) -> list[Written]:
    """The records of `action` written since `mark`, in order: the request's own or the
    facade's, with their outcome, reason and request."""
    records = [record for record, _sent in rig.port.audits.written[mark:]]
    return [
        (type(r).__name__, r.outcome, r.reason, r.request_id)
        for r in records
        if isinstance(r, OrderAuditRecord | RequestRecord) and r.action == action
    ]


def _facades(rig: sr.SubmitRig, mark: int) -> list[tuple[str, str, str | None, str | None]]:
    """The facade's own records since `mark`: their action, severity, and state and exit."""
    records = [record for record, _sent in rig.port.audits.written[mark:]]
    return [
        (r.action, r.severity, r.detail.get("state"), r.detail.get("trigger"))
        for r in records
        if isinstance(r, OrderAuditRecord)
    ]


async def test_on_the_exit_routes_a_cancel_the_chart_refuses_is_409_conflict_and_denied(
    exit_rig: sr.SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel the chart refuses is answered as the table's refusal is, `409 conflict`, never a
    `202` that reads as a timeout. Beside the request's intent stand the facade's one denied
    record (`system:oms`, no request) and the request's own refusal with its code (24 Sec.8.4),
    and no `failure` record; the order stays held, nothing reaches the venue, and no exit
    registration is left for a later call of B1's to spend (#4643)."""
    rig = exit_rig
    row = await _held_row(rig, monkeypatch)
    mark = len(rig.port.audits.written)
    got = await exits_of(rig).cancel_admitted(
        row, actor=_CALLER.actor, reason="user", request_id=REQUEST
    )
    assert (got.kind, got.status, got.code, got.retryable) == ("refused", 409, "conflict", False)
    assert _written(rig, _ACTION["CANCEL"], mark) == [
        ("RequestRecord", "success", "user", REQUEST),
        ("OrderAuditRecord", _OUTCOME, _REFUSED, None),
        ("RequestRecord", _OUTCOME, "conflict", REQUEST),
    ]
    assert _facades(rig, mark) == [(_ACTION["CANCEL"], _SEVERITY, "held", "CANCEL")]
    assert "cancel_order" not in [call.method for call in rig.port.demo.calls]
    assert (list(rig.port.port._exits), rig.count(_COUNTED)) == ([], 1)
    assert rig.machines.state(row.id) == ("held", "not_required")


async def test_on_the_exit_routes_an_amend_the_chart_refuses_is_422_and_denied(
    exit_rig: sr.SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An amend the chart refuses is answered as the table's refusal is, `422
    order_not_amendable`, never a `202` that reads as a timeout. Beside the request's intent
    stand the facade's one denied record (`system:oms`, no request) and the request's own
    refusal with its code (24 Sec.8.4), and no `failure` record; the order stays held as it was,
    nothing reaches the venue, and no exit registration is left behind (#4643)."""
    rig = exit_rig
    row = await _held_row(rig, monkeypatch)
    exits = exits_of(rig)
    found = await exits.scope(_CALLER, row.id)
    assert isinstance(found, ScopedOrder)
    version, mark = rig.machines.version(row.id), len(rig.port.audits.written)
    cut = AmendTerms(qty=Decimal("0.009"))  # never risk-increasing: no gate meets it
    got = await exits.amend(found, cut, caller=_CALLER, expected_seq=None)
    assert (got.kind, got.status, got.code) == ("refused", 422, "order_not_amendable")
    assert _written(rig, _ACTION["AMEND"], mark) == [
        ("RequestRecord", "success", "user", REQUEST),
        ("OrderAuditRecord", _OUTCOME, _REFUSED, None),
        ("RequestRecord", _OUTCOME, "order_not_amendable", REQUEST),
    ]
    assert _facades(rig, mark) == [(_ACTION["AMEND"], _SEVERITY, "held", "AMEND")]
    assert "amend_order" not in [call.method for call in rig.port.demo.calls]
    assert (list(rig.port.port._exits), rig.count(_COUNTED)) == ([], 1)
    assert (rig.machines.state(row.id), rig.machines.version(row.id)) == (
        ("held", "not_required"), version,
    )  # fmt: skip


# --- 24 Sec.15.5 names the record as the facade writes it (SEC-4808-04) ------------------------


def test_24_names_the_record_each_string_as_the_facade_writes_it() -> None:
    """24 Sec.15.5's closed vocabulary names this record, each string as the code spells it and
    as the tests above read it from the facade's writes: the exits' actions, each registered in
    `AUDIT_ACTIONS` (C-2.9; SR-E29-17), the outcome and severity, the two B1 records as the
    reason, `system:oms`, the state and the exit in the detail, and no request."""
    assert set(_ACTION.values()) <= AUDIT_ACTIONS and _ACTOR == SYSTEM_ACTOR
    section = _DOC.read_text(encoding="utf-8").split("### 15.5 ", 1)[1].split("### 15.6 ", 1)[0]
    assert (
        "An exit B1's chart refuses as its state does not take it (`28-statechart-catalogue.md` "
        "INV-B1-r, and `untracked`'s INV-B1-l; #4808), which the facade's static table refuses "
        "first, so only a defect reaches it, is written ahead as that exit's own action, "
        f"`{_ACTION['CANCEL']}` or `{_ACTION['AMEND']}`, with outcome `{_OUTCOME}` (severity "
        f"`{_SEVERITY}`) and the B1 record as the `reason`, `{_REFUSED}`, or `{_UNOWNED}` in "
        f"`untracked`, as `{_ACTOR}` with the order as its object, the refused `state` and the "
        "exit (`trigger`) in its detail and `request_id` NULL, and the exit is then refused as "
        "the table refuses one (§8.4 step 11)."
    ) in " ".join(section.split())
