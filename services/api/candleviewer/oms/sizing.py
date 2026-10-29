"""The size step of an entry (24-internal-schemas.md Sec.8.4 item 2, step 3c; #913 S4-S).

An order that is not reduce-only is sized by its effective profile's sizer (`accounts.sizer`,
24 Sec.9.3), never by a client figure, from step 3a's market read (`SizingMarket`, its ATR None
until the E13 kernel port reaches `oms`, ruling Q6) and the account's figures (`OrderFigures`).
`sizing.mode` `profile` sizes by the profile. Another mode but `pct_position` overlays the
request's values onto a copy of the profile (its `pct` and `risk_per_trade_pct` percents, 100 at
most), and the request's stop overlays the profile's offset (ruling Q2): a `percent` or `ticks`
stop lands a whole tick away from entry, a `price` one keeps its price. The overlaid leg is judged
by the comparator (`judge_leg`, 24 Sec.9.3.2a) beside the profile's own leg and refused whole,
never clamped; a leg a cap would clamp is refused the same way. The leg's stop is the stop its
risk was computed from, so the sizer is an entry's one stop source; `NativeStopGuard` still judges
it (C-2.6). Each outcome but `ok` is one answer (22 `placeOrder`'s mapping), before anything is
recorded or sent. A `figure_unknown` whose symbol's maintenance margin rate is unknown (its tiers
missing from the catalogue) first requests the symbol's tiers (`TierRequests`, 24 Sec.9.3.6), never
awaited, and is `503 sizing_unavailable` with `detail` `tiers_pending`. Every leg the answer rests
on is recorded in `cv_sizer_*`.

The judged path is taken when the request names a sizing value, a `max_notional_usd`, a stop or a
take-profit, each of which the comparator judges: a `max_notional_usd` is refused when the leg is
above it, never capped, and `round_to_lot` `false` is refused (`sizing.round_to_lot`,
`qty_rounding`, ADR-0040 row 16) before any figure is read, as the sizer always floors to the lot
step. The take-profit and the time-in-force are then judged alike: a take-profit the request does
not name is judged as the profile's own (none is sent), and a time-in-force it does not name is
GTC (22 `PlaceOrderRequest`), judged against the profile's default; an entry is never
reduce-only, so a profile whose `reduce_only_default` is set refuses it (`reduce_only`). A
`profile` request naming none of these is the profile's own leg, judged by nothing more: its
time-in-force is what the request sends, as before the size step, its `reduce_only_default` and
its `round_to_lot` are not read.

Two rows of the comparator are not the order path's: the trade group's bound profile is the
account's default, while an order's ceiling is its effective profile, so `is_default` is not
judged; and the `*_after` counts are the risk gate's (E39-S01), which runs after sizing, so their
being unknown here refuses nothing. Every other row holds as it does for a trade group's leg.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, Context, Decimal
from types import MappingProxyType
from typing import Any, Final, Literal

import structlog
from pydantic import ValidationError

from candleviewer.accounts.override_comparator import (
    AccountFigures,
    LegOverrides,
    Refused,
    ResolvedLeg,
    SizingOverride,
    Violation,
    judge_leg,
)
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.profiles import SizingMode as QtyMode
from candleviewer.accounts.sizer import (
    FailReason,
    LegSizing,
    SizingIntent,
    SizingMarket,
    SkipReason,
    resolve_tps,
    size_leg,
)
from candleviewer.accounts.sizer_metrics import SizerMetrics, size_leg_observed
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Px, Qty, Side, Symbol
from candleviewer.exchange.base.models import AccountRef
from candleviewer.storage.repositories.orders import TimeInForce, TpslMode

from .classify import stop_errors
from .errors import (
    DETAIL_TIERS_PENDING,
    RULE_NATIVE_STOP_REQUIRED,
    RULE_QTY_ROUNDING,
    RULE_SIZING_MODE_UNSUPPORTED,
    ExchangeUnavailable,
    FieldError,
    LotSizeViolation,
    OrderInvalid,
    RiskRefused,
    SizingUnavailable,
    StopUnitUnsupported,
)
from .ports import (
    NO_TIER_REQUESTS,
    UNKNOWN_FIGURES,
    FiguresReading,
    OrderEffect,
    OrderFigures,
    OrderType,
    SizingRequest,
    StopOffset,
    TierRequests,
)

__all__ = ["FIGURES_TIMEOUT_S", "SIZING_RETRY_AFTER_S", "EntryIntent", "EntrySize", "EntrySizer"]

#: The bound on one figures read, in seconds: above `DayRiskFigures`' own 2.5 s budget.
FIGURES_TIMEOUT_S: Final = 3.0
#: `sizing_unavailable`'s `Retry-After`, in seconds: the figures are read again at the next request.
SIZING_RETRY_AFTER_S: Final = 1
_EXACT: Final = Context(prec=100)
_STORED: Final = Decimal("1e-18")  # numeric(38,18): a leg's risk, rounded up, never down
_GATE: Final = frozenset({SkipReason.PROFILE_DISABLED, SkipReason.SYMBOL_NOT_ALLOWED,
                          SkipReason.SYMBOL_DENIED})  # fmt: skip
_STOP_FAILS: Final = frozenset({FailReason.INVALID_STOP_DISTANCE,
                                FailReason.STOP_BEYOND_LIQUIDATION})  # fmt: skip
#: The comparator's rows a request field moves, named by the field. Every other row is a sizing
#: row (the mode, the size, the caps, the budgets, leverage and margin), named `sizing`.
_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "sl_offset_value": "stop_loss",
        "tp_offset_value": "take_profit",
        "time_in_force_default": "time_in_force",
        "reduce_only_default": "reduce_only",
        "position_mode": "position_idx",
    }
)
_SIZING_FIELDS: Final = ("fixed_qty", "fixed_notional", "pct_equity", "risk_pct_equity",
                         "risk_fixed_amount")  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EntryIntent:
    """What the request asks of the size step: the order's terms and its own stop."""

    symbol: Symbol
    side: Side
    order_type: OrderType
    price: Px | None
    sizing: SizingRequest
    stop_loss: StopOffset | None
    take_profit: StopOffset | None
    time_in_force: TimeInForce
    tpsl_mode: TpslMode
    position_idx: Literal[0, 1, 2]


