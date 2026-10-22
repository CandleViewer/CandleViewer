"""A profile body's schema refusals and its mapper to the domain profile (E28-T02 #906, slice B1a).

M13 may not import `candleviewer.api`, so the router hands this module the decoded body. A member
left out, or `null`, takes its contract default, never the stored value (R1C-08). Decimals are read
exactly: a percent moves its exponent and trailing zeros go first, so `profiles._fits` never strips
a long run. A broken precondition is a `TypeError` naming the member, never its value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.primitives import TsUs

#: The validated body: `AccountProfileInput.model_dump(mode="json", exclude_unset=True)`.
ProfileBody = Mapping[str, object]
#: C6, matched whole: `$` also accepts a trailing newline (#4098 R1S-05).
_C6: Final = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


@dataclass(frozen=True, slots=True)
class ProfileFieldError:
    """One entry of `ProfileRejected`'s `errors[]`. Its message names no value from the body."""

    field: str  # the JSON path of the body member: `allowed_symbols[2]`, `sizing.qty`
    rule: str  # the contract's rule name
    message: str
    limit: Decimal | None = None  # the bound broken, or the decimal places allowed
    symbol: str | None = None  # the instrument of an exchange limit (the second pass only)

    def to_dict(self) -> dict[str, str]:
        """The `Problem.errors[]` entry; `limit` is written without an exponent."""
        entry = {"field": self.field, "rule": self.rule, "message": self.message}
        if self.limit is not None:
            entry["limit"] = format(self.limit, "f")
        if self.symbol is not None:
            entry["symbol"] = self.symbol
        return entry


_NATIVE_STOP_OFF: Final = ProfileFieldError(
    "require_native_stop",
    "native_stop_mandatory",
    "Every order carries a native stop-loss, so it cannot be turned off.",
)
_NOT_TRUE: Final = ProfileFieldError("require_native_stop", "literal_error", "Input should be True")
_STOP_IN_R: Final = ProfileFieldError(
    "stop_loss.unit",
    "stop_defines_r",
    "The stop defines R, so stop_loss.unit cannot be r_multiple.",
)
_NULL_STOP: Final = ProfileFieldError(
    "stop_loss", "model_type", "stop_loss is an object; leave it out for its default."
)
_NULL_CAPS: Final = ProfileFieldError(
    "risk_caps", "model_type", "risk_caps is an object; leave it out for no caps."
)
#: The rules `schema_errors` can answer with, each in the contract's or the model's own words.
SCHEMA_RULES: Final = frozenset(
    e.rule for e in (_NATIVE_STOP_OFF, _NOT_TRUE, _STOP_IN_R, _NULL_STOP, _NULL_CAPS)
)


def field_path(loc: Sequence[str | int]) -> str:
    """`("take_profit_ladder", 3, "qty_pct")` is `take_profit_ladder[3].qty_pct`; `()` is `""`."""
    parts = (f"[{p}]" if isinstance(p, int) else (f".{p}" if i else p) for i, p in enumerate(loc))
    return "".join(parts)


def schema_errors(
    raw: object, model_errors: Sequence[ProfileFieldError]
) -> list[ProfileFieldError]:
    """The decoded body's schema failures: the generated model's entries (`model_errors`, as the
    router renders them) minus any for a member named here, then these in the contract's member
    order, never truncated. Empty only when `model_errors` is."""
    own: list[ProfileFieldError] = []
    if isinstance(raw, Mapping):
        stop, flag = raw.get("stop_loss", {}), raw.get("require_native_stop", True)
        if stop is None:
            own.append(_NULL_STOP)
        elif isinstance(stop, Mapping) and stop.get("unit") == "r_multiple":
            own.append(_STOP_IN_R)
        if raw.get("risk_caps", {}) is None:
            own.append(_NULL_CAPS)
        if flag is False:
            own.append(_NATIVE_STOP_OFF)
        elif flag is not True:  # the model takes 1 and 1.0 for True (R1S-06)
            own.append(_NOT_TRUE)
    named = {e.field for e in own}
    return [e for e in model_errors if e.field not in named] + own


def _get(obj: ProfileBody, key: str, default: object) -> object:
    """The member's value; a member left out, or `null`, takes `default`."""
    value = obj.get(key)
    return default if value is None else value


