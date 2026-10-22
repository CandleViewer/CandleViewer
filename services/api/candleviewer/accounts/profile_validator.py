"""The profile's second validation pass (E28-T02 #906, slice B2); here, its warnings.

A warning is advice that never blocks a save (`ProfileWarning`, `22-api-openapi.yaml`). T02 gives
the two about the symbol lists, judged by `SymbolScope`, the matcher the order path uses
(PF-T07): `no_symbols`, a profile that allows no symbol and so sizes nothing (decision D11), and
`all_symbols`, one that allows every listed symbol. A read judges the profile alone; a write,
which reads the instrument list, also judges what the exchange lists. `sizing_below_min_order`
and `stop_beyond_liquidation` need the sizer (E28-T03). No I/O, logging or clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

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
    A write passes the instrument list and keeps the read's warning, field included. Of the
    listed, trading USDT perpetuals it also flags none allowed (`blocked_symbols` when the allow
    side admitted some, else `allowed_symbols`) and all admitted by the allow side before the
    block list, its entries together. A listing with nothing trading adds nothing.
    """
    scope = SymbolScope.of(profile)
    tradable = [i for i in (listed or {}).values() if is_trading_usdt_perpetual(i)]
    admitted = [i for i in tradable if scope.admits(i)]
    if _UNIVERSAL in profile.denied_symbols:
        return (ProfileWarning("no_symbols", _NO_SYMBOLS, "blocked_symbols"),)
    if not (profile.all_symbols or profile.allowed_symbols):
        return (ProfileWarning("no_symbols", _NO_SYMBOLS, "allowed_symbols"),)
    if tradable and not any(scope.allows(i) for i in tradable):
        field = "blocked_symbols" if admitted else "allowed_symbols"
        return (ProfileWarning("no_symbols", _NO_SYMBOLS, field),)
    if profile.all_symbols:
        return (ProfileWarning("all_symbols", _ALL_SYMBOLS, "all_symbols"),)
    if _UNIVERSAL in profile.allowed_symbols or (tradable and len(admitted) == len(tradable)):
        return (ProfileWarning("all_symbols", _ALL_SYMBOLS, "allowed_symbols"),)
    return ()
