"""Driver-free port for exchange accounts, key metadata and rotations (E27-T01, M10).

Stdlib only: M13 `accounts` and M18 `auth` import this module, never a driver.

Scoping (SR-051, C-12.4): the scope is resolved server-side from the principal and applied in
SQL, never filtered after fetch. Account writes, key reads and rotations are owner-only and
take an `OwnerScope`; account reads take either scope. Every `OwnerScope` call, reads included,
first checks the live owner role, so a non-owner holding one gets
`AccountsStoreScopeDeniedError` (a uniform 403 that depends only on the caller). A `GrantScope`
narrows silently in SQL. Not-found, not-yours, soft-deleted and path-mismatched all return
`None`, so there is no existence oracle. No method names or returns an envelope column
(C-3.2): key writes (insert, revoke, touch) belong to M2's credential store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OwnerScope:
    """Caller holds the live owner role: every live account is visible."""

    user_id: UUID


@dataclass(frozen=True, slots=True)
class GrantScope:
    """Manager/viewer: only these ids (grants with can_view and not frozen). Empty = nothing."""

    user_id: UUID
    account_ids: frozenset[UUID]


AccountScope = OwnerScope | GrantScope


@dataclass(frozen=True, slots=True)
class AccountKey:
    created_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class AccountsPage[T]:
    items: tuple[T, ...]
    next_after: AccountKey | None


@dataclass(frozen=True, slots=True)
class ExchangeAccountRow:
    id: UUID
    exchange: str
    env: str
    kind: str
    exchange_uid: str
    parent_account_id: UUID | None
    label: str
    colour_token: str
    is_enabled: bool
    trading_enabled: bool
    position_mode: str
    margin_mode: str
    account_type: str
    quote_ccy: str
    equity_cached_usd: Decimal | None
    equity_cached_at: datetime | None
    max_sub_accounts_hint: int
    last_reconciled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class AccountsStoreError(Exception):
    """Base for store errors."""


class AccountsStoreScopeDeniedError(AccountsStoreError):
    """Caller is not a live owner (uniform 403; depends only on the caller)."""


class AccountsStore(Protocol):
    async def get_account(
        self, scope: AccountScope, account_id: UUID
    ) -> ExchangeAccountRow | None: ...

    async def list_accounts(
        self,
        scope: AccountScope,
        *,
        env: str | None,
        kind: str | None,
        after: AccountKey | None,
        limit: int,
    ) -> AccountsPage[ExchangeAccountRow]: ...
