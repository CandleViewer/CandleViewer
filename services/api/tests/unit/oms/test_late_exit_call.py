"""#4662: B1's late call of an exit never names another request (C-2.9).

An exit service registers its request's exit before it commands B1's facade
(`OmsCommandPort.expect_exit`), and forgets the registration on every way out but B1's call
spending it (`oms.exits`). B1's call for the exit's step can come after the exit forgot it: the
invoke a rebuilt machine resumes after `OrderStepUnknown` (SR-E29-15), one that had not begun
within the settle's bound, or one still to come when `aclose` ended the exit. Another request's
registration of the same order and kind can be held meanwhile, its command waiting at the facade
or about to be refused there. B1's call spends only a registration whose command the facade took
(`OrderMachines.command`'s `on_taken`, `OmsCommandPort.take_exit`), and the facade takes an
order's commands one at a time, refusing another while a step stands, so the late call names no
request, never the other's, and the other exit's answer is its own.

The facade calls `on_taken` once its own gates (the version check included) admitted a command,
under the order's lock and before the send: never for a command those gates refuse or whose order
no machine here holds, and on a machine a resync rebuilt, for the attempt that sends. A send the
gateway or B1 then refuses raises after it ran, and the exit forgets its registration; a hook
that raises propagates with nothing sent. An `AMEND` B1 defers is #4711's.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import pytest

from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms import commands as oc
from candleviewer.oms.errors import IllegalTransition, OrderNotLoaded, VersionConflict
from candleviewer.oms.exits import AmendTerms, ExitCaller, ExitCommands, ExitMachines, OrderExits
from candleviewer.oms.order_machine import CommandEvent, OrderMachines
from candleviewer.oms.ports import KeyedRecord, StopOffset, SubmitActor
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import NewOrder, OrderRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms import order_rig as orig
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_exits import OTHER, OWNER, Scripted, exits_of, placed, scripted
from tests.unit.oms.test_exits_amend import scoped

_A = SubmitActor(user_id=OWNER, role="owner")
_B = SubmitActor(user_id=OTHER, role="manager")
_RID_A = UUID("3c9a8b7d-6e5f-4a1b-9c2d-3e4f5a6b7c8d")
_RID_B = UUID("8d7c6b5a-4f3e-4d2c-8b1a-0f9e8d7c6b5a")
#: Both requests tighten the entry's stop, 58000 to 59000.
_TIGHTER = AmendTerms(sides={"stop_loss": StopOffset("price", Decimal("59000"))})
#: B1's amend of the command rig's entry to a tighter stop: both sides recorded ahead.
_B1_TIGHTER = {"stop_loss": "58500"}
#: The store's next commit lands, and its answer is lost: the step's outcome is unknown (S7).
_CUT_OFF = "the commit's answer was cut off"
_NO_ONE = (None, None, None)

type Named = tuple[UUID | None, str | None, UUID | None]


def _named(records: list[Any]) -> list[Named]:
    """The principal, role and request each side's request of an amend names (`sl.modified`,
    `tp.modified`, reason `amend`)."""
    keyed = [r for r in records if isinstance(r, KeyedRecord) and r.reason == oc.AMEND_REASON]
    return [(r.actor_user_id, r.actor.role if r.actor else None, r.request_id) for r in keyed]


# --- end to end: the exits over the real facade and command port (`submit_rig`) -----------------


@pytest.fixture
async def exit_rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


def _caller(actor: SubmitActor, request_id: UUID) -> ExitCaller:
    return ExitCaller(OwnerScope(OWNER), actor, request_id)


class _Late:
    """The race #4662 names, staged on the real facade and port. B1's first call of `kind` is
    held before it spends a registration (`entered`, then `go`; `spent` once it answered): the
    late call of the exit whose step's outcome was unknown, which the rebuilt machine resumes.
    The facade's command of `held_for`'s exit waits before the facade takes or refuses it
    (`waiting`, then `admit`). Each registration is kept by its request's id."""

    def __init__(
        self, rig: SubmitRig, kind: oc.ExitKind, held_for: UUID, mp: pytest.MonkeyPatch
    ) -> None:
        port, machines = rig.port.port, rig.machines
        self.made: dict[UUID | None, oc.ExitWatch] = {}
        self.entered, self.go, self.spent = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.waiting, self.admit = asyncio.Event(), asyncio.Event()
        expect, call, command = port.expect_exit, getattr(port, kind), machines.command

        def registering(order_id: UUID, kind: oc.ExitKind, **kw: Any) -> oc.ExitWatch:
            self.made[kw.get("request_id")] = watch = expect(order_id, kind, **kw)
            return watch

        async def calling(b1: b01.Command) -> Any:
            if self.entered.is_set():
                return await call(b1)
            self.entered.set()
            await self.go.wait()
            try:
                return await call(b1)
            finally:
                self.spent.set()

        async def commanding(*args: Any, **kwargs: Any) -> str:
            if list(self.made)[-1] == held_for:  # its exit registered just before it commands
                self.waiting.set()
                await self.admit.wait()
            state: str = await command(*args, **kwargs)
            return state

        mp.setattr(port, "expect_exit", registering)
        mp.setattr(port, kind, calling)
        mp.setattr(machines, "command", commanding)

    async def late_call(self) -> None:
        """B1's held call goes on and answers, while the other's command still waits."""
        await asyncio.wait_for(self.entered.wait(), 5)  # a bound on the test, never a time
        assert self.waiting.is_set()
        self.go.set()
        await asyncio.wait_for(self.spent.wait(), 5)


