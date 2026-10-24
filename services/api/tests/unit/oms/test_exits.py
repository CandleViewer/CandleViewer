"""The exit service's scope and cancel (E29-T04 slice 4, `oms.exits`; 24 Sec.8.4 "The exit
routes"): over the real B1 facade, the real command port and the fake venue (`submit_rig`), and,
for the waits and a cancelled caller, over a scripted facade whose bounds the test reads, never
the wall clock."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import OmsErrorCode, TransportError
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms import commands as oc
from candleviewer.oms import exits as ex
from candleviewer.oms.errors import AccountScopeDenied, OrderEntryRefused, StoreUnavailable
from candleviewer.oms.exits import ExitCaller, ExitDeps, ExitOutcome, InFlightGuard, OrderExits
from candleviewer.oms.ports import RequestRecord, SubmitActor
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, ScopedOrder
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
        audit=rig.port.audits, environment="demo",
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
    row, exits = await placed(rig), exits_of(rig)
    await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    again = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (again.kind, again.lifecycle_state) == ("accepted", "cancelled")
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
    """On this base the watch answers None for any raise: `transport`; S4-B1's follow-up marks
    110001 `already_terminal` (`test_the_watchs_110001_mark_is_already_terminal`)."""
    row = await placed(rig)
    gone = FakeReject(OmsErrorCode.ORDER_NOT_FOUND, exchange_ret_code=110001)
    rig.port.demo.script("cancel_order", gone)
    got = await exits_of(rig).cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.lifecycle_state) == ("unknown", 202, "unknown")
    assert (got.unknown_reason, got.retryable) == ("transport", False)
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


# --- the waits, a cancelled caller and the watch's answer, on a scripted facade ------------------


@dataclass
class Watches:
    """`ExitCommands`: each watch kept for the scripted facade to answer."""

    held: dict[tuple[UUID, str], oc.ExitWatch] = field(default_factory=dict)

    def expect_exit(self, order_id: UUID, kind: oc.ExitKind, **kw: Any) -> oc.ExitWatch:
        future = asyncio.get_running_loop().create_future()
        watch = self.held[(order_id, kind)] = oc.ExitWatch(order_id, kind, future, **kw)
        return watch

    def forget_exit(self, order_id: UUID, kind: oc.ExitKind) -> None:
        self.held.pop((order_id, kind)).resolve(None)


@dataclass
class Scripted:
    """`ExitMachines` a test scripts: `held` the state, each of `settles` one `settled` call's
    answer (a state, the watch then answered `answer`, or an error raised), each bound asked kept
    in `waits` and each command in `sent`; `gate`, when set, holds every `settled` until set."""

    held: str | None
    settles: list[str | BaseException]
    watches: Watches
    answer: dict[str, Any] | None
    waits: list[float] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    gate: asyncio.Event | None = None
    entered: asyncio.Event = field(default_factory=asyncio.Event)

    def state(self, order_id: UUID) -> tuple[str, str] | None:
        return None if self.held is None else (self.held, "not_required")

    def version(self, order_id: UUID) -> int | None:
        return 7

    async def command(
        self, account_id: UUID, order_id: UUID, event: Any, *_a: Any, **_k: Any
    ) -> str:
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
    held: str | None, *settles: str | BaseException, answer: dict[str, Any] | None = _OK
) -> tuple[OrderExits, Scripted, OrderRow, cr.Rig]:
    port = cr.build_rig()
    row = await port.stored(cr.new_order(), lifecycle="submitted")
    watches = Watches()
    machines = Scripted(held, list(settles), watches, answer)
    deps = ExitDeps(
        machines=machines, commands=watches, orders=port.orders, audit=port.audits,
        environment="demo",
    )  # fmt: skip
    return OrderExits(deps), machines, row, port


@pytest.mark.parametrize(
    ("held", "settles", "kind", "state", "waits", "sent"),
    [
        ("amend_pending", [TimeoutError()], "refused", None, [10.0], []),
        ("cancel_pending", [TimeoutError()], "unknown", "cancel_pending", [10.0], []),
        ("submitted", [TimeoutError()], "unknown", "cancel_pending", [11.0], _SENT),
        ("validated", ["submitted", "cancelled"], "accepted", "cancelled", [10.0, 11.0], _SENT),
        ("held", [], "refused", None, [], []),
        (None, [], "refused", None, [], []),
    ],
    ids=["transitional", "in-flight", "own-settle", "both", "q8-state", "no-machine"],
)  # fmt: skip
async def test_the_waits_are_bounded_and_each_answers_as_the_contract_says(
    held: str | None, settles: list[Any], kind: str, state: str | None, waits: list[float],
    sent: list[str],
) -> None:  # fmt: skip
    """D9: a transitional step is waited out at most `CV_COMMAND_TIMEOUT` (else `409 conflict`;
    a cancel already in flight is B1's, `unknown` `timeout`), then the cancel's own settle at most
    `CV_COMMAND_TIMEOUT` + 1 s, so about 21 s in all, never unbounded; no accepted outcome but a
    settled one (the 12:30Z ruling 6)."""
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


@pytest.mark.parametrize(
    ("answer", "why", "ret"),
    [({"ok": False, "unknown": b01.ALREADY_TERMINAL, "exchange_ret_code": 110001},
      "already_terminal", 110001), (None, "transport", None)],
    ids=["110001", "raised"],
)  # fmt: skip
async def test_the_watchs_110001_mark_is_already_terminal_any_other_raise_transport(
    answer: dict[str, Any] | None, why: str, ret: int | None
) -> None:
    """D2 and the 12:30Z ruling 2: S4-B1's follow-up answers the watch with the mark, read
    defensively, so None (this base's answer to every raise) is `transport`."""
    exits, _, row, _ = await scripted("submitted", "unknown", answer=answer)
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.unknown_reason, got.exchange_ret_code) == ("unknown", why, ret)


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
    """The 12:30Z ruling 5: never re-sent, never undone; it settles and is recorded; `aclose`
    is the shutdown's, which ends an exit no caller waits for."""
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
    written = [
        (r.outcome, r.reason) for r, _ in port.audits.written if isinstance(r, RequestRecord)
    ]
    assert written == [("success", "cancel_all"), ("success", "cancelled")]
    assert exits._running == set()
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
        ("cancel", {"error_code": oc.STORE_UNAVAILABLE, "retry_after_s": 1}, 503,
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
    one retry) and cancel-all's `retryable` (the 12:30Z ruling 7)."""
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
