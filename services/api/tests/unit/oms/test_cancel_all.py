"""`cancelAllOrders`'s service (E29-T04 #913 slice 4, S4-E; the orchestrator's Q1, Q6 and Q12
rulings and S4-A's counting rules): scope first and all or nothing, the selection, one
`cancel_admitted` per selected order with reason `cancel_all`, five accounts at once and one order
at a time on each, the per-account answer, the deadline, and one account's failure kept from the
others."""

from __future__ import annotations

import asyncio
import math
from collections import Counter, OrderedDict
from collections.abc import AsyncIterator, Collection, Mapping, Sequence
from dataclasses import fields
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import account_tag
from candleviewer.domain.primitives import AccountId, Symbol
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, CancelOrderRequest, Order, OrderAck
from candleviewer.oms.cancel_all import (
    ACCOUNTS_AT_ONCE,
    DEADLINE_S,
    FOLD_MIN,
    REASON,
    AccountCancels,
    AccountError,
    CancelAll,
    CancelAllRequest,
    ScopedAccounts,
    selected,
)
from candleviewer.oms.cancel_all_coalescer import CancelAllCoalescer
from candleviewer.oms.cancel_all_fold import CancelAllSpacer
from candleviewer.oms.errors import AccountScopeDenied, StoreUnavailable
from candleviewer.oms.exits import ExitOutcome
from candleviewer.oms.ports import SubmitActor
from candleviewer.oms.recovery import FINALS
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, OrderStoreError
from tests.unit.oms import order_rig as orr

_A, _B = UUID(int=0xA), UUID(int=0xB)
_ACTOR, _REQUEST = SubmitActor(user_id=UUID(int=0x100), role="manager"), UUID(int=0x200)
_SCOPE: Any = object()  # the caller's scope; only `accounts_in_scope` reads it


