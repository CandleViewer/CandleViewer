"""The leg sizer (24 Sec.9.3, E28-T03 #907): the one implementation of a profile's sizing rule.

Pure (no I/O, clock, logs or metrics) and `Decimal` only; a skip or a failure is a typed outcome
with a closed reason (Sec.9.3.4), never an exception. Every step runs at 100 digits rounding down.
A `Price` carries at most 38 digits, 18 of them places (the profile's numeric(38,18)), so a stop's
sums and products are exact there; a quotient (or a wallet figure past that bound) rounds down,
never up onto a lot step. PR2 adds the clamps (Sec.9.3.2), the margin failure, the explanation and
the take-profits at the marked steps.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profiles import AccountProfile, SymbolScope
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Qty, Side, Symbol

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_FLOOR: Final = Context(prec=100, rounding=ROUND_FLOOR)
Price = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)]
MinimumKind = Literal["min_order_qty", "min_notional", "min_leg_notional"]
Minimum = tuple[MinimumKind, Decimal]
Outcome = Literal["ok", "skip", "fail"]
#: Where step 2's reference price came from (Sec.9.3 step 2).
RefSource = Literal["limit", "marketable_limit_mid", "mid", "last"]


class SizingIntent(BaseModel):
    """What the leg asks for; `price` is a limit order's, a market order has none (a client
    price never sizes a market order, Sec.9.3.4)."""

    model_config = _FROZEN
    symbol: Symbol
    side: Side
    order_type: Literal["market", "limit"]
    price: Price | None = None

    @model_validator(mode="after")
    def _price_follows_order_type(self) -> Self:
        if (self.price is None) == (self.order_type == "limit"):
            raise ValueError("a limit order takes a price and a market order none")
        return self


class AtrReading(BaseModel):
    """A self-describing ATR: `timeframe` is the caller's bar timeframe (no domain type exists;
    the caller supplies it), `as_of` the reading's time; `value` is `None` in warm-up."""

    model_config = _FROZEN
    timeframe: Annotated[str, Field(min_length=1, max_length=16)]
    period: Annotated[int, Field(ge=1)]
    value: Price | None
    as_of: AwareDatetime


class SizingMarket(BaseModel):
    """The ticker's prices (neither when stale, 24 Sec.9.3 step 2) and the ATR."""

    model_config = _FROZEN
    mid: Price | None = None
    last_price: Price | None = None
    atr: AtrReading | None = None


class SkipReason(StrEnum):
    """A leg left out (grey), never a failure."""

    PROFILE_DISABLED = "profile_disabled"
    SYMBOL_NOT_ALLOWED = "symbol_not_allowed"
    SYMBOL_DENIED = "symbol_denied"
    BELOW_MIN_NOTIONAL = "below_min_notional"


class FailReason(StrEnum):
    """A leg that cannot be sized (red), never a skip."""

    NO_REFERENCE_PRICE = "no_reference_price"
    INVALID_STOP_DISTANCE = "invalid_stop_distance"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    CAP_BREACHED = "cap_breached"
    FIGURE_UNKNOWN = "figure_unknown"
    LEVERAGE_UNAVAILABLE = "leverage_unavailable"


@dataclass(frozen=True, slots=True)
class ResolvedStop:
    """The native stop on the tick grid; `fallback` when no ATR reading served."""

    price: Decimal
    distance: Decimal
    fallback: bool


@dataclass(frozen=True, slots=True)
class LegSizing:
    """The outcome and what was computed before it (a gate skip: nothing). `risk_usdt` is 1R
    (`distance * qty`); `risk_with_fees_usdt` adds both taker fees, `None` for an unknown rate;
    `minimum` is the one a `below_min_notional` leg missed. `limit_price` is the intent's, kept
    beside `ref_price` so PR2 can judge every cap at the larger of the two notionals."""

    outcome: Outcome
    reason: SkipReason | FailReason | None = None
    ref_price: Decimal | None = None
    stop: ResolvedStop | None = None
    qty: Decimal | None = None
    notional: Decimal | None = None
    risk_usdt: Decimal | None = None
    risk_with_fees_usdt: Decimal | None = None
    minimum: Minimum | None = None
    ref_source: RefSource | None = None
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        kinds: dict[str, type] = {"ok": type(None), "skip": SkipReason, "fail": FailReason}
        kind = kinds[self.outcome]
        if not isinstance(self.reason, kind):
            raise TypeError(f"a {self.outcome} outcome takes no reason {self.reason!r}")


