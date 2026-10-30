"""A position's leverage change (E29-T07 #915; 22 `setPositionLeverage`, 24 Sec.15.5).

`PositionLeverage.apply(request, actor=..., request_id=...)` takes one change the route has
admitted (the principal, RBAC, the position in the caller's scope with a trade grant, the arm
token, the key and the flag) and runs on the order lane, where the trading port lives. Each step
refuses before the next, nothing sent:

1. the synchronous switches (C-2.21: live trading enabled, the B18 kill switch, the order-entry
   gate), `TradingSwitches.refusal`, as every write consults them before a send;
2. the account the change is signed for, by its id alone (`TradingAccounts`, SR-E27-21), of this
   process's environment (C-2.11), and the symbol's instrument;
3. the bounds, server-side (C-12.5): finite and above zero, at least the instrument's minimum, at
   most its maximum, on its leverage step, and at most the account's effective profile's
   `max_leverage_cap` when the profile names one. An account with no default profile is bounded
   by the instrument alone (the coordinator's ruling of 2026-10-29); a profile that cannot be read
   refuses the change (503 `store_unavailable`), never drops its cap (SR-E28-24). A value outside
   them is `LeverageOutOfBounds`, every rule it breaks named (22 `UnprocessableEntity`);
4. the write-ahead record, `position.leverage_changed` with reason `requested`, the leverage before
   and after, made durable before the call (C-2.9); one that does not land is 503
   `audit_unavailable`, nothing sent;
5. the venue's call, within `call_timeout_s`. The venue's "not modified" answer (the value it
   already holds; the adapters' `leverage_not_modified` filter) is the change done, idempotently
   (ruling BQ-8). A rate refusal is 429 `exchange_rate_limited`, a call that did not answer in time
   or a transport failure 503 `exchange_unavailable` (a repeat is safe: a leverage is a level, not
   a delta), and any other refusal 502 `exchange_error` with the venue's return code only
   (SR-E29-09). The outcome's record follows, best effort: the intent is already durable.

Every refusal from step 1 on is recorded (`position.leverage_changed`, outcome `denied`, its
problem code) before it is raised; one whose record does not land is 503 `audit_unavailable`
instead. Logs carry ids and codes, never the key or a token (C-12.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.errors import (
    ExchangeError,
    InstrumentFilterError,
    RateBudgetExceededError,
    RateLimitError,
    TransportError,
)
from candleviewer.exchange.base.models import AccountRef
from candleviewer.oms.errors import (
    AuditNotDurable,
    EnvironmentMismatch,
    ExchangeRejected,
    ExchangeUnavailable,
    FieldError,
    OmsError,
    OmsNotReady,
    OrderInvalid,
    RateBudgetExceeded,
    StoreUnavailable,
    problem_for,
)
from candleviewer.oms.ports import (
    AuditOutcome,
    Instruments,
    Profiles,
    RequestRecord,
    SubmitActor,
    SubmitAudit,
    TradingAccounts,
    TradingSwitches,
)
from candleviewer.storage.errors import StorageError

__all__ = [
    "LEVERAGE_ACTION",
    "LeverageOutOfBounds",
    "LeverageOutcome",
    "LeverageRequest",
    "PositionLeverage",
]

#: The record of every change and refusal (24 Sec.15.5; ruling BQ-5).
LEVERAGE_ACTION: Final = "position.leverage_changed"
#: The adapters' name for the venue's answer to a value it already holds.
NOT_MODIFIED: Final = "leverage_not_modified"
#: The `Retry-After` of a call that did not answer, or a rate refusal with no hint of its own.
RETRY_AFTER_S: Final = 1
_CALL_TIMEOUT_S: Final = 10.0
_STORE_TIMEOUT_S: Final = 5.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class LeverageOutOfBounds(OrderInvalid):
    """The leverage asked for breaks a bound (step 3): `errors` names each rule broken
    (`range`, `min_leverage`, `max_leverage`, `leverage_step`, `max_leverage_cap`). Its code is
    `OrderInvalid`'s, `validation_failed`; the route answers it 422, as 22 declares for this
    operation and as the profile writes answer an exchange limit, not the order routes' 400."""

    default_detail = "The leverage is outside the bounds allowed for this position."

    def __init__(self, errors: tuple[FieldError, ...]) -> None:
        detail = errors[0].message if len(errors) == 1 else f"{len(errors)} bounds are broken."
        super().__init__(detail, errors=errors)


