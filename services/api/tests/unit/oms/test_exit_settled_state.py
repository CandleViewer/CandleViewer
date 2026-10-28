"""#4711: an exit command the facade admits is judged against the order's settled state.

`OrderMachines.command` judges an exit (`AMEND`, `CANCEL`) on the state and version B1 settled
in, never on the facade's plain view of them: under the order's lock it waits until B1 has no
step in flight and no event waiting to begin, at most `QUIESCE_TIMEOUT`, so the exit is the next
event B1 takes. It is taken now, in the state it was judged in, or refused (`IllegalTransition`,
or `VersionConflict` for a version that moved on) with its hook (`on_taken`) never run, and B1
holds none of it for later. An exit B1 has not settled for in time is refused, nothing sent.
Exits on an order B1 has settled are taken as before, and a KILL waits for nothing. A machine
that is not running is waited on for nothing, and a busy B1 is looked at no faster than C-2.20
allows. The guarantee rests on B1's chart, pinned here: no state that takes an exit runs an
invoke or a timer whose result B1 could take first. An exit whose receipt says B1 holds it fails
loudly: logged at ERROR, counted and paged, the command answered as before.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, Final

import pytest
from structlog.testing import capture_logs

from candleviewer.oms.errors import (
    IllegalTransition,
    OrderNotLoaded,
    OrderStepRefused,
    VersionConflict,
)
from candleviewer.oms.order_machine import CommandEvent, Legality, PushEvent
from candleviewer.statechart import persistence
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import NewOrder
from tests.unit.oms import order_rig as orig

_TERMS: Final = {"price": "64000"}
_TAKEN: Final = {"CANCEL": "cancel_pending", "AMEND": "amend_pending"}
_QUIESCE: Final = "candleviewer.oms.order_machine.QUIESCE_TIMEOUT"
_LOOK: Final = "candleviewer.oms.order_machine.quiescent"
#: The exits (24 Sec.8.4), as B1's chart names them.
_EXITS: Final = frozenset({"AMEND", "CANCEL"})
#: What the facade logs and pages for an exit whose receipt says B1 holds it, and its counter.
_SAID: Final = "oms_exit_deferred"
_COUNTED: Final = "oms_exit_deferred_total"
#: A receipt, shaped as the runtime's, that says B1 holds the event for later.
_HELD_FOR_LATER: Final = SimpleNamespace(
    state_ids=frozenset(), changed=False, error=None, deferred=True, denied=False
)


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[orig.Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = orig.build_rig()
    yield built
    await built.facade.stop()


class _Hook:
    """An `on_taken` that counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class _Waits:
    """The facade's `asyncio`, each sleep it asks for noted (`asked`) before it is slept."""

    def __init__(self) -> None:
        self.asked: list[float] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def sleep(self, delay: float) -> None:
        self.asked.append(delay)
        await asyncio.sleep(delay)


