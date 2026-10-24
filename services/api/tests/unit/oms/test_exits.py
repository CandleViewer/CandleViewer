"""The exit service's scope and cancel (E29-T04 slice 4, `oms.exits`; 24 Sec.8.4 "The exit
routes"): over the real B1 facade, the real command port and the fake venue (`submit_rig`), and,
for the waits and a cancelled caller, over a scripted facade whose bounds the test reads, never
the wall clock. The amend's admission is `test_exits_amend.py`'s."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import DenyReason
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import OmsErrorCode, TransportError
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms import commands as oc
from candleviewer.oms import exits as ex
from candleviewer.oms.errors import (
    AccountScopeDenied,
    IllegalTransition,
    OrderEntryRefused,
    OrderNotLoaded,
    OrderStepRefused,
    OrderStepUnknown,
    StoreUnavailable,
    VersionConflict,
)
from candleviewer.oms.exits import ExitCaller, ExitDeps, ExitOutcome, InFlightGuard, OrderExits
from candleviewer.oms.ports import InterimStopResolver, RequestRecord, SubmitActor
from candleviewer.oms.validator import Validator
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import DegradedLatchError
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.orders import (
    LifecycleState,
    NewOrder,
    OrderRow,
    ScopedOrder,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig

OWNER, OTHER = (
    UUID("0e000000-0000-4000-8000-0000000000aa"),
    UUID("0e000000-0000-4000-8000-0000000000bb"),
)
REQUEST = UUID("6f1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f41")
STOP_ID = "x-sl-0009"


def actor(user: UUID = sr.USER) -> SubmitActor:
    return SubmitActor(user_id=user, role="manager", session_id=sr.SESSION, ip="100.64.0.7")


def exits_of(rig: SubmitRig, **over: Any) -> OrderExits:
    deps = ExitDeps(
        machines=rig.machines, commands=rig.port.port, orders=rig.port.orders,
        stops=rig.port.stops, audit=rig.port.audits, instruments=rig.instruments,
        profiles=rig.profiles, stop_resolver=InterimStopResolver(), risk_gate=rig.risk,
        validator=Validator(read_only_gate=rig.read_only), switches=rig.port.switches,
        oms_enabled=lambda: True, environment="demo",
    )  # fmt: skip
    return OrderExits(replace(deps, **over))


def requests(rig: SubmitRig, action: str) -> list[tuple[str, str]]:
    """The exit's own records of `action`, in order: (outcome, reason)."""
    written = rig.records(action)
    return [(r.outcome, r.reason) for r in written if isinstance(r, RequestRecord)]


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


async def placed(rig: SubmitRig) -> OrderRow:
    """The rig's limit buy entry, sent and resting: `submitted`."""
    outcome = await rig.submit()
    await rig.quiet()
    assert outcome.order_id is not None
    row = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert row is not None and rig.machines.state(row.id) == ("submitted", "not_required")
    return row


# --- the scope (step 4; rulings Q6, Q7, Q12) ---------------------------------------------------


@pytest.mark.parametrize(
    ("case", "code", "denied"),
    [
        ("owner", None, None),
        ("its_creator", None, None),
        ("missing", "not_found", None),
        ("ungranted", "not_found", ex.NOT_GRANTED),
        ("view_only", "account_scope_denied", ex.VIEW_ONLY),
        ("another_users", "forbidden", ex.NOT_ORDER_CREATOR),
    ],
)
async def test_scope_answers_the_order_or_the_refusal_audited_as_q6_q7_and_q12_say(
    rig: SubmitRig, case: str, code: str | None, denied: str | None
) -> None:
    """SR-E29-13: a missing id and an order outside the scope answer the same 404, only the real
    one audited; a view-only grant is 403 `account_scope_denied`; a Manager acts only on the
    orders it created (04 Sec.7.2.2 rows 12 and 13)."""
    row = await placed(rig)
    user = sr.USER if case == "its_creator" else OTHER
    if case in ("its_creator", "view_only", "another_users"):
        rig.store.seed_access(user, cr.ACCOUNT, trade=case != "view_only")
    scope = OwnerScope(OWNER) if case == "owner" else GrantScope(user, frozenset({cr.ACCOUNT}))
    got = await exits_of(rig).scope(
        ExitCaller(scope, actor(user)), uuid4() if case == "missing" else row.id
    )
    if code is None:
        assert isinstance(got, ScopedOrder) and got.order.id == row.id and got.created_by == sr.USER
        return
    assert isinstance(got, ExitOutcome) and (got.kind, got.code) == ("refused", code)
    assert requests(rig, "rbac.denied") == ([] if denied is None else [("denied", denied)])


class _Down:
    """An order store whose every read fails as an outage."""

    def __getattr__(self, _name: str) -> Any:
        async def down(*_args: Any, **_kwargs: Any) -> Any:
            raise StorageTierUnavailable("postgres unreachable (OSError)")

        return down


