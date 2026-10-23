"""A profile body's schema refusals, its first validation pass and its mapper to the domain profile
(E28-T02 #906, slices B1a and B1b).

M13 may not import `candleviewer.api`, so the router hands this module the decoded body. A member
left out, or `null`, takes its contract default, never the stored value (R1C-08). Decimals are read
exactly: a percent moves its exponent and trailing zeros go first, so `profiles._fits` never strips
a long run. The first pass bounds every decimal by its column, whole digits and places alike (#906,
ruling of 2026-10-22 13:26Z), so a body it accepts maps, and the store takes it, with no 500 on the
way. A broken precondition is a `TypeError` naming the member, never its value.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from candleviewer.accounts.profiles import AccountProfile, exact_sum
from candleviewer.domain.primitives import TsUs
from candleviewer.domain.text import unpaired_surrogate

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
#: The rules `check_profile_input` can answer with (`ProfileRejected`'s first pass).
FIRST_PASS_RULES: Final = frozenset(
    "required not_allowed range precision ladder_sum above_leverage_cap cap_unbounded "
    "default_has_own_operation".split()
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


# -- The first pass (slice B1b). Rulings (a) to (c) and P14 are #906's, of 2026-10-22 13:26Z -----


@dataclass(frozen=True, slots=True)
class _Bound:
    """A decimal member's `range` and `precision`: above `low` (at least, unless `above`), below
    `high` (at most, unless `below`), and at most `places` decimal places."""

    low: Decimal
    high: Decimal
    places: int
    above: bool = True
    below: bool = True


_E20, _HUNDRED = Decimal("1E+20"), Decimal(100)
#: numeric(38,18): whole digits below 1E+20 (ruling (a)); a rung's `r` alike (ruling (b)).
_MONEY: Final = _Bound(Decimal(0), _E20, 18)
_PERCENT: Final = _Bound(Decimal(0), _HUNDRED, 6, below=False)  # numeric(9,6), a percent of equity
_LEVERAGE: Final = _Bound(Decimal(1), _HUNDRED, 2, above=False, below=False)  # numeric(10,2)
_MIN_LEG: Final = _Bound(Decimal(0), _E20, 18, above=False)  # zero is allowed: no minimum
_ATR_MULTIPLE: Final = _Bound(Decimal(0), Decimal("1E+6"), 4)  # numeric(10,4), ruling (a)
_FALLBACK: Final = _Bound(Decimal(0), _HUNDRED, 6)  # a percent, 0 to 100 exclusive
_DAILY_LOSS_PCT: Final = _Bound(Decimal("0.1"), Decimal(50), 6, above=False, below=False)
#: Each decimal member in the pass's order, read as sent: a percent stays a percent here.
_DECIMALS: Final = (
    ("leverage", _LEVERAGE),
    ("sizing.qty", _MONEY),
    ("sizing.notional_usd", _MONEY),
    ("sizing.pct", _PERCENT),
    ("sizing.risk_per_trade_pct", _PERCENT),
    ("sizing.risk_per_trade_usd", _MONEY),
    ("sizing.min_leg_notional_usd", _MIN_LEG),
    ("stop_loss.value", _MONEY),  # in whole ticks when the unit is `ticks`
    ("stop_loss.atr_multiple", _ATR_MULTIPLE),
    ("stop_loss.fallback_pct", _FALLBACK),
    ("take_profit.value", _MONEY),  # never whole ticks: it rounds to tick at submission (c)
    ("risk_caps.max_position_notional_usd", _MONEY),
    ("risk_caps.max_position_pct_equity", _PERCENT),
    ("risk_caps.max_daily_loss_usd", _MONEY),
    ("risk_caps.max_daily_loss_pct", _DAILY_LOSS_PCT),
    ("risk_caps.max_leverage_cap", _LEVERAGE),
)
#: A rung's members, stored in jsonb: 18 places on both, and `r` below 1E+20 (ruling (b)).
_RUNG: Final = (("qty_pct", _Bound(Decimal(0), _HUNDRED, 18, below=False)), ("r", _MONEY))
#: Each sizing mode's amounts (P4 to P6); `risk_based` takes one of its two.
_AMOUNTS: Final = {
    "fixed_qty": ("qty",),
    "fixed_notional": ("notional_usd",),
    "pct_equity": ("pct",),
    "risk_based": ("risk_per_trade_pct", "risk_per_trade_usd"),
}
_STOP_MEMBER: Final = {"atr": "atr_multiple", "ticks": "value", "percent": "value"}  # P8, P9
#: P13's loss bounds, in order; a pair is open when both its members are null or absent.
_LOSS_BOUNDS: Final = (
    ("position size", ("max_position_notional_usd", "max_position_pct_equity")),
    ("daily loss", ("max_daily_loss_usd", "max_daily_loss_pct")),
    ("open positions", ("max_open_positions",)),
    ("concurrent orders", ("max_concurrent_orders",)),
    ("leverage", ("max_leverage_cap",)),
)
#: P14 (#906, ruling of 2026-10-22 13:26Z): `name` holds no C0 control and no lone surrogate.
#: A U+0000 or a lone surrogate (no UTF-8 form; see `domain.text`) would be a driver 500, not a 422.
_C0: Final = re.compile(r"[\x00-\x1f]")
_OWN_OPERATION: Final = ProfileFieldError(
    "is_default", "default_has_own_operation", "The default binding has its own operation."
)
_CONTROL_IN_NAME: Final = ProfileFieldError(
    "name",
    "not_allowed",
    "name takes no control character (U+0000 to U+001F) or unpaired surrogate.",
)
_NEEDS_STOP: Final = ProfileFieldError(
    "stop_loss", "required", "risk_based sizing needs a stop_loss: the stop defines the risk."
)
_LISTED_TOO: Final = ProfileFieldError(
    "allowed_symbols",
    "not_allowed",
    "all_symbols allows every listed symbol, so allowed_symbols stays empty.",
)
_PAST_THE_LEG: Final = ProfileFieldError(
    "take_profit_ladder",
    "ladder_sum",
    "The take-profit rungs take at most the whole leg: their qty_pct sum to at most 100.",
    _HUNDRED,
)


def _rung_path(i: int, key: str) -> str:
    return f"take_profit_ladder[{i}].{key}"


def _decimals(body: ProfileBody) -> Iterator[tuple[str, Decimal | None, _Bound]]:
    """Each decimal member's path, its value as sent (`None` when absent) and its bound."""
    for path, bound in _DECIMALS:
        parent, _, key = path.rpartition(".")
        yield path, _dec((_obj(body, parent) or {}) if parent else body, key), bound
    for i, rung in enumerate(_rungs(body)):
        yield from ((_rung_path(i, key), _dec(rung, key), b) for key, b in _RUNG)