def _row(n: int, account: UUID = _A, **over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    values |= {
        "id": UUID(int=n), "exchange_account_id": account, "symbol": "BTCUSDT",
        "intent": "entry", "reduce_only": False, "provenance": "placed",
        "state": "accepted", "lifecycle_state": "submitted", "qty": Decimal("0.010"),
    }  # fmt: skip
    return OrderRow(**(values | over))


def _request(**over: Any) -> CancelAllRequest:
    values: dict[str, Any] = {
        "exchange_account_ids": (), "symbol": None, "intents": frozenset(),
        "exclude_reduce_only": True,
    }  # fmt: skip
    return CancelAllRequest(**(values | over))


def _accepted(state: str = "cancelled") -> ExitOutcome:
    return ExitOutcome(kind="accepted", status=202, lifecycle_state=state)


def _unknown(why: str, ret_code: int | None = None) -> ExitOutcome:
    reason: Any = why
    return ExitOutcome(
        kind="unknown", status=202, lifecycle_state="unknown", exchange_ret_code=ret_code,
        unknown_reason=reason,
    )  # fmt: skip


_CANCELLED = _accepted()


def _refused(code: str | None, ret_code: int | None = None, status: int = 409) -> ExitOutcome:
    return ExitOutcome(kind="refused", status=status, code=code, exchange_ret_code=ret_code)


class _Reads:
    """`list_open`, each call recorded: `down` and `stall` name accounts whose read fails or never
    answers."""

    def __init__(
        self,
        rows: Sequence[OrderRow],
        *,
        down: Sequence[UUID] = (),
        refuse: Sequence[UUID] = (),
        stall: Sequence[UUID] = (),
    ):
        self.rows, self.down, self.stall = list(rows), set(down), set(stall)
        self.refuse = set(refuse)
        self.listed: list[tuple[UUID, str | None]] = []

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        self.listed.append((account_id, symbol))
        if account_id in self.stall:
            await asyncio.Event().wait()
        if account_id in self.down:
            raise StorageTierUnavailable("postgres unreachable (OSError)")
        if account_id in self.refuse:
            raise OrderStoreError("the order store refused the read")
        return tuple(
            r for r in self.rows
            if r.exchange_account_id == account_id and (symbol is None or r.symbol == symbol)
        )  # fmt: skip


class _Exits:
    """The exit service's scope helper and `cancel_admitted`, each call recorded. The scope helper
    raises its refusal (`refuse`) or its `StoreUnavailable` (`scope_down`), else answers the ids
    asked for, or every account of `rows` for none. `outcomes` maps an order id to its outcome
    (else cancelled); `stall` names orders whose cancel never answers. With `hold`, every call
    waits for the event, and `ready` is set once `ready_at` calls run at once."""

    def __init__(
        self,
        *,
        rows: Sequence[OrderRow] = (),
        refuse: bool = False,
        scope_down: bool = False,
        outcomes: dict[UUID, ExitOutcome] | None = None,
        stall: Sequence[UUID] = (),
        hold: asyncio.Event | None = None,
        ready_at: int = 1,
    ):
        self.rows, self.refuse, self.scope_down = list(rows), refuse, scope_down
        self.outcomes, self.stall, self.hold = outcomes or {}, set(stall), hold
        self.ready, self.ready_at = asyncio.Event(), ready_at
        self.scoped: list[tuple[object, tuple[UUID, ...]]] = []
        self.calls: list[tuple[UUID, SubmitActor, str, UUID | None]] = []
        self.running: Counter[UUID] = Counter()
        self.peak_accounts = 0
        self.peak_per_account: Counter[UUID] = Counter()

    async def accounts_in_scope(
        self, scope: object, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        self.scoped.append((scope, tuple(requested)))
        if self.refuse:
            raise AccountScopeDenied()
        if self.scope_down:
            raise StoreUnavailable()
        return tuple(requested) or tuple(dict.fromkeys(r.exchange_account_id for r in self.rows))

    async def cancel_admitted(
        self, row: OrderRow, *, actor: SubmitActor, reason: str, request_id: UUID | None
    ) -> ExitOutcome:
        self.calls.append((row.id, actor, reason, request_id))
        account = row.exchange_account_id
        self.running[account] += 1
        self.peak_per_account[account] = max(self.peak_per_account[account], self.running[account])
        self.peak_accounts = max(self.peak_accounts, len(+self.running))
        if sum(self.running.values()) >= self.ready_at:
            self.ready.set()
        try:
            if self.hold is not None:
                await self.hold.wait()
            if row.id in self.stall:
                await asyncio.Event().wait()
        finally:
            self.running[account] -= 1
        return self.outcomes.get(row.id, _CANCELLED)


async def _run(reads: _Reads, exits: _Exits, request: CancelAllRequest, **over: Any) -> Any:
    if not exits.rows:
        exits.rows = reads.rows  # the scope helper's accounts for an empty list
    service = CancelAll(reads, exits, **over)
    async with asyncio.timeout(5):  # a lost bound fails the test instead of hanging it
        accounts = await service.scope(_SCOPE, request)  # the route's step 4
        return await service.run(accounts, request, actor=_ACTOR, request_id=_REQUEST)


async def _settle() -> None:
    """Let every runnable task take its next step: whatever could start, has."""
    for _ in range(20):
        await asyncio.sleep(0)


def test_the_selection_keeps_only_the_oms_own_orders() -> None:
    rows = [
        _row(1),
        _row(2, provenance="recorded_stop"),
        _row(3, provenance="reconciliation"),
    ]
    assert [r.id for r in selected(rows, _request())] == [UUID(int=1)]


@pytest.mark.parametrize("state", ["submitted", "triggered", "partially_filled"])
def test_the_selection_takes_an_order_b1_holds_live(state: str) -> None:
    assert len(selected([_row(1, lifecycle_state=state)], _request())) == 1


@pytest.mark.parametrize(
    "state",
    [
        "cancel_pending", "validated", "submitting", "amend_pending", "unknown", "quarantined",
        "held", "untracked", None,
    ],
)  # fmt: skip
def test_the_selection_leaves_out_every_other_open_order(state: str | None) -> None:
    assert selected([_row(1, lifecycle_state=state)], _request()) == ()


def test_the_selection_leaves_reduce_only_orders_out_by_default() -> None:
    rows = [_row(1), _row(2, reduce_only=True, intent="take_profit")]
    assert [r.id for r in selected(rows, _request())] == [UUID(int=1)]


def test_the_selection_takes_reduce_only_orders_when_asked() -> None:
    rows = [_row(1), _row(2, reduce_only=True, intent="take_profit")]
    got = selected(rows, _request(exclude_reduce_only=False))
    assert [r.id for r in got] == [UUID(int=1), UUID(int=2)]


def test_a_recorded_stop_is_never_selected_even_with_reduce_only_asked() -> None:
    rows = [_row(1, provenance="recorded_stop", reduce_only=True, intent="stop_loss")]
    assert selected(rows, _request(exclude_reduce_only=False, intents=frozenset())) == ()


def test_the_selection_keeps_the_named_intents_only() -> None:
    rows = [_row(1, intent="entry"), _row(2, intent="scale_in"), _row(3, intent="algo_child")]
    got = selected(rows, _request(intents=frozenset({"entry", "scale_in"})))
    assert [r.id for r in got] == [UUID(int=1), UUID(int=2)]


def test_no_intent_named_means_every_intent() -> None:
    rows = [_row(1, intent="entry"), _row(2, intent="algo_child")]
    assert len(selected(rows, _request())) == 2


async def test_a_scope_refusal_reads_no_order_and_sends_nothing() -> None:
    reads, exits = _Reads([_row(1)]), _Exits(refuse=True)
    with pytest.raises(AccountScopeDenied):
        await _run(reads, exits, _request(exchange_account_ids=(_A, _B)))
    assert (exits.scoped, reads.listed, exits.calls) == ([(_SCOPE, (_A, _B))], [], [])


async def test_the_scope_helpers_store_unavailable_reads_no_order_and_sends_nothing() -> None:
    reads, exits = _Reads([_row(1)]), _Exits(scope_down=True)
    with pytest.raises(StoreUnavailable):
        await _run(reads, exits, _request())
    assert (reads.listed, exits.calls) == ([], [])


async def test_an_empty_list_goes_to_the_scope_helper_as_it_is() -> None:
    reads, exits = _Reads([_row(1)]), _Exits()
    await _run(reads, exits, _request())
    assert exits.scoped == [(_SCOPE, ())]


async def test_each_selected_order_is_cancelled_with_the_actor_and_the_reason() -> None:
    reads, exits = _Reads([_row(1), _row(2, account=_B)]), _Exits()
    await _run(reads, exits, _request(exchange_account_ids=(_A, _B)))
    assert sorted(exits.calls) == [
        (UUID(int=1), _ACTOR, REASON, _REQUEST),
        (UUID(int=2), _ACTOR, REASON, _REQUEST),
    ]
    assert REASON == "cancel_all"


async def test_the_symbol_filter_is_passed_to_each_accounts_read() -> None:
    reads, exits = _Reads([_row(1), _row(2, symbol="ETHUSDT")]), _Exits()
    await _run(reads, exits, _request(exchange_account_ids=(_A,), symbol="ETHUSDT"))
    assert (reads.listed, [c[0] for c in exits.calls]) == ([(_A, "ETHUSDT")], [UUID(int=2)])


async def test_no_more_than_five_accounts_are_worked_at_once() -> None:
    hold = asyncio.Event()
    accounts = tuple(UUID(int=n) for n in range(0x10, 0x17))
    reads = _Reads([_row(n, account=account) for n, account in enumerate(accounts, 1)])
    exits = _Exits(hold=hold, ready_at=ACCOUNTS_AT_ONCE)
    task = asyncio.create_task(_run(reads, exits, _request(exchange_account_ids=accounts)))
    async with asyncio.timeout(1):
        await exits.ready.wait()
    await _settle()
    assert (ACCOUNTS_AT_ONCE, exits.peak_accounts, len(reads.listed)) == (5, 5, 5)
    hold.set()
    got = await task
    assert (exits.peak_accounts, len(exits.calls), got.succeeded) == (5, 7, 7)


async def test_one_order_at_a_time_is_cancelled_on_an_account() -> None:
    hold = asyncio.Event()
    reads, exits = _Reads([_row(1), _row(2), _row(3)]), _Exits(hold=hold)
    task = asyncio.create_task(_run(reads, exits, _request(exchange_account_ids=(_A,))))
    async with asyncio.timeout(1):
        await exits.ready.wait()
    await _settle()
    assert len(exits.calls) == 1
    hold.set()
    await task
    assert (exits.peak_per_account[_A], [c[0] for c in exits.calls]) == (
        1,
        [UUID(int=1), UUID(int=2), UUID(int=3)],
    )


@pytest.mark.parametrize("state", sorted(FINALS - {"cancelled"}))
async def test_affected_counts_the_cancelled_and_an_order_ended_by_race_is_neither(
    state: str,
) -> None:
    """A fill, a rejection, an expiry or a kill before the cancel landed lost a race (D2)."""
    reads = _Reads([_row(1), _row(2), _row(3)])
    exits = _Exits(outcomes={UUID(int=2): _accepted(state)})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (AccountCancels(_A, affected=2, error=None),)
    assert got.accounts[0].ok


async def test_a_transport_unknown_is_the_accounts_exchange_unavailable() -> None:
    reads, exits = _Reads([_row(1), _row(2)]), _Exits(outcomes={UUID(int=1): _unknown("transport")})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (
        AccountCancels(_A, affected=1, error=AccountError("exchange_unavailable", False)),
    )


async def test_a_step_unsettled_in_s4cs_bound_is_the_accounts_retryable_timeout() -> None:
    reads, exits = _Reads([_row(1), _row(2)]), _Exits(outcomes={UUID(int=1): _unknown("timeout")})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (AccountCancels(_A, affected=1, error=AccountError("timeout", True)),)


async def test_an_order_the_venue_no_longer_held_lost_a_race_and_counts_nowhere() -> None:
    gone = _unknown("already_terminal", 110001)
    reads, exits = _Reads([_row(1), _row(2)]), _Exits(outcomes={UUID(int=1): gone})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (AccountCancels(_A, affected=1, error=None),)


async def test_an_accepted_outcome_not_terminal_breaks_s4cs_contract_and_is_not_known() -> None:
    """S4-C answers an accepted cancel only once B1 settled it; a breach is not read as ended."""
    reads = _Reads([_row(1)])
    exits = _Exits(outcomes={UUID(int=1): _accepted("cancel_pending")})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts[0] == AccountCancels(
        _A, affected=0, error=AccountError("exchange_unavailable", False)
    )


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (_refused("store_unavailable", status=503), AccountError("store_unavailable", True)),
        (_refused("conflict"), AccountError("conflict", False)),
        (_refused("account_unavailable"), AccountError("account_unavailable", False)),
        (
            _refused("exchange_rate_limited", status=429),
            AccountError("exchange_rate_limited", True),
        ),
        (_refused("exchange_error", 110017, 502), AccountError("exchange_error", False, 110017)),
        # D2a's backpressure, a closing exit service: transient (the 2026-10-25 06:56Z ruling)
        (_refused("oms_not_ready", status=503), AccountError("oms_not_ready", True)),
        # refusals 22's cancel-all text does not list: the code as `cancelOrder` answers it
        (_refused("risk_limit_breached", status=403), AccountError("risk_limit_breached", False)),
        (_refused("stop_request_in_flight"), AccountError("stop_request_in_flight", False)),
        (_refused("audit_unavailable", status=503), AccountError("audit_unavailable", False)),
        (_refused(None, status=503), AccountError("exchange_unavailable", False)),
    ],
)
async def test_a_refusal_is_the_accounts_error_with_its_code(
    outcome: ExitOutcome, error: AccountError
) -> None:
    reads, exits = _Reads([_row(1)]), _Exits(outcomes={UUID(int=1): outcome})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (AccountCancels(_A, affected=0, error=error),)


