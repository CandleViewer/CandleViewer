"""Per-account execution profiles (E28-T01 #905; 24-internal-schemas.md Sec.9.2, M13).

`AccountProfile` is the profile the sizer (E28-T03), the guard (E28-T04) and the fan-out (E34)
read, and the frozen copy a trade-group leg keeps (ADR-0008 rule 3). `profile_from_row` and
`profile_values` are the one adapter between it and an `account_profiles` row
(21-database-schema.md Sec.3.2.4):

- percentages are the percent a user sees (0..100) in Postgres and fractions (0..1) here, and so
  is an offset whose unit is `percent`; a ladder rung's `pct` maps to `qty_pct`;
- `blocked_symbols` is `denied_symbols` here, a NULL symbol list an empty tuple, and times are
  `TsUs` (24 C4);
- every value must fit its column exactly, so a valid profile round-trips through the database
  with `Decimal` equality; the conversions move the exponent and the ladder is summed exactly, so
  no 28-digit context rounds a digit away.

The model repeats the database's rules (SR-E28-08: the floor holds at every layer): the native
stop is mandatory and never defined in R, the sizing fields match `sizing_mode`, the ladder takes
at most the whole leg, and a trading-enabled profile bounds every cap (SR-E28-01, decision D11).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, Inexact, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from candleviewer.domain.primitives import AccountId, Notional, Qty, TsUs
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileRow,
    AccountProfileValues,
    LadderRung,
)

SizingMode = Literal["fixed_qty", "fixed_notional", "pct_equity", "risk_based"]
OffsetUnit = Literal["ticks", "percent", "r_multiple", "atr"]
#: R is defined by the stop distance, so the stop is never expressed in R (24 Sec.9.3.1).
StopUnit = Literal["ticks", "percent", "atr"]
MarginMode = Literal["cross", "isolated"]
PositionMode = Literal["one_way", "hedge"]
TimeInForce = Literal["GTC", "IOC", "FOK", "PostOnly"]
#: A listed symbol, or an anchored suffix pattern (`*USDT`) expanded at evaluation time against the
#: instrument cache, never at write time (E28-T04; SR-E28-06). A bare `*` is refused.
SymbolPattern = Annotated[str, StringConstraints(pattern=r"^\*?[A-Z0-9]{4,20}$")]

_FROZEN = ConfigDict(frozen=True, extra="forbid")
#: Digits the ladder's exact sum may carry; more is refused rather than rounded.
_EXACT_DIGITS = 200
#: The largest exponent a profile value may move to; no column comes near it (38 digits at most).
_EXPONENT_LIMIT = 400
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_US = timedelta(microseconds=1)
#: (precision, scale) of the columns, 21 Sec.3.2.4.
_MONEY, _PERCENT, _LEVERAGE, _MULTIPLE = (38, 18), (9, 6), (10, 2), (10, 4)

Fraction = Annotated[Decimal, Field(gt=0, le=1)]
Positive = Annotated[Decimal, Field(gt=0)]


class TakeProfitRung(BaseModel):
    """One rung of a profile's take-profit ladder, resolved per leg (24 Sec.9.3.3)."""

    model_config = _FROZEN

    qty_pct: Fraction
    r: Positive


