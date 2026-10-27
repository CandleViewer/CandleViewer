"""Driver-free port for trade-group definitions and their members (E28-T05 #909; M10; 21
Sec.3.3.3a). Stdlib only, as its sibling `trade_groups`.

`DefinitionStore` is the Owner's write surface (SR-E28-31): a write passes the live-owner gate
first and awaits its write-ahead record before the commit (C-2.9); `replace` and `soft_delete`
lock the live row first, so a soft-deleted definition takes no member (SEC-2-03, 21 Sec.3.3.3a).
`DefinitionReads` is SR-E28-21 in SQL: an Owner sees every live definition, a grant one with a
member and whose every member account it sees, with all its members or not at all. An error
carries a constraint or rule name, never a value (C-12.6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope
from candleviewer.storage.repositories.trade_groups import ExchangeEnv

#: Unique refusals: a name a live definition holds in any letter case, and the primary key.
DEFINITION_CONFLICTS: Final = frozenset({"ux_tgd_name", "trade_group_definitions_pkey"})
#: The name's CHECK, the write-once and member-environment triggers, a member's account FK.
DEFINITION_RULES: Final = frozenset(
    {"tgd_name", "trg_tgd_write_once", "trg_tgdm_env",
     "trade_group_definition_members_exchange_account_id_fkey"}
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class DefinitionRow:
    """A live definition: every column but `deleted_at`, in table order."""

    id: UUID
    name: str
    env: ExchangeEnv
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemberRow:
    """A member with its account's `env` and `is_enabled`, read in the same statement."""

    exchange_account_id: UUID
    enabled: bool
    account_env: ExchangeEnv
    account_enabled: bool


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    definition: DefinitionRow
    members: tuple[MemberRow, ...]  # by account id


@dataclass(frozen=True, slots=True)
class NewMember:
    exchange_account_id: UUID
    enabled: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class NewDefinition:
    """What `create` inserts and `replace` sets; the writer stored is the scope's Owner."""

    id: UUID
    name: str
    env: ExchangeEnv
    members: tuple[NewMember, ...]


#: Awaited in the write's transaction before its commit with the record before and after (`None`
#: before a create, after a delete); if it raises or outlasts its bound, nothing is written.
DefinitionWriteAhead = Callable[[DefinitionRecord | None, DefinitionRecord | None], Awaitable[None]]


class DefinitionStoreError(Exception):
    """Base of the store's errors; none carries a value."""


class DefinitionScopeDeniedError(DefinitionStoreError):
    """The scope is not a live Owner's (a uniform 403)."""


class DefinitionStaleError(DefinitionStoreError):
    """The row's `updated_at` is not `expected_updated_at`; nothing was written."""


class DefinitionConflictError(DefinitionStoreError):
    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.constraint = constraint


class DefinitionRuleError(DefinitionStoreError):
    """A `DEFINITION_RULES` name, or `ACCOUNT_NOT_LIVE`: a member account gone or soft-deleted."""

    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


class DefinitionStore(Protocol):
    """The Owner's writes. `replace` sets the name and the whole member set; it and `soft_delete`
    answer `None` for a definition that is not live, `soft_delete` with the record it deleted."""

    async def create(
        self, scope: OwnerScope, new: NewDefinition, *, write_ahead: DefinitionWriteAhead
    ) -> DefinitionRecord: ...

    async def replace(
        self,
        scope: OwnerScope,
        definition_id: UUID,
        new: NewDefinition,
        *,
        expected_updated_at: datetime | None,
        write_ahead: DefinitionWriteAhead,
    ) -> DefinitionRecord | None: ...

    async def soft_delete(
        self, scope: OwnerScope, definition_id: UUID, *, write_ahead: DefinitionWriteAhead
    ) -> DefinitionRecord | None: ...


class DefinitionReads(Protocol):
    """The live definition when the scope sees it, else `None`; an empty `GrantScope` runs no
    SQL. The keyset page lands with `listTradeGroupDefinitions`."""

    async def get(self, scope: AccountScope, definition_id: UUID) -> DefinitionRecord | None: ...
