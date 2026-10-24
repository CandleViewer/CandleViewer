"""The exit service (E29-T04 slice 4): `OrderExits`, which the exit routes and cancel-all drive
once RBAC passed, steps 4 and 11 of 24 Sec.8.4 "The exit routes", whose rulings it implements
(Q3 to Q12; the S4-A decisions D1 to D4, D6, D9; the 11:34Z and 12:30Z rulings).

`scope` reads the order in the caller's `AccountScope` (`OrderRepository.get_in_scope`, C-12.4):
`404` outside it (SR-E29-13; `rbac.denied` for a real order only, Q12), `403
account_scope_denied` on a view-only grant (Q7), `403 forbidden` for a Manager on an order it did
not create (Q6), each record best effort. `cancel_admitted` is the route's and cancel-all's one
per-order cancel (04 Sec.7.2.2 row 14: no creator check), with Q8's state rules and D9's bounded
waits. `amend` checks the state (`422`), the body (`400`), the one ratchet (`403`), a
risk-increasing amend's gates (Q10, D1, SEC-S4A-01) and `If-Match` (`412`), in that order (D3).

Every refusal is an `ExitOutcome`, recorded ahead (`deny`, C-2.9), else `503 audit_unavailable`.
An exit is written ahead (`orders.amend`, `orders.cancel`, with the request's reason), so a caller
cancelled before that sends nothing; from its command on it is a task of its own, which a
cancelled caller leaves with B1, never re-sent or undone, and whose answer waits for B1's step,
at most `SETTLE_TIMEOUT_S`: `accepted` carries the settled state, `unknown` the order left with
B1 (`already_terminal`, `transport`, `timeout`), `refused` the 22 problem.
"""

from __future__ import annotations

import asyncio
import functools
from collections import Counter
from collections.abc import Callable, Collection, Coroutine, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.selfcheck import DISABLED_BY_POLICY
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Side
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.observability import spawn
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT
from candleviewer.statechart.persistence import DegradedLatchError
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope
from candleviewer.storage.repositories.orders import (
    AccountsOutOfScope,
    OrderRow,
    OrderStoreError,
    OutOfScope,
    ScopedOrder,
)
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

from .classify import stop_errors, take_profit_errors
from .commands import (
    ACCOUNT_UNAVAILABLE,
    ORDER_NOT_AMENDABLE,
    STOP_LOOSENING_REFUSED,
    STOP_REQUEST_IN_FLIGHT,
    STORE_UNAVAILABLE,
    STORE_UNAVAILABLE_RETRY_AFTER_S,
    ExitKind,
    ExitWatch,
)
from .errors import (
    AccountScopeDenied,
    ExchangeRejected,
    FieldError,
    IdempotencyInFlight,
    IllegalTransition,
    OmsError,
    OmsNotReady,
    OrderEntryRefused,
    OrderInvalid,
    OrderNotAmendable,
    OrderNotFound,
    OrderNotLoaded,
    OrderRefused,
    OrderStepRefused,
    OrderStepUnknown,
    RateBudgetExceeded,
    RiskRefused,
    StopRequestPending,
    StoreUnavailable,
    TradingDisabled,
    VersionConflict,
    problem_for,
)
from .order_machine import Actor, CommandEvent
from .ports import (
    Instruments,
    OrderEffect,
    Profiles,
    RequestRecord,
    RiskGate,
    SizedOrder,
    StopOffset,
    StopResolver,
    SubmitActor,
    SubmitAudit,
    TradingSwitches,
)
from .routing import retry_after
from .stop_ratchet import ratchet_refusal, tpsl_scope_refusal
from .validator import Validator

__all__ = [
    "IN_FLIGHT_RETRY_AFTER_S", "MAX_IN_FLIGHT", "MAX_IN_FLIGHT_PER_PRINCIPAL", "NOT_GRANTED",
    "NOT_ORDER_CREATOR",
    "SETTLE_TIMEOUT_S", "TRANSITION_TIMEOUT_S", "VIEW_ONLY", "AmendTerms", "CancelReason",
    "ExitCaller", "ExitCommands", "ExitDeps", "ExitMachines", "ExitOperation", "ExitOrders",
    "ExitOutcome", "InFlightGuard", "LiveStops", "OrderExits", "OutcomeKind", "UnknownReason",
    "risk_increasing",
]  # fmt: skip

#: What an exit's answer is (the 12:30Z ruling): taken, its outcome not known, or refused.
type OutcomeKind = Literal["accepted", "unknown", "refused"]
#: Why an exit's outcome is not known: the venue no longer holds the order (110001), the port
#: raised, or B1's step had not settled within `SETTLE_TIMEOUT_S` (S4-A decision D2).
type UnknownReason = Literal["already_terminal", "transport", "timeout"]
#: Why a cancel is asked (ruling Q12): a user's, on its route, or a cancel-all's.
type CancelReason = Literal["user", "cancel_all"]
#: The exits the in-flight guard keys (ruling Q11) and the audit names.
type ExitOperation = Literal["amend", "cancel", "cancel_all"]

