"""The size step of an entry (24-internal-schemas.md Sec.8.4 item 2, step 3c; #913 S4-S).

An order that is not reduce-only is sized by its effective profile's sizer (`accounts.sizer`, 24
Sec.9.3), never by a client figure, from step 3a's market read (`SizingMarket`, its ATR None until
the E13 kernel port reaches `oms`, ruling Q6) and the account's figures (`OrderFigures`).
`sizing.mode` `profile` sizes by the profile. `fixed_qty` overlays the request's qty onto a copy of
a `fixed_qty` profile, and the request's stop overlays the profile's offset (ruling Q2). Until the
comparator judges the overlay (an interim, #913 S4-S-b2b) the request only narrows the profile,
each refused whole with 403, never clamped: an overlaid leg a cap would clamp, a qty above the
profile's `fixed_qty` and a stop further from the anchor than the profile's own. Every other mode,
and `fixed_qty` on a profile of another mode, is `sizing_mode_unsupported`. The leg's stop is the
stop its risk was computed from, so the sizer is an entry's one stop source; `NativeStopGuard`
still judges it (C-2.6). Each outcome but `ok` is one answer (22 `placeOrder`'s mapping), before
anything is recorded or sent. A `figure_unknown` whose symbol's maintenance margin rate is unknown
(its tiers missing from the catalogue) first requests the symbol's tiers (`TierRequests`, 24
Sec.9.3.6), never awaited, and is still `503 sizing_unavailable`. Every leg the answer rests on
is recorded in `cv_sizer_*`. An entry's `round_to_lot` is not read: the sizer floors to the lot
step.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Context, Decimal
from typing import Any, Final

import structlog
from pydantic import ValidationError

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.profiles import SizingMode as QtyMode
from candleviewer.accounts.sizer import (
    FailReason,
    LegSizing,
    SizingIntent,
    SizingMarket,
    SkipReason,
    size_leg,
)
from candleviewer.accounts.sizer_metrics import SizerMetrics, size_leg_observed
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Px, Qty, Side, Symbol
from candleviewer.exchange.base.models import AccountRef

from .classify import stop_errors
from .errors import (
    RULE_NATIVE_STOP_REQUIRED,
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


@dataclass(frozen=True, slots=True)
class EntrySize:
    """An `ok` leg (its quantity, its `ResolvedStop`, its `ref_price` and its explanation), the
    resolved sizing mode it was sized by (`requested_qty_mode`), the request's own value of that
    mode (`requested_qty_value`, None for `profile`) and its risk with fees, as a column stores
    it (`risk_usd`)."""

    leg: LegSizing
    mode: QtyMode
    value: Decimal | None
    risk_usd: Decimal
    qty: Qty
    stop: Px
    reference: Px


def _invalid(field: str, rule: str, message: str) -> OrderInvalid:
    return OrderInvalid(message, errors=(FieldError(field, rule, message),))


def _overlay(
    sizing: SizingRequest, profile: AccountProfile
) -> tuple[dict[str, object], Decimal] | None:
    """The request's sizing as profile fields and its raw value; None for `profile`. A mode but
    `fixed_qty`, `fixed_qty` on a profile of another mode (module docstring) and a missing value
    are refused."""
    mode = sizing.mode
    if mode == "profile":
        return None
    if mode != "fixed_qty":
        message = f"{mode} sizing is not available yet."
        raise _invalid("sizing.mode", RULE_SIZING_MODE_UNSUPPORTED, message)
    if profile.sizing_mode != "fixed_qty":
        message = f"fixed_qty sizing on a {profile.sizing_mode} profile is not available yet."
        raise _invalid("sizing.mode", RULE_SIZING_MODE_UNSUPPORTED, message)
    value = sizing.qty
    if value is None or not value.is_finite():
        raise _invalid("sizing.qty", "required", f"{mode} sizing needs its value.")
    return {"sizing_mode": mode, **dict.fromkeys(_SIZING_FIELDS), "fixed_qty": value}, value


def _stop_overlay(
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
    if value.is_finite() and stop.unit != "price":
        distance = value * tick if stop.unit == "ticks" else _EXACT.divide(ref * value, 100)
        level = ref - distance if side == "buy" else ref + distance
    errors = stop_errors(effect=OrderEffect.ENTRY, side=side, reference_price=ref, stop=level)
    if errors:
        raise OrderInvalid(errors[0].message, errors=errors)
    distance = ref - level if side == "buy" else level - ref
    return {"sl_offset_unit": "ticks", "sl_offset_value": _EXACT.divide(distance, tick)}


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


def _narrower(
    profile: AccountProfile, value: Decimal | None, leg: LegSizing, baseline: LegSizing
) -> None:
    """The interim's narrowing rows (module docstring): a qty above the profile's `fixed_qty`,
    and a stop further from the shared anchor than the profile's own, are refused whole, 403."""
    if value is not None and profile.fixed_qty is not None and value > profile.fixed_qty:
        message = "The request's qty is above the profile's."
        raise RiskRefused(message, errors=(FieldError("sizing.qty", "fixed_qty", message),))
    if leg.stop is None or baseline.stop is None:
        raise ValueError("an anchored leg carries its stop")
    if leg.stop.distance > baseline.stop.distance:
        message = "The request's stop is further from entry than the profile's."
        raise RiskRefused(message, errors=(FieldError("stop_loss", "sl_offset_value", message),))


