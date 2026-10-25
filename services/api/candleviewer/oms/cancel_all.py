"""`cancelAllOrders`'s service (E29-T04 #913 slice 4, S4-E; 22 `cancelAllOrders`; the
orchestrator's Q1, Q6 and Q12 rulings and S4-A's counting rules): per-order B1 cancels across the
accounts a request names, folded into the venue's own cancel-all only for an unrestricted request
on a symbol the venue's call would cover (S4-F, 24 Sec.8.7; the 21:11Z ruling).

Each step before the next:

1. **Scope, all or nothing (SR-E29-13; `scope`, the route's step 4).** The exit service's
   `accounts_in_scope` (S4-C) settles the account set, the scope written once in the order store's
   SQL (C-12.4): an empty list is the caller's trade grants, and the Owner's whole environment; one
   id that is foreign, view-only, frozen, missing or of the other environment refuses the whole
   request (`AccountScopeDenied`) before any order is read or any cancel sent. A scope read that
   fails or runs past the service's bound is `StoreUnavailable` (503): nothing is sent. The route
   records its later refusals against these accounts, so `run` takes them as `scope` answered.
2. **Selection, per account.** `list_open(account, symbol=)`, then only the OMS's own orders
   (provenance `placed`: never a recorded stop's TP/SL order, never an adopted one) that B1 holds
   in `submitted`, `triggered` or `partially_filled`, of the request's intents (none named: every
   intent), and a reduce-only order only when the request says `exclude_reduce_only: false`. A
   recorded stop is never selected, whatever the request says (C-2.6). Any other open order (one
   already `cancel_pending`, a transitional or a parked one) is left alone and counted nowhere. An
   account whose read fails or does not answer in time is that account's `store_unavailable`, and
   none of its orders is sent a cancel.
3. **The cancels.** One `cancel_admitted` per selected order with reason `cancel_all`, each written
   ahead and audited `orders.cancel` by the exit service (Q12): at most `accounts_at_once` accounts
   at a time, one order at a time on each. An unrestricted request (no intents,
   `exclude_reduce_only: false`) may fold one symbol's cancels (S4-F, `folds`): when the fold port's
   `poll`-lane read shows every plain order resting there selected, that symbol's orders are
   commanded together, each still written ahead, and meet one venue `cancel-all` at the port
   (`cancel_all_coalescer`); any other symbol, or a fold the port refuses, stays one order at a
   time. Under 04 Sec.7.2.2 row 14 a Manager's cancel-all covers
   every order of a granted trade account, so no order is checked for its creator (Q6 binds the
   single-order routes). Every selected order of an account is sent its cancel, whatever an earlier
   one's outcome, and one account's failure never undoes another's cancels.
4. **The answer, per account.** `affected` counts the orders that ended `cancelled`. An order that
   ended in another final state before its cancel landed (a fill, an expiry) or that the venue no
   longer held (`unknown` for `already_terminal`, its 110001) lost a race: neither affected nor an
   error (D2). The account is `ok` when every selected order ended so; otherwise its `error` is its
   first failure: the exit service's refusal with its code and `retryable`,
   `exchange_unavailable` for an order whose cancel met a transport fault (`unknown`, left to B1,
   never re-sent), or `timeout`, retryable, for one whose step had not settled in S4-C's bound. At
   `deadline_s` the cancels still waiting are let go: `cancel_admitted` is cancel-safe, so a cancel
   already commanded stays with B1 and is never re-sent, and each account not finished answers
   `timeout`, retryable, in place of any failure before it. `requested` and `succeeded` count
   accounts.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Collection, Iterable, Sequence
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from typing import Final, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, Symbol
from candleviewer.exchange.base.models import AccountRef
from candleviewer.observability import spawn_child
from candleviewer.oms.cancel_all_fold import FoldRefused
from candleviewer.oms.exits import CancelReason, ExitOutcome
from candleviewer.oms.ports import SubmitActor, TradingAccounts
from candleviewer.oms.recovery import FINALS
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.orders import (
    LifecycleState,
    OrderIntent,
    OrderRow,
    OrderStoreError,
)

__all__ = [
    "ACCOUNTS_AT_ONCE", "DEADLINE_S", "EXCHANGE_UNAVAILABLE", "READ_TIMEOUT_S", "REASON",
    "SELECTABLE", "STORE_UNAVAILABLE", "TIMEOUT", "AccountCancels", "AccountError", "CancelAll",
    "CancelAllOutcome", "CancelAllRequest", "Exits", "Fold", "Folds", "OrderReads",
    "ScopedAccounts", "selected", "unrestricted",
]  # fmt: skip

#: Each touched order's `orders.cancel` reason (Q12).
REASON: Final[CancelReason] = "cancel_all"
#: The B1 states a cancel-all sends a cancel to; any other open order is counted nowhere.
SELECTABLE: Final = frozenset[LifecycleState]({"submitted", "triggered", "partially_filled"})
#: Accounts worked at once, one order at a time on each (22 `cancelAllOrders`).
ACCOUNTS_AT_ONCE: Final = 5
#: The fan-out's deadline, from `run`'s start to the last cancel (22 `cancelAllOrders`).
DEADLINE_S: Final = 20.0
#: Each account's `list_open` bound (the scope's is the exit service's own).
READ_TIMEOUT_S: Final = 2.0
#: An account whose orders could not be read: none of its orders is sent a cancel.
STORE_UNAVAILABLE: Final = "store_unavailable"
#: An order whose cancel met a transport fault: its outcome is not known, left to B1, never re-sent.
EXCHANGE_UNAVAILABLE: Final = "exchange_unavailable"
#: An order whose step had not settled in S4-C's bound, or an account the deadline cut short.
TIMEOUT: Final = "timeout"


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


@dataclass(frozen=True, slots=True)
class CancelAllRequest:
    """The request's filter (22 `CancelAllRequest`), parsed: an empty `intents` is every intent."""

    exchange_account_ids: tuple[UUID, ...]
    symbol: str | None
    intents: frozenset[OrderIntent]
    exclude_reduce_only: bool = True