class AccountProfile(BaseModel):
    """24-internal-schemas.md Sec.9.2: one `account_profiles` row, in domain units."""

    model_config = _FROZEN

    profile_id: UUID
    account_id: AccountId
    name: Annotated[str, Field(min_length=1, max_length=80)]
    is_default: bool
    enabled: bool
    trading_enabled: bool
    version: Annotated[int, Field(ge=1)]
    # sizing
    sizing_mode: SizingMode
    fixed_qty: Annotated[Qty, Field(gt=0)] | None
    fixed_notional: Annotated[Notional, Field(gt=0)] | None
    pct_equity: Fraction | None
    risk_pct_equity: Fraction | None
    risk_fixed_amount: Annotated[Notional, Field(gt=0)] | None
    min_leg_notional: Annotated[Notional, Field(ge=0)]
    qty_rounding: Literal["floor"] = "floor"
    # leverage and mode
    leverage: Annotated[Decimal, Field(ge=1, le=100)]
    margin_mode: MarginMode
    position_mode: PositionMode
    # protective offsets: the native stop is mandatory (C-2.6, `ap_native_sl`)
    require_native_sl: Literal[True] = True
    sl_offset_value: Positive
    sl_offset_unit: StopUnit
    sl_atr_period: Annotated[int, Field(ge=2, le=200)]
    sl_atr_multiple: Positive
    fallback_sl_offset_pct: Annotated[Decimal, Field(gt=0, lt=1)]
    tp_offset_value: Positive | None
    tp_offset_unit: OffsetUnit | None
    tp_ladder: tuple[TakeProfitRung, ...] = ()
    # risk caps, server-enforced (one gate each: `profile_caps.PROFILE_CAPS`)
    max_position_notional: Annotated[Notional, Field(gt=0)] | None
    max_position_pct_equity: Fraction | None
    max_daily_loss: Annotated[Notional, Field(gt=0)] | None
    max_daily_loss_pct: Fraction | None
    max_open_positions: Annotated[int, Field(ge=1, le=50)] | None
    max_concurrent_orders: Annotated[int, Field(ge=1, le=500)] | None
    max_leverage_cap: Annotated[Decimal, Field(ge=1, le=100)] | None
    max_orders_per_minute: Annotated[int, Field(ge=1, le=600)]
    # symbols: `all_symbols` is explicit; an empty allow-list without it allows nothing (D11)
    all_symbols: bool
    allowed_symbols: tuple[SymbolPattern, ...] = ()
    denied_symbols: tuple[SymbolPattern, ...] = ()
    # order defaults
    reduce_only_default: bool
    time_in_force_default: TimeInForce
    slippage_tolerance_bps: Annotated[int, Field(ge=0, le=1000)]
    updated_at: TsUs

    @model_validator(mode="after")
    def _rules(self) -> AccountProfile:
        _check_sizing(self)
        if (self.tp_offset_value is None) != (self.tp_offset_unit is None):
            raise ValueError("tp_offset_value and tp_offset_unit are set together")
        if _exact_sum(rung.qty_pct for rung in self.tp_ladder) > 1:
            raise ValueError("the take-profit ladder takes more than the whole leg")
        if self.max_leverage_cap is not None and self.leverage > self.max_leverage_cap:
            raise ValueError("leverage is above max_leverage_cap")
        if self.all_symbols and self.allowed_symbols:
            raise ValueError("all_symbols takes no allow-list")
        unbounded = _unbounded_caps(self) if self.trading_enabled else []
        if unbounded:
            raise ValueError(f"a trading-enabled profile bounds every cap: {unbounded}")
        profile_values(self)  # every value fits its column
        return self


def _check_sizing(p: AccountProfile) -> None:
    """`ap_sizing_shape`: exactly the field(s) of `sizing_mode`, and `risk_based` takes exactly one
    of `risk_pct_equity` and `risk_fixed_amount`."""
    present = {
        name
        for name in ("fixed_qty", "fixed_notional", "pct_equity", "risk_pct_equity")
        if getattr(p, name) is not None
    }
    if p.risk_fixed_amount is not None:
        present.add("risk_fixed_amount")
    allowed = {
        "fixed_qty": [{"fixed_qty"}],
        "fixed_notional": [{"fixed_notional"}],
        "pct_equity": [{"pct_equity"}],
        "risk_based": [{"risk_pct_equity"}, {"risk_fixed_amount"}],
    }[p.sizing_mode]
    if present not in allowed:
        raise ValueError(f"sizing_mode {p.sizing_mode} does not match the sizing fields set")


def _unbounded_caps(p: AccountProfile) -> list[str]:
    """`ap_trading_caps` (SR-E28-01, decision D11)."""
    missing = []
    if p.max_position_notional is None and p.max_position_pct_equity is None:
        missing.append("position size")
    if p.max_daily_loss is None and p.max_daily_loss_pct is None:
        missing.append("daily loss")
    for name in ("max_open_positions", "max_concurrent_orders", "max_leverage_cap"):
        if getattr(p, name) is None:
            missing.append(name)
    return missing


def _shift(value: Decimal, places: int) -> Decimal:
    """`value` times 10**places, exactly: only the exponent moves, so no context precision
    rounds the digits (a percent and its fraction hold the same digits)."""
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("a profile value must be finite")
    if abs(exponent + places) > _EXPONENT_LIMIT:  # no column holds it, and Decimal() would trap
        raise ValueError("a profile value is out of range")
    return Decimal((sign, digits, exponent + places))