async def test_the_accounts_error_is_its_first_failure_and_every_order_is_still_sent() -> None:
    reads = _Reads([_row(1), _row(2), _row(3)])
    exits = _Exits(
        outcomes={UUID(int=1): _refused("conflict"), UUID(int=2): _refused("store_unavailable")}
    )
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert len(exits.calls) == 3
    assert got.accounts == (AccountCancels(_A, affected=1, error=AccountError("conflict", False)),)


async def test_one_accounts_failed_read_keeps_the_others_cancels() -> None:
    reads, exits = _Reads([_row(1), _row(2, account=_B)], down=[_A]), _Exits()
    got = await _run(reads, exits, _request(exchange_account_ids=(_A, _B)))
    assert [c[0] for c in exits.calls] == [UUID(int=2)]
    assert got.accounts == (
        AccountCancels(_A, affected=0, error=AccountError("store_unavailable", True)),
        AccountCancels(_B, affected=1, error=None),
    )


async def test_one_accounts_read_past_its_bound_keeps_the_others_cancels() -> None:
    reads, exits = _Reads([_row(1), _row(2, account=_B)], stall=[_A]), _Exits()
    got = await _run(reads, exits, _request(exchange_account_ids=(_A, _B)), read_timeout_s=0.01)
    assert [c[0] for c in exits.calls] == [UUID(int=2)]
    assert got.accounts[0] == AccountCancels(
        _A, affected=0, error=AccountError("store_unavailable", True)
    )