def _to_grid(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    return (value / step).to_integral_value(rounding) * step


def resolve_stop(
    side: Side, profile: AccountProfile, ref: Decimal, inst: Instrument, atr: AtrReading | None
) -> ResolvedStop:
    """24 Sec.9.3.1: below a long's entry, above a short's, on the tick away from entry. An `atr`
    stop with no reading of `sl_atr_period` falls back to `fallback_sl_offset_pct`."""
    with localcontext(_FLOOR):
        unit, fallback = profile.sl_offset_unit, False
        if unit == "ticks":
            offset = profile.sl_offset_value * inst.tick_size
        elif unit == "percent":
            offset = ref * profile.sl_offset_value
        elif unit != "atr":  # r_multiple defines R; AccountProfile refuses it
            raise ValueError(f"no stop resolves in unit {unit!r}")
        elif atr is None or atr.value is None or atr.period != profile.sl_atr_period:
            offset, fallback = ref * profile.fallback_sl_offset_pct, True
        else:
            offset = atr.value * profile.sl_atr_multiple
        if side == "buy":
            price = _to_grid(ref - offset, inst.tick_size, ROUND_FLOOR)
        elif side == "sell":
            price = _to_grid(ref + offset, inst.tick_size, ROUND_CEILING)
        else:  # a programming error: `Side` is validated at every boundary
            raise ValueError(f"no stop resolves for side {side!r}")
        return ResolvedStop(price=price, distance=abs(ref - price), fallback=fallback)


def _fee_per_unit(ref: Decimal, stop: ResolvedStop, taker: Decimal | None) -> Decimal | None:
    """Entry at `ref`, exit at the further of `ref` and the stop (ADR-0040 OPEN-4)."""
    return None if taker is None else (ref + max(ref, stop.price)) * taker


def _raw_qty(p: AccountProfile, w: AccountFigures, ref: Decimal, stop: ResolvedStop) -> Qty | None:
    """Steps 4 and 5: the mode's quantity, unrounded; `None` when a figure it reads is unknown."""
    equity, notional = w.equity, p.fixed_notional
    if p.sizing_mode == "fixed_qty":
        return p.fixed_qty
    if p.sizing_mode == "fixed_notional":
        return None if notional is None else notional / ref
    if p.sizing_mode == "pct_equity":
        pct = p.pct_equity
        return None if equity is None or pct is None else equity * pct * p.leverage / ref
    budget = p.risk_fixed_amount
    if budget is None and p.risk_pct_equity is not None and equity is not None:
        budget = equity * p.risk_pct_equity
    fee = _fee_per_unit(ref, stop, w.taker_fee_rate)
    if budget is None or fee is None:
        return None
    return budget / (stop.distance + fee)  # step 5: the fees shrink it


def _reference(intent: SizingIntent, m: SizingMarket) -> tuple[Decimal, RefSource] | None:
    """Step 2: a marketable limit (a buy at or above mid, a sell at or below) sizes at its
    expected fill, mid; any other limit, or one with no mid, at its price; a market order at mid,
    else last."""
    if intent.price is None:
        if m.mid is not None:
            return m.mid, "mid"
        return None if m.last_price is None else (m.last_price, "last")
    if m.mid is None:
        return intent.price, "limit"
    marketable = m.mid <= intent.price if intent.side == "buy" else m.mid >= intent.price
    return (m.mid, "marketable_limit_mid") if marketable else (intent.price, "limit")


def _missed(qty: Qty, notional: Decimal, p: AccountProfile, inst: Instrument) -> Minimum | None:
    if qty < inst.min_order_qty:
        return ("min_order_qty", inst.min_order_qty)
    floor: Minimum = ("min_notional", inst.min_notional)
    if p.min_leg_notional > inst.min_notional:
        floor = ("min_leg_notional", p.min_leg_notional)
    return floor if notional < floor[1] else None


def size_leg(
    intent: SizingIntent,
    profile: AccountProfile,
    wallet: AccountFigures,
    inst: Instrument,
    metrics: SizingMarket,
) -> LegSizing:
    """24 Sec.9.3: one leg's size, or why it is skipped or failed.

    Until E28-T03 PR2 lands, an `ok` result is NOT submit-safe (no caps, no margin check): no
    caller may wire it, and it stays out of `candleviewer.accounts`' exports."""
    if intent.symbol != inst.symbol:
        raise ValueError("the intent and the instrument name different symbols")
    scope = SymbolScope.of(profile)  # 1. The gate; an empty allow-list admits nothing (D11)
    if not profile.enabled or not profile.trading_enabled:
        return LegSizing("skip", SkipReason.PROFILE_DISABLED)
    if not scope.admits(inst):
        return LegSizing("skip", SkipReason.SYMBOL_NOT_ALLOWED)
    if scope.denied.matches(inst.symbol, wildcard=True):
        return LegSizing("skip", SkipReason.SYMBOL_DENIED)
    found = _reference(intent, metrics)  # 2
    if found is None:
        return LegSizing("fail", FailReason.NO_REFERENCE_PRICE)
    ref, source = found
    stop = resolve_stop(intent.side, profile, ref, inst, metrics.atr)  # 3, measured from `ref`
    seen = LegSizing("ok", None, ref, stop, ref_source=source, limit_price=intent.price)
    # Both, per step 3: a stop at or below 0 is no order, and a zero distance would divide by zero
    # in risk_based (a sub-1e-100 short offset rounds back onto entry).
    if stop.price <= 0 or stop.distance <= 0:
        return replace(seen, outcome="fail", reason=FailReason.INVALID_STOP_DISTANCE)
    with localcontext(_FLOOR):
        raw = _raw_qty(profile, wallet, ref, stop)  # 4 and 5
        if raw is None:
            return replace(seen, outcome="fail", reason=FailReason.FIGURE_UNKNOWN)
        # 6. clamp_to_caps (Sec.9.3.2, each clamp recorded): E28-T03 PR2 hook. Every notional,
        # leverage and margin cap is judged at the larger of qty * limit_price and qty * ref.
        # 7: always floor to the lot; never below 0 (an equity <= 0 sizes nothing, Sec.9.3.4)
        qty = max(_to_grid(raw, inst.qty_step, ROUND_FLOOR), Decimal(0))
        notional, fee = qty * ref, _fee_per_unit(ref, stop, wallet.taker_fee_rate)
        with_fees = None if fee is None else qty * (stop.distance + fee)
        risk = qty * stop.distance
        leg = replace(
            seen, qty=qty, notional=notional, risk_usdt=risk, risk_with_fees_usdt=with_fees
        )
        missed = _missed(qty, notional, profile, inst)  # 8
    if missed is not None:
        return replace(leg, outcome="skip", reason=SkipReason.BELOW_MIN_NOTIONAL, minimum=missed)
    # 8b. Available margin x 0.98, failure insufficient_margin: E28-T03 PR2 hook.
    # 9. The explanation and the take-profits (Sec.9.3.3): E28-T03 PR2 hook.
    return leg
