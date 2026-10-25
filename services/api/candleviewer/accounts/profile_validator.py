"""The profile's second validation pass (E28-T02 #906, slice B2): its warnings and its refusals.

A warning is advice that never blocks a save (`ProfileWarning`, `22-api-openapi.yaml`). T02 gives
the two about the symbol lists, judged by `SymbolScope`, the matcher the order path uses
(PF-T07): `no_symbols`, a profile that allows no symbol and so sizes nothing (decision D11), and
`all_symbols`, one that allows every listed symbol. A read judges the profile alone; a write,
which reads the instrument list, also judges what the exchange lists. E28-T03 (#907) adds
`sizing_below_min_order` and `stop_beyond_liquidation` (SR-E28-26) through the optional
`SizingWarningsPort`: `sizing_warnings` judges them with the order path's sizer, and a missing
input drops a warning with one log line, never a 503 (#907's ruling of 2026-10-25 17:27Z).

`judge_exchange_limits` refuses a write against the exchange's limits (`ProfileRejected`'s second
pass), judged for the entries the write introduces; it has no I/O, logging or clock.
`check_exchange_limits` is its async edge: it reads the listing of the account's environment
through `InstrumentLimitsPort`, bound in the composition root, only when the write introduces
allow scope or moves a judged figure toward a limit. A read it skips is one no listing could
refuse, so a write that introduces nothing never waits on the exchange's data.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import AccountNotFoundError, AccountsError
from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profile_input import ProfileFieldError
from candleviewer.accounts.profiles import AccountProfile, SymbolScope, is_trading_usdt_perpetual
from candleviewer.accounts.sizer import (
    LIQUIDATION_BUFFER_FRACTION,
    FailReason,
    LegSizing,
    SizingIntent,
    SizingMarket,
    beyond_liquidation,
    liquidation_edge,
    liquidation_estimate,
    resolve_stop,
    size_leg,
)
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Environment, Side

#: Every USDT perpetual's symbol ends with `USDT`: allowed, this pattern allows them all; blocked,
#: it blocks them all.
_UNIVERSAL: Final = "*USDT"
_NO_SYMBOLS: Final = "Allows no symbol, so it sizes nothing."
_ALL_SYMBOLS: Final = "Allows every listed symbol — consider restricting."


@dataclass(frozen=True, slots=True)
class ProfileWarning:
    """One entry of a profile answer's `warnings[]`; its message is fixed for its code."""

    code: Literal["all_symbols", "no_symbols", "sizing_below_min_order", "stop_beyond_liquidation"]
    message: str
    field: str  # the `AccountProfileInput` path it is about
    symbol: str | None = None  # a sizing warning's
    estimated: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        """The contract's `ProfileWarning`; T02's set neither `symbol` nor `estimated`."""
        said: dict[str, str | bool] = {"code": self.code, "message": self.message}
        said["field"] = self.field
        if self.symbol is not None:
            said |= {"symbol": self.symbol, "estimated": self.estimated}
        return said


def profile_warnings(
    profile: AccountProfile, listed: Mapping[str, Instrument] | None = None
) -> tuple[ProfileWarning, ...]:
    """At most one symbol warning, `no_symbols` before `all_symbols`.

    A read passes no `listed` and judges the lists alone: `*USDT` blocked, or an empty allow-list
    without `all_symbols` (D11), allows nothing; the flag, or `*USDT` allowed, allows everything.
    A write passes the instrument list. It keeps the read's `no_symbols`, field included, and the
    read's `all_symbols` stands unless the listing shows that nothing is allowed. Of the listed,
    trading USDT perpetuals it also flags none allowed (`blocked_symbols` when the allow side
    admitted some, else `allowed_symbols`) and all admitted by the allow side before the block
    list, its entries together. A listing with nothing trading adds nothing.
    """
    if _UNIVERSAL in profile.denied_symbols:
        return (ProfileWarning("no_symbols", _NO_SYMBOLS, "blocked_symbols"),)
    if not (profile.all_symbols or profile.allowed_symbols):
        return (ProfileWarning("no_symbols", _NO_SYMBOLS, "allowed_symbols"),)
    scope = SymbolScope.of(profile)
    tradable = [i for i in (listed or {}).values() if is_trading_usdt_perpetual(i)]
    admitted = [i for i in tradable if scope.admits(i)]
    if tradable and not any(scope.allows(i) for i in tradable):
        field = "blocked_symbols" if admitted else "allowed_symbols"
        return (ProfileWarning("no_symbols", _NO_SYMBOLS, field),)
    if profile.all_symbols:
        return (ProfileWarning("all_symbols", _ALL_SYMBOLS, "all_symbols"),)
    if _UNIVERSAL in profile.allowed_symbols or (tradable and len(admitted) == len(tradable)):
        return (ProfileWarning("all_symbols", _ALL_SYMBOLS, "allowed_symbols"),)
    return ()


