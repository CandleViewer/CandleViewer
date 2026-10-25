"""`cancelAllOrders`'s service (E29-T04 #913 slice 4, S4-E; the orchestrator's Q1, Q6 and Q12
rulings and S4-A's counting rules): scope first and all or nothing, the selection, one
`cancel_admitted` per selected order with reason `cancel_all`, five accounts at once and one order
at a time on each, the per-account answer, the deadline, and one account's failure kept from the
others."""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import fields
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.oms.cancel_all import (
    ACCOUNTS_AT_ONCE,
    DEADLINE_S,
    REASON,
    AccountCancels,
    AccountError,
    CancelAll,
    CancelAllRequest,
    ScopedAccounts,
    selected,
)
from candleviewer.oms.errors import AccountScopeDenied, StoreUnavailable
from candleviewer.oms.exits import ExitOutcome
from candleviewer.oms.ports import SubmitActor
from candleviewer.oms.recovery import FINALS
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.orders import OrderRow, OrderStoreError

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