@dataclass(frozen=True, slots=True)
class AccountError:
    """An account's first failure (22 `LegError`, less the message the route writes for `code`)."""

    code: str
    retryable: bool
    exchange_ret_code: int | None = None


@dataclass(frozen=True, slots=True)
class AccountCancels:
    """One account's entry of the answer (22 `BulkAccountResult.results`)."""

    exchange_account_id: UUID
    affected: int
    error: AccountError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class CancelAllOutcome:
    """Every account's entry, in the order the scope helper returned them."""

    accounts: tuple[AccountCancels, ...]

    @property
    def requested(self) -> int:
        return len(self.accounts)

    @property
    def succeeded(self) -> int:
        return sum(account.ok for account in self.accounts)


class OrderReads(Protocol):
    """The order store's open-order read (24 Sec.8.2)."""

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]: ...


class Exits(Protocol):
    """The exit service (S4-C, `runtime.exits`): its scope helper and its per-order cancel of an
    order its caller admitted by account."""

    async def accounts_in_scope(
        self, scope: AccountScope, requested: Collection[UUID]
    ) -> tuple[UUID, ...]: ...

    async def cancel_admitted(
        self,
        row: OrderRow,
        *,
        actor: SubmitActor,
        reason: CancelReason,
        request_id: UUID | None,
    ) -> ExitOutcome: ...


class Fold(Protocol):
    """An open fold's join, as the service reads it: a member that will not arrive leaves it."""

    def leave(self, link: str) -> None: ...


class Folds(Protocol):
    """The venue cancel-all fold's port (S4-F, `cancel_all_coalescer.CancelAllCoalescer`)."""

    async def coverage(
        self, account: AccountRef, symbol: Symbol, members: Collection[str]
    ) -> bool: ...

    def fold(
        self, account: AccountRef, symbol: Symbol, members: Collection[str]
    ) -> AbstractContextManager[Fold]:
        """The members' fold while the block runs; `FoldRefused`, raised entering it, when one
        of them is already in another open fold."""
        ...


def unrestricted(request: CancelAllRequest) -> bool:
    """Whether the request may fold (24 Sec.8.7): every intent, reduce-only orders included."""
    return not request.intents and request.exclude_reduce_only is False


def selected(rows: Iterable[OrderRow], request: CancelAllRequest) -> tuple[OrderRow, ...]:
    """Step 2's filter over one account's open orders, in the order read (oldest first)."""
    return tuple(
        row
        for row in rows
        if row.provenance == "placed"
        and row.lifecycle_state in SELECTABLE
        and (not request.intents or row.intent in request.intents)
        and not (request.exclude_reduce_only and row.reduce_only)
    )


