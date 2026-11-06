"""Production `ScopeState` (E35-S04): in-memory snapshot of grants/freeze/live-gate.

Reads are synchronous (the evaluator hot path never awaits); the snapshot per owner is
refreshed from a `ScopeSource` before each API authorization and on auth/account events
(`invalidate`). Fail closed: an owner never loaded has no grants and cannot arm live.
A grant's freeze is read per (owner, account): one owner's refresh never changes another's answer.
Each granted account's own environment is read with the grants, from `exchange_accounts.env`
(E35-T10, BQ-3): an account whose environment was not read has none, which the action re-check
refuses (`environment`, fail closed). E34 replaces the `live_gate_open` body, not the port.
A refresh publishes only if no `invalidate` of the owner ran while it read: a grant revoked
meanwhile never comes back with a read that started before it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
    async def load_account_environments(self, account_ids: Sequence[UUID]) -> Mapping[UUID, str]:
        """Each live account's `exchange_accounts.env`; an account it does not name is unread."""


class SnapshotScopeState:
    def __init__(
        self, source: ScopeSource, live_gate_open: Callable[[], bool] = lambda: False
    ) -> None:
        self._source = source
        self._live_gate = live_gate_open
        self._generation: dict[UUID, int] = {}  # per owner: bumped by each `invalidate`
        self._grants: dict[UUID, dict[UUID, GrantRow]] = {}
        self._perms: dict[UUID, frozenset[str]] = {}
        self._accounts: dict[UUID, AccountState] = {}  # account-level fields only, no freeze
        self._envs: dict[UUID, str | None] = {}  # each granted account's environment, as read

    async def refresh(self, owner: UUID) -> None:
        generation = self._generation.get(owner, 0)
        rows = [GrantRow(*t) for t in await self._source.load_grants(owner) if t[1]]
        perms = await self._source.load_permissions(owner)
        ids = [r.account_id for r in rows]
        envs = await self._source.load_account_environments(ids) if ids else {}
        if self._generation.get(owner, 0) != generation:
            return  # invalidated while it read: the next refresh reads again
        # Load first, publish once: no await below, so a reader sees the old snapshot or the new.
        self._grants[owner] = {r.account_id: r for r in rows}
        self._perms[owner] = perms
        self._envs.update({a: envs.get(a) for a in ids})
        self._sync_accounts()

    def invalidate(self, owner: UUID) -> None:
        self._generation[owner] = self._generation.get(owner, 0) + 1
        self._grants.pop(owner, None)
        self._perms.pop(owner, None)
        self._sync_accounts()

    def _sync_accounts(self) -> None:
        # An account stays while any loaded owner holds a live grant on it; a revoked one goes.
        self._accounts = {
            a: AccountState(self._envs.get(a)) for g in self._grants.values() for a in g
        }

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
