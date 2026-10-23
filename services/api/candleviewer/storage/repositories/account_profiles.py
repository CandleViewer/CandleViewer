"""Driver-free port for `account_profiles` (E28-T01 #905; 21-database-schema.md Sec.3.2.4, M10).

Stdlib only: M13 `accounts` maps these rows to its `AccountProfile` domain model
(`candleviewer.accounts.profiles`). Values are in their stored units: percentages are the percent
a user sees (0..100), money and quantities `Decimal`. `version`, `updated_at` and the
`account_profile_revisions` row are written by the database's triggers, so no writer sets them.
A writer owes two things: every UPDATE sets `updated_by` (a revision's `changed_by` is the row's
`updated_by`, so one without it credits the previous editor), and a refusal is mapped by its
constraint name, never by its message or DETAIL, which repeats the failing row. A profile leaves by
soft delete (`deleted_at`): `cv_app` holds no DELETE on the table.

Scoping copies the accounts store (SR-051, C-12.4): an `OwnerScope` call first checks the live
owner role and answers `AccountProfileStoreScopeDeniedError` to anyone else, reads included; a
`GrantScope` read narrows silently in SQL to the caller's live grants. Writes are owner-only
(`accounts:write`, E28-X01 PF-T01). A profile of another, a missing, a soft-deleted or a
path-mismatched account, and a soft-deleted profile, all read as `None`, so nothing is an
existence oracle. `EffectiveProfileReads` is the one surface with no principal: the order path's
system read of a profile (24-internal-schemas.md Sec.9.3), which no route reaches.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope


@dataclass(frozen=True, slots=True)
class LadderRung:
    """One `tp_ladder` element as stored: `pct` of the leg, as a percent; `r`, an R multiple."""

    pct: Decimal
    r: Decimal


@dataclass(frozen=True, slots=True)
class AccountProfileValues:
    """The columns of a profile a writer sets, in their stored units."""

    name: str
    is_default: bool
    enabled: bool
    trading_enabled: bool
    leverage: Decimal
    margin_mode: str
    position_mode: str
    sizing_mode: str
    size_fixed_qty: Decimal | None
    size_fixed_notional_usd: Decimal | None
    size_pct_equity: Decimal | None
    risk_pct_equity: Decimal | None
    risk_fixed_amount_usd: Decimal | None
    min_leg_notional_usd: Decimal
    sl_offset_value: Decimal
    sl_offset_unit: str
    sl_atr_period: int
    sl_atr_multiple: Decimal
    fallback_sl_offset_pct: Decimal
    tp_offset_value: Decimal | None
    tp_offset_unit: str | None
    tp_ladder: tuple[LadderRung, ...] | None
    require_native_sl: bool
    max_position_notional_usd: Decimal | None
    max_position_pct_equity: Decimal | None
    max_daily_loss_usd: Decimal | None
    max_daily_loss_pct: Decimal | None
    max_open_positions: int | None
    max_concurrent_orders: int | None
    max_leverage_cap: Decimal | None
    max_orders_per_minute: int
    all_symbols: bool
    allowed_symbols: tuple[str, ...] | None
    blocked_symbols: tuple[str, ...] | None
    reduce_only_default: bool
    time_in_force_default: str
    slippage_tolerance_bps: int


@dataclass(frozen=True, slots=True)
class AccountProfileRow:
    """One `account_profiles` row: its identity, the database-written columns and `values`."""

    id: UUID
    exchange_account_id: UUID
    version: int
    values: AccountProfileValues
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountProfileRevision:
    """One `account_profile_revisions` row (21 Sec.3.2.5): `profile` is the row as it stood at
    `version`, decoded from the revision's `payload`."""

    id: int
    version: int
    profile: AccountProfileRow
    changed_by: UUID | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class DefaultMove:
    """`set_default_profile`'s answer: the new default, the profile it replaced (`None` when the
    account had none), whether anything was written (not when it already was the default) and the
    binding's version after the move: unchanged when nothing was written, otherwise one more."""

    profile: AccountProfileRow
    previous: AccountProfileRow | None
    written: bool
    version: int


@dataclass(frozen=True, slots=True)
class DefaultBindingRow:
    """An account's default binding: its live default profile and the binding's version
    (`exchange_accounts.default_binding_version`, 21 Sec.3.2.1)."""

    account_id: UUID
    profile_id: UUID
    version: int


#: Awaited inside a write's transaction, before it commits, once per profile row the write
#: changed (never for a write that changes none): the row as it stood before (`None` for a create)
#: and after, in stored units (`profile_from_row` reads them). A hook that raises, or outlasts the
#: store's audit timeout, rolls the write back (C-2.9 write-ahead; E28-T02 wires the
#: `profile.created|updated|deleted` record). A hook raises its own typed refusal, as
#: `api/users.py`'s `_AuditRefused` does: a raw `OSError` or driver error from it is mapped as the
#: database's own, `StorageTierUnavailable` or `StorageQueryFailed`.
ProfileWriteAhead = Callable[[AccountProfileRow | None, AccountProfileRow], Awaitable[None]]