async def test_a_scope_read_that_fails_is_503_with_the_shared_retry(rig: SubmitRig) -> None:
    exits = exits_of(rig, orders=cast(Any, _Down()))
    got = await exits.scope(ExitCaller(OwnerScope(OWNER), actor(OWNER)), uuid4())
    assert isinstance(got, ExitOutcome)
    assert (got.status, got.code, got.retry_after_s, got.retryable) == (
        503, "store_unavailable", 1, True,
    )  # fmt: skip


async def test_accounts_in_scope_refuses_the_whole_request_or_a_read_that_fails(
    rig: SubmitRig,
) -> None:
    exits = exits_of(rig)
    assert await exits.accounts_in_scope(OwnerScope(OWNER), ()) == (cr.ACCOUNT,)
    with pytest.raises(AccountScopeDenied):  # SR-E29-13: one outside refuses all
        await exits.accounts_in_scope(OwnerScope(OWNER), (cr.ACCOUNT, uuid4()))
    with pytest.raises(StoreUnavailable):
        await exits_of(rig, orders=cast(Any, _Down())).accounts_in_scope(OwnerScope(OWNER), ())


async def test_a_stores_own_scope_refusal_of_the_account_set_is_403_never_503(
    rig: SubmitRig,
) -> None:
    """SR-E29-13: a scope refusal is no outage. Met unwrapped, the store's `AccountsOutOfScope`
    rather than the repository's `AccountScopeDenied`, it is still `403 account_scope_denied`."""
    exits = exits_of(rig, orders=rig.store)
    with pytest.raises(AccountScopeDenied):
        await exits.accounts_in_scope(OwnerScope(OWNER), (cr.ACCOUNT, uuid4()))


def test_the_rbac_denied_reasons_are_those_enforce_builds_from_its_enums() -> None:
    """Ruling Q12: `rbac.denied`'s reasons as `auth.scopes.enforce` writes them for `orders:write`
    on `granted_accounts` (F's route builds the first so), never a literal adrift of the enums."""

    def built(reason: DenyReason) -> str:
        return f"{reason.value}:{Permission.ORDERS_WRITE.value}:{Scope.GRANTED_ACCOUNTS.value}"

    granted, trading = DenyReason.ACCOUNT_NOT_GRANTED, DenyReason.TRADING_NOT_GRANTED
    assert (ex.NOT_GRANTED, ex.VIEW_ONLY) == (built(granted), built(trading))


# --- cancel_admitted (rulings Q8, Q9, Q11; the 12:30Z rulings) -----------------------------------


@pytest.mark.parametrize("reason", ["user", "cancel_all"])
async def test_cancel_admitted_sends_one_cancel_and_answers_once_b1_settled_it(
    rig: SubmitRig, reason: ex.CancelReason, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accepted carries the settled state; the principal reaches the port as the watch's actor;
    the cancel is written ahead with its reason, cancel-all's for another user's order too (row
    14: no creator check here, the route's `scope` holds it)."""
    row, port = await placed(rig), rig.port.port
    asked = actor(OTHER if reason == "cancel_all" else sr.USER)
    watched: list[tuple[UUID, str, SubmitActor | None]] = []
    expect = port.expect_exit

    def recording(order_id: UUID, kind: oc.ExitKind, **kw: Any) -> oc.ExitWatch:
        watched.append((order_id, kind, kw.get("actor")))
        return expect(order_id, kind, **kw)

    monkeypatch.setattr(port, "expect_exit", recording)
    got = await exits_of(rig).cancel_admitted(row, actor=asked, reason=reason, request_id=REQUEST)
    assert (got.kind, got.status, got.lifecycle_state, got.retryable) == (
        "accepted", 202, "cancelled", False,
    )  # fmt: skip
    assert got.row is not None and got.row.lifecycle_state == "cancelled"
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1
    assert watched == [(row.id, "cancel", asked)]
    assert requests(rig, "orders.cancel") == [("success", reason), ("success", "cancelled")]


async def test_a_final_order_is_answered_as_it_stands_and_nothing_is_sent(rig: SubmitRig) -> None:
    """C-2.9 (the orchestrator's ruling of 2026-10-24 21:47Z (2)): the user's cancel is the action
    even when nothing is sent, so it is recorded ahead of its `202`, `orders.cancel` with the
    reason `already_final` (the `audit_outcome` enum has no `noop`: its outcome is `success`)."""
    row, exits = await placed(rig), exits_of(rig)
    await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    again = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=REQUEST)
    assert (again.kind, again.lifecycle_state) == ("accepted", "cancelled")
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1
    assert requests(rig, "orders.cancel") == [
        ("success", "user"), ("success", "cancelled"), ("success", "already_final"),
    ]  # fmt: skip
    noop = [r for r in rig.records("orders.cancel") if isinstance(r, RequestRecord)][-1]
    assert noop.request_id == REQUEST
    assert {k: noop.detail[k] for k in ("operation", "state")} == {
        "operation": "cancel", "state": "cancelled",
    }  # fmt: skip


async def test_a_final_orders_cancel_that_cannot_be_recorded_is_503_audit_unavailable(
    rig: SubmitRig,
) -> None:
    """C-2.9: no order action is answered unrecorded, a cancel that finds nothing to send included;
    nothing is sent either way."""
    row, exits = await placed(rig), exits_of(rig)
    await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    rig.port.audits.refuse = RuntimeError("the audit WAL refused the record")
    got = await exits.cancel_admitted(row, actor=actor(), reason="cancel_all", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "audit_unavailable")
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1


async def test_an_unknown_order_is_409_conflict_nothing_sent_and_audited(rig: SubmitRig) -> None:
    """Q8: reconciliation decides it; until E29-T06 only a KILL cancels it."""
    rig.port.demo.script("place_order", TransportError("the line went down"))
    outcome = await rig.submit()
    await rig.quiet()
    assert outcome.order_id is not None and rig.machines.state(outcome.order_id) is not None
    row = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert row is not None and row.lifecycle_state == "unknown"
    got = await exits_of(rig).cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code, got.retryable) == ("refused", 409, "conflict", False)
    assert "cancel_order" not in [c.method for c in rig.port.demo.calls]
    assert requests(rig, "orders.cancel") == [("denied", "conflict")]