def _failure(outcome: ExitOutcome) -> AccountError | None:
    """`None` when the order ended or lost a race; otherwise what its account reports, if it is
    the first."""
    if outcome.kind == "accepted":
        if outcome.lifecycle_state in FINALS:
            return None
        # S4-C answers an accepted cancel only once B1's step settled it: a breach is not known.
        _log().error("oms_cancel_all_accepted_not_terminal", state=outcome.lifecycle_state)
        return AccountError(EXCHANGE_UNAVAILABLE, retryable=False)
    if outcome.kind == "unknown":
        if outcome.unknown_reason == "already_terminal":
            return None
        if outcome.unknown_reason == "timeout":
            return AccountError(TIMEOUT, retryable=True)
        return AccountError(EXCHANGE_UNAVAILABLE, retryable=False)
    code = outcome.code or EXCHANGE_UNAVAILABLE
    return AccountError(code, outcome.retryable, outcome.exchange_ret_code)


@dataclass(slots=True)
class _Tally:
    """One account's progress, read whether or not its work finished."""

    affected: int = 0
    error: AccountError | None = None
    finished: bool = False

    def count(self, outcome: ExitOutcome) -> None:
        if outcome.kind == "accepted" and outcome.lifecycle_state == "cancelled":
            self.affected += 1
        failure = _failure(outcome)
        if failure is not None and self.error is None:
            self.error = failure

    def entry(self, account: UUID) -> AccountCancels:
        if not self.finished:
            return AccountCancels(account, self.affected, AccountError(TIMEOUT, retryable=True))
        return AccountCancels(account, self.affected, self.error)


@dataclass(frozen=True, slots=True)
class ScopedAccounts:
    """The accounts `CancelAll.scope` settled, each once, in its order: `run` takes nothing else,
    so no account reaches a cancel without the scope's all-or-nothing check (SR-E29-13)."""

    ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class _Run:
    """One request's settled inputs, shared by its account workers."""

    request: CancelAllRequest
    actor: SubmitActor
    request_id: UUID | None
    gate: asyncio.Semaphore
    tallies: dict[UUID, _Tally]


def _bound(name: str, value: float) -> float:
    """A bound in seconds: finite and above zero, as NaN or infinity bounds nothing (C-2.18)."""
    if isinstance(value, bool) or not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite number of seconds above zero")
    return float(value)