async def test_at_the_deadline_an_unfinished_account_is_timeout_with_what_ended() -> None:
    reads = _Reads([_row(1), _row(2), _row(3, account=_B)])
    exits = _Exits(stall=[UUID(int=2)])
    got = await _run(reads, exits, _request(exchange_account_ids=(_A, _B)), deadline_s=0.05)
    assert got.accounts == (
        AccountCancels(_A, affected=1, error=AccountError("timeout", True)),
        AccountCancels(_B, affected=1, error=None),
    )
    assert (got.requested, got.succeeded) == (2, 1)


async def test_an_account_still_waiting_its_turn_at_the_deadline_is_timeout() -> None:
    reads, exits = _Reads([_row(1), _row(2, account=_B)]), _Exits(stall=[UUID(int=1)])
    got = await _run(
        reads,
        exits,
        _request(exchange_account_ids=(_A, _B)),
        accounts_at_once=1,
        deadline_s=0.05,
    )
    assert reads.listed == [(_A, None)]  # B was never read, nor sent anything
    assert [a.error for a in got.accounts] == [AccountError("timeout", True)] * 2


async def test_an_account_named_twice_is_scoped_worked_and_answered_once() -> None:
    """`scope` settles each account once, and `run` takes only what it settled: a repeat sends no
    order a second cancel."""
    reads, exits = _Reads([_row(1)]), _Exits()
    service = CancelAll(reads, exits)
    accounts = await service.scope(_SCOPE, _request(exchange_account_ids=(_A, _A)))
    assert accounts == ScopedAccounts((_A,))
    got = await service.run(accounts, _request(), actor=_ACTOR, request_id=_REQUEST)
    assert [a.exchange_account_id for a in got.accounts] == [_A]
    assert ([c[0] for c in exits.calls], reads.listed) == ([UUID(int=1)], [(_A, None)])


async def test_at_the_deadline_timeout_replaces_an_earlier_failure() -> None:
    """22: the retryable signal wins, so a caller retries the account (the code look's S06)."""
    reads = _Reads([_row(1), _row(2)])
    exits = _Exits(stall=[UUID(int=2)], outcomes={UUID(int=1): _refused("conflict")})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)), deadline_s=0.05)
    assert got.accounts == (AccountCancels(_A, affected=0, error=AccountError("timeout", True)),)


async def test_an_order_store_refusal_is_the_accounts_store_unavailable() -> None:
    """`OrderStoreError` as `StorageError` is: nothing of that account is sent (S16)."""
    reads, exits = _Reads([_row(1)], refuse=[_A]), _Exits()
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (
        AccountCancels(_A, affected=0, error=AccountError("store_unavailable", True)),
    )
    assert exits.calls == []


async def test_the_answer_keeps_the_scope_helpers_account_order() -> None:
    reads, exits = _Reads([_row(1), _row(2, account=_B)]), _Exits()
    got = await _run(reads, exits, _request(exchange_account_ids=(_B, _A)))
    assert [a.exchange_account_id for a in got.accounts] == [_B, _A]


async def test_requested_and_succeeded_count_accounts() -> None:
    rows = [_row(1), _row(2), _row(3, account=_B)]
    reads, exits = _Reads(rows), _Exits(outcomes={UUID(int=2): _refused("conflict")})
    got = await _run(reads, exits, _request(exchange_account_ids=(_A, _B)))
    assert (got.requested, got.succeeded) == (2, 1)


async def test_an_account_with_nothing_to_cancel_succeeds() -> None:
    reads, exits = _Reads([_row(1, provenance="recorded_stop")]), _Exits()
    got = await _run(reads, exits, _request(exchange_account_ids=(_A,)))
    assert got.accounts == (AccountCancels(_A, affected=0, error=None),)
    assert (got.requested, got.succeeded, exits.calls) == (1, 1, [])


def test_the_defaults_are_the_contracts() -> None:
    assert (ACCOUNTS_AT_ONCE, DEADLINE_S) == (5, 20.0)