async def test_the_venues_refusal_is_502_with_its_code_and_the_order_live(rig: SubmitRig) -> None:
    row = await placed(rig)
    refusal = FakeReject(OmsErrorCode.PRICE_OUT_OF_BOUNDS, exchange_ret_code=110003)
    rig.port.demo.script("cancel_order", refusal)
    got = await exits_of(rig).cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code, got.exchange_ret_code) == (
        "refused", 502, "exchange_error", 110003,
    )  # fmt: skip
    assert rig.machines.state(row.id) == ("submitted", "not_required")  # INV-B1-j
    assert requests(rig, "orders.cancel")[-1] == ("denied", "exchange_error")


async def test_the_venues_110001_parks_the_order_unknown_never_re_sent(rig: SubmitRig) -> None:
    """D2 and the 12:30Z ruling 2: the base's B1 (S4-B1's follow-up) marks the venue's 110001 on
    the watch, so the order is parked `unknown` as `already_terminal`, with its code, for
    reconciliation to end; the cancel is never re-sent (24 Sec.8.2 S1)."""
    row = await placed(rig)
    gone = FakeReject(OmsErrorCode.ORDER_NOT_FOUND, exchange_ret_code=110001)
    rig.port.demo.script("cancel_order", gone)
    got = await exits_of(rig).cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.lifecycle_state) == ("unknown", 202, "unknown")
    assert (got.unknown_reason, got.retryable) == ("already_terminal", False)
    assert got.exchange_ret_code == 110001
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1


async def test_any_other_raise_of_the_cancel_parks_the_order_unknown_transport(
    rig: SubmitRig,
) -> None:
    """The watch answers None for any raise but the 110001, read as `transport`: the order parked
    `unknown`, never re-sent."""
    row = await placed(rig)
    rig.port.demo.script("cancel_order", TransportError("the line went down"))
    got = await exits_of(rig).cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.lifecycle_state) == ("unknown", 202, "unknown")
    assert (got.unknown_reason, got.retryable, got.exchange_ret_code) == ("transport", False, None)
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1


async def test_native_sl_a_recorded_stops_cancel_is_403_while_its_position_is_open(
    rig: SubmitRig,
) -> None:
    """Q9, C-2.6: the command port reads the position and refuses; nothing is cancelled."""
    stop = NewOrder(
        id=uuid4(), exchange_account_id=cr.ACCOUNT, order_link_id=ext_key(STOP_ID),
        symbol=cr.SYMBOL, side="Sell", intent="stop_loss", order_type="Market",
        qty=Decimal("0.010"), trigger_price=Decimal("58000"), reduce_only=True,
        close_on_trigger=True, tpsl_mode="Partial", exchange_order_id=STOP_ID,
        provenance="recorded_stop", state="accepted", lifecycle_state="submitted",
    )  # fmt: skip
    await rig.machines.materialise(stop, environment="demo")
    rig.port.demo.seed_position(cr.position())
    row = await rig.port.orders.get(cr.ACCOUNT, stop.id)
    assert row is not None and row.provenance == "recorded_stop"
    got = await exits_of(rig).cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", 403, "risk_limit_breached")
    assert "cancel_order" not in [c.method for c in rig.port.demo.calls]
    assert (rig.machines.state(row.id) or ("",))[0] == "submitted"  # INV-B1-j: kept live