#: `ProfileRejected`'s second pass; each rule is audited as `profile.save_refused`.
SECOND_PASS_RULES: Final = frozenset(
    {"max_leverage", "min_order_qty", "qty_step", "min_notional", "symbol_not_listed"}
)
#: Exact arithmetic for the step and the plain form: 200 digits, against a column's 38. With no
#: trap, a quotient too long for them makes the remainder NaN, not an error; NaN is off the step.
_EXACT: Final = Context(prec=200, traps=[])
#: Each limit rule's body member and SCR-131's copy, which names the instrument, its limit and the
#: profile's own figure, and no other value of the body.
_COPY: Final = {
    "max_leverage": ("leverage", "{s} allows at most {limit}x — your {figure}x would be rejected."),
    "min_order_qty": (
        "sizing.qty",
        "{s} takes at least {limit} per order — your {figure} would be rejected.",
    ),
    "qty_step": (
        "sizing.qty",
        "{s} takes quantities in steps of {limit} — your {figure} would be rejected.",
    ),
    "min_notional": (
        "risk_caps.max_position_notional_usd",
        "{s} takes at least {limit} USDT per order — your {figure} USDT position cap would refuse"
        " every one.",
    ),
}
_NOT_LISTED: Final = "is not a listed, trading USDT perpetual."


@dataclass(frozen=True, slots=True)
class SecondPassResult:
    """The second pass's refusals, every one it finds and none cut, and the write's warnings."""

    errors: tuple[ProfileFieldError, ...]
    warnings: tuple[ProfileWarning, ...]


def judge_exchange_limits(
    profile: AccountProfile, listed: Mapping[str, Instrument], *, stored: AccountProfile | None
) -> SecondPassResult:
    """`ProfileRejected`'s second pass, over a profile the first pass accepted and the exchange's
    listing, judged for the entries the write introduces (#906, rulings of 2026-10-22 14:22Z and
    14:39Z, issuecomment-6360499465). `stored` is the profile it replaces; a create, `None`, is
    compared with a profile that allows nothing.

    The limit rules judge the listed, trading USDT perpetuals the profile allows (the allow side,
    then the block list): those `stored` did not allow (a new entry, `all_symbols` turned on, a
    block entry removed), and every one for a rule whose figure moved toward its limit (leverage
    raised; `fixed_qty` changed or set; `max_position_notional` lowered or set). `symbol_not_listed`
    judges each allow entry naming a symbol that `stored` did not hold. So a pure reduction, or an
    unchanged re-save, is never refused; a limit since tightened is held at order time. Turning
    `trading_enabled` or `enabled` on introduces no scope and moves no figure, so it judges nothing
    new either (ruling of 2026-10-23 07:04Z, in the same comment). Refusals come rule by rule, then
    by symbol, then `symbol_not_listed` by index, each at most once.
    """
    scope = SymbolScope.of(profile)
    allowed = sorted(
        (i for i in listed.values() if is_trading_usdt_perpetual(i) and scope.allows(i)),
        key=lambda i: i.symbol,
    )
    by_leverage, by_qty, by_cap = _judged(profile, stored, allowed)
    lev, qty, cap = profile.leverage, profile.fixed_qty, profile.max_position_notional
    errors = [
        _breach("max_leverage", i, i.max_leverage, lev) for i in by_leverage if lev > i.max_leverage
    ]
    if qty is not None:
        errors += [
            _breach("min_order_qty", i, i.min_order_qty, qty)
            for i in by_qty
            if qty < i.min_order_qty
        ]
        errors += [
            _breach("qty_step", i, i.qty_step, qty)
            for i in by_qty
            if _EXACT.remainder(qty, i.qty_step) != 0
        ]
    if cap is not None:
        errors += [
            _breach("min_notional", i, i.min_notional, cap) for i in by_cap if cap < i.min_notional
        ]
    held = frozenset(() if stored is None else stored.allowed_symbols)
    errors += [
        ProfileFieldError(f"allowed_symbols[{n}]", "symbol_not_listed", f"{entry} {_NOT_LISTED}")
        for n, entry in enumerate(profile.allowed_symbols)
        if not entry.startswith("*") and entry not in held and not _trading(listed.get(entry))
    ]
    return SecondPassResult(tuple(errors), profile_warnings(profile, listed))