def _range(path: str, word: str, limit: Decimal) -> ProfileFieldError:
    return ProfileFieldError(path, "range", f"{path} must be {word} {limit:f}.", limit)


def _out_of_bounds(
    path: str, value: Decimal, bound: _Bound, places: int
) -> list[ProfileFieldError]:
    """P2 and P3 for one member; a message names the bound broken, never the value."""
    broken = []
    if value < bound.low or (bound.above and value == bound.low):
        broken.append(_range(path, "above" if bound.above else "at least", bound.low))
    elif value > bound.high or (bound.below and value == bound.high):
        broken.append(_range(path, "below" if bound.below else "at most", bound.high))
    if -int(value.as_tuple().exponent) > places:  # `_dec` dropped the trailing zeros first
        message = f"{path} takes at most {places} decimal places."
        broken.append(ProfileFieldError(path, "precision", message, Decimal(places)))
    return broken


def _sizing(sizing: ProfileBody) -> tuple[list[ProfileFieldError], set[str]]:
    """P4 to P6 on the amounts sent, and the paths of those they refuse (P2 and P3 skip them)."""
    mode = str(sizing.get("mode"))
    own = _AMOUNTS.get(mode)
    if own is None:
        raise TypeError("sizing.mode is not a sizing mode")
    sent = [m for amounts in _AMOUNTS.values() for m in amounts if sizing.get(m) is not None]
    paths = [f"sizing.{m}" for m in own]
    found = []
    if not set(own) & set(sent):
        message = f"{mode} sizing needs {' or '.join(paths)}."
        found.append(ProfileFieldError(paths[0], "required", message))
    others = [f"sizing.{m}" for m in sent if m not in own]
    found += [ProfileFieldError(p, "not_allowed", f"{mode} sizing takes no {p}.") for p in others]
    if len(set(own) & set(sent)) > 1:  # `risk_based` with both of its amounts
        message = f"{mode} sizing takes one of {' and '.join(paths)}."
        found.append(ProfileFieldError(paths[1], "not_allowed", message))
        others.append(paths[1])
    return found, set(others)