class CancelAll:
    """Steps 1 to 4 over an order store and the exit service."""

    def __init__(
        self,
        reads: OrderReads,
        exits: Exits,
        *,
        folds: tuple[Folds, TradingAccounts] | None = None,
        accounts_at_once: int = ACCOUNTS_AT_ONCE,
        deadline_s: float = DEADLINE_S,
        read_timeout_s: float = READ_TIMEOUT_S,
    ) -> None:
        if isinstance(accounts_at_once, bool) or accounts_at_once < 1:
            raise ValueError("accounts_at_once must be at least 1")
        self._reads, self._exits, self._accounts_at_once = reads, exits, accounts_at_once
        self._folds = folds
        self._deadline_s = _bound("deadline_s", deadline_s)
        self._read_timeout_s = _bound("read_timeout_s", read_timeout_s)

    async def scope(self, scope: AccountScope, request: CancelAllRequest) -> ScopedAccounts:
        """Step 1: the accounts the request covers, each once, in the scope helper's order. Its
        refusal (`AccountScopeDenied`) and its `StoreUnavailable` propagate unchanged."""
        found = await self._exits.accounts_in_scope(scope, request.exchange_account_ids)
        return ScopedAccounts(tuple(dict.fromkeys(found)))

    async def run(
        self,
        accounts: ScopedAccounts,
        request: CancelAllRequest,
        *,
        actor: SubmitActor,
        request_id: UUID | None,
    ) -> CancelAllOutcome:
        """Steps 2 to 4 over the accounts `scope` answered: each account's entry, in their order."""
        tallies = {account: _Tally() for account in accounts.ids}
        gate = asyncio.Semaphore(self._accounts_at_once)
        run = _Run(request, actor, request_id, gate, tallies)
        try:
            async with asyncio.timeout(self._deadline_s), asyncio.TaskGroup() as group:
                for account in run.tallies:
                    spawn_child(group, self._work(run, account), name="oms-cancel-all-account")
        except TimeoutError:
            cut = sum(not tally.finished for tally in run.tallies.values())
            _log().warning("oms_cancel_all_deadline", accounts_cut=cut)
        return CancelAllOutcome(
            tuple(tally.entry(account) for account, tally in run.tallies.items())
        )

    async def _work(self, run: _Run, account: UUID) -> None:
        """One account: its read, then each selected order's cancel in turn; where a fold may
        apply, symbol by symbol in the order read, a covered symbol's orders together."""
        tally = run.tallies[account]
        async with run.gate:
            rows = await self._selected(account, run.request)
            if rows is None:
                tally.error = AccountError(STORE_UNAVAILABLE, retryable=True)
            port = await self._fold_port(account, run.request) if rows else None
            if port is None:
                for row in rows or ():
                    tally.count(await self._cancel(run, row))
            else:
                groups: dict[str, list[OrderRow]] = {}
                for row in rows or ():
                    groups.setdefault(row.symbol, []).append(row)
                for symbol, group in groups.items():
                    if await self._covered(port, symbol, group):
                        for outcome in await self._folded(run, port, symbol, group):
                            tally.count(outcome)
                        continue
                    for row in group:
                        tally.count(await self._cancel(run, row))
            tally.finished = True

    async def _cancel(self, run: _Run, row: OrderRow) -> ExitOutcome:
        return await self._exits.cancel_admitted(
            row, actor=run.actor, reason=REASON, request_id=run.request_id
        )

    async def _fold_port(
        self, account: UUID, request: CancelAllRequest
    ) -> tuple[Folds, AccountRef] | None:
        """The fold port with the account as the venue knows it, for an unrestricted request;
        else, or when the account cannot be read in time, None: per-order cancels. A read that
        answers another account's ref is a defect, as the command port's would be (SR-E27-21):
        nothing is read or sent with it, and the account stays on per-order cancels."""
        if self._folds is None or not unrestricted(request):
            return None
        folds, accounts = self._folds
        try:
            async with asyncio.timeout(self._read_timeout_s):
                ref = await accounts.trading_account(AccountId(account))
        except Exception as exc:  # no venue account read: the per-order path, its own refusals
            _log().warning("oms_cancel_all_fold_account_unread", failure=type(exc).__name__)
            return None
        if ref.account_id != account:  # no identifier logged: the mismatch is the signal
            _log().warning("oms_cancel_all_fold_account_mismatch")
            return None
        return folds, ref

    async def _covered(
        self, port: tuple[Folds, AccountRef], symbol: str, group: Sequence[OrderRow]
    ) -> bool:
        """The fold port's coverage read, bounded; a read past the bound is no proof of it."""
        (folds, ref), links = port, [row.order_link_id for row in group]
        try:
            async with asyncio.timeout(self._read_timeout_s):
                return await folds.coverage(ref, Symbol(symbol), links)
        except TimeoutError:
            _log().warning("oms_cancel_all_coverage_late")
            return False

    async def _folded(
        self, run: _Run, port: tuple[Folds, AccountRef], symbol: str, group: Sequence[OrderRow]
    ) -> list[ExitOutcome]:
        """One symbol's orders commanded together inside their fold (the 21:11Z ruling, Q2): each
        member that finishes leaves it, so a member refused before its send never holds the
        others. A fold the port refuses (`FoldRefused`: an order already meets another request's
        fold) runs the orders in turn instead, as it is raised entering the fold."""
        (folds, ref), links = port, [row.order_link_id for row in group]
        stack = ExitStack()
        try:
            join = stack.enter_context(folds.fold(ref, Symbol(symbol), links))
        except FoldRefused:
            _log().warning("oms_cancel_all_fold_refused", symbol=symbol)
            return [await self._cancel(run, row) for row in group]

        async def member(row: OrderRow) -> ExitOutcome:
            try:
                return await self._cancel(run, row)
            finally:
                join.leave(row.order_link_id)

        with stack:
            async with asyncio.TaskGroup() as members:
                tasks = [
                    spawn_child(members, member(row), name="oms-cancel-all-fold-member")
                    for row in group
                ]
        return [task.result() for task in tasks]

    async def _selected(
        self, account: UUID, request: CancelAllRequest
    ) -> tuple[OrderRow, ...] | None:
        """The account's selected orders, or `None` when they could not be read in time."""
        try:
            async with asyncio.timeout(self._read_timeout_s):
                rows = await self._reads.list_open(account, symbol=request.symbol)
        except (TimeoutError, StorageError, OrderStoreError) as exc:
            _log().warning("oms_cancel_all_read_unavailable", failure=type(exc).__name__)
            return None
        return selected(rows, request)
