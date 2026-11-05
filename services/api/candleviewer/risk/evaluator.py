"""The pure risk evaluator (E39-T01, M17): one order, one account's figures, one verdict.

No I/O, no clock read (`now` is passed in), no statechart (C-2.20, C-2.21): synchronous code
enforces. The checks run in the fixed order of `CHECK_ORDER` and stop at the first refusal, so the
verdict and its message are deterministic. Each cap check judges the cap's blocking limit (refused
on breach) and, independently, the policy's `warn` threshold (a `RiskWarning`), so a warn
threshold never disables a blocking limit (`caps.py`).

Malformed figures never raise and never admit: a non-finite `Decimal` (NaN, an infinity), a negative
quantity, price, notional, held notional or counter, a negative or non-finite cap limit, a figure or
limit whose decimal exponent (`adjusted()`) is beyond +/-100, so no ratio can overflow, a
tz-naive `as_of`, or an order priced at or below 0, whose notional exceeds `qty` at its reference
price, or that opens exposure with a notional at or below 0, refuses `risk_state_unavailable`. An
exception out of `evaluate` is a programmer error only (a tz-naive `now`), never a verdict.
`figures.as_of` and `now` must come from the same injected clock, or freshness is judged across
two clocks.

Comparisons are exact: a ratio cap is compared by cross-multiplying, never by dividing, and every
comparison runs in a `Decimal` context of `_PRECISION` digits, wide enough for the exact product of
two `numeric(38,18)` figures, so no rounding can move a verdict. A figure at its limit is admitted
for a projected amount (notional, positions, orders) and refused for a measured loss (daily loss,
drawdown, consecutive losses), which is reached, not added to.

An exempt order (reduce-only and opening nothing) skips every check, the stale-state refusal and
the lockout included (US-PROF-004, US-ADMIN-003, SR-E39-02).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import Final

from candleviewer.domain.plain_decimal import PlainWidthError, plain_decimal
from candleviewer.risk.caps import ResolvedCap, ResolvedCaps
from candleviewer.risk.inputs import RiskFigures, RiskOrder
from candleviewer.risk.models import RiskDecision, RiskRefusal

#: The order the checks run in; a test pins it so it cannot drift.
CHECK_ORDER: Final = (
    "symbol",
    "kill_switch",
    "lockout",
    "risk_state",
    "max_orders_per_minute",
    "max_concurrent_orders",
    "max_open_positions",
    "max_position_notional_usd",
    "max_total_notional_usd",
    "max_position_pct_equity",
    "per_symbol_concentration_pct",
    "max_leverage",
    "max_daily_loss_usd",
    "max_daily_loss_pct",
    "max_drawdown_pct",
    "max_consecutive_losses",
)
#: `risk_state_max_age_seconds`' default (E39-T01).
DEFAULT_MAX_AGE: Final = timedelta(seconds=10)
_HUNDRED: Final = Decimal(100)
_ZERO: Final = Decimal(0)
#: Digits for every comparison: two 38-digit operands multiply exactly within 80.
_PRECISION: Final = 80
#: A reported ratio (`actual`, the message) is display only, never compared: 28 digits.
_DISPLAY: Final = Context(prec=28)
#: The widest `Decimal.adjusted()` a figure may have: far past `numeric(38,18)`, and a ratio or
#: product of two such figures stays far inside the context's exponent range (no `Overflow`).
_MAX_EXPONENT: Final = 100


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return _DISPLAY.divide(numerator, denominator)


@dataclass(frozen=True, slots=True)
class RiskWarning:
    """A policy `warn` limit the order passed over; E39-S02 turns it into a notice."""

    cap: str
    limit: Decimal
    actual: Decimal


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    decision: RiskDecision
    warnings: tuple[RiskWarning, ...] = ()


class _Refused(Exception):
    def __init__(self, decision: RiskDecision) -> None:
        self.decision = decision


def _fmt(value: Decimal) -> str:
    try:
        return plain_decimal(value)
    except PlainWidthError:  # a figure too wide for plain form: never let wording fail a verdict
        return str(value)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _in_range(value: Decimal) -> bool:
    """Finite and within `_MAX_EXPONENT` orders of magnitude, so no ratio overflows."""
    return value.is_finite() and abs(value.adjusted()) <= _MAX_EXPONENT


def _well_formed(order: RiskOrder, figures: RiskFigures, caps: ResolvedCaps) -> bool:
    """Every figure in range, every amount and counter non-negative, `as_of` tz-aware."""
    signed = (figures.daily_figure, figures.day_peak_figure)
    unsigned = [order.qty, order.reference_price, order.notional]
    unsigned += figures.symbol_notional.values()
    unsigned += [cap.limit for cap in caps.caps.values()]
    unsigned += [cap.limit for cap in caps.warn_limits.values()]
    unsigned += [v for v in (figures.equity, figures.day_start_equity) if v is not None]
    counters = (
        figures.open_positions,
        figures.open_orders,
        figures.orders_last_minute,
        figures.consecutive_losses,
    )
    return (
        _aware(figures.as_of)
        and all(_in_range(v) for v in signed)
        and all(_in_range(v) and v >= _ZERO for v in unsigned)
        and min(counters) >= 0
        and _priced(order)
    )


def _priced(order: RiskOrder) -> bool:
    """A positive reference price; a notional never above `qty` at it, and positive when the
    order opens exposure, since every exposure cap measures the held notional plus this one."""
    return (
        order.reference_price > _ZERO
        and order.notional <= order.qty * order.reference_price
        and (order.notional > _ZERO or not order.opens_exposure)
    )


def evaluate(
    order: RiskOrder,
    figures: RiskFigures,
    caps: ResolvedCaps,
    *,
    now: datetime,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> RiskEvaluation:
    """Judge `order` against `caps` on `figures`; `now` is the injected clock's reading.

    Never raises on malformed figures (it refuses, module docstring); a tz-naive `now` is a
    programmer error and raises `ValueError`.
    """
    if not _aware(now):
        raise ValueError("now must be timezone-aware (the injected clock's UTC reading)")
    if order.exempt:
        return RiskEvaluation(RiskDecision(allowed=True, evaluated_at=now))
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return _judge(order, figures, caps, now, max_age)


def _judge(
    order: RiskOrder,
    figures: RiskFigures,
    caps: ResolvedCaps,
    now: datetime,
    max_age: timedelta,
) -> RiskEvaluation:
    warnings: list[RiskWarning] = []

    def refuse(code: RiskRefusal, cap: str, message: str) -> _Refused:
        return _Refused(
            RiskDecision(allowed=False, code=code, cap=cap, message=message, evaluated_at=now)
        )

    def check(
        name: str, over: Callable[[Decimal], bool], actual: Decimal, after: Decimal | None
    ) -> None:
        """Refuse on the blocking limit, then record the warn threshold, each on its own."""
        cap = caps.get(name)
        if cap is not None and over(cap.limit):
            raise breach(cap, actual, after)
        warn = caps.warn_limit(name)
        if warn is not None and over(warn.limit):
            warnings.append(RiskWarning(name, warn.limit, actual))

    def breach(cap: ResolvedCap, actual: Decimal, after: Decimal | None) -> _Refused:
        projected = "" if after is None else f", after this order {_fmt(after)}"
        message = (
            f"would exceed {cap.name} {_fmt(cap.limit)} (current {_fmt(actual)}{projected}), "
            f"set by {cap.source.label}"
        )
        return _Refused(
            RiskDecision(
                allowed=False,
                code=RiskRefusal.RISK_LIMIT_BREACHED,
                cap=cap.name,
                limit=cap.limit,
                actual=actual,
                message=message,
                evaluated_at=now,
            )
        )

    try:
        if not _well_formed(order, figures, caps):
            raise refuse(
                RiskRefusal.RISK_STATE_UNAVAILABLE, "risk_state", "risk inputs are malformed"
            )
        symbol = order.symbol
        if not (caps.all_symbols or symbol in caps.allowed_symbols):
            raise refuse(RiskRefusal.SYMBOL_NOT_ALLOWED, "allowed_symbols", f"{symbol} not allowed")
        if symbol in caps.blocked_symbols:
            raise refuse(RiskRefusal.SYMBOL_NOT_ALLOWED, "blocked_symbols", f"{symbol} is blocked")
        if figures.kill_switch_engaged:
            raise refuse(RiskRefusal.TRADING_DISABLED, "kill_switch", "the kill switch is engaged")
        if figures.lockout_active:
            raise refuse(RiskRefusal.ACCOUNT_LOCKED, "lockout", "the account is locked out")
        age = now - figures.as_of
        equity, day_equity = figures.equity, figures.day_start_equity
        if (
            age > max_age
            or age < timedelta(0)
            or equity is None
            or equity <= _ZERO
            or day_equity is None
            or day_equity <= _ZERO
        ):
            raise refuse(
                RiskRefusal.RISK_STATE_UNAVAILABLE, "risk_state", "risk state is unavailable"
            )

        sent = Decimal(figures.orders_last_minute)
        check("max_orders_per_minute", lambda limit: sent + 1 > limit, sent, sent + 1)
        working = Decimal(figures.open_orders)
        check("max_concurrent_orders", lambda limit: working + 1 > limit, working, working + 1)
        held = figures.symbol_notional.get(symbol, _ZERO)
        # The OMS's effect, so a hedge-mode second side counts too; an unheld symbol always opens.
        if order.opens_position or held == _ZERO:
            count = Decimal(figures.open_positions)
            check("max_open_positions", lambda limit: count + 1 > limit, count, count + 1)
        held_after = held + order.notional
        check("max_position_notional_usd", lambda limit: held_after > limit, held, held_after)
        gross = figures.gross_notional
        gross_after = gross + order.notional
        check("max_total_notional_usd", lambda limit: gross_after > limit, gross, gross_after)
        check(
            "max_position_pct_equity",
            lambda limit: held_after * _HUNDRED > limit * equity,
            _ratio(held * _HUNDRED, equity),
            _ratio(held_after * _HUNDRED, equity),
        )
        _concentration(caps, held, held_after, check, refuse)
        check(
            "max_leverage",
            lambda limit: gross_after > limit * equity,
            _ratio(gross, equity),
            _ratio(gross_after, equity),
        )
        loss = max(_ZERO, -figures.daily_figure)
        check("max_daily_loss_usd", lambda limit: loss >= limit, loss, None)
        check(
            "max_daily_loss_pct",
            lambda limit: loss * _HUNDRED >= limit * day_equity,
            _ratio(loss * _HUNDRED, day_equity),
            None,
        )
        drawdown = max(_ZERO, figures.day_peak_figure - figures.daily_figure)
        check(
            "max_drawdown_pct",
            lambda limit: drawdown * _HUNDRED >= limit * day_equity,
            _ratio(drawdown * _HUNDRED, day_equity),
            None,
        )
        losses = Decimal(figures.consecutive_losses)
        check("max_consecutive_losses", lambda limit: losses >= limit, losses, None)
    except _Refused as refused:
        return RiskEvaluation(refused.decision, tuple(warnings))
    return RiskEvaluation(RiskDecision(allowed=True, evaluated_at=now), tuple(warnings))


_Check = Callable[[str, Callable[[Decimal], bool], Decimal, Decimal | None], None]


def _concentration(
    caps: ResolvedCaps,
    held: Decimal,
    held_after: Decimal,
    check: _Check,
    refuse: Callable[[RiskRefusal, str, str], _Refused],
) -> None:
    """The symbol's share of the aggregate cap, so a first position is not 100 % of itself.

    The base is the blocking `max_total_notional_usd` only; a policy warn total is never a base.
    A blocking concentration cap with no blocking base cannot be measured and refuses closed; a
    warn-only one is skipped. A zero base has nothing to share: the zero total cap refused first.
    """
    name = "per_symbol_concentration_pct"
    total = caps.get("max_total_notional_usd")
    if total is None:
        if caps.get(name) is not None:
            raise refuse(
                RiskRefusal.RISK_LIMIT_BREACHED,
                name,
                f"{name} cannot be measured without max_total_notional_usd",
            )
        return
    base = total.limit
    if base == _ZERO:  # the zero total cap has refused any positive notional: nothing to share
        return
    check(
        name,
        lambda limit: held_after * _HUNDRED > limit * base,
        _ratio(held * _HUNDRED, base),
        _ratio(held_after * _HUNDRED, base),
    )