def _judged(
    profile: AccountProfile, stored: AccountProfile | None, allowed: list[Instrument]
) -> tuple[list[Instrument], list[Instrument], list[Instrument]]:
    """What the leverage, quantity and position-cap rules judge, in `allowed`'s order: the
    instruments the write introduces, or all it allows when it moved the rule's figure toward
    the limit. A create introduces all it allows. A rule or trigger added here must be added to
    `_needs_listing` too; the skip-implies-no-refusal property test guards the pair."""
    if stored is None:
        return allowed, allowed, allowed
    before = SymbolScope.of(stored)
    new = [i for i in allowed if not before.allows(i)]
    cap, was = profile.max_position_notional, stored.max_position_notional
    return (
        allowed if profile.leverage > stored.leverage else new,
        allowed if profile.fixed_qty != stored.fixed_qty else new,
        allowed if cap is not None and (was is None or cap < was) else new,
    )


def _breach(
    rule: str, instrument: Instrument, limit: Decimal, figure: Decimal
) -> ProfileFieldError:
    """A limit rule's refusal, the limit and the figure written plainly (`20.00` is `20`)."""
    field, copy = _COPY[rule]
    plain = _plain(limit)
    message = copy.format(s=instrument.symbol, limit=f"{plain:f}", figure=f"{_plain(figure):f}")
    return ProfileFieldError(field, rule, message, limit=plain, symbol=instrument.symbol)


def _plain(value: Decimal) -> Decimal:
    return _EXACT.normalize(value)


def _trading(instrument: Instrument | None) -> bool:
    return instrument is not None and is_trading_usdt_perpetual(instrument)


#: `ProfileRejected`: "an instrument cache at most 15 minutes old (refreshed first when older)".
INSTRUMENT_MAX_AGE_S: Final = 900.0
#: Within the profile save's 2 s (the E28 threat model's "Profile save" row, PF-D04), less the
#: write path's own share (06 budget 13) and the client's round trip: a save that waits it out and
#: then succeeds still answers in time.
INSTRUMENT_DEADLINE_S: Final = 1.5


class InstrumentLimitsUnavailable(AccountsError):
    """No listing confirmed within the deadline: the refresh runs on, failed, or no catalogue is
    wired. Nothing is judged or saved (PF-D04): 503 `instrument_cache_unavailable`. Its message is
    a constant, naming no value."""


class InstrumentLimitsPort(Protocol):
    """The exchange's listing for one environment (C-2.11), bound in the composition root."""

    @property
    def environment(self) -> Environment: ...

    async def listed(self, *, max_age_s: float, deadline_s: float) -> Mapping[str, Instrument]:
        """Every instrument of the catalogue by symbol, from a fetch that succeeded at most
        `max_age_s` ago, refreshed first (one fetch for every concurrent caller) when older;
        `InstrumentLimitsUnavailable` when that takes longer than `deadline_s`, fails, or there is
        no catalogue. Never an unconfirmed copy."""


async def check_exchange_limits(
    profile: AccountProfile,
    *,
    environment: Environment,
    instruments: InstrumentLimitsPort,
    stored: AccountProfile | None,
    warnings: SizingWarningsPort | None = None,
) -> SecondPassResult:
    """The second pass over the listing of the account's `environment`, read only when the write
    introduces allow scope (a create allowing anything; a new allow entry, `all_symbols` turned
    on, a block entry removed) or moves a judged figure toward a limit (leverage raised;
    `fixed_qty` changed, set or unset, fail closed by the ruling of 2026-10-23 16:29Z;
    `max_position_notional` lowered or set), per #906's ruling of 2026-10-22 14:39Z
    (issuecomment-6360499465). A read it skips is one no listing could refuse. Any other write,
    a profile allowing nothing (D11) among them, answers no refusal and the read's warnings, and
    is never a 503.

    Before any read, `AccountNotFoundError` for a port of another environment (C-2.11), and for a
    `stored` that is not the profile this write replaces (another profile, or another account's).
    The port's `InstrumentLimitsUnavailable` passes through: nothing is judged. With `warnings`,
    a write that is not refused also carries `sizing_warnings`' (`judge_sizing`), after T02's."""
    if instruments.environment != environment:
        raise AccountNotFoundError("account")
    replaced = (profile.profile_id, profile.account_id)
    if stored is not None and (stored.profile_id, stored.account_id) != replaced:
        raise AccountNotFoundError("profile")
    if not _needs_listing(profile, stored):
        judged = SecondPassResult((), profile_warnings(profile))
    else:
        listed = await instruments.listed(
            max_age_s=INSTRUMENT_MAX_AGE_S, deadline_s=INSTRUMENT_DEADLINE_S
        )
        judged = judge_exchange_limits(profile, listed, stored=stored)
    if warnings is None or judged.errors:
        return judged
    return SecondPassResult((), (*judged.warnings, *await judge_sizing(profile, warnings)))