def _market(mid: Px | None, last: Px | None) -> SizingMarket:
    """Step 3a's read as the sizer takes it; a price no `Price` holds is no price."""
    try:
        return SizingMarket(mid=mid, last_price=last)
    except ValidationError:
        try:
            return SizingMarket(mid=None, last_price=last)
        except ValidationError:
            return SizingMarket()


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
        overlay = _overlay(intent.sizing, profile)
        try:
            asked = SizingIntent(
                symbol=intent.symbol, side=intent.side, order_type=intent.order_type,
                price=intent.price,
            )  # fmt: skip
        except ValidationError:
            raise _invalid("price", "finite", "The price cannot be sized.") from None
        figures, untiered = await self._read(account, intent.symbol, profile)
        market = _market(mid, last)

        def answered(leg: LegSizing) -> LegSizing:
            if untiered and leg.reason is FailReason.FIGURE_UNKNOWN:
                self._tier_requests.request_tiers(intent.symbol)  # never awaited, never raises
            return _answered(leg)

        if overlay is None and intent.stop_loss is None:
            leg = self._observed(asked, profile, figures, instrument, market)
            return self._size(answered(leg), profile.sizing_mode, None)
        started = self._clock()
        baseline = size_leg(asked, profile, figures, instrument, market)
        if baseline.ref_price is None or baseline.stop is None:  # a gate skip or no price
            self._observer.record(baseline, self._clock() - started)
            answered(baseline)
            raise ValueError("a leg with no anchor is never ok")
        fields, value = overlay if overlay is not None else ({}, None)
        stop = _stop_overlay(intent.stop_loss, intent.side, baseline.ref_price, instrument)
        try:
            widened = AccountProfile.model_validate(profile.model_dump() | fields | stop)
        except ValidationError:
            message = "The request's sizing is out of range."
            raise _invalid("sizing", "profile_overlay", message) from None
        leg = answered(self._observed(asked, widened, figures, instrument, market))
        overlaid = overlay is not None or intent.stop_loss is not None
        if overlaid and leg.binding is not None:  # refused whole, never clamped
            message = "The request goes past the profile's caps."
            raise RiskRefused(message, errors=(FieldError("sizing", leg.binding.cap, message),))
        _narrower(profile, value, leg, baseline)
        return self._size(leg, widened.sizing_mode, value)

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
        rates = reading.symbols.get(symbol)
        if rates is None:  # no entry: the source has no rates to read (live, another venue), so
            # no tiers to ask for; `TierRequests` asks only where the figures read them
            return reading.account, False
        known = reading.account.model_copy(
            update={
                "maintenance_margin_rate": rates.maintenance_margin_rate,
                "taker_fee_rate": rates.taker_fee_rate,
            }
        )
        return known, rates.maintenance_margin_rate is None

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