#: The refusals a write can meet, by the name the database gives them: every CHECK of
#: `account_profiles` and the ladder trigger (which names itself as the error's constraint, `USING
#: CONSTRAINT`). Pinned to `db.models.account_profiles` by a unit test.
PROFILE_RULES: Final[frozenset[str]] = frozenset(
    {"ap_leverage", "ap_native_sl", "ap_tif", "ap_slip", "ap_opm", "ap_sl_pos", "ap_tp_pair",
     "ap_tp_pos", "ap_maxpos", "ap_sizing_shape", "ap_ladder_shape", "ap_name", "ap_version",
     "ap_margin_mode", "ap_position_mode", "ap_sl_unit", "ap_atr", "ap_fallback_sl", "ap_min_leg",
     "ap_max_notional", "ap_max_pos_pct", "ap_daily_loss", "ap_daily_loss_pct", "ap_max_orders",
     "ap_lev_cap", "ap_trading_caps", "ap_all_symbols", "ap_finite", "trg_ap_ladder_sum"}
)  # fmt: skip
#: Unique-index refusals, plus `default_profile`: the account's default is never deleted (#906).
PROFILE_CONFLICTS: Final[frozenset[str]] = frozenset(
    {"ux_ap_name", "ux_ap_default", "account_profiles_pkey", "default_profile"}
)
#: `update_profile` never moves the default; `set_default_profile` does, as one change (D7).
DEFAULT_MOVES_ALONE: Final = "default_moves_alone"


class AccountProfileStoreError(Exception):
    """Base for profile store errors; none carries a value, only a rule or constraint name."""


class AccountProfileStoreScopeDeniedError(AccountProfileStoreError):
    """The caller is not a live owner (uniform 403; depends only on the caller)."""


class AccountProfileStoreConflictError(AccountProfileStoreError):
    """A name in `PROFILE_CONFLICTS` (problem code `conflict`)."""

    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.constraint = constraint


class AccountProfileStoreRuleError(AccountProfileStoreError):
    """A name in `PROFILE_RULES`, or `DEFAULT_MOVES_ALONE` (problem code `validation_failed`)."""

    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


class AccountProfileStoreStaleError(AccountProfileStoreError):
    """`expected_version`, or a default move's `expected_binding_version`, no longer matches the
    live row (problem code `version_conflict`)."""


class AccountProfileStore(Protocol):
    """The scoped profile store. `expected_version=None` writes whatever version is current
    (an `If-Match` the client left out); a stale one raises `AccountProfileStoreStaleError`."""

    async def list_profiles(
        self, scope: AccountScope, account_id: UUID
    ) -> tuple[AccountProfileRow, ...]:
        """The live profiles of a live account in scope, the default first, then by name."""
        ...

    async def get_profile(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID
    ) -> AccountProfileRow | None: ...

    async def get_default_binding(
        self, scope: AccountScope, account_id: UUID
    ) -> DefaultBindingRow | None:
        """The binding of a live account in scope; `None` otherwise."""
        ...

    async def create_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        values: AccountProfileValues,
        *,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfileRow | None:
        """`None` when the account is not a live one."""
        ...

    async def update_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        values: AccountProfileValues,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfileRow | None:
        """Every column but `is_default`, which must equal the row's: a different one raises
        `AccountProfileStoreRuleError(DEFAULT_MOVES_ALONE)`."""
        ...

    async def set_default_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        *,
        expected_binding_version: int,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> DefaultMove | None:
        """Unset the account's default and set this profile's, in one transaction, at the
        binding's version, which is required (the binding has no last-write-wins): a stale one
        raises `AccountProfileStoreStaleError` before the profile is read. `write_ahead` sees the
        previous default first, then the new one."""
        ...

    async def delete_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfileRow | None:
        """Soft delete; the default refuses with `AccountProfileStoreConflictError`."""
        ...

    async def get_revision(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID, version: int
    ) -> AccountProfileRevision | None:
        """A profile as it stood at `version`, deleted or not, while its account is live and in
        scope (#906: an edited version stays readable)."""
        ...


class EffectiveProfileReads(Protocol):
    """The order path's system read: no principal, never reached from a route."""

    async def effective_profile(
        self, account_id: UUID, profile_id: UUID | None
    ) -> AccountProfileRow | None:
        """The live profile, or the account's default when `profile_id` is `None`, of a live
        account. `enabled` and `trading_enabled` are not filtered: the sizer reads them (24
        Sec.9.3 step 1)."""
        ...
