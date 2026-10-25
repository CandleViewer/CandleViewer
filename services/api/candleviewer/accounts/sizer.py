"""The leg sizer (24 Sec.9.3, E28-T03 #907): the one implementation of a profile's sizing rule.

Pure (no I/O, clock, logs or metrics) and `Decimal` only; a skip or a failure is a typed outcome
with a closed reason (Sec.9.3.4), never an exception. Every step runs at 100 digits rounding down.
A `Price` carries at most 38 digits, 18 of them places (the profile's numeric(38,18)), so a stop's
sums and products are exact there; a quotient (or a wallet figure past that bound) rounds down,
never up onto a lot step. Every outcome carries the explanation computed before it (BQ-8).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from candleviewer.accounts.override_comparator import MARGIN_SHARE, AccountFigures
from candleviewer.accounts.profiles import AccountProfile, SizingMode, SymbolScope
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Qty, Side, Symbol

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_FLOOR: Final = Context(prec=100, rounding=ROUND_FLOOR)
_CEILING: Final = Context(prec=100, rounding=ROUND_CEILING)
_EXACT: Final = Context(prec=100)
_SHOWN: Final = Decimal("1e-8")  # a quotient is shown cut to 8 places
Price = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)]
MinimumKind = Literal["min_order_qty", "min_notional", "min_leg_notional"]
Minimum = tuple[MinimumKind, Decimal]
Outcome = Literal["ok", "skip", "fail"]
#: Where step 2's reference price came from (Sec.9.3 step 2).
RefSource = Literal["limit", "marketable_limit_worst_fill", "mid", "last"]
#: Sec.9.3.2's caps, each named by its field (the daily room by the tighter of its two).
CapName = Literal[
    "max_leverage_cap",
    "max_position_pct_equity",
    "max_position_notional",
    "max_daily_loss",
    "max_daily_loss_pct",
    "max_order_qty",
    "max_mkt_order_qty",
]
#: Where an ATR came from: PF-T12 and PF-T13 name the worker, client, preset and cached values.
#: Only the kernel's sizes a stop or a take-profit (SR-E28-11); any other falls back (SR-E28-12).
AtrSource = Literal["kernel", "worker", "client", "preset", "cached"]
#: E13's `unavailable(reason)` (24 Sec.7.4 `read`; IR-45, SR-E28-12).
AtrUnavailable = Literal["missing", "parity_flagged", "stale", "warmup", "nan"]
#: A descriptor `version` or a kernel `build_version` (IR-20): a whole number, at least 1.
Version = Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]


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
    """A self-describing ATR with its TB-8 provenance (SR-E28-11 to -13; E13 IR-12, IR-20, IR-45).
    `timeframe` is the caller's bar timeframe (no domain type exists; the caller supplies it),
    `as_of` the closed bar's time; `source` where the value came from, the E13 descriptor's
    `version` and the kernel's `build_version`. `value` is `None` exactly when the kernel read
    `unavailable(reason)`: a typed reason, never a NaN. M13 imports no `orderflow`, so the
    kernel's types are mirrored here as plain closed fields."""

    model_config = _FROZEN
    timeframe: Annotated[str, Field(min_length=1, max_length=16)]
    period: Annotated[int, Field(ge=1)]
    value: Price | None
    as_of: AwareDatetime
    source: AtrSource
    version: Version
    build_version: Version
    unavailable: AtrUnavailable | None = None

    @model_validator(mode="after")
    def _value_or_reason(self) -> Self:
        if (self.value is None) == (self.unavailable is None):
            raise ValueError("an ATR reading takes a value or an unavailable reason, exactly one")
        return self


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
    STOP_BEYOND_LIQUIDATION = "stop_beyond_liquidation"


@dataclass(frozen=True, slots=True)
class ResolvedStop:
    """The native stop on the tick grid; `fallback` when no ATR reading served."""

    price: Decimal
    distance: Decimal
    fallback: bool