@dataclass(frozen=True, slots=True)
class EntrySize:
    """An `ok` leg (its quantity, its `ResolvedStop`, its `ref_price` and its explanation), the
    resolved sizing mode it was sized by (`requested_qty_mode`), the request's own value of that
    mode (`requested_qty_value`, None for `profile`) and its risk with fees, as a column stores
    it (`risk_usd`). An overlaid leg keeps what `EntrySizer.judge` reads: the profile's own leg
    (`baseline`), the profile and the figures."""

    leg: LegSizing
    mode: QtyMode
    value: Decimal | None
    risk_usd: Decimal
    qty: Qty
    stop: Px
    reference: Px
    baseline: LegSizing | None = field(default=None, repr=False)
    profile: AccountProfile | None = field(default=None, repr=False)
    figures: AccountFigures | None = field(default=None, repr=False)


def _invalid(field: str, rule: str, message: str) -> OrderInvalid:
    return OrderInvalid(message, errors=(FieldError(field, rule, message),))


def sizing_overlay(sizing: SizingRequest) -> tuple[dict[str, object], Decimal] | None:
    """The request's sizing as profile fields (fractions for its percents) and its raw value;
    None for `profile`. `pct_position` and a missing value are refused."""
    mode = sizing.mode
    if mode == "profile":
        return None
    if mode == "pct_position":
        message = "pct_position sizing is not available yet."
        raise _invalid("sizing.mode", RULE_SIZING_MODE_UNSUPPORTED, message)
    fields: dict[str, object] = {"sizing_mode": mode, **dict.fromkeys(_SIZING_FIELDS)}
    if mode == "fixed_qty":
        name, value, field = "fixed_qty", sizing.qty, "sizing.qty"
    elif mode == "fixed_notional":
        name, value, field = "fixed_notional", sizing.notional_usd, "sizing.notional_usd"
    elif mode == "pct_equity":
        name, value, field = "pct_equity", sizing.pct, "sizing.pct"
    elif sizing.risk_per_trade_usd is not None:
        name, value, field = "risk_fixed_amount", sizing.risk_per_trade_usd, "sizing.risk"
    else:
        name, value, field = "risk_pct_equity", sizing.risk_per_trade_pct, "sizing.risk"
    if value is None or not value.is_finite():
        raise _invalid(field, "required", f"{mode} sizing needs its value.")
    fields[name] = value / 100 if name in {"pct_equity", "risk_pct_equity"} else value
    return fields, value


