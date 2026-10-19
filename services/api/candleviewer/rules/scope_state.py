"""Production `ScopeState` (E35-S04): in-memory snapshot of grants/freeze/live-gate.

Reads are synchronous (the evaluator hot path never awaits); the snapshot per owner is
refreshed from a `ScopeSource` before each API authorization and on auth/account events
(`invalidate`). Fail closed: an owner never loaded has no grants and cannot arm live.
A grant's freeze is read per (owner, account): one owner's refresh never changes another's answer.
`exchange_accounts` (E27) does not exist yet, so an account's environment is the process
environment; E27/E34 replace `account()`/`live_gate_open` bodies, not the port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from candleviewer.rules.arming import LIVE_ARM_PERMISSION
from candleviewer.rules.scope import AccountState

#: The seeded RBAC code `rules:arm_live` (migration 0015) that `load_permissions` returns (#2624).
ARM_LIVE = LIVE_ARM_PERMISSION


@dataclass(frozen=True, slots=True)
class GrantRow:
    account_id: UUID
    can_view: bool
    frozen: bool


class ScopeSource(Protocol):
    async def load_grants(self, owner: UUID) -> list[tuple[UUID, bool, bool]]: ...
    async def load_permissions(self, owner: UUID) -> frozenset[str]: ...


class SnapshotScopeState:
    def __init__(
        self,
        source: ScopeSource,
        environment: str,
        live_gate_open: Callable[[], bool] = lambda: False,
    ) -> None:
        self._source = source
        self._env = environment
        self._live_gate = live_gate_open
        self._grants: dict[UUID, dict[UUID, GrantRow]] = {}
        self._perms: dict[UUID, frozenset[str]] = {}
        self._accounts: dict[UUID, AccountState] = {}  # account-level fields only, no freeze

    async def refresh(self, owner: UUID) -> None:
        rows = [GrantRow(*t) for t in await self._source.load_grants(owner) if t[1]]
        perms = await self._source.load_permissions(owner)
        # Load first, publish once: no await below, so a reader sees the old snapshot or the new.
        self._grants[owner] = {r.account_id: r for r in rows}
        self._perms[owner] = perms
        self._sync_accounts()

    def invalidate(self, owner: UUID) -> None:
        self._grants.pop(owner, None)
        self._perms.pop(owner, None)
        self._sync_accounts()

    def _sync_accounts(self) -> None:
        # An account stays while any loaded owner holds a live grant on it; a revoked one goes.
        self._accounts = {a: AccountState(self._env) for g in self._grants.values() for a in g}

    def granted_accounts(self, owner: UUID) -> frozenset[UUID]:
        return frozenset(self._grants.get(owner, {}))

    def account(self, owner: UUID, account_id: UUID) -> AccountState | None:
        """The account as `owner` sees it: the freeze is `owner`'s own grant flag; None while
        `owner` holds no live grant on the account."""
        row = self._grants.get(owner, {}).get(account_id)
        acct = self._accounts.get(account_id)
        return None if row is None or acct is None else replace(acct, frozen=row.frozen)

    def owner_frozen(self, owner: UUID) -> bool:
        g = self._grants.get(owner)
        return g is not None and bool(g) and all(r.frozen for r in g.values())

    def live_gate_open(self) -> bool:
        return self._live_gate()

    def can_arm_live(self, owner: UUID) -> bool:
        p = self._perms.get(owner, frozenset())
        return "*" in p or ARM_LIVE in p
