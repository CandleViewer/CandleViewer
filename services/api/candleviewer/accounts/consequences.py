"""The consequence read: what revoking an account's last signable key, disabling it or deleting it
would affect (E27-S04 B2b, #898; 22 `getAccountConsequences`, `AccountConsequenceSummary`,
SR-E27-07, SCR-129).

One server-side aggregate, so no partial picture is shown: the account, then at once its keys
(and with them the exposure read, `accounts.exposure`), its grantees, the armed rules that cover
it and its running algos. SCR-129 fetches it before its dialog renders, within 1 s
(`REQUEST_BUDGET_S`): each store read is bounded by `STORE_BOUND_S`, and the exposure read gets
what is left of the budget, at most `READ_DEADLINE_S`. A store read that is slow or fails fails
the whole read (`StoreReadFailed`, or the store's own error), never a summary with a gap; an
exposure that is unknown or failed to read is answered as 22's `OpenExposure` decides it.

An M13 module (C-3.1): the armed rules and the running algos come through ports the composition
root binds (`exposure_wiring`). The armed rules are those the profile delete's guard reads
(`ArmedRules.covering`: every armed rule whose active version lists the account or lists none,
ruling 10), one predicate, so the disarm that follows the confirm acts on the list shown.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Final, Literal, Protocol
from uuid import UUID, uuid5

from candleviewer.accounts.errors import (
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.exposure import (
    REQUEST_BUDGET_S,
    ExchangePosition,
    ExposureFailed,
    ExposureKnown,
    ExposureOutcome,
    ExposureUnknown,
)
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount
from candleviewer.accounts.profile_repository import ArmedRule, ArmedRules
from candleviewer.observability import spawn_child
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope

__all__ = [
    "ARMED_LISTED",
    "POSITION_NAMESPACE",
    "STORE_BOUND_S",
    "AccountConsequences",
    "AssignedUser",
    "ConsequenceRead",
    "ConsequenceStores",
    "RunningAlgos",
    "StoreReadFailed",
    "position_id",
]

#: Each store read's bound inside the 1 s budget (ruling 11).
STORE_BOUND_S: Final = 0.25
#: The armed rules listed at most; one more fails the read closed (no partial list, C-2.18).
ARMED_LISTED: Final = 1000
#: `Position.id` here is derived, never stored: UUIDv5 of (account, symbol, `position_idx`) in
#: this fixed namespace (24 §8.1).
POSITION_NAMESPACE: Final = UUID("6f1c2a52-8e1b-5f0e-9a43-0c9e8d0b7a31")


@dataclass(frozen=True, slots=True)
class AssignedUser:
    """A user granted the account (`user_account_access`): `trade` or `read`."""

    user_id: UUID
    username: str
    level: Literal["read", "trade"]


@dataclass(frozen=True, slots=True)
class AccountConsequences:
    """22 `AccountConsequenceSummary`, in M13's words: the open positions only (size above
    zero), each with its native stop-loss state (`ExchangePosition.native_stop_present`)."""

    account_id: UUID
    open_positions: tuple[ExchangePosition, ...]
    working_orders: int
    running_algos: int
    assigned_users: tuple[AssignedUser, ...]
    armed_rules: tuple[ArmedRule, ...]


class StoreReadFailed(AccountsError):
    """A store read hit its bound, or the armed rules overflowed the listing: `503
    store_unavailable` (fail closed)."""


class ConsequenceStores(Protocol):
    """`AccountsRepository`'s reads here."""

    async def get_account(self, scope: AccountScope, account_id: UUID) -> ExchangeAccount: ...
    async def list_keys(
        self, scope: OwnerScope, account_id: UUID
    ) -> tuple[ApiKeyMetadata, ...]: ...
    async def list_grantees(
        self, scope: OwnerScope, account_id: UUID
    ) -> tuple[AssignedUser, ...]: ...


class RunningAlgos(Protocol):
    """The emulated algos still running on an account."""

    async def running(self, account_id: UUID) -> int: ...


class ExposureReading(Protocol):
    """`accounts.exposure.ExposureRead`."""

    async def read(
        self,
        account: ExchangeAccount,
        keys: Sequence[ApiKeyMetadata],
        *,
        within_s: float | None = None,
    ) -> ExposureOutcome: ...


