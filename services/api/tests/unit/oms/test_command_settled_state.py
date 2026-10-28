"""#4807: every command the facade admits is judged on the order's settled state.

`OrderMachines.command` judges every command it takes, as it judges an exit (#4711), on the state
and version B1 settled in, never on the facade's plain view of them: under the order's lock it
waits until B1 has no step in flight and no event waiting to begin, at most `QUIESCE_TIMEOUT`, so
the command is the next event B1 takes. It is taken then, in the state it was judged in, or
refused (`IllegalTransition`) with its hook (`on_taken`) never run, and B1 holds none of it for
later. A command B1 has not settled for in time is refused, nothing sent, and counted apart from
the static table's refusals and the exits' waits. On an idle order the wait costs one pass of the
event loop and no poll. A KILL is no command and waits for none of it, and nothing the facade
sends B1 of its own waits for B1 to settle, so no step of B1's waits on a wait for itself. The
guarantee rests on B1's chart, pinned here: no state that takes a command runs an invoke or a
timer whose result B1 could take first. A command whose receipt says B1 holds it fails loudly:
logged at ERROR, counted and paged, the command answered as before.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

import pytest
from structlog.testing import capture_logs

from candleviewer.oms.errors import IllegalTransition
from candleviewer.oms.order_machine import COMMAND_EVENTS, EXITS, Actor, CommandEvent, Legality
from candleviewer.statechart import persistence
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import NewOrder
from tests.unit.oms import order_rig as orig
from tests.unit.oms.test_exit_settled_state import (
    _HELD_FOR_LATER,
    _Held,
    _Hook,
    _stepping,
    _turns,
    _Waits,
)

_QUIESCE: Final = "candleviewer.oms.order_machine.QUIESCE_TIMEOUT"
_LOOK: Final = "candleviewer.oms.order_machine.quiescent"
#: What the facade logs for a command B1 did not settle for, and for one its receipt says B1 holds.
_UNSETTLED: Final = "oms_command_unsettled"
_HELD: Final = "oms_command_deferred"
_RESOLVED: Final = {"decided_by": "owner", "reason": "resolved"}
_FOUND: Final = {"exchange_order_id": "x1"}
#: Steps B1 takes of its own (no facade call sends them), each into a final state.
_EXPIRED: Final = {"type": "EXPIRE", "updated_time": 5}
_GONE: Final = {"type": "RECON_FOUND_CANCELLED", "pass_id": "p0"}
#: Each command but the exits: its actor and payload, a state that takes it, and a step B1 takes
#: of its own from there into a final state, which takes no command, with that state.
_CASES: Final[dict[CommandEvent, tuple[Actor, dict[str, Any], str, dict[str, Any], str]]] = {
    "SEND": ("user", {}, "validated", {"type": "KILL", "reason": "operator"}, "killed"),
    "OPERATOR_RESOLVED": (
        "user", _RESOLVED, "held", {"type": "OPERATOR_RESOLVED", **_RESOLVED}, "rejected"
    ),
    "ADOPT": ("user", {}, "untracked", _GONE, "cancelled"),
    "TRANSPORT_FAULT": ("system", {"reason": "socket closed"}, "submitted", _EXPIRED, "expired"),
    "MISMATCH": ("system", {"exchange_order_id": "x9"}, "submitted", _EXPIRED, "expired"),
    "RECON_FOUND_LIVE": ("system", _FOUND, "unknown", _GONE, "cancelled"),
    "RECON_FOUND_PARTIAL": ("system", _FOUND, "unknown", _GONE, "cancelled"),
    "RECON_FOUND_FILLED": ("system", _FOUND, "unknown", _GONE, "cancelled"),
    "RECON_FOUND_CANCELLED": ("system", _FOUND, "unknown", _GONE, "cancelled"),
    "RECON_MISS": ("system", {"pass_id": "p1"}, "unknown", _GONE, "cancelled"),
}  # fmt: skip


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[orig.Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = orig.build_rig()
    yield built
    await built.facade.stop()


async def _ambiguous(_command: b01.Command) -> Mapping[str, Any]:
    raise TimeoutError  # the place's outcome is unknown (S1)


async def _in(rig: orig.Rig, state: str) -> NewOrder:
    """An order in `state`, B1 and the facade's view agreeing."""
    order = orig.order_of()
    if state == "untracked":
        order = orig.order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
        await rig.facade.discover(order, environment="demo")
    elif state == "validated":
        await rig.start(order)
    elif state == "unknown":
        rig.commands.on_place = _ambiguous
        await rig.start(order)
        await rig.facade.command(orig.ACCOUNT, order.id, "SEND", actor="user")
        await rig.quiet()
    else:
        await rig.submitted(order)
        if state == "held":
            mismatch = {"exchange_order_id": "x9"}
            await rig.facade.command(orig.ACCOUNT, order.id, "MISMATCH", mismatch, actor="system")
    assert rig.facade.state(order.id) == (state, "not_required")
    return order