@pytest.mark.parametrize("accounts_at_once", [0, -1, True])
def test_at_least_one_account_is_worked_at_once(accounts_at_once: int) -> None:
    with pytest.raises(ValueError, match="accounts_at_once"):
        CancelAll(_Reads([]), _Exits(), accounts_at_once=accounts_at_once)


@pytest.mark.parametrize("name", ["read_timeout_s", "deadline_s"])
@pytest.mark.parametrize("bound", [0, -1.0, math.nan, math.inf, True])
def test_each_bound_is_finite_and_above_zero(name: str, bound: float) -> None:
    over: dict[str, Any] = {name: bound}
    with pytest.raises(ValueError, match=name):
        CancelAll(_Reads([]), _Exits(), **over)


# --- S4-F: the venue cancel-all fold (24 Sec.8.7; the 21:11Z ruling) --------------------------

_FOLD_ACCOUNT = AccountId(_A)
_FOLD_REF = AccountRef(
    account_id=_FOLD_ACCOUNT, uid="100001", environment="demo", key_ref=str(UUID(int=1))
)


_B_REF = AccountRef(
    account_id=AccountId(_B), uid="100002", environment="demo", key_ref=str(UUID(int=2))
)


def _link(n: int, account: UUID = _A) -> str:
    """A link id the OMS's generator could have made for `account` (24 Sec.8.3)."""
    return f"cvd-0{n:021d}-{account_tag(AccountId(account))}-00en"


def _venue_order(n: int, symbol: str = "BTCUSDT", kind: Any = "order", account: UUID = _A) -> Order:
    return Order(
        order_link_id=_link(n, account), exchange_order_id=f"x-{n}", account_id=AccountId(account),
        symbol=symbol, side="buy", order_type="limit", qty=Decimal("0.010"),
        price=Decimal("60000"), state="new", filled_qty=Decimal("0"),
        leaves_qty=Decimal("0.010"), avg_fill_price=None, created_at=1_790_000_000_000_000,
        terminal_at=None, order_kind=kind,
    )  # fmt: skip


class _Log(list[tuple[str, str]]):
    """Every write-ahead and venue call, in the order they happened."""


class _Venue(FakeTradingPort):
    def __init__(self, log: _Log) -> None:
        super().__init__()
        self.log = log

    async def cancel_all(self, account: AccountRef, symbol: Any) -> Sequence[OrderAck]:
        self.log.append(("venue", "cancel_all"))
        return await super().cancel_all(account, symbol)

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        self.log.append(("venue", f"cancel_order {req.order_link_id}"))
        return await super().cancel_order(req)


class _PortExits:
    """The exit service as B1's command port reaches the venue: each order's write-ahead, then its
    `cancel_order` through the fold port, its ack read as the outcome. `refuse` names orders
    refused before their send (no write-ahead, no venue call); `refs` holds each account's ref
    other than account A's."""

    def __init__(
        self,
        port: CancelAllCoalescer,
        log: _Log,
        refuse: Collection[UUID] = (),
        refs: Mapping[UUID, AccountRef] | None = None,
    ):
        self.port, self.log, self.refuse = port, log, set(refuse)
        self.refs = dict(refs or {})
        self.running, self.peak = 0, 0

    async def accounts_in_scope(
        self, scope: object, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        return tuple(requested) or (_A,)

    async def cancel_admitted(
        self, row: OrderRow, *, actor: SubmitActor, reason: str, request_id: UUID | None
    ) -> ExitOutcome:
        if row.id in self.refuse:
            return _refused("conflict")
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            self.log.append(("ahead", row.order_link_id))
            account = self.refs.get(row.exchange_account_id, _FOLD_REF)
            request = CancelOrderRequest(
                account=account, symbol=Symbol(row.symbol), order_link_id=row.order_link_id
            )
            ack = await self.port.cancel_order(request)
        finally:
            self.running -= 1
        return _CANCELLED if ack.ok else _refused("exchange_error", status=502)


class _Accounts:
    """The fold port's account read: an account's ref in `refs`, else `ref`; a store fault with
    `fail`."""

    def __init__(
        self,
        fail: bool = False,
        ref: AccountRef = _FOLD_REF,
        refs: Mapping[UUID, AccountRef] | None = None,
    ) -> None:
        self.fail, self.ref, self.refs, self.asked = fail, ref, dict(refs or {}), 0

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        self.asked += 1
        if self.fail:
            raise StorageTierUnavailable("postgres unreachable (OSError)")
        return self.refs.get(account_id, self.ref)


class _Fold:
    """A venue holding `resting`, the fold port over it, and the service over both."""

    def __init__(
        self, rows: Sequence[OrderRow], resting: Sequence[Order], *, refuse: Collection[UUID] = (),
        accounts: _Accounts | None = None, refs: Mapping[UUID, AccountRef] | None = None,
    ) -> None:  # fmt: skip
        self.log, self.accounts = _Log(), accounts or _Accounts(refs=refs)
        self.venue = _Venue(self.log)
        for order in resting:
            self.venue.seed_order(order, uid=_FOLD_REF.uid)
        clock = _Clock()
        self.spacer = CancelAllSpacer(monotonic=clock, sleep=_never)
        self.port = CancelAllCoalescer(
            self.venue, spacer=self.spacer, monotonic=clock, sleep=_never
        )
        self.exits = _PortExits(self.port, self.log, refuse, refs)
        self.service = CancelAll(_Reads(rows), self.exits, folds=(self.port, self.accounts))

    async def run(self, **request: Any) -> Any:
        ask = _request(exclude_reduce_only=False) if not request else _request(**request)
        async with asyncio.timeout(5):
            accounts = await self.service.scope(_SCOPE, ask)
            return await self.service.run(accounts, ask, actor=_ACTOR, request_id=_REQUEST)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def _never(seconds: float) -> None:
    """The gather's bound and the spacer's wait never end on their own here."""
    await asyncio.Event().wait()


def _fold_row(n: int, account: UUID = _A, **over: Any) -> OrderRow:
    return _row(n, account, order_link_id=_link(n, account), **over)


async def test_an_unrestricted_request_folds_a_covered_symbol_into_one_venue_call() -> None:
    """The ruled pin: every member's write-ahead lands before the one venue call (C-2.9)."""
    fold = _Fold([_fold_row(1), _fold_row(2)], [_venue_order(1), _venue_order(2)])
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=2, error=None),)
    venue_at = fold.log.index(("venue", "cancel_all"))
    ahead = [i for i, entry in enumerate(fold.log) if entry[0] == "ahead"]
    assert len(ahead) == 2 and max(ahead) < venue_at
    assert [entry for entry in fold.log if entry[0] == "venue"] == [("venue", "cancel_all")]