async def test_two_cancels_of_one_order_under_two_keys_are_both_202_and_one_is_sent(
    rig: SubmitRig,
) -> None:
    """22 `cancelOrder`: an order whose cancel is in flight answers `202`. Two cancels of one
    order under two keys, which the in-flight guard holds apart: the second meets the first's
    `cancel_pending` at the facade (`IllegalTransition`) and answers as the order then stands,
    never `409`; the venue sees one cancel."""
    row, exits = await placed(rig), exits_of(rig)
    first, second = await asyncio.gather(
        exits.cancel_admitted(row, actor=actor(), reason="user", request_id=REQUEST),
        exits.cancel_admitted(row, actor=actor(OWNER), reason="cancel_all", request_id=None),
    )
    assert [(o.kind, o.status, o.lifecycle_state) for o in (first, second)] == [
        ("accepted", 202, "cancelled"), ("accepted", 202, "cancelled"),
    ]  # fmt: skip
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1


# --- the waits, a cancelled caller and the watch's answer, on a scripted facade ------------------


@dataclass
class Watches:
    """`ExitCommands`: each watch kept for the scripted facade to answer; `made` every one
    registered, in order."""

    held: dict[tuple[UUID, str], oc.ExitWatch] = field(default_factory=dict)
    made: list[oc.ExitWatch] = field(default_factory=list)

    def expect_exit(self, order_id: UUID, kind: oc.ExitKind, **kw: Any) -> oc.ExitWatch:
        future = asyncio.get_running_loop().create_future()
        watch = self.held[(order_id, kind)] = oc.ExitWatch(order_id, kind, future, **kw)
        self.made.append(watch)
        return watch

    def forget_exit(self, order_id: UUID, kind: oc.ExitKind) -> None:
        self.held.pop((order_id, kind)).resolve(None)


@dataclass
class Scripted:
    """`ExitMachines` a test scripts: `held` the state, each of `settles` one `settled` call's
    answer (a state, the watch then answered `answer`, or an error raised), each bound asked kept
    in `waits` and each command taken in `sent`; `refuse`, when set, is what `command` raises,
    taking nothing, the order then in `moved` when one is given (another request took it), or
    its machine evicted when `gone`; `gate`, when set, holds every `settled` until set."""

    held: str | None
    settles: list[str | BaseException]
    watches: Watches
    answer: dict[str, Any] | None
    waits: list[float] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    refuse: BaseException | None = None
    moved: str | None = None
    gone: bool = False
    gate: asyncio.Event | None = None
    entered: asyncio.Event = field(default_factory=asyncio.Event)

    def state(self, order_id: UUID) -> tuple[str, str] | None:
        return None if self.held is None else (self.held, "not_required")

    def version(self, order_id: UUID) -> int | None:
        return 7

    async def command(
        self, account_id: UUID, order_id: UUID, event: Any, *_a: Any, **_k: Any
    ) -> str:
        if self.refuse is not None:
            self.held = None if self.gone else self.moved or self.held
            raise self.refuse
        self.sent.append(event)
        self.held = "cancel_pending"
        return self.held

    async def settled(
        self, account_id: UUID, order_id: UUID, *, leaving: str, timeout_s: float
    ) -> str:
        self.waits.append(timeout_s)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        out = self.settles.pop(0)
        if isinstance(out, BaseException):
            raise out
        if (watch := self.watches.held.get((order_id, "cancel"))) is not None:
            watch.resolve(self.answer)
        self.held = out
        return out


_OK: dict[str, Any] = {"ok": True}
_SENT = ["CANCEL"]


async def scripted(
    held: str | None,
    *settles: str | BaseException,
    answer: dict[str, Any] | None = _OK,
    stored: LifecycleState = "submitted",
    **over: Any,
) -> tuple[OrderExits, Scripted, OrderRow, cr.Rig]:
    """The exits over `Scripted` and the command rig's stores, the order stored `stored`, and
    `over` replacing any other dependency."""
    port = cr.build_rig()
    row = await port.stored(cr.new_order(), lifecycle=stored)
    watches = Watches()
    machines = Scripted(held, list(settles), watches, answer)
    deps = ExitDeps(
        machines=machines, commands=watches, orders=port.orders, stops=port.stops,
        audit=port.audits, instruments=sr.Instruments(), profiles=sr.Profiles(),
        stop_resolver=InterimStopResolver(), risk_gate=sr.Risk(None),
        validator=Validator(read_only_gate=sr.ReadOnly()), switches=port.switches,
        oms_enabled=lambda: True, environment="demo",
    )  # fmt: skip
    return OrderExits(replace(deps, **over)), machines, row, port


def written(port: cr.Rig) -> list[tuple[str, str]]:
    """The exit's own records on the command rig, in order: (outcome, reason)."""
    return [(r.outcome, r.reason) for r, _ in port.audits.written if isinstance(r, RequestRecord)]


