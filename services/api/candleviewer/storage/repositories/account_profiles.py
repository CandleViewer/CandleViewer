"""Stored shape of `account_profiles` (E28-T01 #905; 21-database-schema.md Sec.3.2.4, M10).

Stdlib only: M13 `accounts` maps these rows to its `AccountProfile` domain model
(`candleviewer.accounts.profiles`). Values are in their stored units: percentages are the percent
a user sees (0..100), money and quantities `Decimal`. `version`, `updated_at` and the
`account_profile_revisions` row are written by the database's triggers, so no writer sets them.
A writer owes two things: every UPDATE sets `updated_by` (a revision's `changed_by` is the row's
`updated_by`, so one without it credits the previous editor), and a refusal is mapped by its
constraint name, never by its message or DETAIL, which repeats the failing row. A profile leaves by
soft delete (`deleted_at`): `cv_app` holds no DELETE on the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


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