#: How long a cancel waits for a step in flight to settle before it is sent (D9).
TRANSITION_TIMEOUT_S: Final = CV_COMMAND_TIMEOUT
#: How long an exit waits for B1's step to settle once commanded (24 Sec.8.4).
SETTLE_TIMEOUT_S: Final = CV_COMMAND_TIMEOUT + 1.0
#: The in-flight guard's keys per process (D4) and per principal (SEC-S4A-03), and its refusals'
#: `Retry-After` (Q11).
MAX_IN_FLIGHT: Final = 1024
MAX_IN_FLIGHT_PER_PRINCIPAL: Final = 64
IN_FLIGHT_RETRY_AFTER_S: Final = 1
#: The bound on each store read and audit write of an exit, in seconds.
STORE_TIMEOUT_S: Final = 2.0
#: `rbac.denied`'s reasons (ruling Q12), the first two as `auth.scopes.decide` names them.
NOT_GRANTED: Final = "account_not_granted:orders:write:granted_accounts"
VIEW_ONLY: Final = "trading_not_granted:orders:write:granted_accounts"
NOT_ORDER_CREATOR: Final = "not_order_creator"
_ACTIONS: Final[Mapping[ExitOperation, str]] = {
    "amend": "orders.amend",
    "cancel": "orders.cancel",
    "cancel_all": "orders.cancel",
}
_FINAL: Final = frozenset({"filled", "cancelled", "rejected", "expired", "killed"})
_AMENDABLE: Final = frozenset({"submitted", "partially_filled"})
_CANCELLABLE: Final = frozenset({"submitted", "triggered", "partially_filled"})
_SETTLING: Final = frozenset({"validated", "submitting", "amend_pending", "cancel_pending"})
_SIDES: Final[Mapping[str, Side]] = {"Buy": "buy", "Sell": "sell"}
_TYPES: Final[Mapping[str, Literal["market", "limit"]]] = {"Market": "market", "Limit": "limit"}
#: The retry codes of cancel-all's `retryable` (the 12:30Z ruling): nothing sent, may pass later.
_RETRYABLE: Final = frozenset({"store_unavailable", "exchange_rate_limited"})
#: Q3's rules the command port answers in capitals, which this service checks first.
_TPSL_RULES: Final = frozenset({
    "reduce_only_tpsl", "native_stop_required", "tpsl_clear_unsupported", "tpsl_partial_mode",
    "tpsl_after_fill",
})  # fmt: skip
#: A TP/SL side named by an `Offset`, for Q3's check before it is resolved: not a clear.
_NAMED: Final = Decimal(1)
_UNREAD: Final = (TimeoutError, StorageError, OrderStoreError)
_NOT_TAKEN: Final = (IllegalTransition, DegradedLatchError, OrderNotLoaded, OrderStepRefused)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitOutcome:
    """One exit's answer, which a route renders and cancel-all counts (the 12:30Z ruling).

    `accepted` once B1's step settled: `row` and `lifecycle_state` as it left the order (a
    cancel's `cancelled`, or `filled` by a racing fill; an amend's live state, with `version`, the
    `ETag`'s seq). `unknown`: the order left with B1, never re-sent (S1), `unknown_reason` why;
    `row` and `lifecycle_state` as it stands. `refused`: the 22 problem `code` with its `status`,
    `detail`, `errors`, `retry_after_s` and the order-entry gate's `reason`; nothing sent but for
    the venue's own refusal (`502 exchange_error`). `exchange_ret_code` is the venue's code where
    it gave one (SR-E29-09: never its text). `status` is the route's: 202 for the first two."""

    kind: OutcomeKind
    status: int
    code: str | None = None
    detail: str | None = None
    errors: tuple[FieldError, ...] = ()
    retry_after_s: int | None = None
    reason: str | None = None
    exchange_ret_code: int | None = None
    row: OrderRow | None = None
    lifecycle_state: str | None = None
    version: int | None = None
    unknown_reason: UnknownReason | None = None

    @property
    def retryable(self) -> bool:
        """Cancel-all's `retryable`: a refusal that sent nothing and may pass later
        (`store_unavailable`, `exchange_rate_limited`), or a wait that ran out (`timeout`)."""
        if self.kind == "unknown":
            return self.unknown_reason == "timeout"
        return self.code in _RETRYABLE


def _refused(error: OrderRefused) -> ExitOutcome:
    """`error`'s answer, its `PROBLEMS` row (`errors.problem_for`) and what renders it."""
    problem, delay = problem_for(error), getattr(error, "retry_after_s", None)
    return ExitOutcome(
        kind="refused", status=problem.status, code=problem.code, detail=error.detail,
        errors=error.errors, retry_after_s=delay if type(delay) is int else None,
        reason=error.reason if isinstance(error, OrderEntryRefused) else None,
        exchange_ret_code=error.ret_code if isinstance(error, ExchangeRejected) else None,
    )  # fmt: skip


def _problem(status: int, code: str, detail: str, retry_after_s: int | None = None) -> ExitOutcome:
    """An exit's own answer that no `PROBLEMS` row names (22 `OrderExitConflict`, ruling Q6)."""
    return ExitOutcome(
        kind="refused", status=status, code=code, detail=detail, retry_after_s=retry_after_s
    )


def _store() -> ExitOutcome:
    """`503 store_unavailable` with the shared `Retry-After` (the 11:34Z ruling): nothing sent."""
    retry = retry_after(STORE_UNAVAILABLE_RETRY_AFTER_S)
    return _problem(503, "store_unavailable", StoreUnavailable.default_detail, retry)


def _invalid(field: str, rule: str, message: str) -> ExitOutcome:
    return _refused(OrderInvalid(errors=(FieldError(field, rule, message),)))


_NOT_FOUND: Final = _refused(OrderNotFound())
_SCOPE_VIEW_ONLY: Final = _refused(AccountScopeDenied())
_NOT_CREATOR: Final = _problem(
    403, "forbidden", "Only the order's creator or the Owner may change it."
)
_CONFLICT: Final = _problem(
    409, "conflict", "The order's state takes no such exit now; nothing was sent."
)
_ACCOUNT_UNAVAILABLE: Final = _problem(
    409, "account_unavailable", "The order's account cannot be traded now; nothing was sent."
)
_GUARD_FULL: Final = _problem(
    429, "rate_limited", "Too many exits are in flight; retry shortly.", IN_FLIGHT_RETRY_AFTER_S
)
_IN_FLIGHT: Final = _refused(IdempotencyInFlight(retry_after_s=IN_FLIGHT_RETRY_AFTER_S))
#: An exit asked once the service closed (`aclose`): as the runtime answers once stopped.
_CLOSED: Final = _refused(OmsNotReady())