async def forgotten(machines: Scripted) -> bool:
    """Whether the one watch the exit registered was forgotten: dropped, and answered None."""
    [watch] = machines.watches.made
    return machines.watches.held == {} and watch.answered and await watch.answer() is None


def refuse_after(audits: cr.Audits, landed: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """`audits` lands `landed` records, then refuses every later one."""
    write = audits.write

    async def counted(record: cr.AnyRecord) -> None:
        if len(audits.written) >= landed:
            raise RuntimeError("the audit WAL refused the record")
        await write(record)

    monkeypatch.setattr(audits, "write", counted)


@pytest.mark.parametrize(
    ("held", "settles", "kind", "state", "waits", "sent"),
    [
        ("amend_pending", [TimeoutError()], "refused", None, [10.0], []),
        ("cancel_pending", [TimeoutError()], "unknown", "cancel_pending", [10.0], []),
        ("submitted", [TimeoutError()], "unknown", "cancel_pending", [11.0], _SENT),
        ("validated", ["submitting", "submitted", "cancelled"], "accepted", "cancelled",
         [10.0, 10.0, 11.0], _SENT),
        ("validated", ["submitting", TimeoutError()], "refused", None, [10.0, 10.0], []),
        ("submitting", ["submitting"], "refused", None, [10.0], []),
        ("held", [], "refused", None, [], []),
        (None, [], "refused", None, [], []),
    ],
    ids=["transitional", "in-flight", "own-settle", "hop-by-hop", "a-hop-unsettled",
         "row-unmoved", "q8-state", "no-machine"],
)  # fmt: skip
async def test_the_waits_are_bounded_and_each_answers_as_the_contract_says(
    held: str | None, settles: list[Any], kind: str, state: str | None, waits: list[float],
    sent: list[str],
) -> None:  # fmt: skip
    """D9: a transitional step is waited out hop by hop (`validated`, then `submitting`), all
    within one `CV_COMMAND_TIMEOUT` (else `409 conflict`; a cancel already in flight is B1's,
    `unknown` `timeout`), then the cancel's own settle at most `CV_COMMAND_TIMEOUT` + 1 s, so
    about 21 s in all, never unbounded; no accepted outcome but a settled one (the 12:30Z ruling
    6)."""
    exits, machines, row, _ = await scripted(held, *settles)
    got = await exits.cancel_admitted(row, actor=actor(), reason="cancel_all", request_id=None)
    assert (got.kind, got.lifecycle_state, machines.waits, machines.sent) == (
        kind,
        state,
        waits,
        sent,
    )
    assert got.code == ("conflict" if kind == "refused" else None)
    assert got.retryable is (kind == "unknown")


async def test_a_caller_cancelled_before_the_write_ahead_commits_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exits, machines, row, port = await scripted("submitted", "cancelled")
    entered = asyncio.Event()

    async def hangs(_record: Any) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(port.audits, "write", hangs)
    task = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=actor(), reason="cancel_all", request_id=None)
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert machines.sent == [] and exits._running == set()


async def test_a_caller_cancelled_after_the_command_leaves_the_cancel_with_b1() -> None:
    """The 12:30Z ruling 5: never re-sent, never undone; it settles and is recorded."""
    exits, machines, row, port = await scripted("submitted", "cancelled")
    machines.gate = asyncio.Event()
    task = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=actor(), reason="cancel_all", request_id=None)
    )
    await machines.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    [running] = exits._running
    machines.gate.set()
    outcome = await running
    assert (outcome.kind, outcome.lifecycle_state, machines.sent) == (
        "accepted",
        "cancelled",
        ["CANCEL"],
    )
    assert written(port) == [("success", "cancel_all"), ("success", "cancelled")]
    assert exits._running == set()


async def test_aclose_ends_an_exit_still_running_at_shutdown() -> None:
    """`aclose` is the shutdown's: it cancels the exits still running and awaits them."""
    exits, machines, row, _ = await scripted("submitted", "cancelled")
    machines.gate = asyncio.Event()
    task = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    )
    await machines.entered.wait()
    await exits.aclose()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exits._running == set()


async def test_after_aclose_a_cancel_starts_nothing() -> None:
    """Once the service is closed no exit starts: `503 oms_not_ready`, as the runtime answers
    once stopped, with nothing recorded, commanded or sent."""
    exits, machines, row, port = await scripted("submitted", "cancelled")
    await exits.aclose()
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "oms_not_ready")
    assert (machines.sent, machines.watches.made, written(port)) == ([], [], [])
    assert exits._running == set()