def stop_overlay(
    stop: StopOffset | None, side: Side, ref: Decimal, instrument: Instrument
) -> dict[str, object]:
    """The request's stop as the profile's offset (ruling Q2), measured from the sizer's anchor so
    an absolute stop keeps its price; an `atr` one keeps its unit and multiple (ruling Q6)."""
    if stop is None:
        return {}
    if stop.unit == "atr":
        if not (stop.value.is_finite() and stop.value > 0):
            raise _invalid("stop_loss", "native_stop_required", "The stop must be above zero.")
        return {"sl_offset_unit": "atr", "sl_atr_multiple": stop.value}
    if stop.unit == "r_multiple":
        raise StopUnitUnsupported
    value, tick = stop.value, instrument.tick_size
    level = value
    if value.is_finite() and stop.unit != "price":  # a whole tick away from entry, never closer
        distance = value * tick if stop.unit == "ticks" else _EXACT.divide(ref * value, 100)
        distance = _EXACT.divide(distance, tick).to_integral_value(rounding=ROUND_CEILING) * tick
        level = ref - distance if side == "buy" else ref + distance
    errors = stop_errors(effect=OrderEffect.ENTRY, side=side, reference_price=ref, stop=level)
    if errors:
        raise OrderInvalid(errors[0].message, errors=errors)
    distance = ref - level if side == "buy" else level - ref
    return {"sl_offset_unit": "ticks", "sl_offset_value": _EXACT.divide(distance, tick)}


def out_of_range(profile: AccountProfile, fields: dict[str, object]) -> OrderInvalid:
    """An overlay the profile model refuses, named by its field: the stop when the sizing alone
    holds, else the sizing."""
    try:
        AccountProfile.model_validate(profile.model_dump() | fields)
    except ValidationError:
        return _invalid("sizing", "profile_overlay", "The request's sizing is out of range.")
    return _invalid("stop_loss", "profile_overlay", "The request's stop is out of range.")


def _answered(leg: LegSizing) -> LegSizing:
    """The leg when `ok`, else its answer (22 `placeOrder`'s mapping)."""
    reason = leg.reason
    if reason is None:
        return leg
    if reason in _GATE:
        message = "The account's profile does not allow this order."
        raise RiskRefused(message, errors=(FieldError("symbol", reason.value, message),))
    if reason is SkipReason.BELOW_MIN_NOTIONAL:
        kind = "min_notional" if leg.minimum is None else leg.minimum[0]
        message = "The sized quantity is below the instrument's or the profile's minimum."
        raise LotSizeViolation(message, errors=(FieldError("sizing", kind, message),))
    if reason in {FailReason.CAP_BREACHED, FailReason.INSUFFICIENT_MARGIN}:
        rule = reason.value if leg.binding is None else leg.binding.cap
        message = "The sized order would break the profile's caps or the account's margin."
        raise RiskRefused(message, errors=(FieldError("sizing", rule, message),))
    if reason is FailReason.LEVERAGE_UNAVAILABLE:
        raise _invalid("leverage", "max_leverage", "The profile's leverage is above the symbol's.")
    if reason in _STOP_FAILS:
        raise _invalid("stop_loss", reason.value, "The stop cannot protect this order.")
    if reason is FailReason.NO_REFERENCE_PRICE:
        raise ExchangeUnavailable(retry_after_s=SIZING_RETRY_AFTER_S)
    raise SizingUnavailable(retry_after_s=SIZING_RETRY_AFTER_S)  # figure_unknown