@pytest.mark.parametrize(
    "request_over",
    [
        {"exclude_reduce_only": True},
        {"exclude_reduce_only": False, "intents": frozenset({"entry"})},
    ],
    ids=["reduce_only_left_out", "intents_named"],
)
async def test_a_restricted_request_never_folds(request_over: dict[str, Any]) -> None:
    fold = _Fold([_fold_row(1), _fold_row(2)], [_venue_order(1), _venue_order(2)])
    await fold.run(**request_over)
    assert ("venue", "cancel_all") not in fold.log and fold.accounts.asked == 0
    assert [c.method for c in fold.venue.calls] == ["cancel_order", "cancel_order"]


async def test_a_symbol_with_another_plain_order_resting_stays_on_per_order_cancels() -> None:
    """Coverage fails: the venue's call would take an order the request did not select."""
    fold = _Fold([_fold_row(1), _fold_row(2)], [_venue_order(1), _venue_order(2), _venue_order(9)])
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=2, error=None),)
    assert [c.method for c in fold.venue.calls] == ["open_orders", "cancel_order", "cancel_order"]
    assert [o.order_link_id for o in await fold.venue.open_orders(_FOLD_REF)] == [_link(9)]


async def test_a_member_refused_before_its_send_leaves_the_others_their_own_cancels() -> None:
    """The fail-safe: no venue call goes out for a fold one member never reaches."""
    rows = [_fold_row(1), _fold_row(2), _fold_row(3)]
    fold = _Fold(rows, [_venue_order(n) for n in (1, 2, 3)], refuse={UUID(int=2)})
    got = await fold.run()
    assert ("venue", "cancel_all") not in fold.log
    assert sorted(e[1] for e in fold.log if e[0] == "venue") == [
        f"cancel_order {_link(1)}", f"cancel_order {_link(3)}",
    ]  # fmt: skip
    assert got.accounts[0].affected == 2 and got.accounts[0].error is not None


async def test_an_account_the_fold_cannot_read_stays_on_per_order_cancels() -> None:
    fold = _Fold(
        [_fold_row(1), _fold_row(2)], [_venue_order(1), _venue_order(2)],
        accounts=_Accounts(fail=True),
    )  # fmt: skip
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=2, error=None),)
    assert [c.method for c in fold.venue.calls] == ["cancel_order", "cancel_order"]


async def test_an_account_read_that_answers_another_account_never_folds() -> None:
    """L2 (CR-S4F-11; SR-E27-21, as the command port's and the router's reads check it): the fold
    port's account read answers another account's ref, a defect. Nothing is read or sent with it:
    the account stays on per-order cancels, and the WARNING carries no identifier."""
    other = AccountRef(
        account_id=AccountId(_B), uid="100002", environment="demo", key_ref=str(UUID(int=2))
    )
    fold = _Fold(
        [_fold_row(1), _fold_row(2)], [_venue_order(1), _venue_order(2)],
        accounts=_Accounts(ref=other),
    )  # fmt: skip
    with capture_logs() as logs:
        got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=2, error=None),)
    assert [c.method for c in fold.venue.calls] == ["cancel_order", "cancel_order"]
    [warned] = [e for e in logs if e["event"] == "oms_cancel_all_fold_account_mismatch"]
    assert warned["log_level"] == "warning"
    assert not [
        v for v in warned.values() for a in (_A, _B, "100001", "100002") if str(a) in str(v)
    ]


async def test_two_overlapping_unrestricted_requests_on_one_symbol_both_finish() -> None:
    """CR-S4F-02 (vw2's code look): a second request meets orders already in the first's open
    fold. Its fold is refused, so that account falls back to per-order cancels, with no
    ExceptionGroup and no page, and its sibling account finishes as it would alone."""
    rows = [_fold_row(1), _fold_row(2), _fold_row(3, account=_B)]
    resting = [_venue_order(1), _venue_order(2), _venue_order(3, account=_B)]
    fold = _Fold(rows, resting, refs={_B: _B_REF})
    assert await fold.spacer.turn(_FOLD_REF.uid, deadline=100.0)  # the first's call then waits
    first = asyncio.create_task(fold.run())  # account A: its fold opens, its call held
    try:
        await _settle()
        assert ("venue", "cancel_all") not in fold.log and len(fold.log) == 2  # both arrived
        got = await fold.run(exchange_account_ids=(_A, _B), exclude_reduce_only=False)
        assert got.accounts == (
            AccountCancels(_A, affected=2, error=None), AccountCancels(_B, affected=1, error=None),
        )  # fmt: skip
    finally:
        first.cancel()
        await asyncio.wait([first])