def check_profile_input(
    body: ProfileBody, *, stored_is_default: bool | None
) -> list[ProfileFieldError]:
    """The first pass over the `exclude_unset` dump of a body the schema phase passed: every
    failure, none cut, in this order. P1 `is_default` (a create counts as false); P14 `name`
    (#906, ruling of 2026-10-22 13:26Z); P2 and P3 `range` and `precision`, member by member in
    the order of `_DECIMALS` and then each rung; P4 to P6 the sizing amounts; P7 to P9 the stop;
    P10 `all_symbols` with a list; P11 `ladder_sum`; P12 `above_leverage_cap`; P13 `cap_unbounded`.
    `stored_is_default` is `None` on a create and the stored profile's `is_default` on a replace.
    Each rule reads what the client sent, never a default, and P11 and P12 wait until their
    members pass `range` and `precision`."""
    errors: list[ProfileFieldError] = []
    if bool(body.get("is_default")) != bool(stored_is_default):  # P1: a create counts as false
        errors.append(_OWN_OPERATION)
    name = body.get("name")
    if not isinstance(name, str):
        raise TypeError("name is not a string")
    if _C0.search(name) or unpaired_surrogate(name):  # P14
        errors.append(_CONTROL_IN_NAME)
    sizing, stop = _obj(body, "sizing") or {}, _obj(body, "stop_loss")
    shape, refused = _sizing(sizing)
    in_ticks = stop is not None and stop.get("unit") == "ticks"
    valid: dict[str, Decimal] = {}
    for path, value, bound in _decimals(body):  # P2 and P3
        if value is None or path in refused:
            continue
        places = 0 if in_ticks and path == "stop_loss.value" else bound.places  # whole ticks
        broken = _out_of_bounds(path, value, bound, places)
        errors += broken
        if not broken:
            valid[path] = value
    errors += shape
    if stop is None and sizing.get("mode") == "risk_based":  # P7
        errors.append(_NEEDS_STOP)
    elif stop is not None:
        unit = str(stop.get("unit"))
        member = _STOP_MEMBER.get(unit)
        if member is not None and stop.get(member) is None:  # P8, P9: as sent, not its default
            message = f"A stop in {unit} needs stop_loss.{member}."
            errors.append(ProfileFieldError(f"stop_loss.{member}", "required", message))
    if body.get("all_symbols") and body.get("allowed_symbols"):  # P10
        errors.append(_LISTED_TOO)
    shares = [_rung_path(i, "qty_pct") for i in range(len(_rungs(body)))]
    if all(p in valid for p in shares) and exact_sum(valid[p] for p in shares) > _HUNDRED:
        errors.append(_PAST_THE_LEG)  # P11, on the exact sum
    leverage, cap = valid.get("leverage"), valid.get("risk_caps.max_leverage_cap")
    if leverage is not None and cap is not None and leverage > cap:  # P12, audited
        message = "leverage must be at most risk_caps.max_leverage_cap."
        errors.append(ProfileFieldError("leverage", "above_leverage_cap", message, cap))
    caps = _obj(body, "risk_caps") or {}
    for what, members in _LOSS_BOUNDS if body.get("trading_enabled") else ():  # P13, audited
        if all(caps.get(m) is None for m in members):
            needed = " or ".join(f"risk_caps.{m}" for m in members)
            message = f"A trading-enabled profile caps {what}: set {needed}."
            errors.append(ProfileFieldError(f"risk_caps.{members[0]}", "cap_unbounded", message))
    return errors