async def test_an_amends_late_call_after_its_unknown_step_names_no_other_request(
    exit_rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#4662, C-2.9: two principals amend one order at once. A's `AMEND` step commits but its
    answer is lost (`OrderStepUnknown`), so A's exit forgets its registration and answers
    `unknown`, while the rebuilt machine resumes the amend's invoke. B's exit registered before
    its command reached the facade; B1's late call for A's step then comes. It spends nothing,
    so its sides' requests name no principal, role or request, never B's; B's watch is not B1's
    answer to A's step, and B's command, once the facade meets it, is refused on its own terms:
    the order took steps since B read it (`409 conflict`), its watch forgotten."""
    found, exits = await scoped(exit_rig), exits_of(exit_rig)
    race = _Late(exit_rig, "amend", _RID_B, monkeypatch)
    # A's step is the store's first commit from here on
    exit_rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    first = asyncio.ensure_future(
        exits.amend(found, _TIGHTER, caller=_caller(_A, _RID_A), expected_seq=None)
    )
    second = asyncio.ensure_future(
        exits.amend(found, _TIGHTER, caller=_caller(_B, _RID_B), expected_seq=None)
    )
    got = await first
    assert (got.kind, got.lifecycle_state, got.unknown_reason) == (
        "unknown", "amend_pending", "timeout",
    )  # fmt: skip
    mine, theirs = race.made[_RID_A], race.made[_RID_B]
    assert mine.answered and await mine.answer() is None  # forgotten as its step faulted
    await race.late_call()
    assert _named(exit_rig.records()) == [_NO_ONE] * 2  # each side's request names no one
    assert not theirs.answered  # B1's late call never answered B's exit
    await exit_rig.quiet()  # A's step settled: B meets the order as A's late call left it
    race.admit.set()
    outcome = await second
    assert (outcome.kind, outcome.status, outcome.code) == ("refused", 409, "conflict")
    assert theirs.answered and await theirs.answer() is None
    await exit_rig.quiet()
    assert _named(exit_rig.records()) == [_NO_ONE] * 2


async def test_a_cancels_late_call_after_its_unknown_step_answers_no_other_exit(
    exit_rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#4662: the cancel alike. A's `CANCEL` step's outcome is unknown, so its exit forgets its
    registration; B's cancel registered before its command reached the facade. B1's late call
    for A's step cancels the order and answers no exit, never B's (whose watch would read A's
    answer as its own); B, meeting the order cancelled, answers as it stands, its watch
    forgotten."""
    row, exits = await placed(exit_rig), exits_of(exit_rig)
    race = _Late(exit_rig, "cancel", _RID_B, monkeypatch)
    exit_rig.store.fail_next(TimeoutError(_CUT_OFF), committed=True)
    first = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
    )
    second = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=_B, reason="user", request_id=_RID_B)
    )
    got = await first
    assert (got.kind, got.lifecycle_state, got.unknown_reason) == (
        "unknown", "cancel_pending", "timeout",
    )  # fmt: skip
    mine, theirs = race.made[_RID_A], race.made[_RID_B]
    assert mine.answered and await mine.answer() is None
    await race.late_call()
    assert not theirs.answered
    await exit_rig.quiet()
    race.admit.set()
    outcome = await second
    assert (outcome.kind, outcome.status, outcome.lifecycle_state) == ("accepted", 202, "cancelled")
    assert theirs.answered and await theirs.answer() is None
    assert [c.method for c in exit_rig.port.demo.calls].count("cancel_order") == 1