async def _own_step(
    rig: orig.Rig, order: NewOrder, event: dict[str, Any], into: str, mp: pytest.MonkeyPatch
) -> tuple[Any, _Held]:
    """B1 takes `event` of its own, its write into `into` held in flight: the facade's view still
    reads the state B1 is leaving. Answers the order's interpreter and the held write."""
    held = _Held(rig, into, mp)
    interp = rig.facade._orders[order.id].interp
    interp.send(event)
    await asyncio.wait_for(held.reached.wait(), 5)  # a bound on the test, never a time
    return interp, held


def _command(
    rig: orig.Rig,
    order: NewOrder,
    event: CommandEvent,
    payload: Mapping[str, Any],
    actor: Actor,
    hook: _Hook,
) -> asyncio.Future[str]:
    sent = rig.facade.command(orig.ACCOUNT, order.id, event, payload, actor=actor, on_taken=hook)
    return asyncio.ensure_future(sent)


@pytest.mark.parametrize("event", sorted(_CASES))
async def test_a_command_that_meets_a_step_of_b1s_own_is_judged_on_the_state_b1_settles_in(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """A command that meets a step B1 takes of its own, its write in flight, is judged once B1
    settled, on the state it settled in, never on the view of the state B1 was leaving: a final
    state takes no command, so it is refused by the static table, its hook never run, nothing
    sent for it, and B1 holds none of it."""
    actor, payload, state, own, final = _CASES[event]
    order = await _in(rig, state)
    interp, held = await _own_step(rig, order, own, final, monkeypatch)
    sent, hook = list(rig.commands.sent), _Hook()
    command = _command(rig, order, event, payload, actor, hook)
    await _turns()
    held.go.set()
    with pytest.raises(IllegalTransition, match=f"{event} is not a transition of {final}"):
        await asyncio.wait_for(command, 5)  # a bound on the test, never a time
    assert (hook.calls, interp.deferred_count, rig.commands.sent) == (0, 0, sent)
    assert rig.count("oms_illegal_transitions_total") == 1


@pytest.mark.parametrize("event", sorted(_CASES))
async def test_a_command_b1_does_not_settle_for_in_time_is_refused_and_never_runs(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """A command B1 has not settled for within `QUIESCE_TIMEOUT` is refused at once, its hook
    never run and nothing sent, never judged on a state B1 may still leave: logged
    `oms_command_unsettled` and counted in `oms_command_unsettled_total`, apart from the static
    table's refusals and the exits' waits. B1, once settled, holds none of it."""
    actor, payload, state, own, final = _CASES[event]
    order = await _in(rig, state)
    interp, held = await _own_step(rig, order, own, final, monkeypatch)
    monkeypatch.setattr(_QUIESCE, 0.0)
    sent, hook = list(rig.commands.sent), _Hook()
    with capture_logs() as logs:
        command = _command(rig, order, event, payload, actor, hook)
        try:
            await _turns()
            assert command.done() and isinstance(command.exception(), IllegalTransition)
        finally:
            held.go.set()
    said = [(log["log_level"], log["attempted"]) for log in logs if log["event"] == _UNSETTLED]
    assert said == [("warning", event)]
    counted = ("oms_command_unsettled_total", "oms_exit_unsettled_total")
    assert [rig.count(name) for name in (*counted, "oms_illegal_transitions_total")] == [1, 0, 0]
    await rig.quiet()
    assert (hook.calls, interp.deferred_count, rig.commands.sent) == (0, 0, sent)


async def test_a_finding_that_meets_a_step_of_b1s_own_is_taken_in_the_state_b1_settles_in(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finding the system sends (`RECON_FOUND_LIVE`) that meets a step B1 takes of its own, the
    place's unknown outcome being written into `unknown` while the view still reads `submitting`,
    waits for that step to end, and no longer: judged on `unknown`, which takes it, it is taken at
    once, its hook run once, the order bound and live."""
    rig.commands.on_place = _ambiguous
    order = orig.order_of()
    await rig.start(order)
    held = _Held(rig, "unknown", monkeypatch)
    await rig.facade.command(orig.ACCOUNT, order.id, "SEND", actor="user")
    await asyncio.wait_for(held.reached.wait(), 5)  # a bound on the test, never a time
    assert rig.facade.state(order.id) == ("submitting", "not_required")
    hook = _Hook()
    found = _command(rig, order, "RECON_FOUND_LIVE", _FOUND, "system", hook)
    await _turns()
    held.go.set()
    assert await asyncio.wait_for(found, 5) == "submitted"
    assert (hook.calls, rig.context(order)["exchange_order_id"]) == (1, "x1")


@pytest.mark.parametrize("event", ["TRANSPORT_FAULT", "MISMATCH"])
async def test_a_system_command_is_refused_on_the_state_b1_settles_in_and_never_held(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """`TRANSPORT_FAULT` and `MISMATCH`, which `submitted` takes, meet a step B1 takes of its own
    out of `submitted` into `triggered`, which takes neither: each is refused once B1 settled,
    its hook never run, and B1, which lives on, holds none of it for a later state."""
    order, held = await _stepping(rig, monkeypatch, "TRIGGERED", into="triggered")
    actor, payload, *_ = _CASES[event]
    hook = _Hook()
    command = _command(rig, order, event, payload, actor, hook)
    await _turns()
    held.go.set()
    with pytest.raises(IllegalTransition, match=f"{event} is not a transition of triggered"):
        await asyncio.wait_for(command, 5)
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, ("triggered", "not_required"))
    assert rig.facade._orders[order.id].interp.deferred_count == 0


async def test_a_send_on_an_idle_order_waits_one_pass_of_the_loop_and_no_poll(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pipeline's `SEND`, on the order its `VALIDATE` left idle, costs the submit path two
    looks at B1, a pass of the event loop apart, and no poll (`QUIESCE_POLL`) at all."""
    order = orig.order_of()
    await rig.start(order)
    looks: list[bool] = []

    def quiescent(interp: Any) -> bool:
        looks.append(persistence.quiescent(interp))
        return looks[-1]

    waits = _Waits()
    monkeypatch.setattr(_LOOK, quiescent)
    monkeypatch.setattr("candleviewer.oms.order_machine.asyncio", waits)
    assert await rig.facade.command(orig.ACCOUNT, order.id, "SEND", actor="user") == "submitting"
    assert (looks, waits.asked) == ([True, True], [0])


@pytest.mark.parametrize("event", sorted(_CASES))
async def test_a_command_whose_receipt_says_b1_holds_it_is_logged_counted_and_paged(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """B1 never holds a command for later, so one whose receipt says it does fails loudly: logged
    at ERROR (`oms_command_deferred`, with the order's id and the command's kind), counted in
    `oms_command_deferred_total`, never as an exit, and paged; it is answered as before, with the
    state the order holds."""
    actor, payload, state, *_ = _CASES[event]
    order = await _in(rig, state)
    send = rig.facade._gateway.send

    async def holding(key: str, sent: Any, *, wait: bool = False) -> Any:
        if isinstance(sent, Mapping) and sent.get("type") == event:
            return _HELD_FOR_LATER  # B1 is never sent it: the receipt alone says B1 holds it
        return await send(key, sent, wait=wait)

    monkeypatch.setattr(rig.facade._gateway, "send", holding)
    with capture_logs() as logs:
        assert await _command(rig, order, event, payload, actor, _Hook()) == state
    said = [(x["log_level"], x["order_id"], x["kind"]) for x in logs if x["event"] == _HELD]
    assert said == [("error", str(order.id), event)]
    assert (rig.count(f"{_HELD}_total"), rig.count("oms_exit_deferred_total")) == (1, 0)
    assert (rig.pager.calls.count(_HELD), rig.pager.severities[-1]) == (1, "page")


async def test_a_kill_never_looks_for_b1_to_settle(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A KILL is no command: on an order whose B1 takes a step of its own, with B1 never reading
    settled and no time to wait for it, the KILL is recorded and the order killed, B1 never
    looked at for it (C-2.21)."""
    order, held = await _stepping(rig, monkeypatch, "TRIGGERED", into="triggered")
    looks: list[object] = []

    def never(interp: object) -> bool:
        looks.append(interp)
        return False

    monkeypatch.setattr(_LOOK, never)
    monkeypatch.setattr(_QUIESCE, 0.0)
    kill = asyncio.ensure_future(rig.facade.kill("operator", account_id=orig.ACCOUNT))
    await _turns()
    held.go.set()
    assert await asyncio.wait_for(kill, 5) == ()
    await rig.quiet()
    assert (rig.facade.state(order.id), looks) == (None, [])  # killed, final: its machine gone
    assert rig.audit.reasons("orders.cancel")[:1] == ["halted_by_kill"]


async def test_what_the_facade_sends_b1_of_its_own_never_waits_for_b1_to_settle(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a command waits for B1 to settle. What the facade sends B1 of its own, from a push, a
    turn or a KILL (a fill, its first fill's stop, a hostile fill's quarantine, the KILL), never
    looks at B1 for it, so no step of B1's, hook or turn waits on a wait for itself."""
    filled, hostile = await rig.submitted(), await rig.submitted(orig.order_of(2))
    looks: list[object] = []

    def never(interp: object) -> bool:
        looks.append(interp)
        return False

    monkeypatch.setattr(_LOOK, never)
    monkeypatch.setattr(_QUIESCE, 0.0)
    await rig.facade.push(orig.ACCOUNT, filled.id, "EXEC", orig.fill_of(filled, "e1", "0.4"))
    foreign = orig.fill_of(hostile, "e2", "0.4", exchange_order_id="x-foreign")
    await rig.facade.push(orig.ACCOUNT, hostile.id, "EXEC", foreign)
    await rig.quiet()
    assert rig.facade.state(filled.id) == ("partially_filled", "sl_present")
    assert rig.facade.state(hostile.id) == ("quarantined", "not_required")
    assert await rig.facade.kill("operator", account_id=orig.ACCOUNT) == ()
    await rig.quiet()
    assert (rig.facade.state(filled.id), rig.facade.state(hostile.id), looks) == (None, None, [])


def test_no_state_that_takes_a_command_runs_an_invoke_or_a_timer() -> None:
    """The guarantee rests on B1's chart: no `lifecycle` state that takes a command, an exit or
    any other, runs an invoke or an `after` timer, whose result B1 could take before the command,
    and the region takes none of its own but to refuse it, as the facade's static table reads B1
    (the `protection` region's answers move only that region, as #4711's test pins). The cases
    above cover every command but the exits."""
    assert set(_CASES) == COMMAND_EVENTS - EXITS
    chart = Registry().get("order")
    lifecycle = chart["states"]["lifecycle"]
    handled = Legality.of(chart).handled
    taking = {name for name in lifecycle["states"] if COMMAND_EVENTS & handled[name]}
    timed = {name for name in taking if {"invoke", "after"} & {*lifecycle["states"][name]}}
    assert taking >= {state for _, _, state, _, _ in _CASES.values()} and timed == set()