async def test_each_symbol_folds_or_not_on_its_own_coverage() -> None:
    rows = [_fold_row(1), _fold_row(2, symbol="ETHUSDT"), _fold_row(3)]
    resting = [
        _venue_order(1), _venue_order(3), _venue_order(2, "ETHUSDT"), _venue_order(7, "ETHUSDT"),
    ]  # fmt: skip
    fold = _Fold(rows, resting)
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=3, error=None),)
    venue = [entry[1] for entry in fold.log if entry[0] == "venue"]
    assert venue == ["cancel_all", f"cancel_order {_link(2)}"]  # BTC folded, ETH per-order


async def test_uncovered_orders_keep_the_read_order_across_symbols() -> None:
    """CR-S4F-05: three orders over two symbols, none folded, are cancelled in the order read,
    as S4-E sends them, never grouped by symbol."""
    rows = [_fold_row(1), _fold_row(2, symbol="ETHUSDT"), _fold_row(3)]
    resting = [_venue_order(1), _venue_order(2, "ETHUSDT"), _venue_order(3), _venue_order(9)]
    fold = _Fold(rows, resting)  # BTC holds 9, which no request selected: no fold there
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=3, error=None),)
    assert [entry for entry in fold.log if entry[0] == "venue"] == [
        ("venue", f"cancel_order {_link(n)}") for n in (1, 2, 3)
    ]


async def test_a_single_covered_order_sends_its_own_cancel_and_reads_nothing() -> None:
    """CR-S4F-06 (a): a fold of one gains nothing and would spend its UID's second, so a symbol
    with one selected order is never folded: no account read, no coverage read, no cancel-all."""
    rows = [_fold_row(1), _fold_row(2, symbol="ETHUSDT"), _fold_row(3, symbol="SOLUSDT")]
    resting = [_venue_order(1), _venue_order(2, "ETHUSDT"), _venue_order(3, "SOLUSDT")]
    fold = _Fold(rows, resting)
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=3, error=None),)
    assert [c.method for c in fold.venue.calls] == ["cancel_order"] * 3
    assert fold.accounts.asked == 0 and FOLD_MIN == 2


async def test_a_fold_of_a_hundred_runs_its_hundred_write_aheads_at_once() -> None:
    """CR-S4F-06 (b), ruled (c): a covered symbol's orders are commanded together, so a fold of N
    runs its N members at once, bounded by the store pool and the audit WAL (C-2.18), with the
    1 s gather its fail-safe. Measured: the peak is N, and one cancel-all answers them all."""
    rows, resting = [_fold_row(n) for n in range(1, 101)], [_venue_order(n) for n in range(1, 101)]
    fold = _Fold(rows, resting)
    got = await fold.run()
    assert got.accounts == (AccountCancels(_A, affected=100, error=None),)
    assert fold.exits.peak == 100
    assert [entry for entry in fold.log if entry[0] == "venue"] == [("venue", "cancel_all")]


# --- L1 (CR-S4F-03): the real B1 machine meets the fold -----------------------------------------

_B1_REF = AccountRef(
    account_id=AccountId(orr.ACCOUNT), uid="100001", environment="demo", key_ref=str(UUID(int=1))
)
_BTC = Symbol("BTCUSDT")


