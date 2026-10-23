"""Profile repository: the M13 domain facade over the profile store (E28-T01 #905).

Maps store rows to `AccountProfile` (through `profile_from_row`, the one percent/fraction adapter)
and store errors to the accounts domain errors, `from None` (a driver error can carry parameter
values). Scoping is the store's, in SQL (SR-051): reads take an `AccountScope`, writes an
`OwnerScope` (`accounts:write` is Owner-only, E28-X01 PF-T01). Missing, soft-deleted, another
account's and path-mismatched profiles are all the same `AccountNotFoundError("profile")`.

A write sends the profile through `profile_values` (the model's rules ran when it was built, and
the database repeats them), never `version`: the database bumps it and records the revision
(SR-E28-07). `update_profile` and `delete_profile` take the client's `If-Match` as
`expected_version` (`None` writes whatever is current); `set_default_profile` is the one write
that moves the default (decision D7, the bound profile is the account's ceiling), and it takes the
binding's `If-Match` as `expected_binding_version`, which it requires (#906 0d). The binding
reads through `get_default_binding`, whose miss is `AccountNotFoundError("account")`. The default
is never deleted (`AccountConflictError("default_profile")`).

Every write, whatever its outcome, invalidates the account in `EffectiveProfiles` before it
returns (SR-E28-15), and `version_bumps` counts the profile rows a write bumped. A refusal by a
named rule or constraint is logged at WARN with that name, never with a value. Each write takes an
optional `write_ahead` hook, run in the write's transaction before it commits (C-2.9) with the
store's rows in stored units (`profile_from_row` reads them): E28-T02 (#906) wires the
`profile.created|updated|deleted` record through it, as a typed refusal when it fails, and maps the
`ap_native_sl` rule (unreachable through `AccountProfile`, whose `require_native_sl` is
`Literal[True]`) to `native_stop_mandatory` with its audit row (SR-E28-08).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
)
from candleviewer.accounts.profiles import AccountProfile, profile_from_row, profile_values
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileRow,
    AccountProfileStore,
    AccountProfileStoreConflictError,
    AccountProfileStoreError,
    AccountProfileStoreRuleError,
    AccountProfileStoreScopeDeniedError,
    AccountProfileStoreStaleError,
    ProfileWriteAhead,
)
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope

if TYPE_CHECKING:
    from candleviewer.accounts.profile_cache import EffectiveProfiles
    from candleviewer.observability.metrics import BoundedMetric


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DefaultProfileMove:
    """The new default, the profile it replaced (`None` when nothing was replaced) and the
    binding's version after the move (unchanged when nothing was written)."""

    profile: AccountProfile
    previous: AccountProfile | None
    version: int


@dataclass(frozen=True, slots=True)
class DefaultBinding:
    """An account's default binding (decision D7): its default profile and the binding's version,
    the `ETag` of `getAccountDefaultProfile`, one more with each move and never repeated."""

    account_id: UUID
    profile_id: UUID
    version: int


