"""The profile's second validation pass (E28-T02 #906, slice B2): its warnings and its refusals.

A warning is advice that never blocks a save (`ProfileWarning`, `22-api-openapi.yaml`). T02 gives
the two about the symbol lists, judged by `SymbolScope`, the matcher the order path uses
(PF-T07): `no_symbols`, a profile that allows no symbol and so sizes nothing (decision D11), and
`all_symbols`, one that allows every listed symbol. A read judges the profile alone; a write,
which reads the instrument list, also judges what the exchange lists. `sizing_below_min_order`
and `stop_beyond_liquidation` need the sizer (E28-T03).

`judge_exchange_limits` refuses a write against the exchange's limits (`ProfileRejected`'s second
pass), judged for the entries the write introduces. No I/O, logging or clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Context, Decimal
from typing import Final, Literal

from candleviewer.accounts.profile_input import ProfileFieldError
from candleviewer.accounts.profiles import AccountProfile, SymbolScope, is_trading_usdt_perpetual
from candleviewer.domain.events import Instrument

#: Every USDT perpetual's symbol ends with `USDT`: allowed, this pattern allows them all; blocked,
#: it blocks them all.
_UNIVERSAL: Final = "*USDT"
_NO_SYMBOLS: Final = "Allows no symbol, so it sizes nothing."
_ALL_SYMBOLS: Final = "Allows every listed symbol — consider restricting."


@dataclass(frozen=True, slots=True)
class ProfileWarning:
    """One entry of a profile answer's `warnings[]`; its message is fixed for its code."""

    code: Literal["all_symbols", "no_symbols"]
    message: str
    field: str  # the `AccountProfileInput` path it is about

    def to_dict(self) -> dict[str, str]:
        """The contract's `ProfileWarning`; T02 sets neither `symbol` nor `estimated`."""
        return {"code": self.code, "message": self.message, "field": self.field}


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
    14:39Z). `stored` is the profile it replaces; a create, `None`, is compared with a profile that
    allows nothing.

    The limit rules judge the listed, trading USDT perpetuals the profile allows (the allow side,
    then the block list): those `stored` did not allow (a new entry, `all_symbols` turned on, a
    block entry removed), and every one for a rule whose figure moved toward its limit (leverage
    raised; `fixed_qty` changed or set; `max_position_notional` lowered or set). `symbol_not_listed`
    judges each allow entry naming a symbol that `stored` did not hold. So a pure reduction, or an
    unchanged re-save, is never refused; a limit since tightened is held at order time. Refusals
    come rule by rule, then by symbol, then `symbol_not_listed` by index, each at most once.
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
    the limit. A create introduces all it allows."""
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
