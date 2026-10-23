"""A stored profile's REST document (E28-T02 #906, slice D1b; 24-internal-schemas.md Sec.9.2).

`profile_document` renders a profile as the contract's `AccountProfile`, and `profile_body` its
`profile` member, the `AccountProfileInput` a client sends back to replace it. The values are the
stored ones, `profile_values(profile)`: a percent is the percent a user sees, and so is an offset
whose unit is `percent`, with no arithmetic here. Every member is answered at every depth, its
default included, and `null` only where the contract makes a member nullable: `stop_loss` and
`risk_caps` are always objects. A decimal is every stored digit, with no exponent and no trailing
fractional zero; a time is RFC 3339 in UTC to the microsecond (`22-api-openapi.yaml` conventions
C6 and C7). A read renders a row as stored: it is a projection, not a validator.

`created_at` (the row's) and `environment` (the account's, C-2.11) are arguments, since the model
holds neither; `warnings` are a read's, `profile_warnings` with no instrument listing. Nothing here
sets a header: the single-profile read sends `profile_etag` as its `ETag`.
"""

from __future__ import annotations

from decimal import Decimal

from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_validator import profile_warnings
from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.accounts.trade_groups import from_us
from candleviewer.domain.primitives import TsUs


def plain(value: Decimal) -> str:
    """C6: every digit, no exponent and no trailing fractional zero (`1E+2` is `100`, `1.500` is
    `1.5`). Never `normalize()`, which rounds at 28 digits: a `numeric(38,18)` holds 38."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else plain(value)


def rfc3339(us: TsUs) -> str:
    """C7: epoch microseconds as UTC, to the microsecond, with `Z`."""
    return from_us(us).isoformat(timespec="microseconds").replace("+00:00", "Z")


def profile_etag(profile: AccountProfile) -> str:
    """`ProfileETag`: weak, naming the profile and its version."""
    return f'W/"{profile.profile_id}:{profile.version}"'


def profile_body(profile: AccountProfile) -> dict[str, object]:
    """The contract's `AccountProfileInput` of `profile`, every member at every depth."""
    v = profile_values(profile)
    take = None if v.tp_offset_value is None else plain(v.tp_offset_value)
    return {
        "name": v.name,
        "is_default": v.is_default,
        "enabled": v.enabled,
        "trading_enabled": v.trading_enabled,
        "leverage": plain(v.leverage),
        "margin_mode": v.margin_mode,
        "position_mode": v.position_mode,
        "sizing": {
            "mode": v.sizing_mode,
            "qty": _plain(v.size_fixed_qty),
            "notional_usd": _plain(v.size_fixed_notional_usd),
            "pct": _plain(v.size_pct_equity),
            "risk_per_trade_pct": _plain(v.risk_pct_equity),
            "risk_per_trade_usd": _plain(v.risk_fixed_amount_usd),
            "min_leg_notional_usd": plain(v.min_leg_notional_usd),
        },
        "stop_loss": {
            "unit": v.sl_offset_unit,
            "value": plain(v.sl_offset_value),
            "atr_period": v.sl_atr_period,
            "atr_multiple": plain(v.sl_atr_multiple),
            "fallback_pct": plain(v.fallback_sl_offset_pct),
        },
        "take_profit": None if take is None else {"unit": v.tp_offset_unit, "value": take},
        "take_profit_ladder": [
            {"qty_pct": plain(rung.pct), "r": plain(rung.r)} for rung in v.tp_ladder or ()
        ],
        "risk_caps": {
            "max_position_notional_usd": _plain(v.max_position_notional_usd),
            "max_position_pct_equity": _plain(v.max_position_pct_equity),
            "max_daily_loss_usd": _plain(v.max_daily_loss_usd),
            "max_daily_loss_pct": _plain(v.max_daily_loss_pct),
            "max_open_positions": v.max_open_positions,
            "max_concurrent_orders": v.max_concurrent_orders,
            "max_leverage_cap": _plain(v.max_leverage_cap),
            "max_orders_per_minute": v.max_orders_per_minute,
        },
        "all_symbols": v.all_symbols,
        "allowed_symbols": list(v.allowed_symbols or ()),
        "blocked_symbols": list(v.blocked_symbols or ()),
        "require_native_stop": v.require_native_sl,
        "default_time_in_force": v.time_in_force_default,
        "reduce_only_default": v.reduce_only_default,
        "slippage_tolerance_bps": v.slippage_tolerance_bps,
    }


def profile_document(
    profile: AccountProfile, *, created_at: TsUs, environment: ExchangeEnv
) -> dict[str, object]:
    """The contract's `AccountProfile` of `profile`, created at `created_at` (its row's, us) on an
    account of `environment`."""
    return {
        "id": str(profile.profile_id),
        "exchange_account_id": str(profile.account_id),
        "environment": environment.value,
        "version": profile.version,
        "created_at": rfc3339(created_at),
        "updated_at": rfc3339(profile.updated_at),
        "warnings": [w.to_dict() for w in profile_warnings(profile)],
        "profile": profile_body(profile),
    }
