"""Check 5's principal reads, bound at the composition root (E35-T11 slice 3b; 24 §11.5 "The
principal"; the E35 threat model's RE-S1, RE-E1, RE-E3 and RE-E6; E35-FR-01).

`rules` imports neither `auth` nor `storage` (`forbidden-M15`), so the executor's `PrincipalReads`
is bound here. `RulePrincipals` serves each user's `PrincipalView` from memory, synchronously, and
its refresh task, which the rules service starts with the evaluator and stops with it, reads them
again every `PRINCIPAL_REFRESH_S` (250 ms: BQ-6 as ruled, well inside the executor's one-second
age bound, `gates.PRINCIPAL_MAX_AGE_S`) for the users the service names: the owners and the
armers of the rules it evaluates. A user is read by id, never from a session (E35-FR-01): the
identity read (`identity_snapshot`: active, a system role, its permissions) and the trade grants
(`load_trade_grants`), each user within `PRINCIPAL_READ_TIMEOUT_S`, the reads side by side. The
accounts a view admits are the order route's own decision (`decide(orders:write,
GRANTED_ACCOUNTS, requires_trade=True)`, 24 §8.4) over the process's environment: every account of
it for an Owner, only the granted ones for anyone else, a view-only or frozen grant none.

It fails closed. A user who cannot act (not active, deleted, a role outside the system set) is an
inactive view at once. A read that fails or runs past its bound leaves the user's last view, which
ages past the bound and is refused (`permission`); so does a cycle whose environment read fails,
for every user. A task that ends other than by `stop()` is logged CRITICAL and paged once, and
every view then ages out. Nothing here logs a grant or an account: ids and error classes only.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import replace
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.api.audit_principal import identity_snapshot
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import AccountGrant, Allow, PrincipalSnapshot, decide
from candleviewer.observability import spawn
from candleviewer.rules.executor.ports import PrincipalView

#: How often the views are read again (BQ-6 as ruled): well inside the one-second age bound, so a
#: view is refused only when its reads fail or run late, never between two refreshes.
PRINCIPAL_REFRESH_S: Final = 0.25
#: Each user's reads, together (and the environment's accounts), at most this long.
PRINCIPAL_READ_TIMEOUT_S: Final = 2.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Identity(Protocol):
    """The identity read by user id (`SqlAlchemyIdentityProvider`), as `identity_snapshot` reads
    it: a user the store does not hold raises `LookupError`."""

    async def user(self, user_id: str) -> dict[str, Any]: ...

    async def session_info(self, user_id: str) -> dict[str, Any]: ...


class _Grants(Protocol):
    """`SqlAlchemyScopeSource`'s two reads: a user's trade grants, and an environment's accounts."""

    async def load_trade_grants(self, user_id: UUID) -> list[tuple[UUID, bool, bool, bool]]: ...

    async def load_environment_accounts(self, environment: str) -> frozenset[UUID]: ...


class PrincipalSource(Protocol):
    """What a refresh reads: a user's snapshot by id, its trade grants with it (an Owner's are
    every account, so none are read), `None` for a user who cannot act and `LookupError` for one
    the store does not hold; and the accounts of the process's environment."""

    async def snapshot(self, user_id: UUID) -> PrincipalSnapshot | None: ...

    async def live_accounts(self) -> frozenset[UUID]: ...


class IdentityPrincipalSource:
    """`PrincipalSource` over the identity read and the scope source's grant reads, the order
    route's own (`order_principal.SessionTradingPrincipalResolver._granted`), by user id."""

    def __init__(self, identity: _Identity, grants: _Grants, environment: str) -> None:
        self._identity, self._grants, self._environment = identity, grants, environment

    async def snapshot(self, user_id: UUID) -> PrincipalSnapshot | None:
        snapshot = await identity_snapshot(self._identity, user_id)
        if snapshot is None or snapshot.is_owner:
            return snapshot
        rows = await self._grants.load_trade_grants(user_id)
        return replace(snapshot, account_grants=tuple(AccountGrant(*row) for row in rows))

    async def live_accounts(self) -> frozenset[UUID]:
        return await self._grants.load_environment_accounts(self._environment)