def position_id(account_id: UUID, position: ExchangePosition) -> UUID:
    """The position's id in the summary: stable for its (account, symbol, `position_idx`)."""
    return uuid5(POSITION_NAMESPACE, f"{account_id}:{position.symbol}:{position.position_idx}")


def _first(group: BaseExceptionGroup[Exception]) -> Exception:
    """The error the read raises for a failed group: the store's owner gate first (a 403),
    then the first other one."""
    leaves: list[Exception] = []
    pending: list[BaseException] = [group]
    while pending:
        one = pending.pop(0)
        if isinstance(one, BaseExceptionGroup):
            pending[:0] = list(one.exceptions)
        elif isinstance(one, Exception):
            leaves.append(one)
    denied = [one for one in leaves if isinstance(one, AccountScopeDeniedError)]
    return (denied or leaves)[0]


class ConsequenceRead:
    """Reads an account's consequence summary for the process's environment (C-2.11)."""

    def __init__(
        self,
        stores: ConsequenceStores,
        exposure: ExposureReading,
        rules: ArmedRules,
        algos: RunningAlgos,
        *,
        env: str,
        budget_s: float = REQUEST_BUDGET_S,
        store_bound_s: float = STORE_BOUND_S,
        clock: Callable[[], float] = time.monotonic,
        deadline: Callable[[float], AbstractAsyncContextManager[object]] = asyncio.timeout,
    ) -> None:
        if not 0 < store_bound_s < budget_s:
            raise ValueError("a store bound inside the budget")
        self._stores, self._exposure, self._rules, self._algos = stores, exposure, rules, algos
        self._env, self._budget_s, self._bound_s = env, budget_s, store_bound_s
        self._clock, self._deadline = clock, deadline

    async def _bounded[T](self, read: Callable[[], Awaitable[T]]) -> T:
        try:
            async with self._deadline(self._bound_s):
                return await read()
        except TimeoutError:
            raise StoreReadFailed("a store read hit its bound") from None

    async def _exposure_of(
        self, account: ExchangeAccount, owner: OwnerScope, started: float
    ) -> ExposureOutcome:
        keys = await self._bounded(lambda: self._stores.list_keys(owner, account.id))
        left = self._budget_s - (self._clock() - started)
        return await self._exposure.read(account, keys, within_s=left)

    async def _armed(self, account_id: UUID) -> tuple[ArmedRule, ...]:
        listed = await self._rules.covering(account_id, limit=ARMED_LISTED + 1)
        if len(listed) > ARMED_LISTED:
            raise StoreReadFailed("more armed rules than the summary lists")
        return listed

    async def read(
        self, scope: AccountScope, owner: OwnerScope, account_id: UUID
    ) -> AccountConsequences | ExposureUnknown | ExposureFailed:
        """The summary of `account_id` read in the caller's `scope` (its keys and grantees in
        `owner`, the owner-only reads). Raises `AccountNotFoundError` for an account absent,
        foreign or of another environment (one answer), `AccountScopeDeniedError` when the
        store's owner gate refuses, `StoreReadFailed` or the store's error for an outage.
        Cancellation propagates."""
        started = self._clock()
        account = await self._bounded(lambda: self._stores.get_account(scope, account_id))
        if account.env.value != self._env:
            raise AccountNotFoundError("account")
        try:
            async with asyncio.TaskGroup() as group:
                exposure = spawn_child(
                    group, self._exposure_of(account, owner, started), name="consequence-exposure"
                )
                users = spawn_child(
                    group,
                    self._bounded(lambda: self._stores.list_grantees(owner, account.id)),
                    name="consequence-grantees",
                )
                rules = spawn_child(
                    group, self._bounded(lambda: self._armed(account.id)), name="consequence-rules"
                )
                algos = spawn_child(
                    group,
                    self._bounded(lambda: self._algos.running(account.id)),
                    name="consequence-algos",
                )
        except ExceptionGroup as failed:
            raise _first(failed) from None
        read = exposure.result()
        if not isinstance(read, ExposureKnown):
            return read
        return AccountConsequences(
            account_id=account.id,
            open_positions=tuple(p for p in read.positions if p.size > 0),
            working_orders=read.working_orders,
            running_algos=algos.result(),
            assigned_users=users.result(),
            armed_rules=rules.result(),
        )