@dataclass(frozen=True, slots=True)
class Clamp:
    """One cap of Sec.9.3.2 as the most quantity it admits (at most 100 digits, rounded down)."""

    cap: CapName
    limit: Decimal


@dataclass(frozen=True, slots=True)
class TakeProfit:
    """A take-profit rung (Sec.9.3.3): its price on the tick toward entry and its quantity."""

    price: Decimal
    qty: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class SizingExplanation:
    """What the sizer computed, in step order, for the ticket and the preview (a contract, not a
    debug aid). `basis / per_unit` is the mode's raw quantity (`per_unit` `None` for `fixed_qty`);
    `clamps` every cap judged, `binding` the last one that lowered the quantity; `risk_usdt` is 1R
    (`distance * qty`) and `risk_with_fees_usdt` adds both taker fees; `notional` is at `ref`
    (the anchor), while the caps and `initial_margin` use `px`, the larger notional (mid's for a
    marketable sell, else `ref`'s); `mid_price` the mid seen; `atr` the reading the stop or the
    take-profit used, with its provenance; an `atr` stop's `atr_source` (`kernel`, or `fallback`
    when no kernel reading served) and `atr_multiple` (SR-E28-13); `minimum` the one a leg
    missed; `liquidation_price` the estimate the stop was judged against (SR-E28-26); `rules`
    the rules that fired, in order. A gate skip carries none."""

    ref_price: Decimal | None = None
    ref_source: RefSource | None = None
    mid_price: Decimal | None = None
    limit_price: Decimal | None = None
    stop: ResolvedStop | None = None
    atr: AtrReading | None = None
    atr_source: Literal["kernel", "fallback"] | None = None
    atr_multiple: Decimal | None = None
    mode: SizingMode | None = None
    basis: Decimal | None = None
    per_unit: Decimal | None = None
    raw_qty: Decimal | None = None
    clamps: tuple[Clamp, ...] = ()
    binding: Clamp | None = None
    qty: Decimal | None = None
    rounding_delta: Decimal | None = None
    notional: Decimal | None = None
    risk_usdt: Decimal | None = None
    risk_with_fees_usdt: Decimal | None = None
    initial_margin: Decimal | None = None
    liquidation_price: Decimal | None = None
    minimum: Minimum | None = None
    rules: tuple[str, ...] = ()
    base_coin: str = ""
    settle_coin: str = ""

    @property
    def stop_fallback(self) -> bool:
        return self.stop is not None and self.stop.fallback


@dataclass(frozen=True, slots=True)
class LegSizing(SizingExplanation):
    """The outcome, its reason, the take-profits of an `ok` leg, and the explanation computed
    before the outcome (BQ-8)."""

    outcome: Outcome
    reason: SkipReason | FailReason | None = None
    tps: tuple[TakeProfit, ...] = ()

    def __post_init__(self) -> None:
        kinds: dict[str, type] = {"ok": type(None), "skip": SkipReason, "fail": FailReason}
        kind = kinds[self.outcome]
        if not isinstance(self.reason, kind):
            raise TypeError(f"a {self.outcome} outcome takes no reason {self.reason!r}")

    def render(self) -> str:
        """22 `ResolvedLegParams.sizing_explanation`: `<mode>: <basis> / <per unit> = <raw>
        capped by <cap> -> <qty>`, then the stop, notional, risk and margin (`at <mid>` when a
        marketable sell's mid, not `ref`, prices it); every figure carries its unit."""
        base, usdt, parts = self.base_coin, self.settle_coin, []
        basis, raw, qty, delta = self.basis, self.raw_qty, self.qty, self.rounding_delta
        if basis is not None and raw is not None and qty is not None and delta is not None:
            how = f"{_shown(basis)} {base}"
            if self.per_unit is not None:
                how = f"{_shown(basis)} {usdt} / {_shown(self.per_unit)} {usdt} per {base}"
            parts.append(f"{self.mode}: {how} = {_shown(raw)} {base}")
            if self.binding is not None:
                cap = self.binding
                parts[-1] += f" capped by {cap.cap} at {_shown(cap.limit)} {base}"
            parts[-1] += f" -> {_shown(qty)} {base}"
            if delta > 0:
                parts[-1] += f" (floored by {_shown(delta)} {base})"
        if self.stop is not None:
            fallback = " (ATR fallback)" if self.stop.fallback else ""
            parts.append(f"stop {_shown(self.stop.price)} {usdt}{fallback}")
            if self.atr is not None and self.atr.value is not None:
                atr = f"{self.atr.period}-bar {self.atr.timeframe} ATR"
                parts[-1] += f" from a {atr} of {_shown(self.atr.value)} {usdt}"
        figures = (
            ("notional", self.notional),
            ("1R =", self.risk_usdt),
            ("risk with fees", self.risk_with_fees_usdt),
        )
        parts += [f"{name} {_shown(value)} {usdt}" for name, value in figures if value is not None]
        if self.initial_margin is not None and self.ref_price is not None:
            margin = f"initial margin {_shown(self.initial_margin)} {usdt}"
            px = _priced_at(self.ref_source, self.ref_price, self.mid_price)
            if px != self.ref_price:  # the margin's price, when not `ref`
                margin += f" at {_shown(px)} {usdt}"
            parts.append(margin)
        if self.reason is not None:
            parts.append(f"{'skipped' if self.outcome == 'skip' else 'failed'}: {self.reason}")
            if self.minimum is not None:
                kind, value = self.minimum
                unit = base if kind == "min_order_qty" else usdt
                parts[-1] += f", {kind} {_shown(value)} {unit}"
        return "; ".join(parts)