def _needs_listing(profile: AccountProfile, stored: AccountProfile | None) -> bool:
    """Whether the write introduces allow scope or moves a judged figure toward a limit, from the
    lists and the figures alone: `_judged`'s triggers, known before the listing is read."""
    if not (profile.all_symbols or profile.allowed_symbols):
        return False  # D11: it allows nothing, so nothing is judged
    if stored is None:
        return True  # a create introduces all it allows
    cap, was = profile.max_position_notional, stored.max_position_notional
    return (
        not set(profile.allowed_symbols) <= set(stored.allowed_symbols)
        or (profile.all_symbols and not stored.all_symbols)
        or not set(stored.denied_symbols) <= set(profile.denied_symbols)
        or profile.leverage > stored.leverage
        or profile.fixed_qty != stored.fixed_qty
        or (cap is not None and (was is None or cap < was))
    )


#: The symbols a save's sizing warnings judge, at most (#907's ruling of 2026-10-25 17:27Z).
WARNING_SYMBOLS_MAX: Final = 25
#: The warnings port's share of the save's 2 s, after the listing's 1.5 s (PF-D04).
WARNINGS_DEADLINE_S: Final = 0.25
_SIZING: Final = ("sizing_below_min_order", "stop_beyond_liquidation")
_SIDES: Final[tuple[Side, Side]] = ("buy", "sell")


@dataclass(frozen=True, slots=True)
class SymbolFigures:
    """One symbol's save-time inputs: its instrument; its ticker and ATR as the order path builds
    the `SizingMarket` (mid, else the last price; a stale ticker gives neither); and the
    maintenance margin rate of the account's risk-limit tier for it, else tier 1's."""

    instrument: Instrument | None
    market: SizingMarket
    maintenance_margin_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class SaveFigures:
    """The account's figures (`equity` from the account health feed's wallet), whether that
    equity is older than the feed's staleness bound, and the inputs of each symbol asked."""

    figures: AccountFigures
    equity_stale: bool
    symbols: Mapping[str, SymbolFigures]


class SizingWarningsPort(Protocol):
    """The account's market and wallet at save time, injected by the profile routes' wiring."""

    async def open_symbols(self, account_id: UUID) -> Sequence[str]:
        """The symbols of the account's open positions."""

    async def figures(self, account_id: UUID, symbols: Sequence[str]) -> SaveFigures:
        """The account's figures and each symbol's inputs; an unknown one is `None`."""


@dataclass(frozen=True, slots=True)
class DroppedWarning:
    """A sizing warning not judged for want of an input; logged, never a 503."""

    code: str
    symbol: str | None
    reason: str


def warning_symbols(profile: AccountProfile, open_symbols: Sequence[str]) -> tuple[str, ...]:
    """The profile's exact `allowed_symbols` entries (none for `all_symbols` or a pattern), then
    the open positions' symbols: deduplicated in that order, at most `WARNING_SYMBOLS_MAX`."""
    exact = () if profile.all_symbols else [e for e in profile.allowed_symbols if "*" not in e]
    return tuple(dict.fromkeys([*exact, *open_symbols]))[:WARNING_SYMBOLS_MAX]