@pytest.fixture
async def b1(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[orr.Rig]:
    """The real B1 facade over the in-memory stores (`order_rig`)."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    rig = orr.build_rig()
    yield rig
    await rig.facade.stop()


class _Answered(FakeTradingPort):
    """A venue that runs a cancel-all at once and holds its answer until `answer` is set: the
    window in which the venue's own pushes can reach B1 first."""

    def __init__(self) -> None:
        super().__init__()
        self.answer = asyncio.Event()

    async def cancel_all(self, account: AccountRef, symbol: Symbol | None) -> Sequence[OrderAck]:
        acks = await super().cancel_all(account, symbol)
        await self.answer.wait()
        return acks


class _Gate:
    """An injected sleep that ends once the test opens the gate."""

    def __init__(self) -> None:
        self.open, self.asked = asyncio.Event(), list[float]()

    async def sleep(self, seconds: float) -> None:
        self.asked.append(seconds)
        await self.open.wait()


def _b1_resting(order: NewOrder) -> Order:
    return Order(
        order_link_id=order.order_link_id, exchange_order_id=f"x{order.id.int}",
        account_id=AccountId(orr.ACCOUNT), symbol="BTCUSDT", side="buy", order_type="limit",
        qty=Decimal("1"), price=Decimal("63000"), state="new", filled_qty=Decimal("0"),
        leaves_qty=Decimal("1"), avg_fill_price=None, created_at=1_790_000_000_000_000,
        terminal_at=None, order_kind="order",
    )  # fmt: skip


async def _b1_fold(
    rig: orr.Rig, venue: FakeTradingPort
) -> tuple[CancelAllCoalescer, _Gate, NewOrder, NewOrder]:
    """o1 and o2 `submitted` on B1 and resting at the venue; the fold port over the venue, the
    UID's slot at 100 spent by an earlier fold, so the fold's call waits for its slot at 101. B1's
    cancel is a stand-in for `OmsCommandPort._cancel`'s venue step: it awaits the fold port's
    `cancel_order` in the task B1's `cancel_pending` invoke runs, and lets what it raises go."""
    o1, o2 = orr.order_of(1), orr.order_of(2)
    for order in (o1, o2):
        await rig.submitted(order)
        venue.seed_order(_b1_resting(order), uid=_B1_REF.uid)
    clock, spacer_wait = _Clock(), _Gate()
    spacer = CancelAllSpacer(monotonic=clock, sleep=spacer_wait.sleep)
    assert await spacer.turn(_B1_REF.uid, deadline=clock.now + 5)
    port = CancelAllCoalescer(venue, spacer=spacer, monotonic=clock, sleep=_never)

    async def cancel(command: b01.Command) -> Mapping[str, Any]:
        link = str(command.order["order_link_id"])
        request = CancelOrderRequest(account=_B1_REF, symbol=_BTC, order_link_id=link)
        ack = await port.cancel_order(request)
        assert ack.ok
        return {"ok": True, "exchange_order_id": ack.exchange_order_id}

    rig.commands.on_cancel = cancel
    return port, spacer_wait, o1, o2


async def _b1_cancel_both(rig: orr.Rig, o1: NewOrder, o2: NewOrder) -> None:
    """Each order's B1 `CANCEL`, written ahead; o2 arrives last at the fold, so it leads."""
    for order in (o1, o2):
        await rig.facade.command(orr.ACCOUNT, order.id, "CANCEL", actor="user")
        await rig.quiet()


async def _b1_states(rig: orr.Rig, *orders: NewOrder) -> list[str | None]:
    rows = [await rig.orders.get(orr.ACCOUNT, order.id) for order in orders]
    return [None if row is None else row.lifecycle_state for row in rows]


async def test_on_b1_a_fold_answers_both_members_by_the_one_call(b1: orr.Rig) -> None:
    venue = FakeTradingPort()
    port, spacer_wait, o1, o2 = await _b1_fold(b1, venue)
    async with asyncio.timeout(5):
        with port.fold(_B1_REF, _BTC, [o1.order_link_id, o2.order_link_id]):
            await _b1_cancel_both(b1, o1, o2)
            assert spacer_wait.asked == [1.0] and venue.calls == []  # the call waits for its slot
            spacer_wait.open.set()
            await b1.quiet()
    assert await _b1_states(b1, o1, o2) == ["cancelled", "cancelled"]
    assert [c.method for c in venue.calls] == ["cancel_all"]


@pytest.mark.parametrize("ending", ["EXEC", "REMOTE_CANCELLED"])
async def test_on_b1_a_leader_whose_order_ends_before_the_call_leaves_abandons_the_fold(
    b1: orr.Rig, ending: str
) -> None:
    """L1 (vw2's B1 repro A): the leader's order ends while the fold's call waits for its slot, so
    B1 leaves `cancel_pending` and cancels the leader's invoke. Nothing has left: the fold is
    abandoned, and o1 sends its own cancel and ends `cancelled`, never `unknown`."""
    venue = FakeTradingPort()
    port, spacer_wait, o1, o2 = await _b1_fold(b1, venue)
    async with asyncio.timeout(5):
        with port.fold(_B1_REF, _BTC, [o1.order_link_id, o2.order_link_id]):
            await _b1_cancel_both(b1, o1, o2)
            assert spacer_wait.asked == [1.0] and venue.calls == []
            if ending == "EXEC":
                await b1.facade.push(orr.ACCOUNT, o2.id, "EXEC", orr.fill_of(o2, "e1", "1"))
            else:
                await b1.facade.push(orr.ACCOUNT, o2.id, "REMOTE_CANCELLED", {"updated_time": 9})
            await b1.quiet()
    ended = "filled" if ending == "EXEC" else "cancelled"
    assert await _b1_states(b1, o1, o2) == ["cancelled", ended]
    assert [c.method for c in venue.calls] == ["cancel_order"]  # o1's own: nothing folded left


async def test_on_b1_a_leader_whose_push_beats_the_calls_answer_leaves_it_to_answer_o1(
    b1: orr.Rig,
) -> None:
    """L1 (vw2's B1 repro B): the call has left and the venue ran it; the leader's own push
    reaches B1 before the call's answer and cancels the leader's invoke. The call runs on, and
    its ack answers o1, `cancelled`, never `unknown`."""
    venue = _Answered()
    port, spacer_wait, o1, o2 = await _b1_fold(b1, venue)
    async with asyncio.timeout(5):
        with port.fold(_B1_REF, _BTC, [o1.order_link_id, o2.order_link_id]):
            await _b1_cancel_both(b1, o1, o2)
            spacer_wait.open.set()  # the slot comes: the call leaves, and the venue runs it
            await b1.quiet()
            assert [c.method for c in venue.calls] == ["cancel_all"]
            await b1.facade.push(orr.ACCOUNT, o2.id, "REMOTE_CANCELLED", {"updated_time": 9})
            await b1.quiet()
            venue.answer.set()
            await b1.quiet()
    assert await _b1_states(b1, o1, o2) == ["cancelled", "cancelled"]
    assert [c.method for c in venue.calls] == ["cancel_all"]