def with_rates(reading: FiguresReading, symbol: Symbol) -> AccountFigures:
    """The account's figures with `symbol`'s rates, as the leg on it is sized; with no entry for
    the symbol (the source reads no rates), the account's alone. The size step's merge and the
    trade-group preview's (E28-T05 S3c), which asks no tiers."""
    rates = reading.symbols.get(symbol)
    if rates is None:
        return reading.account
    update = {"maintenance_margin_rate": rates.maintenance_margin_rate}
    return reading.account.model_copy(update=update | {"taker_fee_rate": rates.taker_fee_rate})


def sizing_market(mid: Px | None, last: Px | None) -> SizingMarket:
    """Step 3a's read as the sizer takes it; a price no `Price` holds is no price."""
    try:
        return SizingMarket(mid=mid, last_price=last)
    except ValidationError:
        try:
            return SizingMarket(mid=None, last_price=last)
        except ValidationError:
            return SizingMarket()


def _judged(violation: Violation) -> bool:
    """The comparator's rows the order path judges (module docstring)."""
    if violation.field == "is_default":
        return False
    return not (violation.rule == "R7" and violation.reason == "unknown_input")


class EntrySizer:
    """The size step of an entry (module docstring), over the account's figures."""

    def __init__(
        self,
        figures: OrderFigures,
        observer: SizerMetrics,
        *,
        timeout_s: float = FIGURES_TIMEOUT_S,
        clock: Callable[[], float] = time.perf_counter,
        tier_requests: TierRequests = NO_TIER_REQUESTS,
    ) -> None:
        self._figures = figures
        self._tier_requests = tier_requests
        self._observer = observer
        self._timeout_s = timeout_s
        self._clock = clock

    def invalidate(self, account: AccountRef) -> None:
        """Drop the account's kept figures: an accepted send took room (24 Sec.9.3.6)."""
        self._figures.invalidate(account.account_id)

    async def size(
        self,
        intent: EntryIntent,
        *,
        account: AccountRef,
        instrument: Instrument,
        profile: AccountProfile | None,
        mid: Px | None,
        last: Px | None,
    ) -> EntrySize:
        """The entry's `ok` leg, or its refusal (module docstring)."""
        if profile is None:  # D11: never sized from a default; C-2.6's refusal comes first
            if intent.stop_loss is None:
                message = "No stop_loss supplied and the account profile defines no SL offset."
                raise _invalid("stop_loss", RULE_NATIVE_STOP_REQUIRED, message)
            raise RiskRefused("No profile allows this order.")
        if not (profile.enabled and profile.trading_enabled):  # before any figure is read
            raise RiskRefused("The account's profile is not enabled for trading.")
        overlay = sizing_overlay(intent.sizing)
        named = (intent.sizing.max_notional_usd, intent.stop_loss, intent.take_profit)
        judged = overlay is not None or any(value is not None for value in named)
        if judged and not intent.sizing.round_to_lot:  # ADR-0040 row 16: always floored
            message = "The order's quantity is always floored to the lot step."
            raise _invalid("sizing.round_to_lot", RULE_QTY_ROUNDING, message)
        try:
            asked = SizingIntent(
                symbol=intent.symbol, side=intent.side, order_type=intent.order_type,
                price=intent.price,
            )  # fmt: skip
        except ValidationError:
            raise _invalid("price", "finite", "The price cannot be sized.") from None
        figures, untiered = await self._read(account, intent.symbol, profile)
        market = sizing_market(mid, last)

        def answered(leg: LegSizing) -> LegSizing:
            if untiered and leg.reason is FailReason.FIGURE_UNKNOWN:
                self._tier_requests.request_tiers(intent.symbol)  # never awaited, never raises
                retry = SIZING_RETRY_AFTER_S
                raise SizingUnavailable(retry_after_s=retry, detail=DETAIL_TIERS_PENDING)
            return _answered(leg)

        if not judged:
            leg = self._observed(asked, profile, figures, instrument, market)
            return self._size(answered(leg), profile.sizing_mode, None)
        started = self._clock()
        baseline = size_leg(asked, profile, figures, instrument, market)
        if baseline.ref_price is None or baseline.stop is None:  # a gate skip or no price
            self._observer.record(baseline, self._clock() - started)
            answered(baseline)
            raise ValueError("a leg with no anchor is never ok")
        fields, value = overlay if overlay is not None else ({}, None)
        stop = stop_overlay(intent.stop_loss, intent.side, baseline.ref_price, instrument)
        try:
            widened = AccountProfile.model_validate(profile.model_dump() | fields | stop)
        except ValidationError:
            raise out_of_range(profile, fields) from None
        leg = answered(self._observed(asked, widened, figures, instrument, market))
        overlaid = overlay is not None or intent.stop_loss is not None
        if overlaid and leg.binding is not None:  # refused whole, never clamped
            message = "The request goes past the profile's caps."
            raise RiskRefused(message, errors=(FieldError("sizing", leg.binding.cap, message),))
        size = self._size(leg, widened.sizing_mode, value)
        return replace(size, baseline=baseline, profile=profile, figures=figures)

    def judge(
        self,
        size: EntrySize,
        intent: EntryIntent,
        *,
        take_profit: Px | None,
        instrument: Instrument,
    ) -> None:
        """An overlaid leg beside the profile's own (`judge_leg`), once its take-profit is known,
        refused whole when it goes past the profile (`403 risk_limit_breached`); a take-profit the
        request does not name is judged as the profile's own (none is sent). The profile's own
        take-profit is the profile's offset from the profile's own leg's anchor and stop at the
        judged quantity, whatever that leg's outcome. A leg sized by the profile alone passes."""
        baseline, profile, figures = size.baseline, size.profile, size.figures
        if baseline is None or profile is None or figures is None:
            return
        own_tp = own_take_profit(intent.side, profile, baseline, size.leg, instrument)
        try:
            judged = resolved_leg(
                intent, profile, size.leg, own_tp if take_profit is None else take_profit
            )
            bound = resolved_leg(intent, profile, replace(baseline, qty=size.leg.qty), own_tp)
            requested = requested_layers(intent.sizing)
        except ValidationError:
            raise _invalid("sizing", "profile_overlay", "The request cannot be judged.") from None
        verdict = judge_leg(
            profile, judged, baseline=bound, instrument=instrument, figures=figures,
            requested=requested,
        )  # fmt: skip
        found = (
            [v for v in verdict.violations if _judged(v)] if isinstance(verdict, Refused) else []
        )
        if not found:
            return
        message = "The request goes past the account's profile."
        errors = [FieldError(_FIELDS.get(v.field, "sizing"), v.field, message) for v in found]
        _log().info("oms_submit_overlay_refused", fields=",".join(e.rule for e in errors))
        raise RiskRefused(message, errors=errors)

    async def _read(
        self, account: AccountRef, symbol: Symbol, profile: AccountProfile
    ) -> tuple[AccountFigures, bool]:
        """The account's figures with the symbol's rates, and whether the reading answered the
        symbol's maintenance margin rate unknown (its tiers missing); on a read that fails or does
        not answer in time, every figure unknown (the leg then fails `figure_unknown`)."""
        try:
            async with asyncio.timeout(self._timeout_s):
                reading = await self._figures.read(
                    account, (symbol,), fallback_sl_offset_pct=profile.fallback_sl_offset_pct
                )
        except Exception as exc:
            _log().warning("oms_submit_figures_unread", failure=type(exc).__name__)
            return UNKNOWN_FIGURES, False
        rates = reading.symbols.get(symbol)  # none: no rates to read (live, another venue), so
        # no tiers to ask for; `TierRequests` asks only where the figures read them
        untiered = rates is not None and rates.maintenance_margin_rate is None
        return with_rates(reading, symbol), untiered

    def _observed(
        self,
        asked: SizingIntent,
        profile: AccountProfile,
        figures: AccountFigures,
        instrument: Instrument,
        market: SizingMarket,
    ) -> LegSizing:
        return size_leg_observed(
            asked, profile, figures, instrument, market, observer=self._observer, clock=self._clock
        )

    @staticmethod
    def _size(leg: LegSizing, mode: QtyMode, value: Decimal | None) -> EntrySize:
        risk = leg.risk_with_fees_usdt
        if leg.qty is None or leg.stop is None or risk is None:  # an `ok` leg carries all three
            raise ValueError("an ok leg carries its quantity, stop and risk")
        stored = risk.quantize(_STORED, rounding=ROUND_CEILING, context=_EXACT)
        if leg.ref_price is None:
            raise ValueError("an ok leg carries its anchor")
        return EntrySize(leg, mode, value, stored, leg.qty, leg.stop.price, leg.ref_price)


