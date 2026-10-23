"""Is a profile write relaxing? (SR-E28-01; #906 D2, the 2026-10-22 11:57Z and 17:25Z rulings.)

A write is relaxing when it loosens a cap or, for a replace, widens the symbols a profile that can
trade may reach; a move is judged on its caps alone. Each cap of `PROFILE_CAPS` is compared on the
stored values as a `Decimal`: `None` is no bound, higher than any number, and every cap of a profile
that cannot trade (`enabled` or `trading_enabled` false), or of no profile, counts as zero, since it
sizes nothing (decision D11). So a move onto the bootstrap `Default` while it cannot trade is not
relaxing, turning trading on always is, and turning it off or clearing the caps of a profile that
cannot trade never is. Only column names leave this module, never a value (C-12.6).
"""

from __future__ import annotations

from decimal import Decimal

from candleviewer.accounts.profile_caps import PROFILE_CAPS
from candleviewer.storage.repositories.account_profiles import AccountProfileValues

_ZERO = Decimal(0)


def can_trade(values: AccountProfileValues) -> bool:
    """The profile may size an order: enabled, with trading on."""
    return values.enabled and values.trading_enabled


def _bound(values: AccountProfileValues | None, column: str) -> Decimal | None:
    """A cap's bound: `None` for none; zero for a profile that cannot trade, or for no profile."""
    if values is None or not can_trade(values):
        return _ZERO
    bound = getattr(values, column)
    return None if bound is None else Decimal(bound)


def looser_caps(
    before: AccountProfileValues | None, after: AccountProfileValues
) -> tuple[str, ...]:
    """The `PROFILE_CAPS` columns whose bound is higher on `after` than on `before`, in
    `PROFILE_CAPS` order."""
    looser: list[str] = []
    for cap in PROFILE_CAPS:
        old, new = _bound(before, cap.column), _bound(after, cap.column)
        if (new is None and old is not None) or (new is not None and old is not None and new > old):
            looser.append(cap.column)
    return tuple(looser)


def widens_symbols(before: AccountProfileValues, after: AccountProfileValues) -> bool:
    """A replace that lets a profile that can trade reach a symbol it could not: false when `after`
    cannot trade; when `before` cannot, whether `after` allows anything; when `before` allows every
    symbol, a block entry removed; otherwise `all_symbols` set, an allow entry added (as written,
    a pattern being an entry) or a block entry removed."""
    if not can_trade(after):
        return False
    if not can_trade(before):
        return after.all_symbols or bool(after.allowed_symbols)
    unblocked = bool(set(before.blocked_symbols or ()) - set(after.blocked_symbols or ()))
    if before.all_symbols:
        return unblocked
    added = bool(set(after.allowed_symbols or ()) - set(before.allowed_symbols or ()))
    return after.all_symbols or added or unblocked