async def test_a_cancel_whose_intent_was_written_as_aclose_ran_starts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`aclose` while the cancel's intent is written: nothing starts, `503 oms_not_ready`, the
    refusal recorded beside the intent (C-2.9)."""
    exits, machines, row, port = await scripted("submitted", "cancelled")
    entered, release, write = asyncio.Event(), asyncio.Event(), port.audits.write

    async def held(record: cr.AnyRecord) -> None:
        entered.set()
        await release.wait()
        await write(record)

    monkeypatch.setattr(port.audits, "write", held)
    task = asyncio.ensure_future(
        exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    )
    await entered.wait()
    await exits.aclose()
    release.set()
    got = await task
    assert (got.kind, got.status, got.code) == ("refused", 503, "oms_not_ready")
    assert (machines.sent, machines.watches.made, exits._running) == ([], [], set())
    assert written(port) == [("success", "user"), ("denied", "oms_not_ready")]


# --- the cancel core's error paths ---------------------------------------------------------------


async def test_a_cancel_whose_intent_cannot_be_recorded_is_503_and_sends_nothing() -> None:
    """C-2.9: the write-ahead `orders.cancel` that does not land answers `503 audit_unavailable`
    before anything is commanded: no watch, no task, nothing sent."""
    exits, machines, row, port = await scripted("submitted", "cancelled")
    port.audits.refuse = RuntimeError("the audit WAL refused the record")
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "audit_unavailable")
    assert (machines.sent, machines.watches.made, written(port)) == ([], [], [])
    assert exits._running == set()


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (VersionConflict(), 412, "version_conflict"),
        (OrderStepRefused("CANCEL", "StorageTierUnavailable"), 503, "store_unavailable"),
        (IllegalTransition("held", "CANCEL"), 409, "conflict"),
        (OrderNotLoaded("no machine in this process holds the order"), 409, "conflict"),
        (DegradedLatchError("latched"), 409, "conflict"),
    ],
    ids=["version", "step-refused", "illegal", "not-loaded", "latched"],
)
async def test_a_command_the_facade_did_not_take_is_refused_and_its_watch_forgotten(
    error: BaseException, status: int, code: str
) -> None:
    """`_taken_not`: a stale version (412), a step the store refused (503, the shared retry), a
    state the order no longer takes it in, an order not loaded or a latched machine (409, CV-C63):
    nothing sent, the watch forgotten (it answers None), the refusal recorded beside the intent."""
    exits, machines, row, port = await scripted("submitted")
    machines.refuse = error
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", status, code)
    assert machines.sent == [] and await forgotten(machines)
    assert written(port) == [("success", "user"), ("denied", code)]


async def test_a_step_whose_outcome_is_not_known_answers_the_order_as_it_stands() -> None:
    """`OrderStepUnknown`: B1 rebuilt the order from its events, so the cancel is never re-sent
    and answers the state the order stands in, `unknown`, `timeout`."""
    exits, machines, row, port = await scripted("submitted")
    machines.refuse = OrderStepUnknown("CANCEL", "StepOutcomeUnknown")
    machines.moved = "cancel_pending"
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.lifecycle_state, got.unknown_reason) == (
        "unknown", 202, "cancel_pending", "timeout",
    )  # fmt: skip
    assert machines.sent == [] and await forgotten(machines)
    assert written(port) == [("success", "user"), ("failure", "timeout")]


async def test_an_unlisted_raise_forgets_the_watch_and_is_raised_and_logged_once() -> None:
    """A defect at the facade: the watch forgotten, the raise the caller's, the exit's task
    logged failed once as it ends (`_ended`); only the intent was recorded."""
    exits, machines, row, port = await scripted("submitted")
    machines.refuse = RuntimeError("a defect")
    with capture_logs() as logs, pytest.raises(RuntimeError, match="a defect"):
        await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert machines.sent == [] and await forgotten(machines) and exits._running == set()
    assert written(port) == [("success", "user")]
    failed = [(log["event"], log["failure"]) for log in logs if log["log_level"] == "error"]
    assert failed == [("oms_exit_task_failed", "RuntimeError")]


async def test_a_stored_row_that_cannot_be_read_is_503_and_nothing_is_sent() -> None:
    """With no machine here the stored row decides (`_lifecycle`): a read that fails answers `503
    store_unavailable` with the shared retry, recorded, nothing sent."""
    exits, machines, row, port = await scripted(None, orders=cast(Any, _Down()))
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code, got.retry_after_s) == (
        "refused", 503, "store_unavailable", 1,
    )  # fmt: skip
    assert (machines.sent, machines.watches.made) == ([], [])
    assert written(port) == [("denied", "store_unavailable")]


async def test_a_re_read_that_fails_answers_the_order_as_the_caller_read_it() -> None:
    """`_fresh`: once B1 settled the cancel, a re-read that fails answers the row the caller
    passed, logged; the settled state stands."""
    exits, _, row, _ = await scripted("submitted", "cancelled", orders=cast(Any, _Down()))
    with capture_logs() as logs:
        got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.lifecycle_state, got.row) == ("accepted", "cancelled", row)
    assert "oms_exit_reread_failed" in [log["event"] for log in logs]


@pytest.mark.parametrize(
    ("moved", "gone", "stored", "settles", "state", "waits"),
    [
        ("cancel_pending", False, "submitted", ["cancelled"], "cancelled", [11.0]),
        ("filled", False, "submitted", [], "filled", []),
        (None, True, "cancelled", [], "cancelled", []),
    ],
    ids=["another-cancel-in-flight", "filled-meanwhile", "ended-its-machine-gone"],
)  # fmt: skip
async def test_a_cancel_the_order_moved_under_answers_as_it_then_stands(
    moved: str | None, gone: bool, stored: LifecycleState, settles: list[str], state: str,
    waits: list[float],
) -> None:  # fmt: skip
    """22 `cancelOrder`: an order whose cancel is in flight, or that ended (its machine gone, its
    row then the answer), answers `202` as it stands, never `409`: another request's cancel is
    waited for as this one's own would be."""
    exits, machines, row, port = await scripted("submitted", *settles, stored=stored)
    machines.refuse = IllegalTransition(moved or stored, "CANCEL")
    machines.moved, machines.gone = moved, gone
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.lifecycle_state, machines.waits) == (
        "accepted", 202, state, waits,
    )  # fmt: skip
    assert machines.sent == [] and await forgotten(machines)
    assert written(port) == [("success", "user"), ("success", state)]