def resolved_leg(
    intent: EntryIntent, profile: AccountProfile, leg: LegSizing, tp: Decimal | None
) -> ResolvedLeg:
    """A leg as the comparator judges it: the order's terms, the profile's account-wide modes."""
    if leg.ref_price is None or leg.stop is None or leg.qty is None:
        raise ValueError("a judged leg carries its anchor, stop and quantity")
    return ResolvedLeg(
        account_id=profile.account_id, profile_id=profile.profile_id, symbol=intent.symbol,
        side=intent.side, ref_price=leg.ref_price, qty=leg.qty, leverage=profile.leverage,
        stop_price=leg.stop.price, tpsl_mode=intent.tpsl_mode, take_profit_price=tp,
        time_in_force=intent.time_in_force, reduce_only=False, margin_mode=profile.margin_mode,
        position_mode=profile.position_mode, position_idx=intent.position_idx,
        slippage_tolerance_bps=profile.slippage_tolerance_bps,
    )  # fmt: skip


def own_take_profit(
    side: Side, profile: AccountProfile, baseline: LegSizing, leg: LegSizing, inst: Instrument
) -> Px | None:
    """The profile's own take-profit (its last rung), resolved from the profile, never read from
    the profile's own leg, whose take-profits only an `ok` outcome carries."""
    if baseline.ref_price is None or baseline.stop is None or leg.qty is None:
        raise ValueError("a judged leg's baseline carries its anchor and stop")
    tps = resolve_tps(side, profile, baseline.ref_price, baseline.stop, leg.qty, inst, baseline.atr)
    return tps[-1].price if tps else None


def requested_layers(sizing: SizingRequest) -> tuple[LegOverrides, ...]:
    """The request's sizing as the comparator's layer, in fractions; none for a `profile` request
    with no `max_notional_usd`. `round_to_lot` is left out: `false` is refused before (module
    docstring)."""
    if sizing.mode == "profile" and sizing.max_notional_usd is None:
        return ()
    pct = None if sizing.pct is None else sizing.pct / 100
    risk_pct = sizing.risk_per_trade_pct
    values = {
        "mode": sizing.mode, "qty": sizing.qty, "notional_usd": sizing.notional_usd, "pct": pct,
        "risk_per_trade_usd": sizing.risk_per_trade_usd,
        "risk_per_trade_pct": None if risk_pct is None else risk_pct / 100,
        "max_notional_usd": sizing.max_notional_usd,
    }  # fmt: skip
    if sizing.mode == "risk_based" and sizing.risk_per_trade_usd is not None:
        values["risk_per_trade_pct"] = None  # the one the overlay sized by
    known = {name: value for name, value in values.items() if value is not None}
    return (LegOverrides(sizing=SizingOverride.model_validate(known)),)