def sizing_warnings(
    profile: AccountProfile, save: SaveFigures, symbols: Sequence[str]
) -> tuple[tuple[ProfileWarning, ...], tuple[DroppedWarning, ...]]:
    """Every symbol in scope, each side as a market order through the order path's `size_leg`:
    `sizing_below_min_order` when a leg misses a minimum (estimated when priced at the last
    price, on the ATR fallback stop, or at a stale equity); `stop_beyond_liquidation` when a
    side's stop is not inside `liquidation_estimate` (always estimated). Pure: what it cannot
    judge comes back as dropped."""
    found: list[ProfileWarning] = []
    dropped: list[DroppedWarning] = []
    able = profile.model_copy(update={"enabled": True, "trading_enabled": True})
    for symbol in symbols:
        got = save.symbols.get(symbol)
        inst = None if got is None else got.instrument
        ref = None if got is None else got.market.mid or got.market.last_price
        reason = "instrument" if inst is None or inst.symbol != symbol else "no_reference_price"
        if got is None or inst is None or ref is None or reason == "instrument":
            dropped += [DroppedWarning(code, symbol, reason) for code in _SIZING]
            continue
        mmr, last = got.maintenance_margin_rate, got.market.mid is None
        figures = save.figures.model_copy(update={"maintenance_margin_rate": mmr})
        legs = [
            size_leg(SizingIntent(symbol=inst.symbol, side=side, order_type="market"), able,
                     figures, inst, got.market)
            for side in _SIDES
        ]  # fmt: skip
        if missed := next((leg for leg in legs if leg.minimum is not None), None):
            stale = last or missed.stop_fallback or save.equity_stale
            found.append(_below_minimum(symbol, missed, estimated=stale))
        elif any(leg.qty is None and leg.reason is FailReason.FIGURE_UNKNOWN for leg in legs):
            dropped.append(DroppedWarning(_SIZING[0], symbol, "figure_unknown"))
        if mmr is None:
            dropped.append(DroppedWarning(_SIZING[1], symbol, "maintenance_margin_rate"))
        elif (beyond := _beyond(able, inst, ref, got.market, mmr)) is not None:
            found.append(beyond)
    return tuple(found), tuple(dropped)


def _below_minimum(symbol: str, leg: LegSizing, *, estimated: bool) -> ProfileWarning:
    said = f"{symbol}: at the account's equity the sizing gives less than its minimum order"
    return ProfileWarning("sizing_below_min_order", f"{said}: {leg.render()}.", "sizing",
                          symbol, estimated)  # fmt: skip


def _beyond(
    p: AccountProfile, inst: Instrument, ref: Decimal, market: SizingMarket, mmr: Decimal
) -> ProfileWarning | None:
    """The first side whose stop is not inside the liquidation estimate by the buffer (the leg
    refusal's `beyond_liquidation`); the estimate shown on the tick toward entry, the edge on the
    tick away from it. `None` when both are inside."""
    for side in _SIDES:
        stop = resolve_stop(side, p, ref, inst, market.atr)
        liquidation = liquidation_estimate(side, ref, p.leverage, mmr)
        tick = inst.tick_size
        if beyond_liquidation(side, stop.price, liquidation, entry=ref, tick=tick):
            buy = side == "buy"
            toward, away = (ROUND_CEILING, ROUND_FLOOR) if buy else (ROUND_FLOOR, ROUND_CEILING)
            shown = (liquidation / tick).to_integral_value(toward) * tick
            edge = liquidation_edge(side, ref, liquidation, tick)
            edge = (edge / tick).to_integral_value(away) * tick
            share = _plain(LIQUIDATION_BUFFER_FRACTION * 100)
            message = (
                f"{inst.symbol}: a {'long' if buy else 'short'}'s stop at "
                f"{_plain(stop.price):f} USDT is not inside the estimated liquidation price "
                f"{_plain(shown):f} USDT at {_plain(p.leverage):f}x by the {share:f} % buffer: "
                f"it must be {'above' if buy else 'below'} {_plain(edge):f} USDT."
            )
            return ProfileWarning("stop_beyond_liquidation", message, "stop_loss", inst.symbol,
                                  True)  # fmt: skip
    return None


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


async def judge_sizing(
    profile: AccountProfile, port: SizingWarningsPort
) -> tuple[ProfileWarning, ...]:
    """`sizing_warnings` over the port's figures, within `WARNINGS_DEADLINE_S`. An empty scope
    judges nothing; a port that fails or runs out of time drops every warning of the scope known
    so far. One structured log line per dropped warning (`code`, `symbol`, `reason`)."""
    symbols = warning_symbols(profile, ())
    try:
        async with asyncio.timeout(WARNINGS_DEADLINE_S):
            symbols = warning_symbols(profile, await port.open_symbols(profile.account_id))
            if not symbols:
                return ()
            save = await port.figures(profile.account_id, symbols)
    except Exception as exc:  # advice only: never a 503 (CancelledError is not an Exception)
        reason = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        found: tuple[ProfileWarning, ...] = ()
        dropped = tuple(DroppedWarning(c, s, reason) for s in symbols or (None,) for c in _SIZING)
    else:
        found, dropped = sizing_warnings(profile, save, symbols)
    for drop in dropped:
        _log().info("profile_sizing_warning_dropped", code=drop.code, symbol=drop.symbol,
                    reason=drop.reason)  # fmt: skip
    return found