class _Held:
    """The store's next write of a step into `state`, a fill's too, waits for `go`: B1's step
    stays in flight."""

    def __init__(self, rig: orig.Rig, state: str, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reached, self.go = asyncio.Event(), asyncio.Event()
        for store, name in ((rig.store, "transition"), (rig.fills, "commit_fill")):
            monkeypatch.setattr(store, name, self._holding(getattr(store, name), state))

    def _holding(self, write: Any, state: str) -> Any:
        async def held(unit: Any) -> Any:
            if getattr(unit, "step", unit).lifecycle_state == state and not self.go.is_set():
                self.reached.set()
                await self.go.wait()
            return await write(unit)

        return held


async def _stepping(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, push: PushEvent, into: str
) -> tuple[NewOrder, _Held]:
    """A live order on which B1 takes steps of its own, its write into `into` in flight."""
    order = await rig.submitted()
    gate, rig.commands.on_cancel = orig.gated({"ok": False, "error_code": "INSTRUMENT_FILTER"})
    await rig.facade.command(orig.ACCOUNT, order.id, "CANCEL", actor="user")
    await rig.facade.push(orig.ACCOUNT, order.id, push, {"updated_time": 5})
    held = _Held(rig, into, monkeypatch)
    gate.set()
    await asyncio.wait_for(held.reached.wait(), 5)  # a bound on the test, never a time
    return order, held


def _exit(
    rig: orig.Rig, order: NewOrder, event: CommandEvent, hook: _Hook, seq: int | None = None
) -> asyncio.Future[str]:
    payload = _TERMS if event == "AMEND" else None
    sent = rig.facade.command(
        orig.ACCOUNT, order.id, event, payload, actor="user", expected_seq=seq, on_taken=hook
    )
    return asyncio.ensure_future(sent)


async def _turns() -> None:
    for _ in range(64):
        await asyncio.sleep(0)


def _holds(rig: orig.Rig, order: NewOrder) -> int:
    """The events B1 holds for later (S10)."""
    held: int = rig.facade._orders[order.id].interp.deferred_count
    return held


async def _filled_later(rig: orig.Rig, order: NewOrder) -> None:
    await rig.facade.push(orig.ACCOUNT, order.id, "EXEC", orig.fill_of(order, "e1", "0.4"))
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")


async def test_an_amend_is_judged_on_the_state_b1_settles_in_and_never_runs_later(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `AMEND` that meets a step B1 takes of its own is judged once B1 settled, on the state it
    settled in: `triggered` takes no amend, so it is refused with its hook never run, and B1 holds
    none of it."""
    order, held = await _stepping(rig, monkeypatch, "TRIGGERED", into="triggered")
    hook = _Hook()
    amend = _exit(rig, order, "AMEND", hook)
    await _turns()
    held.go.set()
    with pytest.raises(IllegalTransition):
        await amend
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, ("triggered", "not_required"))
    assert _holds(rig, order) == 0
    await _filled_later(rig, order)
    assert "amend" not in rig.commands.kinds()


async def test_a_cancel_is_judged_on_the_state_b1_settles_in(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `CANCEL` that meets a step B1 takes of its own is judged once B1 settled: `expired`
    takes no cancel, so it is refused with its hook never run, and no second cancel is sent."""
    order, held = await _stepping(rig, monkeypatch, "EXPIRE", into="expired")
    hook = _Hook()
    cancel = _exit(rig, order, "CANCEL", hook)
    await _turns()
    held.go.set()
    with pytest.raises(IllegalTransition):
        await cancel
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, None)  # final: its machine is gone
    assert rig.commands.kinds() == ["place", "cancel"]


async def test_an_exit_is_judged_only_once_b1_has_no_step_in_flight_or_waiting(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exit is judged only once B1 has no step in flight and none waiting to begin, on the state
    its last step left, here `triggered`, which takes no amend: refused with its hook never run, and
    B1 holds none of it."""
    order, held = await _stepping(rig, monkeypatch, "TRIGGERED", into="submitted")
    hook = _Hook()
    amend = _exit(rig, order, "AMEND", hook)
    await _turns()
    held.go.set()
    with pytest.raises(IllegalTransition):
        await amend
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, ("triggered", "not_required"))
    assert _holds(rig, order) == 0


async def test_an_exit_b1_does_not_settle_for_in_time_is_refused_and_never_runs(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exit B1 has not settled for within `QUIESCE_TIMEOUT` is refused, its hook never run and
    nothing sent, never judged on a state B1 may still leave, and counted apart from the static
    table's refusals; B1, once settled, holds none of it."""
    order, held = await _stepping(rig, monkeypatch, "TRIGGERED", into="submitted")
    monkeypatch.setattr(_QUIESCE, 0.0)
    hook = _Hook()
    amend = _exit(rig, order, "AMEND", hook)
    try:
        await _turns()
        assert amend.done() and isinstance(amend.exception(), IllegalTransition)
    finally:
        held.go.set()
    unsettled = rig.count("oms_exit_unsettled_total")
    assert (unsettled, rig.count("oms_illegal_transitions_total")) == (1, 0)
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, ("triggered", "not_required"))
    assert _holds(rig, order) == 0
    await _filled_later(rig, order)
    assert "amend" not in rig.commands.kinds()


async def test_an_exit_whose_machine_is_closed_while_it_waits_is_answered_not_loaded(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exit waiting for B1 to settle when the order's machine is closed (the facade stops) is
    answered as an order no machine here holds is (`OrderNotLoaded`), its hook never run and
    nothing sent."""
    order, _held = await _stepping(rig, monkeypatch, "TRIGGERED", into="submitted")
    hook = _Hook()
    amend = _exit(rig, order, "AMEND", hook)
    await _turns()
    await rig.facade.stop()
    with pytest.raises(OrderNotLoaded):
        await amend
    assert hook.calls == 0 and "amend" not in rig.commands.kinds()


@pytest.mark.parametrize("end", ["stopped", "run loop ended"])
async def test_an_exit_on_a_machine_that_is_not_running_waits_for_nothing(
    rig: orig.Rig, end: str
) -> None:
    """A machine that is not running takes no event and holds none for later, so an exit on it
    waits for nothing, the order's lock held for no wait: it is answered at once, the runtime
    refusing the send (`OrderStepRefused`), and nothing reaches the venue."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    if end == "stopped":
        await o.interp.stop()
    else:
        o.interp._event_loop_task.cancel()
        await _turns()
    cancel = _exit(rig, order, "CANCEL", _Hook())
    try:
        await _turns()
        assert cancel.done() and isinstance(cancel.exception(), OrderStepRefused)
    finally:
        cancel.cancel()
    assert not o.lock.locked() and rig.commands.kinds() == ["place"]


async def test_b1_reads_settled_only_when_two_looks_a_pass_of_the_loop_apart_agree(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1 is taken as settled only once two looks, a pass of the event loop apart, both find it
    so: a look that finds a step begun in between starts the wait again, so an event B1 took but
    had not begun is never judged past. A look that finds B1 busy is followed by the next only a
    poll later, 10 ms at the least, so B1 is never looked at faster than ~100 Hz (C-2.20)."""
    order = await rig.submitted()
    reads = iter([True, False, True, True])
    looks: list[bool] = []

    def quiescent(_interp: object) -> bool:
        looks.append(next(reads))
        return looks[-1]

    waits = _Waits()
    monkeypatch.setattr(_LOOK, quiescent)
    monkeypatch.setattr("candleviewer.oms.order_machine.asyncio", waits)
    assert await _exit(rig, order, "CANCEL", _Hook()) == "cancel_pending"
    assert looks == [True, False, True, True]
    one_pass, poll, another_pass = waits.asked
    assert one_pass == another_pass == 0 and poll >= 0.01


async def test_an_event_b1_accepted_and_has_not_taken_keeps_an_exit_waiting(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1 with an event accepted and not yet taken is not settled, though no step of its own is
    in flight: an `AMEND` that meets one is judged once B1 has taken it, on the state it left,
    `triggered`, which takes no amend, so it is refused with its hook never run, and B1 holds
    none of it."""
    order = await rig.submitted()
    looks = 0

    def looking(interp: Any) -> bool:
        nonlocal looks
        looks += 1
        if looks == 2:  # B1 accepts an event before the look that would confirm it calm
            interp.send({"type": "TRIGGERED", "updated_time": 5})
        return persistence.quiescent(interp)

    monkeypatch.setattr(_LOOK, looking)
    hook = _Hook()
    with pytest.raises(IllegalTransition):
        await _exit(rig, order, "AMEND", hook)
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, ("triggered", "not_required"))
    assert _holds(rig, order) == 0


async def test_an_exit_is_judged_on_b1s_state_never_on_the_facades_view(rig: orig.Rig) -> None:
    """The facade judges an exit on the state B1 settled in, never on its own plain view: with the
    view `submitted` and B1 `triggered`, an `AMEND` is refused with its hook never run, and B1
    holds none of it."""
    order = await rig.submitted()
    await rig.facade.push(orig.ACCOUNT, order.id, "TRIGGERED", {"updated_time": 5})
    rig.facade._orders[order.id].lifecycle = "submitted"  # the view and B1 disagree
    hook = _Hook()
    with pytest.raises(IllegalTransition):
        await _exit(rig, order, "AMEND", hook)
    assert (hook.calls, _holds(rig, order)) == (0, 0)


async def test_an_exits_version_is_judged_on_the_step_b1_settles_on(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exit's version is checked against the step B1 settled on, never against the view's: a
    `CANCEL` at the version the facade gave before B1's step of its own committed is refused
    (`VersionConflict`), its hook never run and nothing sent."""
    order = await rig.submitted()
    gate, rig.commands.on_amend = orig.gated({"ok": True})
    await rig.facade.command(orig.ACCOUNT, order.id, "AMEND", _TERMS, actor="user")
    await rig.facade.push(orig.ACCOUNT, order.id, "EXEC", orig.fill_of(order, "e1", "0.4"))
    held = _Held(rig, "partially_filled", monkeypatch)
    gate.set()
    await asyncio.wait_for(held.reached.wait(), 5)
    hook = _Hook()
    cancel = _exit(rig, order, "CANCEL", hook, rig.facade.version(order.id))
    await _turns()
    held.go.set()
    with pytest.raises(VersionConflict):
        await cancel
    await rig.quiet()
    assert (hook.calls, rig.facade.state(order.id)) == (0, ("partially_filled", "sl_present"))
    assert "cancel" not in rig.commands.kinds()


async def test_an_exits_version_is_b1s_own_never_the_views(rig: orig.Rig) -> None:
    """An exit's version is read from the step B1 settled on, never from the view: with the view
    at another version than B1's, a `CANCEL` at the view's version is refused (`VersionConflict`),
    its hook never run and nothing sent, and one at B1's is taken."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    seq: int = rig.context(order)["event_seq"]
    o.view = {**o.view, "event_seq": seq - 1}  # the view and B1 disagree
    viewed = _Hook()
    with pytest.raises(VersionConflict):
        await _exit(rig, order, "CANCEL", viewed, seq - 1)
    assert (viewed.calls, rig.commands.kinds()) == (0, ["place"])
    hook = _Hook()
    assert (await _exit(rig, order, "CANCEL", hook, seq), hook.calls) == ("cancel_pending", 1)


@pytest.mark.parametrize("event", ["CANCEL", "AMEND"])
async def test_an_exit_on_a_settled_order_is_taken_at_once_as_before(
    rig: orig.Rig, event: CommandEvent
) -> None:
    """An exit on an order B1 has settled is taken at once at the version the facade gave: its
    hook runs once, and B1's call for it comes once."""
    order = await rig.submitted()
    hook = _Hook()
    state = await _exit(rig, order, event, hook, rig.facade.version(order.id))
    assert (state, hook.calls) == (_TAKEN[event], 1)
    await rig.quiet()
    assert rig.commands.kinds() == ["place", event.lower()] and hook.calls == 1


@pytest.mark.parametrize("event", ["CANCEL", "AMEND"])
async def test_an_exit_whose_receipt_says_b1_holds_it_is_logged_counted_and_paged(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch, event: CommandEvent
) -> None:
    """B1 never holds an exit for later, so an exit whose receipt says it does fails loudly: it is
    logged at ERROR (`oms_exit_deferred`, with the order's id and the exit's kind), counted in
    `oms_exit_deferred_total` and paged, and the command is answered as before, with the state
    the order holds. An exit B1 takes is logged, counted and paged for none of it."""
    taken, held = await rig.submitted(), await rig.submitted(orig.order_of(2))
    send = rig.facade._gateway.send

    async def holding(key: str, sent: Any, *, wait: bool = False) -> Any:
        if key == str(held.id) and isinstance(sent, Mapping) and sent.get("type") == event:
            return _HELD_FOR_LATER  # B1 is never sent it: the receipt alone says B1 holds it
        return await send(key, sent, wait=wait)

    monkeypatch.setattr(rig.facade._gateway, "send", holding)
    with capture_logs() as logs:
        assert await _exit(rig, taken, event, _Hook()) == _TAKEN[event]
        await rig.quiet()
        assert (_said(logs), rig.count(_COUNTED), rig.pager.calls) == ([], 0, [])
        hook = _Hook()
        assert (await _exit(rig, held, event, hook), hook.calls) == ("submitted", 1)
        await rig.quiet()
    assert _said(logs) == [("error", str(held.id), event)]
    assert (rig.count(_COUNTED), rig.pager.calls, rig.pager.severities) == (1, [_SAID], ["page"])


def _said(logs: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """What the facade logged of an exit whose receipt says B1 holds it: level, order and kind."""
    said = [log for log in logs if log["event"] == _SAID]
    return [(log["log_level"], log["order_id"], log["kind"]) for log in said]


async def test_a_kill_waits_for_no_step_of_b1s(
    rig: orig.Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exits' wait for B1 to settle is never a KILL's: with B1 taking a step of its own and no
    time to wait at all, a KILL is still recorded and the order killed."""
    order, held = await _stepping(rig, monkeypatch, "TRIGGERED", into="submitted")
    monkeypatch.setattr(_QUIESCE, 0.0)
    kill = asyncio.ensure_future(rig.facade.kill("operator", account_id=orig.ACCOUNT))
    await _turns()
    held.go.set()
    assert await asyncio.wait_for(kill, 5) == ()
    await rig.quiet()
    assert rig.facade.state(order.id) is None  # killed, final: its machine is gone
    assert rig.audit.reasons("orders.cancel")[:1] == ["halted_by_kill"]


def test_no_state_that_takes_an_exit_runs_an_invoke_or_a_timer() -> None:
    """The guarantee rests on B1's chart: no `lifecycle` state that takes an exit runs an invoke
    or an `after` timer, whose result B1 could take before the exit, and the region takes no exit
    of its own; what the `protection` region's invokes and timers answer moves only that
    region. A state takes an exit as the facade's static table reads it: an arm that only records
    the exit's refusal takes none (INV-B1-r)."""
    chart = Registry().get("order")
    lifecycle, protection = chart["states"]["lifecycle"], chart["states"]["protection"]
    handled = Legality.of(chart).handled
    taking = [name for name in lifecycle["states"] if _EXITS & handled[name]]
    timed = [name for name in taking if {"invoke", "after"} & {*lifecycle["states"][name]}]
    assert taking and timed == [] and not _EXITS & {*lifecycle.get("on", {})}
    nodes = protection["states"].values()
    specs = [n["invoke"].get(key) for n in nodes if "invoke" in n for key in ("onDone", "onError")]
    specs += [spec for n in nodes for spec in n.get("after", {}).values()]
    arms = [arm for spec in specs if spec for arm in (spec if isinstance(spec, list) else [spec])]
    assert arms and all(arm["target"].startswith("#order.protection.") for arm in arms)
