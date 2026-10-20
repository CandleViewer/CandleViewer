"""The profile caps and the one gate that enforces each (SR-E28-10; E28-X01 F-10, F-25).

Every cap an `AccountProfile` stores maps to exactly one enforcing gate. The orchestrator's ruling
on F-25 (2026-10-20, recorded on #905) puts cap enforcement at order time in E39-S01; E28-T04 owns
the cap configuration and the validation of stored values. A new cap column without an entry here
fails `test_every_cap_has_exactly_one_enforcing_gate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

CapUnit = Literal["usd", "fraction", "count", "leverage", "per_minute"]
#: The ticket that enforces a cap at order time (F-25 ruling).
Gate = Literal["E39-S01"]


@dataclass(frozen=True, slots=True)
class ProfileCap:
    field: str  # `AccountProfile` field
    column: str  # `account_profiles` column (21-database-schema.md Sec.3.2.4)
    unit: CapUnit
    gate: Gate = "E39-S01"


PROFILE_CAPS: Final[tuple[ProfileCap, ...]] = (
    ProfileCap("max_position_notional", "max_position_notional_usd", "usd"),
    ProfileCap("max_position_pct_equity", "max_position_pct_equity", "fraction"),
    ProfileCap("max_daily_loss", "max_daily_loss_usd", "usd"),
    ProfileCap("max_daily_loss_pct", "max_daily_loss_pct", "fraction"),
    ProfileCap("max_open_positions", "max_open_positions", "count"),
    ProfileCap("max_concurrent_orders", "max_concurrent_orders", "count"),
    ProfileCap("max_leverage_cap", "max_leverage_cap", "leverage"),
    ProfileCap("max_orders_per_minute", "max_orders_per_minute", "per_minute"),
)
