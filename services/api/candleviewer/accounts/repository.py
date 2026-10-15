"""Accounts repository facade and debounced `last_used_at` writer (E27-T01).

At most one write per key per interval (default 60 s) — the write-amplification guard in
21-database-schema.md §3.2.2. In-memory by design so it stays testable and cheap.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
)
from candleviewer.accounts.models import (
    AccountKind,
    ApiKeyMetadata,
    ApiKeyRotation,
    ExchangeAccount,
    ExchangeEnv,
    KeyStatus,
)
from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountScope,
    AccountsPage,
    AccountsStore,
    AccountsStoreConflictError,
    AccountsStoreError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    ExchangeAccountPatch,
    NewExchangeAccount,
    NewKeyRotation,
    OwnerScope,
    RotationStep,
)

Writer = Callable[[UUID, datetime], Awaitable[None]]


class LastUsedDebouncer:
    def __init__(self, writer: Writer, interval: timedelta = timedelta(seconds=60)) -> None:
        self._writer = writer
        self._interval = interval
        self._last: dict[UUID, datetime] = {}

    async def touch(self, key_id: UUID, now: datetime) -> bool:
        """Record use at `now` (tz-aware UTC); return True iff a write was issued."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        prev = self._last.get(key_id)
        if prev is not None and now - prev < self._interval:
            return False
        await self._writer(key_id, now)
        self._last[key_id] = now
        return True


class AccountsRepository:
    """M13 facade over the driver-free `AccountsStore` (SR-051 scoping happens in the store).

    Returns domain models (no ciphertext fields exist on them) and raises domain errors. Every
    "no row" outcome is the same `AccountNotFoundError`, so nothing is an existence oracle. An
    `OwnerScope` whose caller is not a live owner raises `AccountScopeDeniedError` on every
    method, reads included.
    """

    def __init__(self, store: AccountsStore) -> None:
        self._store = store

    @staticmethod
    def _map(exc: AccountsStoreError) -> AccountsError:
        if isinstance(exc, AccountsStoreScopeDeniedError):
            return AccountScopeDeniedError()
        if isinstance(exc, AccountsStoreConflictError):
            return AccountConflictError(exc.constraint)
        if isinstance(exc, AccountsStoreRuleError):
            return AccountRuleError(exc.rule)
        if isinstance(exc, AccountsStoreStaleError):
            return AccountVersionConflictError()
        return AccountsError("store error")

    async def create_account(
        self,
        scope: OwnerScope,
        *,
        id: UUID,
        exchange: str,
        env: ExchangeEnv,
        kind: AccountKind,
        exchange_uid: str,
        label: str,
        parent_account_id: UUID | None = None,
    ) -> ExchangeAccount:
        new = NewExchangeAccount(
            id, exchange, env.value, kind.value, exchange_uid, label, parent_account_id
        )
        try:
            row = await self._store.create_account(scope, new)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        return ExchangeAccount.model_validate(row, from_attributes=True)

    async def get_account(self, scope: AccountScope, account_id: UUID) -> ExchangeAccount:
        try:
            row = await self._store.get_account(scope, account_id)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("account")
        return ExchangeAccount.model_validate(row, from_attributes=True)

    async def list_accounts(
        self,
        scope: AccountScope,
        *,
        env: ExchangeEnv | None = None,
        kind: AccountKind | None = None,
        after: AccountKey | None = None,
        limit: int = 50,
    ) -> AccountsPage[ExchangeAccount]:
        try:
            page = await self._store.list_accounts(
                scope,
                env=None if env is None else env.value,
                kind=None if kind is None else kind.value,
                after=after,
                limit=limit,
            )
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        items = tuple(ExchangeAccount.model_validate(r, from_attributes=True) for r in page.items)
        return AccountsPage(items, page.next_after)

    async def update_account(
        self,
        scope: OwnerScope,
        account_id: UUID,
        patch: ExchangeAccountPatch,
        *,
        if_match: datetime | None = None,
    ) -> ExchangeAccount:
        try:
            row = await self._store.update_account(scope, account_id, patch, if_match=if_match)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("account")
        return ExchangeAccount.model_validate(row, from_attributes=True)

    async def soft_delete_account(self, scope: OwnerScope, account_id: UUID) -> None:
        try:
            deleted = await self._store.soft_delete_account(scope, account_id)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if not deleted:
            raise AccountNotFoundError("account")

    async def get_key(self, scope: OwnerScope, account_id: UUID, key_id: UUID) -> ApiKeyMetadata:
        try:
            row = await self._store.get_key(scope, account_id, key_id)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("key")
        return ApiKeyMetadata.model_validate(row, from_attributes=True)

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyMetadata, ...]:
        try:
            rows = await self._store.list_keys(scope, account_id)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        return tuple(ApiKeyMetadata.model_validate(r, from_attributes=True) for r in rows)

    async def transition_key_status(
        self,
        scope: OwnerScope,
        account_id: UUID,
        key_id: UUID,
        *,
        expected: KeyStatus,
        new: KeyStatus,
    ) -> ApiKeyMetadata:
        try:
            row = await self._store.transition_key_status(
                scope, account_id, key_id, expected=expected.value, new=new.value
            )
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("key")
        return ApiKeyMetadata.model_validate(row, from_attributes=True)

    async def start_rotation(self, scope: OwnerScope, new: NewKeyRotation) -> ApiKeyRotation:
        try:
            row = await self._store.start_rotation(scope, new)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("key")
        return ApiKeyRotation.model_validate(row, from_attributes=True)

    async def get_rotation(
        self, scope: OwnerScope, account_id: UUID, rotation_id: UUID
    ) -> ApiKeyRotation:
        try:
            row = await self._store.get_rotation(scope, account_id, rotation_id)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("rotation")
        return ApiKeyRotation.model_validate(row, from_attributes=True)

    async def list_rotations(
        self, scope: OwnerScope, account_id: UUID, *, limit: int = 50
    ) -> tuple[ApiKeyRotation, ...]:
        try:
            rows = await self._store.list_rotations(scope, account_id, limit=limit)
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        return tuple(ApiKeyRotation.model_validate(r, from_attributes=True) for r in rows)

    async def record_rotation_step(
        self,
        scope: OwnerScope,
        account_id: UUID,
        rotation_id: UUID,
        step: RotationStep,
        *,
        failure_reason: str | None = None,
    ) -> ApiKeyRotation:
        try:
            row = await self._store.record_rotation_step(
                scope, account_id, rotation_id, step, failure_reason=failure_reason
            )
        except AccountsStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("rotation")
        return ApiKeyRotation.model_validate(row, from_attributes=True)