_PORT_REFUSALS: list[tuple[dict[str, Any], int, str]] = [
    ({"error_code": b01.NATIVE_STOP_REQUIRED}, 403, "risk_limit_breached"),
    ({"error_code": oc.ACCOUNT_UNAVAILABLE}, 409, "account_unavailable"),
    ({"error_code": "RATE_BUDGET_EXCEEDED", "retry_after_s": 3}, 429, "exchange_rate_limited"),
    ({"error_code": "INSUFFICIENT_MARGIN", "exchange_ret_code": 110007}, 502, "exchange_error"),
    ({"error_code": oc.STORE_UNAVAILABLE, "retry_after_s": 1}, 503, "store_unavailable"),
]
_PORT_IDS = ["native-stop", "account", "rate", "venue", "store"]


@pytest.mark.parametrize(("answer", "status", "code"), _PORT_REFUSALS, ids=_PORT_IDS)
async def test_a_refusal_the_port_answers_is_recorded_denied_by_the_exit_service(
    answer: dict[str, Any], status: int, code: str
) -> None:
    """24 Sec.8.4: the command port records none of a user's cancel it refuses, so the exit
    service does, before it answers: `orders.cancel` denied with the code, beside the intent."""
    exits, _, row, port = await scripted("submitted", "submitted", answer={"ok": False} | answer)
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", status, code)
    assert written(port) == [("success", "user"), ("denied", code)]


