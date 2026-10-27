"""#4643: a user's amend is recorded under its own request (C-2.9).

An exit service registers the exit it is about to command (`OmsCommandPort.expect_exit`) with
its request's principal (`actor`) and correlation id (`request_id`), and B1's call of the order's
amend spends the registration (`amend`). Each record the port writes for that amend names the
request's correlation id: each side's request (`sl.modified` / `tp.modified`, reason `amend`)
and each void of a refused one beside its principal and role, and the port's own refusal
(`orders.amend` denied), as a place's records name theirs (#3990; SEC-4609-01).

A second request's exit of the same order, registered before B1's call for the first, is a
registration of its own (SEC-4609-02). The facade takes the order's commands one at a time and
refuses a later one while the first's step stands, and B1's call spends the order's oldest
registration of its kind whose command the facade took (`take_exit`, #4662); a request whose
command the facade refused forgets its own registration and no other; and an exit whose step B1
settled without a call of the port leaves none behind. So neither request's rows or records name
the other's principal, role or request, and no exit is answered another's call.

B1's call spends a registration of its own order and kind only, never an older one of another
order or of the other kind (CR-4650-01). An exit that ends any other way than by B1's call taking
its registration forgets it as well, over the scripted facade: its settle timed out or raised, or
`aclose` cancelled it, the cancellation going on (CR-4650-03, CR-4650-04).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.exchange.base.errors import OmsErrorCode, RateBudgetExceededError
from candleviewer.exchange.base.fakes import FakeOutcome, FakeReject
from candleviewer.oms import commands as oc
from candleviewer.oms.errors import AccountScopeDenied, StoreUnavailable
from candleviewer.oms.exits import AmendTerms, ExitCaller
from candleviewer.oms.order_machine import OrderAuditRecord
from candleviewer.oms.ports import KeyedRecord, RequestRecord, StopOffset, SubmitActor
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import OwnerScope
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.command_rig import Rig
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_exits import OTHER, OWNER, exits_of, forgotten, scripted
from tests.unit.oms.test_exits_amend import scoped

#: Two principals amending one order, each under its own request's correlation id.
_A = SubmitActor(user_id=OWNER, role="owner")
_B = SubmitActor(user_id=OTHER, role="manager")
_RID_A = UUID("4b2a1c3d-5e6f-4a7b-8c9d-0e1f2a3b4c5d")
_RID_B = UUID("9c8b7a6d-5e4f-4d3c-8b2a-1f0e9d8c7b6a")
#: B1's amend of the entry's stop-loss to a tighter one: both of its sides recorded ahead.
_TIGHTER = {"stop_loss": "58500"}
#: The exit service's amend of the same order's stop, 58000 to 59000.
_TIGHTER_TERMS = AmendTerms(sides={"stop_loss": StopOffset("price", Decimal("59000"))})
_REFUSED = FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "refused")
_AMEND: oc.ExitKind = "amend"
#: B1's one cancel, which the scripted facade takes.
_SENT = ["CANCEL"]

type Named = tuple[UUID | None, str | None, UUID | None]


def _named(record: KeyedRecord) -> Named:
    """The principal, its role and the request a record names."""
    role = None if record.actor is None else record.actor.role
    return record.actor_user_id, role, record.request_id


def _as(actor: SubmitActor, request_id: UUID) -> Named:
    return actor.user_id, actor.role, request_id


def _keyed(written: list[tuple[cr.AnyRecord, int]]) -> list[KeyedRecord]:
    return [record for record, _ in written if isinstance(record, KeyedRecord)]


# --- the command port, B1's calls in a set order (`command_rig`) ---------------------------------


@pytest.fixture
def rig() -> Rig:
    return cr.build_rig()


async def _live(rig: Rig, **over: Any) -> Any:
    """An entry resting at the venue with its stop-loss and take-profit, stored `submitted`."""
    order = cr.new_order(**over)
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_order(cr.exchange_order(order), uid="100001")
    return order


@pytest.mark.parametrize(
    ("venue", "voided"),
    [(None, 0), (_REFUSED, 2), (RateBudgetExceededError("no token", retry_after_s=2.0), 2)],
    ids=["accepted", "venue_refused", "no_rate_token"],
)
async def test_a_users_amend_names_its_request_on_each_sides_request_and_void(
    rig: Rig, venue: FakeOutcome | None, voided: int
) -> None:
    """SEC-4609-01: each side's request record and, once the venue refused the amend or no rate
    token came, each void carries the request's correlation id beside its principal and role."""
    order = await _live(rig)
    cr.taken(rig.port, order.id, "amend", request_id=_RID_A, actor=_A)
    if venue is not None:
        rig.demo.script("amend_order", venue)
    await rig.port.amend(cr.command("amend", order, _TIGHTER))
    records = _keyed(rig.audits.written)
    reasons = [oc.AMEND_REASON] * 2 + [oc.AMEND_REFUSED] * voided
    assert [record.reason for record in records] == reasons
    assert {_named(record) for record in records} == {_as(_A, _RID_A)}