# --- the exits' other ways out, over the scripted facade and the real port ----------------------


async def test_an_exit_hands_the_facade_a_mark_of_its_own_registration() -> None:
    """`_commanded`'s `on_taken` marks the exit's own registration, and only once the facade
    took its command."""
    exits, machines, row, _ = await scripted("submitted", "cancelled")
    got = await exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
    assert got.kind == "accepted" and machines.sent == ["CANCEL"]
    [mine] = machines.watches.made
    assert machines.watches.taken == [mine] and mine.request_id == _RID_A


async def _on_the_port(
    *settles: str | BaseException,
) -> tuple[OrderExits, Scripted, OrderRow, cr.Rig]:
    """`test_exits.scripted`'s exits with the command port's own exit watch in place of the
    scripted one, the order it stored (`cr.new_order()`) resting at the venue."""
    exits, machines, row, port = await scripted("submitted", *settles)
    port.demo.seed_order(cr.exchange_order(cr.new_order()), uid="100001")
    return OrderExits(replace(exits._d, commands=port.port)), machines, row, port


@pytest.mark.parametrize("way_out", ["settle_timed_out", "aclose"])
async def test_a_late_call_after_the_exit_ended_answers_no_other_exit(way_out: str) -> None:
    """#4662, CR-4650-03 and -04: A's exit ended while B1's step stood, its settle out of time or
    cancelled by `aclose`, and forgot its registration (taken, as the facade took its command).
    B's exit then registered, its command not yet at the facade. B1's call for A's step, coming
    now, spends neither: B's watch stays B's own, unanswered."""
    if way_out == "settle_timed_out":
        exits, machines, row, port = await _on_the_port(TimeoutError())
        got = await exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
        assert (got.kind, got.unknown_reason) == ("unknown", "timeout")
    else:
        exits, machines, row, port = await _on_the_port("cancelled")
        machines.gate = asyncio.Event()
        task = asyncio.ensure_future(
            exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
        )
        await machines.entered.wait()
        await exits.aclose()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert machines.sent == ["CANCEL"]
    theirs = port.port.expect_exit(row.id, "cancel", request_id=_RID_B, actor=_B)
    answer = await port.port.cancel(cr.command("cancel", row))
    assert answer["ok"] is True and not theirs.answered


# --- the command port: B1's call spends a registration the facade took (`take_exit`) ------------


async def _resting(rig: cr.Rig) -> NewOrder:
    """An entry resting at the venue with its stop and take-profit, stored `submitted`."""
    order = cr.new_order()
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_order(cr.exchange_order(order), uid="100001")
    return order


def _b1(kind: oc.ExitKind, rig: cr.Rig, order: NewOrder) -> Any:
    """B1's call of `kind` for the order, as its invoke makes it."""
    if kind == "amend":
        return rig.port.amend(cr.command("amend", order, _B1_TIGHTER))
    return rig.port.cancel(cr.command("cancel", order))


