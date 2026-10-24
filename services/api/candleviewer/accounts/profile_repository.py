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

The REST reads, `read_profiles` and `read_profile` (#906 D1b), and the writes `create_profile` and
`update_profile` (D2-3) answer a profile with its row's `created_at` (`StoredProfile`); a stored
row the store or the model cannot read is `ProfileUnavailableError`, logged by its error class
alone, as the order path's cache fails closed (SR-E28-24), from every write too, once committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import structlog

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
    ProfileUnavailableError,
)
from candleviewer.accounts.profiles import (
    AccountProfile,
    profile_from_row,
    profile_values,
    to_us,
)
from candleviewer.domain.primitives import TsUs
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


#: A stored row that cannot be read, from the store's decode or the model (pydantic's
#: ValidationError is a ValueError), as `profile_cache` catches it.
_UNREADABLE: Final = (ValueError, TypeError, KeyError, ArithmeticError)


@dataclass(frozen=True, slots=True)
class StoredProfile:
    """A live profile as a read answers it: the model and its row's `created_at` (us), which the
    model does not hold (24 Sec.9.2 maps `created_at` to no domain field)."""

    profile: AccountProfile
    created_at: TsUs


def _stored(row: AccountProfileRow) -> StoredProfile:
    return StoredProfile(profile_from_row(row), to_us(row.created_at))


def _unreadable(
    account_id: UUID, exc: Exception, reason: str = "invalid_row"
) -> ProfileUnavailableError:
    _log().warning(
        "profile.read_failed_closed",
        reason=reason,
        account_id=str(account_id),
        error=type(exc).__name__,  # never a value
    )
    return ProfileUnavailableError("stored profile unreadable")


def _read_back(account_id: UUID, row: AccountProfileRow | None) -> StoredProfile:
    """A write's row as a read answers it: `None` is the one not-found, and a row the model
    cannot read `ProfileUnavailableError`, though the write committed (a 503, never a 500), logged
    as `committed_row_unreadable` so an operator knows it committed."""
    if row is None:
        raise AccountNotFoundError("profile")
    try:
        return _stored(row)
    except _UNREADABLE as exc:
        raise _unreadable(account_id, exc, "committed_row_unreadable") from None


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

    def _written(self, bumped: int) -> None:
        """`bumped` profile rows got a new version (and a revision)."""
        if self._bumps is not None:
            self._bumps.inc(bumped)

    def _invalidate(self, account_id: UUID) -> None:
        if self._cache is not None:
            self._cache.invalidate(account_id)

    async def read_profiles(
        self, scope: AccountScope, account_id: UUID
    ) -> tuple[StoredProfile, ...]:
        """The account's live profiles, the default first, then by name; `()` when the account is
        missing, deleted or outside `scope`, alike (an account in scope always has its default)."""
        try:
            return tuple(_stored(r) for r in await self._store.list_profiles(scope, account_id))
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        except _UNREADABLE as exc:
            raise _unreadable(account_id, exc) from None

    async def read_profile(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID
    ) -> StoredProfile:
        """`AccountNotFoundError("profile")` for a profile missing, deleted, another account's or
        out of scope, all alike."""
        try:
            row = await self._store.get_profile(scope, account_id, profile_id)
            stored = None if row is None else _stored(row)
        except AccountProfileStoreError as exc:
            raise self._map(exc) from None
        except _UNREADABLE as exc:
            raise _unreadable(account_id, exc) from None
        if stored is None:  # outside the try: ruff TRY301
            raise AccountNotFoundError("profile")
        return stored

    async def list_profiles(
        self, scope: AccountScope, account_id: UUID
    ) -> tuple[AccountProfile, ...]:
        return tuple(s.profile for s in await self.read_profiles(scope, account_id))

    async def get_profile(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID
    ) -> AccountProfile:
        return (await self.read_profile(scope, account_id, profile_id)).profile

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
    ) -> StoredProfile:
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
        return _read_back(account_id, row)

    async def update_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        profile: AccountProfile,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> StoredProfile:
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
        if row is not None:  # committed: counted whether or not the row reads back
            self._written(1)
        return _read_back(account_id, row)

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
        if move.written:  # committed: counted whether or not its rows read back
            self._written(1 + (move.previous is not None))
        try:
            previous = None if move.previous is None else profile_from_row(move.previous)
            profile = profile_from_row(move.profile)
        except _UNREADABLE as exc:
            reason = "committed_row_unreadable" if move.written else "invalid_row"
            raise _unreadable(account_id, exc, reason) from None
        return DefaultProfileMove(profile=profile, previous=previous, version=move.version)

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
        if row is not None:  # committed: counted whether or not the row reads back
            self._written(1)
        return _read_back(account_id, row).profile

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