@pytest.mark.parametrize("answer", [answer for answer, _, _ in _PORT_REFUSALS], ids=_PORT_IDS)
async def test_a_port_refusal_whose_record_cannot_be_written_is_503_audit_unavailable(
    answer: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9, 24 Sec.8.4: as any later refusal the route makes, never answered beside a lone
    `success` intent: `503 audit_unavailable`."""
    exits, _, row, port = await scripted("submitted", "submitted", answer={"ok": False} | answer)
    refuse_after(port.audits, 1, monkeypatch)
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "audit_unavailable")
    assert written(port) == [("success", "user")]


def test_an_exits_bounds_are_b1s_and_only_ever_tightened() -> None:
    assert (ex.TRANSITION_TIMEOUT_S, ex.SETTLE_TIMEOUT_S) == (10.0, 11.0)
    deps = cast(ExitDeps, None)
    for bound in ("transition_timeout_s", "settle_timeout_s", "store_timeout_s"):
        with pytest.raises(ValueError, match="tightened"):
            OrderExits(deps, **{bound: 60.0})


# --- the answers, the guard and the records ------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "answer", "status", "code", "retry", "retryable"),
    [
        ("cancel", {"error_code": "RATE_BUDGET_EXCEEDED", "retry_after_s": 3}, 429,
         "exchange_rate_limited", 3, True),
        ("cancel", {"error_code": oc.STORE_UNAVAILABLE, "retry_after_s": 5}, 503,
         "store_unavailable", 1, True),
        ("amend", {"error_code": oc.ACCOUNT_UNAVAILABLE}, 409, "account_unavailable", None, False),
        ("amend", {"error_code": oc.STOP_REQUEST_IN_FLIGHT, "retry_after_s": 5}, 409,
         "stop_request_in_flight", 5, False),
        ("cancel", {"error_code": b01.NATIVE_STOP_REQUIRED}, 403, "risk_limit_breached", None,
         False),
        ("amend", {"error_code": b01.NATIVE_STOP_REQUIRED}, 400, "validation_failed", None, False),
        ("amend", {"error_code": oc.STOP_LOOSENING_REFUSED}, 403, "risk_limit_breached", None,
         False),
        ("amend", {"error_code": oc.ORDER_NOT_AMENDABLE}, 422, "order_not_amendable", None, False),
        ("amend", {"error_code": "TPSL_AFTER_FILL"}, 400, "validation_failed", None, False),
        ("amend", {"error_code": "INSTRUMENT_FILTER"}, 400, "validation_failed", None, False),
        ("cancel", {"error_code": "INSUFFICIENT_MARGIN", "exchange_ret_code": 110007}, 502,
         "exchange_error", None, False),
    ],
)  # fmt: skip
def test_the_command_ports_refusals_map_as_24_sec_8_4_says(
    kind: oc.ExitKind, answer: dict[str, Any], status: int, code: str, retry: int | None,
    retryable: bool,
) -> None:  # fmt: skip
    """Rulings Q9 and Q11, the 11:34Z ruling (`account_unavailable`, never `conflict`; the 503's
    one shared retry, whatever figure the port gives) and cancel-all's `retryable` (the 12:30Z
    ruling 7)."""
    got = ex._answered(kind, {"ok": False} | answer)
    assert (got.kind, got.status, got.code, got.retry_after_s) == ("refused", status, code, retry)
    assert got.retryable is retryable


def test_the_in_flight_guard_holds_one_exit_per_principal_operation_and_key() -> None:
    """Ruling Q11: `409 idempotency_in_flight`, `Retry-After: 1`, nothing sent; another operation
    of the key is its own; a release, called twice, frees the key once."""
    guard, user, key = InFlightGuard(), uuid4(), uuid4()
    release = guard.claim(user, "cancel", key)
    again, other = guard.claim(user, "cancel", key), guard.claim(user, "amend", key)
    assert callable(release) and callable(other) and isinstance(again, ExitOutcome)
    assert (again.status, again.code, again.retry_after_s) == (409, "idempotency_in_flight", 1)
    release()
    release()
    assert callable(guard.claim(user, "cancel", key))


def test_a_release_frees_its_own_claim_only_never_a_later_one_of_the_key() -> None:
    """Each claim is released by its own release alone: one called again once the key was claimed
    anew frees nothing, so the new claim's repeat is still `409` while its exit runs."""
    guard, user, key = InFlightGuard(), uuid4(), uuid4()
    first = guard.claim(user, "cancel", key)
    assert callable(first)
    first()
    second = guard.claim(user, "cancel", key)
    assert callable(second)
    first()
    held = guard.claim(user, "cancel", key)
    assert isinstance(held, ExitOutcome) and held.code == "idempotency_in_flight"
    second()
    assert callable(guard.claim(user, "cancel", key))


def test_the_in_flight_guard_is_bounded_per_principal_and_per_process() -> None:
    """D4 and SEC-S4A-03: 64 keys a principal, 1,024 a process; past either `429 rate_limited`
    with `Retry-After: 1`, nothing sent, while the other principals' exits, cancels too, go."""
    assert (ex.MAX_IN_FLIGHT, ex.MAX_IN_FLIGHT_PER_PRINCIPAL) == (1024, 64)
    guard, (busy, calm, late) = InFlightGuard(max_keys=3, max_per_principal=2), _users(3)
    releases = [guard.claim(busy, "cancel", uuid4()) for _ in range(2)]
    full = guard.claim(busy, "cancel_all", uuid4())
    assert isinstance(full, ExitOutcome) and callable(guard.claim(calm, "cancel", uuid4()))
    assert (full.status, full.code, full.retry_after_s) == (429, "rate_limited", 1)
    shut = guard.claim(late, "cancel", uuid4())  # the process's 3 are held
    assert isinstance(shut, ExitOutcome) and shut.code == "rate_limited"
    cast(Any, releases[0])()
    assert callable(guard.claim(late, "cancel", uuid4()))
    with pytest.raises(ValueError, match="at least one"):
        InFlightGuard(max_keys=2, max_per_principal=3)


def _users(n: int) -> list[UUID]:
    return [uuid4() for _ in range(n)]


async def test_deny_records_the_refusal_ahead_or_answers_503_audit_unavailable(
    rig: SubmitRig,
) -> None:
    """C-2.9, 24 Sec.8.4: the order-entry gate's as `account.disabled_by_policy` with its reason."""
    row, exits = await placed(rig), exits_of(rig)
    gate = ex._refused(OrderEntryRefused(OrderEntryRefusal("maintenance", "Paused.")))
    assert await exits.deny(row, "amend", gate, actor=actor(), request_id=REQUEST) == gate
    assert requests(rig, "account.disabled_by_policy") == [("denied", "maintenance")]
    rig.port.audits.refuse = RuntimeError("the audit WAL refused the record")
    got = await exits.deny(row, "cancel", ex._CONFLICT, actor=actor(), request_id=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "audit_unavailable")