async def _raises(error: BaseException) -> Any:
    raise error


def _unread(target: str, error: BaseException) -> Callable[[Rig, pytest.MonkeyPatch], None]:
    """A read before the send that fails: the stored row's, the account's or the stop gate's."""

    def patch(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
        owner, name = {
            "row": (rig.orders, "get"),
            "account": (rig.accounts, "trading_account"),
            "gate": (rig.port._gate, "clear"),
        }[target]
        monkeypatch.setattr(owner, name, lambda *_a, **_k: _raises(error))

    return patch


@pytest.mark.parametrize(
    ("over", "terms", "fail", "reason"),
    [
        ({}, {"leverage": "5"}, None, "terms_not_staged"),
        ({"provenance": "recorded_stop"}, {"price": "60500"}, None, "not_amendable"),
        ({"cum_exec_qty": Decimal("0.004")}, _TIGHTER, None, "tpsl_after_fill"),
        ({}, {"stop_loss": None}, None, "native_stop_required"),
        ({"stop_loss": None}, {"take_profit": "65000"}, None, "native_stop_required"),
        ({}, {"stop_loss": "57999"}, None, "looser_than_order"),
        ({}, _TIGHTER, _unread("account", AccountScopeDenied()), "account_unavailable"),
        ({}, _TIGHTER, _unread("row", StorageError("down")), "store_unavailable"),
        ({}, _TIGHTER, _unread("account", StoreUnavailable()), "store_unavailable"),
        ({}, _TIGHTER, _unread("gate", StoreUnavailable()), "store_unavailable"),
    ],
    ids=["terms_not_staged", "not_amendable", "tpsl_rule", "native_stop", "native_stop_paired",
         "looser_stop", "account_unavailable", "row_unread", "account_unread", "gate_unread"],
)  # fmt: skip
async def test_each_refusal_the_port_records_for_a_users_amend_names_its_request(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    over: dict[str, Any],
    terms: dict[str, str | None],
    fail: Callable[[Rig, pytest.MonkeyPatch], None] | None,
    reason: str,
) -> None:
    """SEC-4609-01: the port's own refusal of a user's amend, nothing recorded ahead or sent, is
    recorded (`orders.amend` denied) under the request's correlation id too; `native_stop` asks
    the stop cleared (Q3's scope), `native_stop_paired` a take-profit on an order that holds no
    stop, so the re-paired request would go bare (`_paired`, CR-4650-02)."""
    order = await _live(rig, **over)
    cr.taken(rig.port, order.id, "amend", request_id=_RID_A, actor=_A)
    if fail is not None:
        fail(rig, monkeypatch)
    answer = await rig.port.amend(cr.command("amend", order, terms))
    assert answer["ok"] is False and rig.demo.calls == []
    [(record, _)] = rig.audits.written
    assert isinstance(record, OrderAuditRecord)
    assert (record.action, record.outcome, record.reason, record.request_id) == (
        "orders.amend", "denied", reason, _RID_A,
    )  # fmt: skip


async def test_each_registration_of_one_order_is_spent_by_b1s_call_for_it_in_turn(
    rig: Rig,
) -> None:
    """SEC-4609-02: a second request's registration of the order, made before B1's call for the
    first, never replaces the first's. B1's calls come in the order the facade took the commands,
    each spending its own: the first's, refused by the venue, requests and voids under the first
    request; the second's, sent once the first's rows are void, under the second. Each watch gets
    its own call's answer."""
    order = await _live(rig)
    first = cr.taken(rig.port, order.id, "amend", request_id=_RID_A, actor=_A)
    second = cr.taken(rig.port, order.id, "amend", request_id=_RID_B, actor=_B)
    rig.demo.script("amend_order", _REFUSED)
    refused = await rig.port.amend(cr.command("amend", order, _TIGHTER))
    taken = await rig.port.amend(cr.command("amend", order, _TIGHTER))
    assert (refused["ok"], taken["ok"]) == (False, True)
    assert first.answered and second.answered  # so a regression fails, never hangs
    assert (await first.answer(), await second.answer()) == (refused, taken)
    named = [_named(record) for record in _keyed(rig.audits.written)]
    assert named == [_as(_A, _RID_A)] * 4 + [_as(_B, _RID_B)] * 2


@pytest.mark.parametrize("refused", ["first", "second"])
async def test_a_request_the_facade_refused_forgets_its_own_registration_and_no_other(
    rig: Rig, refused: str
) -> None:
    """SEC-4609-02: the facade refused one request's command, never taken, and its exit forgot
    its registration (`forget_exit`) before B1's call for the other's command, which the facade
    took and B1's call spends, whichever was registered first; the forgotten watch answers None."""
    order = await _live(rig)
    first = rig.port.expect_exit(order.id, "amend", request_id=_RID_A, actor=_A)
    second = rig.port.expect_exit(order.id, "amend", request_id=_RID_B, actor=_B)
    gone, kept = (first, second) if refused == "first" else (second, first)
    rig.port.take_exit(kept)
    rig.port.forget_exit(gone)
    answer = await rig.port.amend(cr.command("amend", order, _TIGHTER))
    assert answer["ok"] is True and gone.answered and kept.answered
    assert (await gone.answer(), await kept.answer()) == (None, answer)
    expected = _as(_B, _RID_B) if refused == "first" else _as(_A, _RID_A)
    assert {_named(record) for record in _keyed(rig.audits.written)} == {expected}


async def test_two_requests_cancels_of_one_order_each_keep_their_own_registration(
    rig: Rig,
) -> None:
    """The cancel's registrations are kept apart alike: B1's call answers the first request's
    watch, whose command the facade took, never a second request's registered before the call,
    its command not taken (#4662)."""
    order = await _live(rig)
    first, second = (
        rig.port.expect_exit(order.id, "cancel", request_id=rid) for rid in (_RID_A, _RID_B)
    )
    rig.port.take_exit(first)
    answer = await rig.port.cancel(cr.command("cancel", order))
    assert answer["ok"] is True and first.answered and not second.answered
    assert await first.answer() == answer


async def test_b1s_amend_never_takes_another_orders_older_registration(rig: Rig) -> None:
    """CR-4650-01: B1's call spends a registration of its own order and kind only (`_spend`). An
    amend registered earlier for another order stays unanswered when B1 calls this order's amend,
    whose records name this order's request; B1's call for the other order then spends it."""
    other, order = await _live(rig, seq=1), await _live(rig)
    earlier = cr.taken(rig.port, other.id, _AMEND, request_id=_RID_A, actor=_A)
    own = cr.taken(rig.port, order.id, _AMEND, request_id=_RID_B, actor=_B)
    answer = await rig.port.amend(cr.command(_AMEND, order, _TIGHTER))
    assert answer["ok"] is True and own.answered and not earlier.answered
    assert await own.answer() == answer
    assert {_named(record) for record in _keyed(rig.audits.written)} == {_as(_B, _RID_B)}
    later = await rig.port.amend(cr.command(_AMEND, other, _TIGHTER))
    assert earlier.answered and await earlier.answer() == later


@pytest.mark.parametrize(("first", "called"), [("cancel", "amend"), ("amend", "cancel")])
async def test_b1s_call_never_takes_its_orders_older_registration_of_the_other_kind(
    rig: Rig, first: oc.ExitKind, called: oc.ExitKind
) -> None:
    """CR-4650-01: a cancel and an amend of one order, each its own request's: B1's call of one
    kind spends that kind's registration only, though the other kind's is older, which stays
    unanswered; an amend's records name its own request, never the cancel's."""
    order = await _live(rig)
    older = cr.taken(rig.port, order.id, first, request_id=_RID_A, actor=_A)
    own = cr.taken(rig.port, order.id, called, request_id=_RID_B, actor=_B)
    call = rig.port.amend if called == "amend" else rig.port.cancel
    answer = await call(cr.command(called, order, _TIGHTER if called == "amend" else None))
    assert answer["ok"] is True and own.answered and not older.answered
    assert await own.answer() == answer
    named = {_named(record) for record in _keyed(rig.audits.written)}
    assert named == ({_as(_B, _RID_B)} if called == "amend" else set())


# --- the exit service over the real facade and port (`submit_rig`) ------------------------------


@pytest.fixture
async def exit_rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


def _caller(actor: SubmitActor, request_id: UUID) -> ExitCaller:
    return ExitCaller(OwnerScope(OWNER), actor, request_id)


def _sides_named(rig: SubmitRig) -> list[Named]:
    """The principal, role and request each record of an amend's sides names."""
    written = [r for r in rig.records() if isinstance(r, KeyedRecord)]
    return [_named(r) for r in written if r.reason == oc.AMEND_REASON]


def _staging(rig: SubmitRig, monkeypatch: pytest.MonkeyPatch) -> list[UUID | str | None]:
    """In order: each exit registered (its request's id) and each call B1 made of the amend."""
    seen: list[UUID | str | None]
    port, seen = rig.port.port, []
    expect, amend = port.expect_exit, port.amend

    def registering(order_id: UUID, kind: oc.ExitKind, **kw: Any) -> oc.ExitWatch:
        seen.append(kw.get("request_id"))
        return expect(order_id, kind, **kw)

    async def calling(command: b01.Command) -> Any:
        seen.append("called")
        return await amend(command)

    monkeypatch.setattr(port, "expect_exit", registering)
    monkeypatch.setattr(port, "amend", calling)
    return seen


async def test_two_principals_amends_of_one_order_each_record_under_their_own_request(
    exit_rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-4609-02 end to end: two principals amend one order at once, the second's exit
    registered between the first's and B1's call for it (asserted, so the run proves the race it
    stages). The first amend is taken, answered as taken, its sides recorded under its own
    principal, role and request; the second's `AMEND` meets the first's step and is refused,
    recorded under its own."""
    found, exits = await scoped(exit_rig), exits_of(exit_rig)
    staged = _staging(exit_rig, monkeypatch)
    first, second = await asyncio.gather(
        exits.amend(found, _TIGHTER_TERMS, caller=_caller(_A, _RID_A), expected_seq=None),
        exits.amend(found, _TIGHTER_TERMS, caller=_caller(_B, _RID_B), expected_seq=None),
    )
    await exit_rig.quiet()
    assert staged == [_RID_A, _RID_B, "called"]
    assert (first.kind, first.status, first.lifecycle_state) == ("accepted", 202, "submitted")
    assert (second.kind, second.status, second.code) == ("refused", 422, "order_not_amendable")
    assert _sides_named(exit_rig) == [_as(_A, _RID_A)] * 2
    denied = [r for r in exit_rig.records("orders.amend") if r.outcome == "denied"]
    assert [(r.actor, r.request_id) for r in denied if isinstance(r, RequestRecord)] == [
        (_B, _RID_B)
    ]


async def test_an_exit_whose_step_b1_settled_with_no_call_leaves_no_registration_behind(
    exit_rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1 took one request's `AMEND` and settled its step with no call of the port (a step that
    left `amend_pending` first, or an invoke its record answered): that exit forgets its
    registration once B1 settled, so the next request's amend, sent through the port, is
    recorded under its own principal, role and request, never the first's."""
    found, exits = await scoped(exit_rig), exits_of(exit_rig)
    port = exit_rig.port.port

    async def uncalled(_command: b01.Command) -> dict[str, Any]:
        return {"ok": False, "error_code": OmsErrorCode.INSTRUMENT_FILTER.value}

    monkeypatch.setattr(port, "amend", uncalled)
    await exits.amend(found, _TIGHTER_TERMS, caller=_caller(_A, _RID_A), expected_seq=None)
    monkeypatch.undo()
    later = await exits.amend(found, _TIGHTER_TERMS, caller=_caller(_B, _RID_B), expected_seq=None)
    assert later.kind == "accepted"
    assert _sides_named(exit_rig) == [_as(_B, _RID_B)] * 2


# --- the exit service's other ways out, over the scripted facade (`test_exits.scripted`) ---------


async def test_an_exit_whose_settle_timed_out_forgets_its_registration() -> None:
    """CR-4650-03: B1 took the command and did not settle it within the bound, so the exit
    answers `unknown` and forgets its registration: a missing principal beats a stale one, which
    a later request's call would spend and name. A call of B1's that comes later finds none."""
    exits, machines, row, _ = await scripted("submitted", TimeoutError())
    got = await exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
    assert (got.kind, got.lifecycle_state, machines.sent) == ("unknown", "cancel_pending", _SENT)
    assert await forgotten(machines)


async def test_an_exit_whose_settle_raised_forgets_its_registration_and_raises() -> None:
    """CR-4650-04: any other raise of B1's settle forgets the registration, and goes on."""
    exits, machines, row, _ = await scripted("submitted", RuntimeError("a defect"))
    with pytest.raises(RuntimeError, match="a defect"):
        await exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
    assert machines.sent == _SENT and await forgotten(machines)


async def test_aclose_forgets_a_waiting_exits_registration_and_its_cancellation_goes_on() -> None:
    """CR-4650-04: `aclose` at shutdown cancels an exit waiting on B1's settle. Its registration is
    forgotten, and the cancellation is never swallowed: the exit's task ends cancelled, and so
    does its caller's wait."""
    exits, machines, row, _ = await scripted("submitted", "cancelled")
    machines.gate = asyncio.Event()
    caller = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=_A, reason="user", request_id=_RID_A)
    )
    await machines.entered.wait()
    [running] = exits._running
    await exits.aclose()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert running.cancelled() and await forgotten(machines)