class RoutedLeverage(Protocol):
    """The trading port's leverage call, as the environment's routed port offers it."""

    async def set_leverage(
        self, account: AccountRef, symbol: Symbol, leverage: Decimal
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class LeverageRequest:
    """One admitted change: the position the route read in scope, its account and symbol, the
    leverage the row holds now (`before`, None when the venue has pushed none) and the one asked
    for (`leverage`, a `Decimal`, never a float)."""

    position_id: UUID
    account_id: AccountId
    symbol: Symbol
    before: Decimal | None
    leverage: Decimal


@dataclass(frozen=True, slots=True)
class LeverageOutcome:
    """The leverage the venue holds once the change is done; `changed` False when it held it."""

    leverage: Decimal
    changed: bool


@dataclass(frozen=True, slots=True)
class LeverageDeps:
    """The service's collaborators, each the instance the pipeline was built with."""

    accounts: TradingAccounts
    instruments: Instruments
    profiles: Profiles
    ports: Callable[[Environment], RoutedLeverage]
    switches: TradingSwitches
    audit: SubmitAudit
    environment: Environment


def bounds_errors(
    leverage: Decimal, instrument: Instrument, profile: AccountProfile | None
) -> tuple[FieldError, ...]:
    """Step 3's rules, each one that `leverage` breaks (module docstring)."""
    if not leverage.is_finite() or leverage <= 0:
        return (FieldError("leverage", "range", "Send a leverage above zero."),)
    errors: list[FieldError] = []
    low, high, step = instrument.min_leverage, instrument.max_leverage, instrument.leverage_step
    if leverage < low:
        errors.append(FieldError(
            "leverage", "min_leverage", f"{instrument.symbol} allows at least {low:f}x."
        ))  # fmt: skip
    if leverage > high:
        errors.append(FieldError(
            "leverage", "max_leverage", f"{instrument.symbol} allows at most {high:f}x."
        ))  # fmt: skip
    if step > 0 and not _on_step(leverage, step):
        errors.append(FieldError(
            "leverage", "leverage_step", f"Send a leverage in steps of {step:f}."
        ))  # fmt: skip
    cap = None if profile is None else profile.max_leverage_cap
    if cap is not None and leverage > cap:
        errors.append(FieldError(
            "leverage", "max_leverage_cap", f"The account's profile allows at most {cap:f}x."
        ))  # fmt: skip
    return tuple(errors)


def _on_step(value: Decimal, step: Decimal) -> bool:
    try:
        return value % step == 0
    except InvalidOperation:  # a quotient no context can hold: not on any step
        return False


class PositionLeverage:
    """Step 1 to 5 of a leverage change (module docstring), on the order lane."""

    def __init__(
        self,
        deps: LeverageDeps,
        *,
        call_timeout_s: float = _CALL_TIMEOUT_S,
        store_timeout_s: float = _STORE_TIMEOUT_S,
    ) -> None:
        if call_timeout_s <= 0 or store_timeout_s <= 0:
            raise ValueError("every bound is above zero")
        self._deps = deps
        self._call_timeout_s, self._store_timeout_s = call_timeout_s, store_timeout_s

    async def apply(
        self, request: LeverageRequest, *, actor: SubmitActor, request_id: UUID | None
    ) -> LeverageOutcome:
        """The change done, or its refusal raised once recorded (module docstring)."""
        step = "switches"
        try:
            deps = self._deps
            switched = deps.switches.refusal(request.account_id, deps.environment)
            if switched is not None:
                raise switched
            step = "resolve"
            account = await self._account(request.account_id)
            instrument = await self._instrument(request.symbol)
            profile = await self._profile(request.account_id)
            step = "bounds"
            errors = bounds_errors(request.leverage, instrument, profile)
            if errors:
                raise LeverageOutOfBounds(errors)
        except OmsNotReady:  # order entry not open yet: counted by the route, never recorded
            raise
        except OmsError as refusal:
            await self._refused(request, refusal, step, actor, request_id)
            raise
        await self._write_ahead(request, actor, request_id)
        try:
            changed = await self._call(account, request)
        except OmsError as refusal:
            await self._record(request, actor, request_id, "failure", problem_for(refusal).code)
            raise
        await self._record(
            request, actor, request_id, "success", "applied" if changed else "not_modified"
        )
        return LeverageOutcome(request.leverage, changed)

    async def _account(self, account_id: AccountId) -> AccountRef:
        try:
            async with asyncio.timeout(self._store_timeout_s):
                account = await self._deps.accounts.trading_account(account_id)
        except (TimeoutError, StorageError) as exc:
            _log().warning("oms_leverage_account_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None
        if account.account_id != account_id:
            raise ValueError("the trading account resolved is another account's")
        if account.environment != self._deps.environment:  # C-2.11: never signed for another
            raise EnvironmentMismatch(
                order_environment=account.environment, route_environment=self._deps.environment
            )
        return account

    async def _instrument(self, symbol: Symbol) -> Instrument:
        """The symbol's instrument; none listed, or a catalogue that does not answer, refuses the
        change: no bound can be judged without it (fail closed)."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                instrument = await self._deps.instruments.instrument(symbol)
        except TimeoutError:
            instrument = None
        if instrument is None or instrument.symbol != symbol:
            _log().warning("oms_leverage_instrument_unread", symbol=symbol)
            raise StoreUnavailable("The instrument's limits cannot be read, so nothing changed.")
        return instrument

    async def _profile(self, account_id: AccountId) -> AccountProfile | None:
        """The account's effective profile, None when it has no default (the instrument alone
        bounds it); a profile that cannot be read refuses the change (SR-E28-24)."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                return await self._deps.profiles.get_effective_profile(account_id, None)
        except AccountNotFoundError:
            return None
        except (TimeoutError, ProfileUnavailableError, StorageError) as exc:
            _log().warning("oms_leverage_profile_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None

    async def _call(self, account: AccountRef, request: LeverageRequest) -> bool:
        """Step 5: True once the venue took the change, False when it held the value already."""
        port = self._deps.ports(account.environment)
        try:
            async with asyncio.timeout(self._call_timeout_s):
                await port.set_leverage(account, request.symbol, request.leverage)
        except InstrumentFilterError as exc:
            if exc.filter_name == NOT_MODIFIED:
                return False
            raise ExchangeRejected(ret_code=exc.exchange_ret_code) from None
        except (RateLimitError, RateBudgetExceededError) as exc:
            raise RateBudgetExceeded(retry_after_s=_wait(exc.retry_after_s)) from None
        except (TimeoutError, TransportError) as exc:
            _log().warning(
                "oms_leverage_unanswered", account_id=str(account.account_id),
                failure=type(exc).__name__,
            )  # fmt: skip
            raise ExchangeUnavailable(retry_after_s=RETRY_AFTER_S) from None
        except ExchangeError as exc:
            raise ExchangeRejected(ret_code=exc.exchange_ret_code) from None
        return True

    async def _write_ahead(
        self, request: LeverageRequest, actor: SubmitActor, request_id: UUID | None
    ) -> None:
        """Step 4: the intent, durable before the call, else 503 and nothing sent."""
        try:
            await self._write(self._record_of(request, actor, request_id, "success", "requested"))
        except Exception as exc:  # nothing is sent unrecorded
            _log().error("oms_leverage_unrecorded", step="ahead", failure=type(exc).__name__)
            raise AuditNotDurable("the change's record did not land") from None

    async def _record(
        self, request: LeverageRequest, actor: SubmitActor, request_id: UUID | None,
        outcome: AuditOutcome, reason: str,
    ) -> None:  # fmt: skip
        """The outcome's record, best effort: the intent is already durable (step 4)."""
        try:
            await self._write(self._record_of(request, actor, request_id, outcome, reason))
        except Exception as exc:  # never the answer
            _log().error("oms_leverage_outcome_unrecorded", failure=type(exc).__name__)

    async def _refused(
        self, request: LeverageRequest, refusal: OmsError, step: str, actor: SubmitActor,
        request_id: UUID | None,
    ) -> None:  # fmt: skip
        """A refusal's record before it is answered; one that does not land is 503 instead."""
        code = problem_for(refusal).code
        record = self._record_of(request, actor, request_id, "denied", code, step=step)
        try:
            await self._write(record)
        except Exception as exc:  # no refusal is answered unrecorded
            _log().error("oms_leverage_unrecorded", step=step, failure=type(exc).__name__)
            raise AuditNotDurable("the refusal's record did not land") from None

    async def _write(self, record: RequestRecord) -> None:
        async with asyncio.timeout(self._store_timeout_s):
            await self._deps.audit.write(record)

    def _record_of(
        self, request: LeverageRequest, actor: SubmitActor, request_id: UUID | None,
        outcome: AuditOutcome, reason: str, *, step: str | None = None,
    ) -> RequestRecord:  # fmt: skip
        detail: Mapping[str, str | None] = {
            "position_id": str(request.position_id), "symbol": request.symbol,
            "leverage_before": None if request.before is None else format(request.before, "f"),
            "leverage_after": format(request.leverage, "f"),
            "environment": self._deps.environment, "step": step,
        }  # fmt: skip
        failed = outcome != "success"
        return RequestRecord(
            LEVERAGE_ACTION, request.account_id, "position", request.position_id,
            outcome, "warning" if failed else "info", reason, actor, detail, request_id,
        )  # fmt: skip


def _wait(hint: float | None) -> int:
    """A rate refusal's `Retry-After`: its own hint rounded up, else `RETRY_AFTER_S`."""
    if hint is None or hint <= 0:
        return RETRY_AFTER_S
    return max(RETRY_AFTER_S, int(-(-hint // 1)))