def _shown(value: Decimal) -> str:
    """The figure as computed, or cut down to 8 places when it is longer (a quotient); no
    exponent and no trailing zeros."""
    cut = value.quantize(_SHOWN, context=_FLOOR)
    shown = (value if cut == value else cut).normalize(_FLOOR)
    return format(_EXACT.add(shown, Decimal(0)), "f")  # never "-0" (0 - 0 rounding down)


def _priced_at(source: RefSource | None, ref: Decimal, mid: Decimal | None) -> Decimal:
    """The price the caps and the margin are judged at: the larger notional, which is mid for a
    marketable sell (its anchor, the limit, is below mid) and the anchor otherwise."""
    if source == "marketable_limit_worst_fill" and mid is not None:
        return max(ref, mid)
    return ref


def _positive(value: Decimal) -> Decimal:
    """The value, or a plain 0 for one at or below 0 (never a `-0`)."""
    return value if value > 0 else Decimal(0)


def _to_grid(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    return (value / step).to_integral_value(rounding) * step


def _atr_value(profile: AccountProfile, atr: AtrReading | None) -> Decimal | None:
    """The reading's value, when the kernel's, warm and of `sl_atr_period`; otherwise none serves
    (SR-E28-11, SR-E28-12): never a worker, client, preset or cached value."""
    if atr is None or atr.source != "kernel" or atr.period != profile.sl_atr_period:
        return None
    return atr.value


def resolve_stop(
    side: Side, profile: AccountProfile, ref: Decimal, inst: Instrument, atr: AtrReading | None
) -> ResolvedStop:
    """24 Sec.9.3.1: below a long's entry, above a short's, on the tick away from entry. An `atr`
    stop with no warm kernel reading of `sl_atr_period` falls back to `fallback_sl_offset_pct`."""
    with localcontext(_FLOOR):
        unit, fallback = profile.sl_offset_unit, False
        if unit == "ticks":
            offset = profile.sl_offset_value * inst.tick_size
        elif unit == "percent":
            offset = ref * profile.sl_offset_value
        elif unit != "atr":  # r_multiple defines R; AccountProfile refuses it
            raise ValueError(f"no stop resolves in unit {unit!r}")
        elif (reading := _atr_value(profile, atr)) is None:
            offset, fallback = ref * profile.fallback_sl_offset_pct, True
        else:
            offset = reading * profile.sl_atr_multiple
        if side == "buy":
            price = _to_grid(ref - offset, inst.tick_size, ROUND_FLOOR)
        elif side == "sell":
            price = _to_grid(ref + offset, inst.tick_size, ROUND_CEILING)
        else:  # a programming error: `Side` is validated at every boundary
            raise ValueError(f"no stop resolves for side {side!r}")
        return ResolvedStop(price=price, distance=abs(ref - price), fallback=fallback)


def liquidation_estimate(side: Side, entry: Decimal, leverage: Decimal, mmr: Decimal) -> Decimal:
    """24 Sec.9.3.6 (SR-E28-26, F-15): the one liquidation estimate, of an isolated position at
    `leverage` with maintenance margin rate `mmr`, fees and funding ignored: a long's
    `entry * (1 - 1/leverage + mmr)`, a short's `entry * (1 + 1/leverage - mmr)`. For cross margin
    it is the conservative bound (nearer entry than the real one). Every step rounds toward entry
    at 100 digits, so a stop is never judged inside a liquidation it is not inside."""
    if leverage <= 0:  # a programming error: `AccountProfile` refuses it
        raise ValueError("no liquidation estimate at a leverage at or below 0")
    inverse = _FLOOR.divide(Decimal(1), leverage)  # the smaller move: nearer entry
    if side == "buy":
        with localcontext(_CEILING):
            return entry * (1 - inverse + mmr)
    if side == "sell":
        with localcontext(_FLOOR):
            return entry * (1 + inverse - mmr)
    raise ValueError(f"no liquidation estimate for side {side!r}")


def beyond_liquidation(side: Side, stop: Decimal, liquidation: Decimal) -> bool:
    """Whether a stop is not strictly inside the estimate: at it, the stop races the
    liquidation (the comparator's R3 refuses equality too)."""
    return stop <= liquidation if side == "buy" else stop >= liquidation


def _fee_per_unit(ref: Decimal, stop: ResolvedStop, taker: Decimal | None) -> Decimal | None:
    """Entry at `ref`, exit at the further of `ref` and the stop (ADR-0040 OPEN-4)."""
    return None if taker is None else (ref + max(ref, stop.price)) * taker


def _raw_qty(
    p: AccountProfile, w: AccountFigures, ref: Decimal, stop: ResolvedStop
) -> tuple[Decimal, Decimal | None] | None:
    """Steps 4 and 5: the mode's `(basis, per_unit)`, its raw quantity `basis / per_unit` (the
    basis itself for `fixed_qty`); `None` when a figure it reads is unknown."""
    equity, notional = w.equity, p.fixed_notional
    if p.sizing_mode == "fixed_qty":
        return None if p.fixed_qty is None else (p.fixed_qty, None)
    if p.sizing_mode == "fixed_notional":
        return None if notional is None else (notional, ref)
    if p.sizing_mode == "pct_equity":
        pct = p.pct_equity
        return None if equity is None or pct is None else (equity * pct * p.leverage, ref)
    budget = p.risk_fixed_amount
    if budget is None and p.risk_pct_equity is not None and equity is not None:
        budget = equity * p.risk_pct_equity
    fee = _fee_per_unit(ref, stop, w.taker_fee_rate)
    if budget is None or fee is None:
        return None
    return budget, stop.distance + fee  # step 5: the fees shrink it


def _caps(
    p: AccountProfile,
    w: AccountFigures,
    inst: Instrument,
    stop: ResolvedStop,
    px: Decimal,
    *,
    ref: Decimal,
    market: bool,
) -> tuple[list[Clamp], Decimal] | None:
    """Step 6's caps in Sec.9.3.2's order, and the fee per unit; `None` for an unknown figure.
    The position caps bound the leg alone (BQ-12) at `px`, the larger of the limit and `ref`;
    the daily room is the comparator's R2 (BQ-11): the tighter daily cap less the day's realised
    loss and the committed risk, over the loss per unit at the stop, both taker fees included.
    (R2 also caps a `risk_based` leg at its budget, which step 5 already holds it to.)"""
    e, lost, held = w.equity, w.realised_loss_today, w.committed_risk
    fee = _fee_per_unit(ref, stop, w.taker_fee_rate)
    if e is None or lost is None or held is None or fee is None:
        return None
    caps = []
    if p.max_leverage_cap is not None:  # BQ-10: qty <= max_leverage_cap * equity / px
        caps.append(Clamp("max_leverage_cap", p.max_leverage_cap * e / px))
    if p.max_position_pct_equity is not None:
        caps.append(Clamp("max_position_pct_equity", p.max_position_pct_equity * e / px))
    if p.max_position_notional is not None:
        caps.append(Clamp("max_position_notional", p.max_position_notional / px))
    rooms: list[tuple[CapName, Decimal]] = []
    if p.max_daily_loss is not None:
        rooms.append(("max_daily_loss", p.max_daily_loss))
    if p.max_daily_loss_pct is not None:
        rooms.append(("max_daily_loss_pct", p.max_daily_loss_pct * e))
    if rooms:  # the tighter; on a tie, max_daily_loss, as R2 names it; an overspent room is 0
        name, room = min(rooms, key=lambda entry: entry[1])
        caps.append(Clamp(name, _positive((room - lost - held) / (stop.distance + fee))))
    caps.append(Clamp("max_order_qty", inst.max_order_qty))  # BQ-13, by order type
    if market:
        caps.append(Clamp("max_mkt_order_qty", inst.max_mkt_order_qty))
    return caps, fee


def _reference(intent: SizingIntent, m: SizingMarket) -> tuple[Decimal, RefSource] | None:
    """Step 2, the anchor: a marketable limit (a buy at or above mid, a sell at or below) sizes at
    its worst-case fill, the higher of mid and its price for a buy and the lower for a sell (its
    price); any other limit, or one with no mid, at its price; a market order at mid, else last."""
    if intent.price is None:
        if m.mid is not None:
            return m.mid, "mid"
        return None if m.last_price is None else (m.last_price, "last")
    if m.mid is None:
        return intent.price, "limit"
    if intent.side == "buy" and m.mid <= intent.price:
        return max(m.mid, intent.price), "marketable_limit_worst_fill"
    if intent.side != "buy" and m.mid >= intent.price:
        return min(m.mid, intent.price), "marketable_limit_worst_fill"
    return intent.price, "limit"


def _missed(qty: Qty, notional: Decimal, p: AccountProfile, inst: Instrument) -> Minimum | None:
    if qty < inst.min_order_qty:
        return ("min_order_qty", inst.min_order_qty)
    floor: Minimum = ("min_notional", inst.min_notional)
    if p.min_leg_notional > inst.min_notional:
        floor = ("min_leg_notional", p.min_leg_notional)
    return floor if notional < floor[1] else None


def _tp_offset(
    p: AccountProfile, ref: Decimal, stop: ResolvedStop, inst: Instrument, atr: AtrReading | None
) -> Decimal | None:
    """The single take-profit's offset from `ref` in `tp_offset_unit`; `None` for an `atr` one with
    no warm reading of `sl_atr_period`, or with no `tp_offset_*` set."""
    value, unit = p.tp_offset_value, p.tp_offset_unit
    if value is None or unit is None:
        return None
    if unit == "r_multiple":
        return value * stop.distance
    if unit == "ticks":
        return value * inst.tick_size
    if unit == "percent":
        return ref * value
    if unit == "atr":
        reading = _atr_value(p, atr)
        return None if reading is None else reading * value
    raise ValueError(f"no take-profit resolves in unit {unit!r}")  # a programming error


def resolve_tps(
    side: Side,
    p: AccountProfile,
    ref: Decimal,
    stop: ResolvedStop,
    qty: Decimal,
    inst: Instrument,
    atr: AtrReading | None,
) -> tuple[TakeProfit, ...]:
    """Sec.9.3.3 from `ref`, the anchor (a marketable limit's worst-case fill, BQ-17): a ladder
    rung at `ref +/- r * distance` takes `floor(qty * qty_pct)` and the last rung the rest of
    `floor(qty * sum)`. No rung is left under `min_order_qty` (one no
    reduce-only order can carry): a non-final one is folded into the last, and a last one into
    the previous kept rung, or dropped when there is none. With no ladder, one take-profit of the
    whole quantity at `tp_offset_*`. Prices round toward entry, and a price not beyond `ref`, or
    not above 0, is dropped."""
    buy, step, least = side == "buy", inst.qty_step, inst.min_order_qty
    rungs: list[tuple[Decimal, Decimal]] = []  # (offset from ref, qty)
    with localcontext(_FLOOR):
        if p.tp_ladder:
            sizes = [_to_grid(qty * rung.qty_pct, step, ROUND_FLOOR) for rung in p.tp_ladder[:-1]]
            sizes = [size if size >= least else Decimal(0) for size in sizes]
            whole = _to_grid(qty * sum(rung.qty_pct for rung in p.tp_ladder), step, ROUND_FLOOR)
            sizes.append(whole - sum(sizes))
            if sizes[-1] < least:  # the last, too: into the previous kept rung, else dropped
                kept = [i for i, size in enumerate(sizes[:-1]) if size > 0]
                if kept:
                    sizes[kept[-1]] += sizes[-1]
                sizes[-1] = Decimal(0)
            rungs = [(r.r * stop.distance, n) for r, n in zip(p.tp_ladder, sizes, strict=True)]
        elif (offset := _tp_offset(p, ref, stop, inst, atr)) is not None:
            rungs = [(offset, qty)]
        tps = []
        for offset, size in rungs:
            target = ref + offset if buy else ref - offset
            price = _to_grid(target, inst.tick_size, ROUND_FLOOR if buy else ROUND_CEILING)
            if size > 0 and ((price > ref) if buy else (0 < price < ref)):
                tps.append(TakeProfit(price, size))
    return tuple(tps)


def size_leg(
    intent: SizingIntent,
    profile: AccountProfile,
    wallet: AccountFigures,
    inst: Instrument,
    metrics: SizingMarket,
) -> LegSizing:
    """24 Sec.9.3: one leg's size, or why it is skipped or failed, with the explanation."""
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
    unit, mode = profile.sl_offset_unit, profile.sizing_mode
    kernel_atr = unit == "atr" and not stop.fallback  # SR-E28-13: the stop's ATR provenance
    seen = LegSizing(
        "ok",
        ref_price=ref,
        ref_source=source,
        mid_price=metrics.mid,
        limit_price=intent.price,
        stop=stop,
        atr=metrics.atr if kernel_atr else None,
        atr_source=("kernel" if kernel_atr else "fallback") if unit == "atr" else None,
        atr_multiple=profile.sl_atr_multiple if kernel_atr else None,
        mode=mode,
        rules=("stop_fallback" if stop.fallback else f"stop_{unit}", mode),
        base_coin=inst.base_coin,
        settle_coin=inst.settle_coin,
    )
    # Per step 3: a stop at or below 0 is no order, and a zero distance would divide by zero in
    # risk_based (a sub-1e-100 short offset rounds back onto entry). A stop not on the loss side of
    # a known mid (a marketable limit more than one stop distance through it) is no placeable SL.
    mid = metrics.mid
    through = mid is not None and (stop.price >= mid if intent.side == "buy" else stop.price <= mid)
    if stop.price <= 0 or stop.distance <= 0 or through:
        return replace(seen, outcome="fail", reason=FailReason.INVALID_STOP_DISTANCE)
    if profile.leverage > inst.max_leverage:
        return replace(seen, outcome="fail", reason=FailReason.LEVERAGE_UNAVAILABLE)
    # Every notional, leverage and margin cap is judged at the larger notional (a marketable
    # buy's anchor, its limit; mid above a marketable sell's). The leg passes the comparator's
    # R1/R2/R6 when its `ResolvedLeg.ref_price` is this `ref`, the anchor (a marketable limit's
    # worst-case fill): R2 measures the stop distance from `ref_price` (24 Sec.9.3.5).
    px = _priced_at(source, ref, metrics.mid)
    with localcontext(_FLOOR):
        sized = _raw_qty(profile, wallet, ref, stop)  # 4 and 5
        caps = _caps(profile, wallet, inst, stop, px, ref=ref, market=intent.price is None)
        if sized is None or caps is None:
            return replace(seen, outcome="fail", reason=FailReason.FIGURE_UNKNOWN)
        (basis, per_unit), (clamps, fee) = sized, caps
        raw = basis if per_unit is None else basis / per_unit
        clamped, binding, fired = _positive(raw), None, list(seen.rules)
        if mode == "risk_based":
            fired.append("fee_correction")
        for clamp in clamps:  # 6. Sec.9.3.2: down only, never below 0
            if _positive(clamp.limit) < clamped:
                clamped, binding = _positive(clamp.limit), clamp
                fired.append(clamp.cap)
        qty = _to_grid(clamped, inst.qty_step, ROUND_FLOOR)  # 7: always floor to the lot
        if qty < clamped:
            fired.append("lot_floor")
        leg = replace(
            seen,
            basis=basis,
            per_unit=per_unit,
            raw_qty=raw,
            clamps=tuple(clamps),
            binding=binding,
            qty=qty,
            rounding_delta=clamped - qty,
            notional=qty * ref,
            risk_usdt=qty * stop.distance,
            risk_with_fees_usdt=qty * (stop.distance + fee),
            rules=tuple(fired),
        )
        missed = _missed(qty, qty * ref, profile, inst)  # 8
        margin = _CEILING.divide(_CEILING.multiply(qty, px), profile.leverage)
    if missed is not None and binding is not None:  # a clamp pushed it under: red (BQ-6)
        return replace(leg, outcome="fail", reason=FailReason.CAP_BREACHED, minimum=missed)
    if missed is not None:
        return replace(leg, outcome="skip", reason=SkipReason.BELOW_MIN_NOTIONAL, minimum=missed)
    # 8b. The comparator's R6: the initial margin, rounded up, within 0.98 of the available
    # margin; a failure, never a clamp (BQ-19: one shared constant).
    leg = replace(leg, initial_margin=margin)
    if wallet.available_margin is None:
        return replace(leg, outcome="fail", reason=FailReason.FIGURE_UNKNOWN)
    # The limit rounds down at 100 digits (fail closed); the comparator's R6 forms the same
    # product, `available_margin * MARGIN_SHARE`, in the default context.
    if margin > _FLOOR.multiply(wallet.available_margin, MARGIN_SHARE):
        return replace(leg, outcome="fail", reason=FailReason.INSUFFICIENT_MARGIN)
    # 8c. SR-E28-26: the native stop must fire before the estimated liquidation (PF-D06, the 2 %
    # fallback included); an unknown rate fails closed, as the comparator's R3 does.
    if (mmr := wallet.maintenance_margin_rate) is None:
        return replace(leg, outcome="fail", reason=FailReason.FIGURE_UNKNOWN)
    liquidation = liquidation_estimate(intent.side, ref, profile.leverage, mmr)
    leg = replace(leg, liquidation_price=liquidation)
    if beyond_liquidation(intent.side, stop.price, liquidation):
        return replace(leg, outcome="fail", reason=FailReason.STOP_BEYOND_LIQUIDATION)
    tps = resolve_tps(intent.side, profile, ref, stop, qty, inst, metrics.atr)  # 9, from the anchor
    if not tps:
        return leg
    tp_rule = "tp_ladder" if profile.tp_ladder else f"tp_{profile.tp_offset_unit}"
    tp_atr = not profile.tp_ladder and profile.tp_offset_unit == "atr"  # the explanation's reading
    if tp_atr and _atr_value(profile, metrics.atr) is not None:
        leg = replace(leg, atr=metrics.atr)
    return replace(leg, tps=tps, rules=(*leg.rules, tp_rule))