@pytest.mark.parametrize("kind", ["cancel", "amend"])
async def test_b1s_call_spends_no_registration_whose_command_the_facade_has_not_taken(
    kind: oc.ExitKind,
) -> None:
    """`_spend`, #4662: a registration whose command waits at the facade, or which the facade
    refused, is no call's to spend: B1's call (the venue refuses it, so the order stays live)
    answers no watch, and an amend's records name no request. Once the facade took the command
    (`take_exit`), B1's next call spends it, an amend's records under its own request."""
    rig = cr.build_rig()
    order = await _resting(rig)
    waiting = rig.port.expect_exit(order.id, kind, request_id=_RID_B, actor=_B)
    rig.demo.script(f"{kind}_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003))
    first = await _b1(kind, rig, order)
    assert first["ok"] is False and not waiting.answered
    unnamed = [_NO_ONE] * 2 if kind == "amend" else []
    assert _named([r for r, _ in rig.audits.written]) == unnamed
    rig.port.take_exit(waiting)
    again = await _b1(kind, rig, order)
    assert again["ok"] is True and waiting.answered and await waiting.answer() == again
    own = [(OTHER, "manager", _RID_B)] * 2 if kind == "amend" else []
    assert _named([r for r, _ in rig.audits.written]) == unnamed + own


async def test_a_watch_no_longer_held_is_never_taken_again() -> None:
    """`take_exit` marks only a registration the port still holds: a watch no longer held, here
    one its exit forgot, is never registered anew, so B1's later call spends nothing. A watch
    answers once, so an amend's records show it: they name no principal, role or request."""
    rig = cr.build_rig()
    order = await _resting(rig)
    gone = rig.port.expect_exit(order.id, "amend", request_id=_RID_A, actor=_A)
    rig.port.forget_exit(gone)
    rig.port.take_exit(gone)
    answer = await _b1("amend", rig, order)
    assert answer["ok"] is True and gone.answered and await gone.answer() is None
    assert _named([r for r, _ in rig.audits.written]) == [_NO_ONE] * 2


# --- the facade's `on_taken` (`OrderMachines.command`) ----------------------------------------


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[orig.Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = orig.build_rig()
    yield built
    await built.facade.stop()


class _Taken:
    """An `on_taken` that keeps, for each call, whether the order's lock was held, the order's
    lifecycle state and B1's port calls so far, and the machine that held the order."""

    def __init__(self, rig: orig.Rig, order_id: UUID) -> None:
        self.rig, self.order_id = rig, order_id
        self.seen: list[tuple[bool, str, list[str]]] = []
        self.machines: list[object] = []

    def __call__(self) -> None:
        o = self.rig.facade._orders[self.order_id]
        state = (self.rig.facade.state(self.order_id) or ("",))[0]
        self.seen.append((o.lock.locked(), state, self.rig.commands.kinds()))
        self.machines.append(o)


async def test_on_taken_runs_once_under_the_lock_after_every_gate_and_before_the_send(
    rig: orig.Rig,
) -> None:
    """The exit's mark is set before B1 can call for the step: once, under the order's lock, once
    the version check admitted the command, with the order still where it was and B1's cancel
    not yet called."""
    order = await rig.submitted()
    taken = _Taken(rig, order.id)
    seq = rig.facade.version(order.id)
    state = await rig.facade.command(
        orig.ACCOUNT, order.id, "CANCEL", actor="user", expected_seq=seq, on_taken=taken
    )
    assert state == "cancel_pending" and taken.seen == [(True, "submitted", ["place"])]
    await rig.quiet()
    assert rig.commands.kinds() == ["place", "cancel"] and len(taken.seen) == 1


_STANDS: Final[Mapping[str, str]] = {"CANCEL": "cancel_pending", "AMEND": "amend_pending"}


@pytest.mark.parametrize("first", ["CANCEL", "AMEND"])
@pytest.mark.parametrize("second", ["CANCEL", "AMEND"])
async def test_the_facade_refuses_an_exit_while_another_exits_step_stands(
    rig: orig.Rig, first: CommandEvent, second: CommandEvent
) -> None:
    """The claim #4662 rests on (`_admit`, B1's table): while one exit's step stands, its
    invoke's call not yet answered, the facade refuses a second exit of the order, of either
    kind, before any send, and never runs its `on_taken`."""
    order = await rig.submitted()
    gate, held = orig.gated({"ok": True})
    rig.commands.on_cancel = rig.commands.on_amend = held
    payload = {"price": "64000"} if first == "AMEND" else None
    state = await rig.facade.command(orig.ACCOUNT, order.id, first, payload, actor="user")
    assert state == _STANDS[first]
    taken = _Taken(rig, order.id)
    terms = {"price": "64500"} if second == "AMEND" else None
    with pytest.raises(IllegalTransition):
        await rig.facade.command(
            orig.ACCOUNT, order.id, second, terms, actor="user", on_taken=taken
        )
    assert taken.seen == []
    gate.set()
    await rig.quiet()


@pytest.mark.parametrize("refusal", ["version_moved", "not_loaded"])
async def test_on_taken_never_runs_for_a_command_the_facade_does_not_send(
    rig: orig.Rig, refusal: str
) -> None:
    """A command the facade's own gates refuse for a version that moved on (`VersionConflict`),
    or whose order no machine here holds (`OrderNotLoaded`), sends nothing and runs no
    `on_taken`. It runs once those gates admitted the command, before the send, so a send the
    gateway or B1 then refuses raises after it ran, and the exit forgets its registration."""
    order = await rig.submitted()
    calls: list[int] = []

    def hook() -> None:
        calls.append(1)

    if refusal == "version_moved":
        stale = (rig.facade.version(order.id) or 0) - 1
        with pytest.raises(VersionConflict):
            await rig.facade.command(
                orig.ACCOUNT, order.id, "CANCEL", actor="user", expected_seq=stale, on_taken=hook
            )
    else:
        with pytest.raises(OrderNotLoaded):
            await rig.facade.command(
                orig.ACCOUNT, UUID(int=99), "CANCEL", actor="user", on_taken=hook
            )
    assert calls == [] and rig.commands.kinds() == ["place"]


async def test_an_on_taken_that_raises_sends_nothing_and_lets_the_order_go(rig: orig.Rig) -> None:
    """A hook that raises propagates before the send: nothing is sent, the order's lock and
    `busy` are released, and the order takes its next command."""
    order = await rig.submitted()

    def raising() -> None:
        raise RuntimeError("the hook failed")

    with pytest.raises(RuntimeError, match="the hook failed"):
        await rig.facade.command(orig.ACCOUNT, order.id, "CANCEL", actor="user", on_taken=raising)
    o = rig.facade._orders[order.id]
    assert not o.lock.locked() and not o.busy
    await rig.quiet()
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert rig.commands.kinds() == ["place"]
    state = await rig.facade.command(orig.ACCOUNT, order.id, "CANCEL", actor="user")
    await rig.quiet()
    assert state == "cancel_pending" and rig.commands.kinds() == ["place", "cancel"]


async def test_on_taken_runs_once_on_the_machine_a_resync_rebuilt(rig: orig.Rig) -> None:
    """A command that waited on the order's lock while a resync replaced its machine is taken by
    the rebuilt machine: its `on_taken` runs once, there, and never for the closed one."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    taken = _Taken(rig, order.id)
    async with o.lock:  # as a caller's settle holds it while it resyncs
        cancel = asyncio.create_task(
            rig.facade.command(orig.ACCOUNT, order.id, "CANCEL", actor="user", on_taken=taken)
        )
        await asyncio.sleep(0)
        o.resync = True
        await rig.facade._resync(o)
    assert await cancel == "cancel_pending"
    assert [m is not o for m in taken.machines] == [True] and len(taken.seen) == 1


# --- the exits' ports keep the signatures of what they drive ------------------------------------


@pytest.mark.parametrize(
    ("declared", "built", "member"),
    [
        *[(ExitMachines, OrderMachines, n) for n in ("state", "version", "command", "settled")],
        *[
            (ExitCommands, oc.OmsCommandPort, n)
            for n in ("expect_exit", "forget_exit", "take_exit")
        ],
    ],
)
def test_the_exits_ports_keep_the_signatures_of_what_they_drive(
    declared: type, built: type, member: str
) -> None:
    """`ExitMachines` and `ExitCommands` re-declare the facade's and the command port's members,
    so a keyword one of them gains (`on_taken`) is never dropped by the other."""
    assert inspect.signature(getattr(declared, member)) == inspect.signature(getattr(built, member))