def _exact_sum(values: Iterable[Decimal]) -> Decimal:
    """The sum with every digit kept: a rounded sum could pass `<= 1` when the exact one does not
    (the database sums the stored `numeric`s exactly)."""
    context = Context(prec=_EXACT_DIGITS, traps=[Inexact, InvalidOperation])
    total = Decimal(0)
    try:
        for value in values:
            total = context.add(total, value)
    except (Inexact, InvalidOperation):
        raise ValueError("the take-profit ladder is too precise to sum exactly") from None
    return total


def _fits(value: Decimal, column: tuple[int, int], field: str, *, shift: int = 0) -> Decimal:
    """`value` times 10**shift, exactly, if its column stores that exactly; Postgres would round
    or refuse it. Counted on the digits themselves: no context rounding can hide one."""
    precision, scale = column
    shifted = _shift(value, shift)
    _, digits, exponent = shifted.as_tuple()
    if not isinstance(exponent, int):  # unreachable: _shift refused it
        raise ValueError("a profile value must be finite")
    if not any(digits):  # zero fits every column, whatever exponent it was written with
        return shifted
    while exponent < 0 and len(digits) > 1 and digits[-1] == 0:  # trailing zeros need no scale
        digits, exponent = digits[:-1], exponent + 1
    fraction = max(-exponent, 0)
    whole = len(digits) + exponent if any(digits) else 0
    if fraction > scale or whole > precision - scale:
        raise ValueError(f"{field} does not fit numeric({precision},{scale})")
    return shifted


def _opt(value: Decimal | None, column: tuple[int, int], field: str) -> Decimal | None:
    return None if value is None else _fits(value, column, field)


def _to_percent(value: Decimal | None, field: str) -> Decimal | None:
    return None if value is None else _fits(value, _PERCENT, field, shift=2)


def _offset_out(value: Decimal, unit: str | None, field: str) -> Decimal:
    return _fits(value, _MONEY, field, shift=2 if unit == "percent" else 0)


def _offset_in(value: Decimal, unit: str | None) -> Decimal:
    return _shift(value, -2) if unit == "percent" else value


def _fraction(value: Decimal | None) -> Decimal | None:
    return None if value is None else _shift(value, -2)


def _to_us(moment: datetime) -> TsUs:
    """Exact epoch microseconds of an aware datetime (integer arithmetic, no float rounding)."""
    return (moment - _EPOCH) // _ONE_US


def profile_values(p: AccountProfile) -> AccountProfileValues:
    """The writable columns of `p` in their stored units (the inverse of `profile_from_row`)."""
    ladder = tuple(LadderRung(pct=_shift(rung.qty_pct, 2), r=rung.r) for rung in p.tp_ladder)
    return AccountProfileValues(
        name=p.name,
        is_default=p.is_default,
        enabled=p.enabled,
        trading_enabled=p.trading_enabled,
        leverage=_fits(p.leverage, _LEVERAGE, "leverage"),
        margin_mode=p.margin_mode,
        position_mode=p.position_mode,
        sizing_mode=p.sizing_mode,
        size_fixed_qty=_opt(p.fixed_qty, _MONEY, "fixed_qty"),
        size_fixed_notional_usd=_opt(p.fixed_notional, _MONEY, "fixed_notional"),
        size_pct_equity=_to_percent(p.pct_equity, "pct_equity"),
        risk_pct_equity=_to_percent(p.risk_pct_equity, "risk_pct_equity"),
        risk_fixed_amount_usd=_opt(p.risk_fixed_amount, _MONEY, "risk_fixed_amount"),
        min_leg_notional_usd=_fits(p.min_leg_notional, _MONEY, "min_leg_notional"),
        sl_offset_value=_offset_out(p.sl_offset_value, p.sl_offset_unit, "sl_offset_value"),
        sl_offset_unit=p.sl_offset_unit,
        sl_atr_period=p.sl_atr_period,
        sl_atr_multiple=_fits(p.sl_atr_multiple, _MULTIPLE, "sl_atr_multiple"),
        fallback_sl_offset_pct=_fits(
            p.fallback_sl_offset_pct, _PERCENT, "fallback_sl_offset_pct", shift=2
        ),
        tp_offset_value=(
            None
            if p.tp_offset_value is None
            else _offset_out(p.tp_offset_value, p.tp_offset_unit, "tp_offset_value")
        ),
        tp_offset_unit=p.tp_offset_unit,
        tp_ladder=ladder or None,
        require_native_sl=p.require_native_sl,
        max_position_notional_usd=_opt(p.max_position_notional, _MONEY, "max_position_notional"),
        max_position_pct_equity=_to_percent(p.max_position_pct_equity, "max_position_pct_equity"),
        max_daily_loss_usd=_opt(p.max_daily_loss, _MONEY, "max_daily_loss"),
        max_daily_loss_pct=_to_percent(p.max_daily_loss_pct, "max_daily_loss_pct"),
        max_open_positions=p.max_open_positions,
        max_concurrent_orders=p.max_concurrent_orders,
        max_leverage_cap=_opt(p.max_leverage_cap, _LEVERAGE, "max_leverage_cap"),
        max_orders_per_minute=p.max_orders_per_minute,
        all_symbols=p.all_symbols,
        allowed_symbols=p.allowed_symbols or None,
        blocked_symbols=p.denied_symbols or None,
        reduce_only_default=p.reduce_only_default,
        time_in_force_default=p.time_in_force_default,
        slippage_tolerance_bps=p.slippage_tolerance_bps,
    )