class InFlightGuard:
    """Ruling Q11's in-flight guard (24 Sec.8.4, the exit routes' step 9; D4), reusable by every
    exit (`operation`): one exit at a time per principal, operation and `Idempotency-Key`, in this
    process, with no anchor (OM-T11). `claim` answers the claim's own release, which its holder
    calls once its exit has ended (its task's end, not its request's), or the refusal, nothing sent:
    `409 idempotency_in_flight` while the key's exit runs; `429 rate_limited` while `max_keys` are
    held, or `max_per_principal` of the principal's (SEC-S4A-03), so no principal holds the others
    out, their protective cancels included; each with `Retry-After: 1`. One event loop's, as the
    24 h record is."""

    def __init__(
        self,
        *,
        max_keys: int = MAX_IN_FLIGHT,
        max_per_principal: int = MAX_IN_FLIGHT_PER_PRINCIPAL,
    ) -> None:
        if not 1 <= max_per_principal <= max_keys:
            raise ValueError("the in-flight guard holds at least one key, a principal's within all")
        self._max, self._per = max_keys, max_per_principal
        self._held: dict[tuple[UUID, ExitOperation, UUID], object] = {}
        self._mine = Counter[UUID]()

    def claim(
        self, user_id: UUID, operation: ExitOperation, key: UUID
    ) -> Callable[[], None] | ExitOutcome:
        held = (user_id, operation, key)
        if held in self._held:
            return _IN_FLIGHT
        if len(self._held) >= self._max or self._mine[user_id] >= self._per:
            return _GUARD_FULL
        self._held[held] = token = object()
        self._mine[user_id] += 1
        return functools.partial(self._release, held, token)

    def _release(self, held: tuple[UUID, ExitOperation, UUID], token: object) -> None:
        """The claim's own, once: a second call, or one once the key was claimed anew, frees
        nothing, as the key no longer holds the claim's token."""
        if self._held.get(held) is token:
            del self._held[held]
            self._mine[held[0]] -= 1
            if not self._mine[held[0]]:
                del self._mine[held[0]]


@dataclass(frozen=True, slots=True)
class ExitCaller:
    """Who asks, as the route admitted them: the accounts the principal reaches
    (`auth.scopes.account_scope`), its records' actor (C-2.9) and the request's correlation id."""

    scope: AccountScope
    actor: SubmitActor
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AmendTerms:
    """22 `AmendOrderRequest`, read strictly by the route: each term named, else None; `sides` the
    TP/SL sides named, None for one asked cleared (`null`)."""

    qty: Decimal | None = None
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    sides: Mapping[str, StopOffset | None] | None = None


def risk_increasing(row: OrderRow, terms: AmendTerms) -> bool:
    """24 Sec.8.10, ruling Q10 (D5) and the S4-A security look's default (SEC-S4A-01): an amend of
    an order that is not reduce-only raises exposure when it raises the quantity or moves the
    price or the trigger (a deep limit entry repriced through the market fills at once), each
    compared with the scoped read's terms. A reduce-only order's terms, any quantity cut, a stop
    or a take-profit change and every cancel are never gated (C-2.6); a figure that is no number
    is not compared, the body refuses it."""
    if row.reduce_only:
        return False
    raised = terms.qty is not None and terms.qty.is_finite() and terms.qty > row.qty
    moves = ((terms.price, row.price), (terms.trigger_price, row.trigger_price))
    return raised or any(new is not None and new.is_finite() and new != old for new, old in moves)


class ExitMachines(Protocol):
    """`order_machine.OrderMachines` as the exits drive it."""

    def state(self, order_id: UUID) -> tuple[str, str] | None: ...

    def version(self, order_id: UUID) -> int | None: ...

    async def command(
        self,
        account_id: UUID,
        order_id: UUID,
        event: CommandEvent,
        payload: Mapping[str, Any] | None = None,
        *,
        actor: Actor,
        expected_seq: int | None = None,
    ) -> str: ...

    async def settled(
        self, account_id: UUID, order_id: UUID, *, leaving: str, timeout_s: float
    ) -> str: ...


class ExitCommands(Protocol):
    """`commands.OmsCommandPort`'s exit watch."""

    def expect_exit(
        self,
        order_id: UUID,
        kind: ExitKind,
        *,
        request_id: UUID | None = None,
        actor: SubmitActor | None = None,
    ) -> ExitWatch: ...

    def forget_exit(self, order_id: UUID, kind: ExitKind) -> None: ...


class ExitOrders(Protocol):
    """`repository.OrderRepository` as the exits read it: the stored row and the two reads in the
    caller's scope (C-12.4), and no write."""

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...

    async def get_in_scope(
        self, scope: AccountScope, order_id: UUID, *, environment: Environment
    ) -> ScopedOrder | OutOfScope: ...

    async def accounts_in_scope(
        self, scope: AccountScope, environment: Environment, requested: Collection[UUID]
    ) -> tuple[UUID, ...]: ...


