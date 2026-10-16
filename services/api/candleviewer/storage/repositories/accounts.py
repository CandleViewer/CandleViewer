"""Driver-free port for exchange accounts, key metadata and rotations (E27-T01, M10).

Stdlib only: M13 `accounts` and M18 `auth` import this module, never a driver.

Scoping (SR-051, C-12.4): the scope is resolved server-side from the principal and applied in
SQL, never filtered after fetch. Account writes, key reads and rotations are owner-only and
take an `OwnerScope`; account reads take either scope. Every `OwnerScope` call, reads included,
first checks the live owner role, so a non-owner holding one gets
`AccountsStoreScopeDeniedError` (a uniform 403 that depends only on the caller). A `GrantScope`
narrows silently in SQL. Not-found, not-yours, soft-deleted and path-mismatched all return
`None`, so there is no existence oracle. No method names or returns an envelope column
(C-3.2): key writes (insert, revoke, touch) belong to M2's credential store. Two surfaces take no
scope, and no route reaches either: `AccountsRowCounts`, aggregate counts for the M13 gauges, never
a row (#2314), and `KeySelfCheckStore`, the stored-key self-check's system port (E27-T03, #836).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
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


@dataclass(frozen=True, slots=True)
class ApiKeyRow:
    """Metadata only; no ciphertext, nonce or DEK handle."""

    id: UUID
    exchange_account_id: UUID
    label: str
    key_id_last4: str
    kek_version: int
    permission_snapshot: dict[str, object]
    permission_snapshot_at: datetime
    can_trade: bool
    can_withdraw: bool
    can_transfer: bool
    read_only: bool
    status: str
    expires_at: datetime | None
    last_used_at: datetime | None
    rotation_due_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApiKeyRotationRow:
    id: UUID
    old_api_key_id: UUID
    new_api_key_id: UUID
    started_at: datetime
    validated_at: datetime | None
    cutover_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    grace_seconds: int


@dataclass(frozen=True, slots=True)
class NewExchangeAccount:
    id: UUID
    exchange: str
    env: str
    kind: str
    exchange_uid: str
    label: str
    parent_account_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ExchangeAccountPatch:
    """Identity fields and `trading_enabled` are deliberately not patchable."""

    label: str | None = None
    is_enabled: bool | None = None
    position_mode: str | None = None
    margin_mode: str | None = None


@dataclass(frozen=True, slots=True)
class NewKeyRotation:
    id: UUID
    exchange_account_id: UUID
    old_api_key_id: UUID
    new_api_key_id: UUID
    grace_seconds: int = 900


RotationStep = Literal["validated", "cutover", "completed", "failed"]


class AccountsStoreError(Exception):
    """Base for store errors."""


class AccountsStoreScopeDeniedError(AccountsStoreError):
    """Caller is not a live owner (uniform 403; depends only on the caller)."""


class AccountsStoreConflictError(AccountsStoreError):
    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.constraint = constraint


class AccountsStoreRuleError(AccountsStoreError):
    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


class AccountsStoreStaleError(AccountsStoreError):
    """If-Match token no longer matches a live row."""


class AccountsRowCounts(Protocol):
    """System telemetry for the M13 row gauges (#2314): counts for one environment, no row data
    and no account id, so these reads take no principal scope. They are never reachable from a
    route: `accounts.service.AccountsService` is the only caller (pinned by
    `tests/unit/architecture/test_accounts_row_counts_callers.py`). An unknown `env` raises
    `ValueError` instead of counting nothing."""

    async def count_accounts_by_kind(self, env: str) -> dict[str, int]:
        """Non-deleted `exchange_accounts` of `env` per `kind`; absent kinds are omitted."""
        ...

    async def count_api_keys_by_status(self, env: str) -> dict[str, int]:
        """Every `api_keys` row of `env`'s accounts per `status` (21 §3.2 excludes none: keys have
        no soft delete, and keys of soft-deleted accounts still exist)."""
        ...


class AccountsStore(AccountsRowCounts, Protocol):
    async def create_account(
        self, scope: OwnerScope, new: NewExchangeAccount
    ) -> ExchangeAccountRow: ...

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

    async def update_account(
        self,
        scope: OwnerScope,
        account_id: UUID,
        patch: ExchangeAccountPatch,
        *,
        if_match: datetime | None,
    ) -> ExchangeAccountRow | None: ...

    async def soft_delete_account(self, scope: OwnerScope, account_id: UUID) -> bool: ...

    async def get_key(
        self, scope: OwnerScope, account_id: UUID, key_id: UUID
    ) -> ApiKeyRow | None: ...

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyRow, ...]: ...

    async def transition_key_status(
        self, scope: OwnerScope, account_id: UUID, key_id: UUID, *, expected: str, new: str
    ) -> ApiKeyRow | None: ...

    async def start_rotation(
        self, scope: OwnerScope, new: NewKeyRotation
    ) -> ApiKeyRotationRow | None: ...

    async def get_rotation(
        self, scope: OwnerScope, account_id: UUID, rotation_id: UUID
    ) -> ApiKeyRotationRow | None: ...

    async def list_rotations(
        self, scope: OwnerScope, account_id: UUID, *, limit: int
    ) -> tuple[ApiKeyRotationRow, ...]: ...

    async def record_rotation_step(
        self,
        scope: OwnerScope,
        account_id: UUID,
        rotation_id: UUID,
        step: RotationStep,
        *,
        failure_reason: str | None,
    ) -> ApiKeyRotationRow | None: ...


@dataclass(frozen=True, slots=True)
class SelfCheckTargetRow:
    """One usable stored key for the self-check, with its account: no ciphertext, no whitelist."""

    key_id: UUID
    read_only: bool
    #: `api_keys.permission_snapshot_at`: the last passing verification (only a pass writes it).
    verified_at: datetime
    account: ExchangeAccountRow


@dataclass(frozen=True, slots=True)
class VerifiedKey:
    """What a passing self-check writes to `api_keys` (21-database-schema.md §3.2.2). `snapshot`
    holds the verified key-info fields; it is merged into `permission_snapshot`."""

    snapshot: dict[str, object]
    can_trade: bool
    read_only: bool
    ip_whitelist: tuple[str, ...]
    expires_at: datetime | None
    at: datetime


class KeySelfCheckStore(Protocol):
    """The stored-key self-check's system port (E27-T03), bound to one environment (C-2.11).

    The job has no principal, so it takes no scope: `accounts.selfcheck` is its one caller. It
    writes the verification columns of `api_keys` and `exchange_accounts.trading_enabled`, never
    a ciphertext, identity or status column. Each write returns whether it changed a row."""

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        """Every `active` or `rotating`, unrevoked key of a non-deleted account."""
        ...

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool: ...

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        """`last_error_code` and `last_error_at` only: the verified columns keep their time."""
        ...

    async def disable_trading(self, account_id: UUID) -> bool:
        """`trading_enabled` to false; `False` when the account was not armed."""
        ...