class ProfilesRepository:
    """`AccountProfile` reads and writes over an `AccountProfileStore`."""

    def __init__(
        self,
        store: AccountProfileStore,
        *,
        cache: EffectiveProfiles | None,
        version_bumps: BoundedMetric | None = None,
    ) -> None:
        """`cache` is required: a root that passes `None` opts out of SR-E28-15's invalidation
        knowingly, never by forgetting it."""
        self._store = store
        self._cache = cache
        self._bumps = None if version_bumps is None else version_bumps.child()

    @staticmethod
    def _map(exc: AccountProfileStoreError) -> AccountsError:
        if isinstance(exc, AccountProfileStoreScopeDeniedError):
            return AccountScopeDeniedError()
        if isinstance(exc, AccountProfileStoreConflictError):
            _log().warning("profile.constraint_violation", constraint=exc.constraint)
            return AccountConflictError(exc.constraint)
        if isinstance(exc, AccountProfileStoreRuleError):
            _log().warning("profile.constraint_violation", constraint=exc.rule)
            return AccountRuleError(exc.rule)
        if isinstance(exc, AccountProfileStoreStaleError):
            return AccountVersionConflictError()
        return AccountsError("store error")

    @staticmethod
    def _found(row: AccountProfileRow | None) -> AccountProfile:
        if row is None:
            raise AccountNotFoundError("profile")
        return profile_from_row(row)

    def _written(self, bumped: int) -> None:
        """`bumped` profile rows got a new version (and a revision)."""
        if self._bumps is not None:
            self._bumps.inc(bumped)

    def _invalidate(self, account_id: UUID) -> None:
        if self._cache is not None:
            self._cache.invalidate(account_id)

    async def list_profiles(
        self, scope: AccountScope, account_id: UUID
    ) -> tuple[AccountProfile, ...]:
        try:
            rows = await self._store.list_profiles(scope, account_id)
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        return tuple(profile_from_row(row) for row in rows)

    async def get_profile(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID
    ) -> AccountProfile:
        try:
            row = await self._store.get_profile(scope, account_id, profile_id)
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        return self._found(row)

    async def get_default_binding(self, scope: AccountScope, account_id: UUID) -> DefaultBinding:
        """The account's default binding; an account missing, soft-deleted or out of scope is
        `AccountNotFoundError("account")`, all alike."""
        try:
            row = await self._store.get_default_binding(scope, account_id)
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        if row is None:
            raise AccountNotFoundError("account")
        return DefaultBinding(
            account_id=row.account_id, profile_id=row.profile_id, version=row.version
        )

    async def create_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile: AccountProfile,
        *,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfile:
        """Store `profile` under its own id on account `account_id`, the path's; its `version` and
        `updated_at` are the database's. `AccountNotFoundError("profile")` when the account is not
        a live one, or when `profile` names another account: a path mismatch reads as missing."""
        if profile.account_id != account_id:
            raise AccountNotFoundError("profile")
        try:
            row = await self._store.create_profile(
                scope,
                account_id,
                profile.profile_id,
                profile_values(profile),
                write_ahead=write_ahead,
            )
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        finally:
            self._invalidate(account_id)
        return self._found(row)

    async def update_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        profile: AccountProfile,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfile:
        """Every field of profile `profile_id` of account `account_id` (the path's ids) but
        `is_default`, which must be unchanged (`set_default_profile` moves it): a different one is
        `AccountRuleError("default_moves_alone")`. A `profile` naming another account or profile
        is `AccountNotFoundError("profile")`, like any path mismatch."""
        if (profile.account_id, profile.profile_id) != (account_id, profile_id):
            raise AccountNotFoundError("profile")
        try:
            row = await self._store.update_profile(
                scope,
                account_id,
                profile_id,
                profile_values(profile),
                expected_version=expected_version,
                write_ahead=write_ahead,
            )
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        finally:
            self._invalidate(account_id)
        updated = self._found(row)
        self._written(1)
        return updated

    async def set_default_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        *,
        expected_binding_version: int,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> DefaultProfileMove:
        """At the binding's version (`If-Match`): a stale one is `AccountVersionConflictError`
        and moves nothing; the answer carries the version after the move."""
        try:
            move = await self._store.set_default_profile(
                scope,
                account_id,
                profile_id,
                expected_binding_version=expected_binding_version,
                write_ahead=write_ahead,
            )
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        finally:
            self._invalidate(account_id)
        if move is None:
            raise AccountNotFoundError("profile")
        previous = None if move.previous is None else profile_from_row(move.previous)
        if move.written:
            self._written(1 + (previous is not None))
        return DefaultProfileMove(
            profile=profile_from_row(move.profile), previous=previous, version=move.version
        )

    async def delete_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfile:
        """Soft delete; the profile as it stood once deleted (its last revision)."""
        try:
            row = await self._store.delete_profile(
                scope,
                account_id,
                profile_id,
                expected_version=expected_version,
                write_ahead=write_ahead,
            )
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        finally:
            self._invalidate(account_id)
        deleted = self._found(row)
        self._written(1)
        return deleted

    async def get_revision(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID, version: int
    ) -> AccountProfile:
        """The profile as it stood at `version`, deleted since or not (#906)."""
        try:
            revision = await self._store.get_revision(scope, account_id, profile_id, version)
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        if revision is None:
            raise AccountNotFoundError("profile")
        return profile_from_row(revision.profile)