class LiveStops(Protocol):
    """The recorded-stop repository as the exits read it: one key's records in force, for an
    amend's ratchet (ruling Q4), and nothing it records, settles or sweeps; so this module names
    none of the store-callers fence's surface (`test_order_submission_store_callers.py`)."""

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitDeps:
    """What the composition root (`oms_wiring`) builds the exits over: the facade and the command
    port the pipeline drives, the order store's reads, the stops in force, the audit, and the
    pipeline's own checks (D1)."""

    machines: ExitMachines
    commands: ExitCommands
    orders: ExitOrders
    stops: LiveStops
    audit: SubmitAudit
    instruments: Instruments
    profiles: Profiles
    stop_resolver: StopResolver
    risk_gate: RiskGate
    validator: Validator
    switches: TradingSwitches
    oms_enabled: Callable[[], bool]
    environment: Environment


class OrderExits:
    """The exit service of this process's environment (module docstring); `guard` is the exit
    routes' in-flight guard. `aclose()` closes it: no exit starts after it, and the exits still
    running once their callers left are cancelled."""

    def __init__(
        self,
        deps: ExitDeps,
        *,
        transition_timeout_s: float = TRANSITION_TIMEOUT_S,
        settle_timeout_s: float = SETTLE_TIMEOUT_S,
        store_timeout_s: float = STORE_TIMEOUT_S,
    ) -> None:
        bounds = (
            (transition_timeout_s, TRANSITION_TIMEOUT_S),
            (settle_timeout_s, SETTLE_TIMEOUT_S),
            (store_timeout_s, STORE_TIMEOUT_S),
        )
        if not all(0 < bound <= most for bound, most in bounds):  # NaN fails it too
            raise ValueError("an exit's bound is only ever tightened, never raised")
        self._d = deps
        self._waits = (transition_timeout_s, settle_timeout_s, store_timeout_s)
        self.guard = InFlightGuard()
        self._running: set[asyncio.Task[ExitOutcome]] = set()
        self._closed = False

    async def aclose(self) -> None:
        """At shutdown: no exit starts after it (`503 oms_not_ready`, as the runtime answers once
        stopped), and the exits whose callers left are cancelled and awaited."""
        self._closed = True
        running = set(self._running)
        for task in running:
            task.cancel()
        if running:
            await asyncio.wait(running)

    # --- the scope (step 4) ---------------------------------------------------------------------

    async def scope(self, caller: ExitCaller, order_id: UUID) -> ScopedOrder | ExitOutcome:
        """The order in the caller's scope, or the refusal (module docstring)."""
        try:
            read = self._d.orders.get_in_scope(caller.scope, order_id, environment=self._env)
            found = await self._bounded(read)
        except _UNREAD as exc:  # nothing read, so no account to record it on: logged
            _log().warning("oms_exit_scope_unread", failure=type(exc).__name__)
            return _store()
        if isinstance(found, OutOfScope):
            if found.account_id is not None:
                await self._rbac(found.account_id, order_id, NOT_GRANTED, caller)
            return _NOT_FOUND
        account = found.order.exchange_account_id
        if not found.can_trade:
            await self._rbac(account, order_id, VIEW_ONLY, caller)
            return _SCOPE_VIEW_ONLY
        if isinstance(caller.scope, GrantScope) and found.created_by != caller.scope.user_id:
            await self._rbac(account, order_id, NOT_ORDER_CREATOR, caller)
            return _NOT_CREATOR
        return found

    async def accounts_in_scope(
        self, scope: AccountScope, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        """Cancel-all's accounts of this environment (`OrderRepository.accounts_in_scope`):
        `AccountScopeDenied` for the whole request when one requested is outside the scope
        (SR-E29-13), a store's own refusal too, `StoreUnavailable` when the read fails; nothing
        sent either way."""
        try:
            read = self._d.orders.accounts_in_scope(scope, self._env, requested)
            return await self._bounded(read)
        except AccountsOutOfScope:  # met unwrapped: the caller's scope, never an outage
            raise AccountScopeDenied from None
        except _UNREAD as exc:
            _log().warning("oms_exit_accounts_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None

    async def deny(
        self,
        row: OrderRow,
        operation: ExitOperation,
        outcome: ExitOutcome,
        *,
        actor: SubmitActor,
        request_id: UUID | None,
    ) -> ExitOutcome:
        """`outcome`, a refusal, recorded before it is answered (C-2.9): `orders.amend` or
        `orders.cancel` denied with its code, the order-entry gate's `account.disabled_by_policy`
        with its reason; else `503 audit_unavailable` in its place, nothing sent. The route's own
        refusals of an order (its in-flight guard's, the arm token's) take it too."""
        action = DISABLED_BY_POLICY if outcome.reason is not None else _ACTIONS[operation]
        detail = {"operation": operation, "code": outcome.code, "order_link_id": row.order_link_id}
        severity: Literal["warning", "error"] = "error" if outcome.status >= 500 else "warning"
        reason = outcome.reason or outcome.code or ""
        written = await self._record(
            row, action, "denied", reason, detail, actor, request_id, severity=severity
        )
        if written:
            return outcome
        return _problem(503, "audit_unavailable", "The refusal could not be recorded.")

    # --- cancel ----------------------------------------------------------------------------------

    async def cancel_admitted(
        self,
        row: OrderRow,
        *,
        actor: SubmitActor,
        reason: CancelReason,
        request_id: UUID | None,
    ) -> ExitOutcome:
        """The per-order cancel of the route (after `scope`) and of cancel-all, one code path
        (module docstring): no creator check here, as cancel-all covers every order of a granted
        trade account (04 Sec.7.2.2 row 14); `reason` names the request in its `orders.cancel`."""
        if self._closed:
            return _CLOSED
        operation: ExitOperation = "cancel_all" if reason == "cancel_all" else "cancel"
        state = await self._lifecycle(row)
        if not isinstance(state, ExitOutcome) and state in _SETTLING:
            try:  # D9: hop by hop (`validated`, then `submitting`), all within the one bound
                async with asyncio.timeout(self._waits[0]):
                    while state in _SETTLING:
                        left = state
                        state = await self._d.machines.settled(
                            row.exchange_account_id, row.id, leaving=left,
                            timeout_s=self._waits[0],
                        )  # fmt: skip
                        if state == left:  # its row's, no machine here to move it on
                            break
            except (TimeoutError, OrderNotLoaded):
                if state == "cancel_pending":  # the cancel in flight is B1's: as it stands
                    return await self._standing(row, "unknown", state, "timeout")
                state = _CONFLICT
        if not isinstance(state, ExitOutcome) and state in _FINAL:
            return await self._standing(row, "accepted", state)
        if isinstance(state, ExitOutcome) or state not in _CANCELLABLE:
            refusal = state if isinstance(state, ExitOutcome) else _CONFLICT
            return await self.deny(row, operation, refusal, actor=actor, request_id=request_id)
        detail = {"operation": operation, "state": state, "order_link_id": row.order_link_id}
        if not await self._record(
            row, "orders.cancel", "success", reason, detail, actor, request_id
        ):
            return _problem(503, "audit_unavailable", "The cancel could not be recorded.")
        if self._closed:  # `aclose` ran while the intent was written: nothing starts
            return await self.deny(row, operation, _CLOSED, actor=actor, request_id=request_id)
        send = self._send(row, operation, "CANCEL", {}, actor=actor, request_id=request_id)
        return await self._shielded(send, operation)

    async def _lifecycle(self, row: OrderRow) -> str | ExitOutcome:
        """The order's B1 state: its machine's, else, with none here, its stored row's."""
        held = self._d.machines.state(row.id)
        if held is not None:
            return held[0]
        try:
            stored = await self._bounded(self._d.orders.get(row.exchange_account_id, row.id))
        except _UNREAD as exc:
            _log().warning("oms_exit_row_unread", failure=type(exc).__name__)
            return _store()
        state = None if stored is None else stored.lifecycle_state
        return state if state in _FINAL else _CONFLICT  # no machine holds a live one here

    # --- the send, both exits ------------------------------------------------------------------

    async def _shielded(
        self, send: Coroutine[Any, Any, ExitOutcome], operation: ExitOperation
    ) -> ExitOutcome:
        """`send` as a task of its own (the 12:30Z ruling): a caller cancelled now leaves the exit
        with B1, which settles it, never re-sent and never undone; `aclose` ends it at shutdown."""
        task = spawn(send, name=f"oms-exit-{operation}")
        self._running.add(task)
        task.add_done_callback(self._ended)
        return await asyncio.shield(task)

    def _ended(self, task: asyncio.Task[ExitOutcome]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().error("oms_exit_task_failed", failure=type(error).__name__)

    async def _send(
        self,
        row: OrderRow,
        operation: ExitOperation,
        event: CommandEvent,
        payload: Mapping[str, str],
        *,
        actor: SubmitActor,
        request_id: UUID | None,
        expected_seq: int | None = None,
        terms: Mapping[str, Decimal] | None = None,
    ) -> ExitOutcome:
        """The command through the exit watch (the principal its `actor`), then B1's settle, at
        most `SETTLE_TIMEOUT_S`; its outcome recorded beside its intent (`_outcome`)."""
        kind = _kind(operation)
        account, pending = row.exchange_account_id, f"{kind}_pending"
        watch = self._d.commands.expect_exit(row.id, kind, request_id=request_id, actor=actor)
        try:
            state: str | None = await self._d.machines.command(
                account, row.id, event, payload, actor="user", expected_seq=expected_seq
            )
        except OrderStepUnknown:  # rebuilt from its events: as it stands, never re-sent
            self._d.commands.forget_exit(row.id, kind)
            state = None
        except BaseException as exc:
            self._d.commands.forget_exit(row.id, kind)
            if not isinstance(exc, (VersionConflict, *_NOT_TAKEN)):
                raise
            state = await self._moved(row, kind, exc)
            if state is None:
                refusal = _taken_not(kind, exc)
                return await self._outcome(row, operation, refusal, actor, request_id)
        if state == pending:
            try:
                state = await self._d.machines.settled(
                    account, row.id, leaving=pending, timeout_s=self._waits[1]
                )
            except (TimeoutError, OrderNotLoaded):
                state = None
        answer = await watch.answer() if watch.answered else None
        held = self._d.machines.state(row.id)
        state = state if state is not None else (None if held is None else held[0])
        outcome = await self._result(row, kind, state, answer, watch.answered, terms)
        return await self._outcome(row, operation, outcome, actor, request_id)

    async def _moved(self, row: OrderRow, kind: ExitKind, error: BaseException) -> str | None:
        """A cancel the order moved under at the facade (`IllegalTransition`) answers as the order
        then stands (22 `cancelOrder`: `202`), read again as `_lifecycle` reads it: a final order,
        or another request's cancel in flight, waited for as this one's own would be. None for any
        other refusal or state: `_taken_not`'s answer."""
        if kind != "cancel" or not isinstance(error, IllegalTransition):
            return None
        state = await self._lifecycle(row)
        if isinstance(state, ExitOutcome):
            return None
        return state if state in _FINAL or state == "cancel_pending" else None

    async def _result(
        self,
        row: OrderRow,
        kind: ExitKind,
        state: str | None,
        answer: Mapping[str, Any] | None,
        answered: bool,
        terms: Mapping[str, Decimal] | None,
    ) -> ExitOutcome:
        """What B1's settle and the port's answer say: a final order, or an amend taken, is
        `accepted`; `unknown` is `unknown` (the watch's 110001 mark read defensively: any other
        raise answers None); a port's refusal is mapped; anything else had not settled."""
        if state in _FINAL or (kind == "amend" and state in _AMENDABLE and _ok(answer)):
            fresh = await self._fresh(row, terms if _ok(answer) else None)
            version = self._d.machines.version(row.id) if kind == "amend" else None
            return ExitOutcome(
                kind="accepted", status=202, row=fresh, lifecycle_state=state, version=version
            )
        if state == "unknown":
            terminal = answer is not None and answer.get("unknown") == b01.ALREADY_TERMINAL
            fresh, ret = await self._fresh(row, None), _int(answer, "exchange_ret_code")
            why: UnknownReason = "already_terminal" if terminal else "transport"
            return ExitOutcome(
                kind="unknown", status=202, row=fresh, lifecycle_state=state,
                exchange_ret_code=ret, unknown_reason=why,
            )  # fmt: skip
        if answered and answer is not None and answer.get("ok") is False:
            return _answered(kind, answer)
        return await self._standing(row, "unknown", state, "timeout")

    async def _standing(
        self,
        row: OrderRow,
        kind: Literal["accepted", "unknown"],
        state: str | None,
        why: UnknownReason | None = None,
    ) -> ExitOutcome:
        """The order as it stands, read again: a final one's answer, nothing sent, or an exit's
        that had not settled (`timeout`)."""
        fresh = await self._fresh(row, None)
        return ExitOutcome(
            kind=kind, status=202, row=fresh, lifecycle_state=state, unknown_reason=why
        )

    async def _fresh(self, row: OrderRow, terms: Mapping[str, Decimal] | None) -> OrderRow:
        """The row read again, once the exit's step settled; a read that fails answers `row` with
        an amend's taken `terms`, logged: the step stands."""
        try:
            fresh = await self._bounded(self._d.orders.get(row.exchange_account_id, row.id))
        except _UNREAD as exc:
            _log().warning("oms_exit_reread_failed", failure=type(exc).__name__)
            fresh = None
        if fresh is not None:
            return fresh
        taken: dict[str, Any] = dict(terms or {})
        return replace(row, **taken)

    async def _outcome(
        self,
        row: OrderRow,
        operation: ExitOperation,
        outcome: ExitOutcome,
        actor: SubmitActor,
        request_id: UUID | None,
    ) -> ExitOutcome:
        """The exit's outcome beside its intent. A refusal is recorded before it is answered, by
        `deny` (C-2.9; 24 Sec.8.4: the command port records none of a cancel it refuses), so one
        whose record cannot be written answers `503 audit_unavailable`; an accepted or unknown
        outcome is recorded best effort (as `orders.submit`'s)."""
        if outcome.kind == "refused":
            return await self.deny(row, operation, outcome, actor=actor, request_id=request_id)
        accepted = outcome.kind == "accepted"
        result: Literal["success", "failure"] = "success" if accepted else "failure"
        reason = outcome.lifecycle_state if accepted else None
        reason = reason or outcome.unknown_reason or outcome.code or ""
        kind = _kind(operation)
        detail = {"operation": kind, "code": outcome.code, "state": outcome.lifecycle_state}
        await self._record(row, _ACTIONS[kind], result, reason, detail, actor, request_id)
        return outcome

    # --- amend -----------------------------------------------------------------------------------

    async def amend(
        self,
        scoped: ScopedOrder,
        terms: AmendTerms,
        *,
        caller: ExitCaller,
        expected_seq: int | None,
    ) -> ExitOutcome:
        """`amendOrder`'s admission and send (module docstring) for an order `scope` returned;
        `expected_seq` is `If-Match`'s version (`api.order_etag.expected_seq`), None without one."""
        if self._closed:
            return _CLOSED
        row, actor, rid = scoped.order, caller.actor, caller.request_id
        held = self._d.machines.state(row.id)
        if row.provenance != "placed" or held is None or held[0] not in _AMENDABLE:
            return await self.deny(
                row, "amend", _refused(OrderNotAmendable()), actor=actor, request_id=rid
            )
        checked = await self._checked(row, terms)
        if isinstance(checked, ExitOutcome):
            return await self.deny(row, "amend", checked, actor=actor, request_id=rid)
        sized, instrument, sides = checked
        refusal = await self._ratchet(row, sized.stop_loss if sides else None)
        if refusal is None and risk_increasing(row, terms):
            refusal = await self._gated(scoped, sized, instrument)
        if refusal is None and expected_seq is not None:
            if self._d.machines.version(row.id) != expected_seq:  # again under the lock (Q5)
                refusal = _refused(VersionConflict())
        if refusal is not None:
            return await self.deny(row, "amend", refusal, actor=actor, request_id=rid)
        named = {"qty": terms.qty, "price": terms.price, "trigger_price": terms.trigger_price}
        if sides:  # Q2: both sides re-paired, the unchanged one at its current value
            named |= {"stop_loss": sized.stop_loss, "take_profit": sized.take_profit}
        taken = {key: value for key, value in named.items() if value is not None}
        payload = {key: _text(value) for key, value in taken.items()}
        changed = ",".join(sorted(taken))
        detail = {"operation": "amend", "terms": changed, "order_link_id": row.order_link_id}
        if not await self._record(row, "orders.amend", "success", "user", detail, actor, rid):
            return _problem(503, "audit_unavailable", "The amend could not be recorded.")
        if self._closed:  # `aclose` ran while the intent was written: nothing starts
            return await self.deny(row, "amend", _CLOSED, actor=actor, request_id=rid)
        send = self._send(
            row, "amend", "AMEND", payload, actor=actor, request_id=rid,
            expected_seq=expected_seq, terms=taken,
        )  # fmt: skip
        return await self._shielded(send, "amend")

    async def _checked(
        self, row: OrderRow, terms: AmendTerms
    ) -> tuple[SizedOrder, Instrument, bool] | ExitOutcome:
        """The body (400), every rule that fails listed (22 `amendOrder`): Q3's and the quantity's,
        then, on the amended terms, the stop's and the take-profit's, and, once those hold so the
        order can be sized, the instrument's limits; `validation_failed` when rules of both kinds
        fail. Answers the amended order, sized as it would be sent, its instrument, and whether it
        names a TP/SL side."""
        figures = {"qty": terms.qty, "price": terms.price, "trigger_price": terms.trigger_price}
        sides = dict(terms.sides or {})
        if not sides and all(value is None for value in figures.values()):
            return _invalid("body", "nothing_to_amend", "Name at least one term to amend.")
        odd = [key for key, value in figures.items() if value is not None and not value.is_finite()]
        if odd:  # as `Validator.check_order` names it: never compared
            return _invalid(odd[0], "finite", "Each term amended is a finite number.")
        named = {side: None if offset is None else _NAMED for side, offset in sides.items()}
        rule = tpsl_scope_refusal(
            named, reduce_only=row.reduce_only, tpsl_mode=row.tpsl_mode, filled_qty=row.cum_exec_qty
        )
        errors: list[FieldError] = [] if rule is None else [_tpsl_error(rule, sides)]
        qty = row.qty if terms.qty is None else terms.qty
        if not qty > row.cum_exec_qty:
            errors.append(
                FieldError(
                    "qty",
                    "qty_not_above_filled",
                    "The quantity must stay above the filled quantity.",
                )
            )
        try:
            instrument = await self._bounded(self._d.instruments.instrument(row.symbol))
        except OmsError as exc:  # the catalogue not composed yet: `oms_not_ready`
            return _refused(exc) if isinstance(exc, OrderRefused) else _store()
        except _UNREAD:
            return _store()
        if instrument is None or instrument.symbol != row.symbol:
            unlisted = FieldError("symbol", "listed", "No instrument is listed under this symbol.")
            return _refused(OrderInvalid(errors=[*errors, unlisted]))
        price = row.price if terms.price is None else terms.price
        trigger = row.trigger_price if terms.trigger_price is None else terms.trigger_price
        reference = price if price is not None else trigger
        if reference is None:
            unpriced = FieldError("price", "required", "The order has no price to measure from.")
            return _refused(OrderInvalid(errors=[*errors, unpriced]))
        side, stop, take_profit = _SIDES[row.side], row.stop_loss, row.take_profit
        effect = OrderEffect.REDUCE if row.reduce_only else OrderEffect.ENTRY
        resolver = self._d.stop_resolver
        try:
            if (offset := sides.get("stop_loss")) is not None:
                stop = resolver.resolve(
                    offset, side=side, reference_price=reference, effect=effect,
                    instrument=instrument, profile=None,
                )  # fmt: skip
            if (offset := sides.get("take_profit")) is not None:
                take_profit = resolver.resolve_take_profit(
                    offset, side=side, reference_price=reference, instrument=instrument,
                    profile=None,
                )  # fmt: skip
        except OrderInvalid as exc:  # a unit the resolver cannot resolve
            errors.extend(exc.errors)
        sided = stop_errors(effect=effect, side=side, reference_price=reference, stop=stop)
        sided += take_profit_errors(side=side, reference_price=reference, take_profit=take_profit)
        if sided:  # no order `SizedOrder` holds (C-2.6): the instrument's limits not judged
            return _refused(OrderInvalid(errors=[*errors, *sided]))
        try:
            sized = SizedOrder(
                account_id=AccountId(row.exchange_account_id), environment=self._env,
                symbol=row.symbol, side=side, order_type=_TYPES[row.order_type], qty=qty,
                price=price, trigger_price=trigger, reference_price=reference,
                reduce_only=row.reduce_only, intent=row.intent, effect=effect, stop_loss=stop,
                take_profit=take_profit,
            )  # fmt: skip
        except ValueError:  # a figure `SizedOrder` itself refuses (a reference not above zero)
            unsized = FieldError("price", "min_price", "The amended terms are no order to send.")
            return _refused(OrderInvalid(errors=[*errors, unsized]))
        try:
            self._d.validator.check_terms(sized, instrument=instrument)
        except OrderRefused as exc:  # beside a rule above, both kinds: `validation_failed`
            if not errors:
                return _refused(exc)
            errors.extend(exc.errors)
        if errors:
            return _refused(OrderInvalid(errors=errors))
        return sized, instrument, bool(sides)

    async def _ratchet(self, row: OrderRow, stop: Decimal | None) -> ExitOutcome | None:
        """Q4's one ratchet on the stop the amend would send, before any record or send: against
        the order's stop and the key's records in force (Full mode, same side)."""
        if stop is None:
            return None
        live = self._d.stops.live_for_key(row.exchange_account_id, row.symbol, row.position_idx)
        try:
            in_force = await self._bounded(live)
        except _UNREAD:
            return _store()
        loose = ratchet_refusal(
            side=row.side, requested=stop, current=row.stop_loss, in_force=in_force
        )
        if loose is None:
            return None
        return _refused(
            RiskRefused(
                "A stop-loss may only be tightened: the owner loosens it on setPositionTpSl."
            )
        )

    async def _gated(
        self, scoped: ScopedOrder, sized: SizedOrder, instrument: Instrument
    ) -> ExitOutcome | None:
        """Ruling Q10 and D1, a risk-increasing amend: what `placeOrder` meets, in its order."""
        row = scoped.order
        if not self._d.oms_enabled():
            return _refused(TradingDisabled())
        switched = self._d.switches.refusal(AccountId(row.exchange_account_id), self._env)
        if switched is not None:
            return _refused(switched)
        profile: AccountProfile | None = None
        try:
            read = self._d.profiles.get_effective_profile(
                row.exchange_account_id, scoped.profile_id
            )
            profile = await self._bounded(read)
        except AccountNotFoundError:  # no profile allows it: the check refuses it (D11)
            profile = None
        except (ProfileUnavailableError, *_UNREAD):
            return _store()
        try:
            self._d.validator.check_order(sized, instrument=instrument, profile=profile)
        except OrderRefused as exc:
            return _refused(exc)
        if not self._d.risk_gate.check(sized, profile=profile).allowed:
            return _refused(RiskRefused())
        return None

    # --- the rest --------------------------------------------------------------------------------

    @property
    def _env(self) -> Environment:
        return self._d.environment

    async def _bounded[T](self, call: Coroutine[Any, Any, T]) -> T:
        async with asyncio.timeout(self._waits[2]):
            return await call

    async def _record(
        self,
        row: OrderRow,
        action: str,
        outcome: Literal["success", "failure", "denied"],
        reason: str,
        detail: Mapping[str, str | None],
        actor: SubmitActor,
        request_id: UUID | None,
        *,
        severity: Literal["info", "warning", "error"] = "info",
    ) -> bool:
        """One record about the order, naming the principal (C-2.9): True once durable."""
        return await self._write(RequestRecord(
            action, row.exchange_account_id, "order", row.id, outcome, severity, reason, actor,
            dict(detail), request_id,
        ))  # fmt: skip

    async def _rbac(self, account: UUID, order_id: UUID, reason: str, caller: ExitCaller) -> None:
        """A scope refusal's `rbac.denied`, best effort: its 403 or 404 stands (24 Sec.8.4)."""
        await self._write(RequestRecord(
            "rbac.denied", account, "order", order_id, "denied", "warning", reason, caller.actor,
            {"operation": "exit"}, caller.request_id,
        ))  # fmt: skip

    async def _write(self, record: RequestRecord) -> bool:
        """`record` written within the store's bound: False when it did not land, logged; its
        caller decides (a refusal answers 503, an outcome or a scope refusal stands)."""
        try:
            await self._bounded(self._d.audit.write(record))
        except Exception as exc:
            _log().error("oms_exit_unrecorded", action=record.action, failure=type(exc).__name__)
            return False
        return True


def _ok(answer: Mapping[str, Any] | None) -> bool:
    return answer is not None and answer.get("ok") is True


def _kind(operation: ExitOperation) -> ExitKind:
    """The B1 exit an operation commands: a cancel-all's is a cancel."""
    return "amend" if operation == "amend" else "cancel"


def _int(answer: Mapping[str, Any] | None, key: str) -> int | None:
    value = None if answer is None else answer.get(key)
    return value if type(value) is int else None


def _text(value: Decimal) -> str:
    """Canonical decimal text, as B1's `AMEND` schema takes money: no exponent, no trailing zero."""
    out = format(value, "f")
    return out.rstrip("0").rstrip(".") if "." in out else out


def _tpsl_error(rule: str, sides: Mapping[str, object]) -> FieldError:
    """Q3's rule, on the side it names: a clear's own, else the stop if named."""
    named = "stop_loss" if "stop_loss" in sides or not sides else "take_profit"
    field = {"native_stop_required": "stop_loss", "tpsl_clear_unsupported": "take_profit"}
    message = "The order takes no such take-profit or stop-loss change."
    return FieldError(field.get(rule, named), rule, message)


def _tpsl_refused(rule: str, sides: Mapping[str, object]) -> ExitOutcome:
    """Q3's refusal (`_tpsl_error`)."""
    return _refused(OrderInvalid(errors=(_tpsl_error(rule, sides),)))


def _taken_not(kind: ExitKind, error: BaseException) -> ExitOutcome:
    """A command the facade did not take, nothing sent: a stale `If-Match` (412), a state that
    moved under it (an amend's 422, a cancel's 409), a latched machine (409, CV-C63), or a step
    the store refused (503)."""
    if isinstance(error, VersionConflict):
        return _refused(error)
    if isinstance(error, OrderStepRefused):
        return _store()
    if kind == "amend" and not isinstance(error, DegradedLatchError):
        return _refused(OrderNotAmendable())
    return _CONFLICT


def _answered(kind: ExitKind, answer: Mapping[str, Any]) -> ExitOutcome:
    """The command port's refusal (24 Sec.8.4, rulings Q9, Q11; the 11:34Z ruling)."""
    code, retry = answer.get("error_code"), _int(answer, "retry_after_s")
    delay = max(1, retry or 1)
    if code == OmsErrorCode.RATE_BUDGET_EXCEEDED:
        return _refused(RateBudgetExceeded(retry_after_s=delay))
    if code == STORE_UNAVAILABLE:  # the one shared retry (the 11:34Z ruling), never the port's
        return _store()
    if code == ACCOUNT_UNAVAILABLE:
        return _ACCOUNT_UNAVAILABLE
    if code == STOP_REQUEST_IN_FLIGHT:
        return _refused(StopRequestPending(retry_after_s=delay))
    if code == STOP_LOOSENING_REFUSED or (kind == "cancel" and code == b01.NATIVE_STOP_REQUIRED):
        return _refused(RiskRefused())
    if code == ORDER_NOT_AMENDABLE:
        return _refused(OrderNotAmendable())
    rule = code.lower() if isinstance(code, str) else ""
    if rule in _TPSL_RULES:
        return _tpsl_refused(rule, {})
    ret = _int(answer, "exchange_ret_code")
    if code == OmsErrorCode.INSTRUMENT_FILTER and ret is None:  # terms B1 could not stage
        return _invalid("body", "staged", "The amended terms could not be read.")
    return _refused(ExchangeRejected(ret_code=ret))