def principal_view(
    user_id: UUID,
    snapshot: PrincipalSnapshot | None,
    accounts: Collection[UUID],
    read_at: float,
) -> PrincipalView:
    """The executor's view of one user (24 §11.5): inactive for a user who cannot act; else its
    role, whether it is the Owner role, and the accounts of `accounts` (the environment's) the
    order route's decision admits with `requires_trade`, read at `read_at`."""
    if snapshot is None:
        return PrincipalView(
            user_id=user_id, active=False, role=None, is_owner=False, trade_accounts=frozenset(),
            read_at=read_at,
        )  # fmt: skip
    admitted = frozenset(
        account for account in accounts
        if isinstance(
            decide(snapshot, Permission.ORDERS_WRITE, scope=Scope.GRANTED_ACCOUNTS,
                   exchange_account_id=account, requires_trade=True),
            Allow,
        )
    )  # fmt: skip
    role = "owner" if snapshot.is_owner else min(snapshot.roles, default=None)
    return PrincipalView(
        user_id=user_id, active=True, role=role, is_owner=snapshot.is_owner,
        trade_accounts=admitted, read_at=read_at,
    )  # fmt: skip


class RulePrincipals:
    """`PrincipalReads` from memory, and the task that refreshes it (module docstring)."""

    def __init__(
        self,
        source: PrincipalSource,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        refresh_s: float = PRINCIPAL_REFRESH_S,
        read_timeout_s: float = PRINCIPAL_READ_TIMEOUT_S,
    ) -> None:
        self._source, self._clock, self._sleep = source, clock, sleep
        self._refresh_s, self._read_timeout_s = refresh_s, read_timeout_s
        self._views: dict[UUID, PrincipalView] = {}
        self._task: asyncio.Task[None] | None = None
        self._unread: set[UUID | None] = set()  # warned about, until its read answers again

    def principal(self, user_id: UUID) -> PrincipalView | None:
        """The user's view as last read; `None` before its first read. Never awaits."""
        return self._views.get(user_id)

    def start(self, users: Callable[[], Collection[UUID]]) -> None:
        """Spawn the refresh task, reading `users()` at each cycle; once until `stop()`."""
        if self._task is None:
            self._task = spawn(self._run(users), name="rule-principals")
            self._task.add_done_callback(self._ended)

    async def stop(self) -> None:
        """End the task, its reads with it, and forget every view."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        self._views.clear()

    async def refresh(self, users: Collection[UUID]) -> None:
        """One cycle: the environment's accounts, then every user's reads side by side, each view
        stamped with the cycle's start; a user no longer named is forgotten."""
        named = frozenset(users)
        started = self._clock()
        try:
            async with asyncio.timeout(self._read_timeout_s):
                accounts = await self._source.live_accounts()
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            self._lost(None, exc)
        else:
            self._unread.discard(None)
            order: Sequence[UUID] = sorted(named, key=str)
            reads = await asyncio.gather(*(self._read(user) for user in order))
            for user, (answered, snapshot) in zip(order, reads, strict=True):
                if answered:  # else the last view stays, to age out
                    self._views[user] = principal_view(user, snapshot, accounts, started)
        for gone in [user for user in self._views if user not in named]:
            del self._views[gone]

    async def _read(self, user: UUID) -> tuple[bool, PrincipalSnapshot | None]:
        """Whether the user's reads answered, and its snapshot: `None` for one who cannot act or
        the store does not hold; a read that failed or ran past its bound answers nothing."""
        try:
            async with asyncio.timeout(self._read_timeout_s):
                snapshot = await self._source.snapshot(user)
        except LookupError:  # no such user: none can act for it
            snapshot = None
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            self._lost(user, exc)
            return False, None
        self._unread.discard(user)
        return True, snapshot

    def _lost(self, user: UUID | None, exc: Exception) -> None:
        """A read that did not answer: warned once until it answers again, by its class alone."""
        if user not in self._unread:
            self._unread.add(user)
            who = "environment" if user is None else str(user)
            _log().warning("rules.principal_unread", user=who, error=type(exc).__name__)

    async def _run(self, users: Callable[[], Collection[UUID]]) -> None:
        while True:
            started = self._clock()
            await self.refresh(users())
            await self._sleep(max(0.0, self._refresh_s - (self._clock() - started)))

    def _ended(self, task: asyncio.Task[None]) -> None:
        """Only `stop()` ends the task, and it lets go of it first: any other end leaves every view
        to age out, so it pages once, by the error's class alone."""
        error = None if task.cancelled() else task.exception()
        if task is self._task:
            name = None if error is None else type(error).__name__
            _log().critical("rules.principals_ended", cv_page=True, error=name)