def profile_from_row(row: AccountProfileRow) -> AccountProfile:
    """The domain model of a stored row. A stored row the model refuses raises `ValueError`
    (`pydantic.ValidationError`, a subclass, for any field the model checks) rather than being
    read: the database does not check symbol entries (`SymbolPattern` does), and any other
    refusal is a schema drift."""
    v = row.values
    ladder = [{"qty_pct": _shift(rung.pct, -2), "r": rung.r} for rung in v.tp_ladder or ()]
    return AccountProfile.model_validate(
        {
            "profile_id": row.id,
            "account_id": row.exchange_account_id,
            "name": v.name,
            "is_default": v.is_default,
            "enabled": v.enabled,
            "trading_enabled": v.trading_enabled,
            "version": row.version,
            "sizing_mode": v.sizing_mode,
            "fixed_qty": v.size_fixed_qty,
            "fixed_notional": v.size_fixed_notional_usd,
            "pct_equity": _fraction(v.size_pct_equity),
            "risk_pct_equity": _fraction(v.risk_pct_equity),
            "risk_fixed_amount": v.risk_fixed_amount_usd,
            "min_leg_notional": v.min_leg_notional_usd,
            "leverage": v.leverage,
            "margin_mode": v.margin_mode,
            "position_mode": v.position_mode,
            "require_native_sl": v.require_native_sl,
            "sl_offset_value": _offset_in(v.sl_offset_value, v.sl_offset_unit),
            "sl_offset_unit": v.sl_offset_unit,
            "sl_atr_period": v.sl_atr_period,
            "sl_atr_multiple": v.sl_atr_multiple,
            "fallback_sl_offset_pct": _shift(v.fallback_sl_offset_pct, -2),
            "tp_offset_value": (
                None
                if v.tp_offset_value is None
                else _offset_in(v.tp_offset_value, v.tp_offset_unit)
            ),
            "tp_offset_unit": v.tp_offset_unit,
            "tp_ladder": ladder,
            "max_position_notional": v.max_position_notional_usd,
            "max_position_pct_equity": _fraction(v.max_position_pct_equity),
            "max_daily_loss": v.max_daily_loss_usd,
            "max_daily_loss_pct": _fraction(v.max_daily_loss_pct),
            "max_open_positions": v.max_open_positions,
            "max_concurrent_orders": v.max_concurrent_orders,
            "max_leverage_cap": v.max_leverage_cap,
            "max_orders_per_minute": v.max_orders_per_minute,
            "all_symbols": v.all_symbols,
            "allowed_symbols": v.allowed_symbols or (),
            "denied_symbols": v.blocked_symbols or (),
            "reduce_only_default": v.reduce_only_default,
            "time_in_force_default": v.time_in_force_default,
            "slippage_tolerance_bps": v.slippage_tolerance_bps,
            "updated_at": _to_us(row.updated_at),
        }
    )