def _dec(
    obj: ProfileBody, key: str, default: str | None = None, *, percent: bool = False
) -> Decimal | None:
    """A C6 member as the exact `Decimal` (a percent as its fraction); `None` if absent."""
    raw = _get(obj, key, default)
    if raw is None:
        return None
    if not isinstance(raw, str) or _C6.fullmatch(raw) is None:
        raise TypeError(f"{key} is not a C6 decimal string")
    whole, _, fraction = raw.partition(".")
    fraction = fraction.rstrip("0")  # `profiles._fits` strips them one digit at a time
    digits = f"{whole}.{fraction}" if fraction else whole
    # The constructor is exact; `scaleb` would round past 28 digits.
    return Decimal(f"{digits}E-2" if percent else digits)


def _obj(body: ProfileBody, key: str) -> ProfileBody | None:
    value = body.get(key)
    if value is not None and not isinstance(value, Mapping):
        raise TypeError(f"{key} is not an object")
    return value


def _rungs(body: ProfileBody) -> list[ProfileBody]:
    rungs = _get(body, "take_profit_ladder", [])
    if not isinstance(rungs, list):
        raise TypeError("take_profit_ladder is not a list")
    if not all(isinstance(rung, Mapping) for rung in rungs):
        raise TypeError("a take_profit_ladder rung is not an object")
    return rungs


def map_profile_input(
    body: ProfileBody, *, profile_id: UUID, account_id: UUID, version: int, updated_at: TsUs
) -> AccountProfile:
    """The domain profile of a body the first pass accepted; one it refuses raises `ValueError`
    (the domain model's `ValidationError`). The store writes `version` and `updated_at`."""
    sizing, stop = _obj(body, "sizing") or {}, _obj(body, "stop_loss") or {}
    take, caps = _obj(body, "take_profit") or {}, _obj(body, "risk_caps") or {}
    stop_unit, take_unit = _get(stop, "unit", "ticks"), take.get("unit")  # no stop is 10 ticks
    return AccountProfile.model_validate(
        {
            "profile_id": profile_id,
            "account_id": account_id,
            "name": body.get("name"),
            "is_default": _get(body, "is_default", False),
            "enabled": _get(body, "enabled", True),
            "trading_enabled": _get(body, "trading_enabled", False),
            "version": version,
            "sizing_mode": sizing.get("mode"),
            "fixed_qty": _dec(sizing, "qty"),
            "fixed_notional": _dec(sizing, "notional_usd"),
            "pct_equity": _dec(sizing, "pct", percent=True),
            "risk_pct_equity": _dec(sizing, "risk_per_trade_pct", percent=True),
            "risk_fixed_amount": _dec(sizing, "risk_per_trade_usd"),
            "min_leg_notional": _dec(sizing, "min_leg_notional_usd", "0"),
            "leverage": _dec(body, "leverage"),
            "margin_mode": _get(body, "margin_mode", "cross"),
            "position_mode": _get(body, "position_mode", "one_way"),
            "require_native_sl": _get(body, "require_native_stop", True),  # the domain re-checks
            "sl_offset_value": _dec(stop, "value", "10", percent=stop_unit == "percent"),
            "sl_offset_unit": stop_unit,
            "sl_atr_period": _get(stop, "atr_period", 14),
            "sl_atr_multiple": _dec(stop, "atr_multiple", "2"),
            "fallback_sl_offset_pct": _dec(stop, "fallback_pct", "2", percent=True),
            "tp_offset_value": _dec(take, "value", percent=take_unit == "percent"),
            "tp_offset_unit": take_unit,
            "tp_ladder": [
                {"qty_pct": _dec(rung, "qty_pct", percent=True), "r": _dec(rung, "r")}
                for rung in _rungs(body)
            ],
            "max_position_notional": _dec(caps, "max_position_notional_usd"),
            "max_position_pct_equity": _dec(caps, "max_position_pct_equity", percent=True),
            "max_daily_loss": _dec(caps, "max_daily_loss_usd"),
            "max_daily_loss_pct": _dec(caps, "max_daily_loss_pct", percent=True),
            "max_open_positions": caps.get("max_open_positions"),
            "max_concurrent_orders": caps.get("max_concurrent_orders"),
            "max_leverage_cap": _dec(caps, "max_leverage_cap"),
            "max_orders_per_minute": _get(caps, "max_orders_per_minute", 30),
            "all_symbols": _get(body, "all_symbols", False),
            "allowed_symbols": _get(body, "allowed_symbols", ()),
            "denied_symbols": _get(body, "blocked_symbols", ()),
            "reduce_only_default": _get(body, "reduce_only_default", False),
            "time_in_force_default": _get(body, "default_time_in_force", "GTC"),
            "slippage_tolerance_bps": _get(body, "slippage_tolerance_bps", 10),
            "updated_at": updated_at,
        }
    )
