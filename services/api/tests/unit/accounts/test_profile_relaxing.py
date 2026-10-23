"""The relaxing judgement (#906 D2, SR-E28-01; the 2026-10-22 11:57Z and 17:25Z rulings).

A cap is looser when raised or removed (no bound) on a profile that can trade; every cap of a
profile that cannot trade, or of no profile, counts as zero. A replace also relaxes when it widens
the symbols of a profile that can trade. Values are the `risk_based` fixture's, in stored units.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.accounts.profile_caps import PROFILE_CAPS
from candleviewer.accounts.profile_relaxing import can_trade, looser_caps, widens_symbols
from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.storage.repositories.account_profiles import AccountProfileValues

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "profiles" / "risk_based.json"
#: Trading on; every cap bounded above zero but `max_position_pct_equity` (no bound).
_TRADES = profile_values(AccountProfile.model_validate_json(_FIXTURE.read_text(encoding="utf-8")))
_CAPS = tuple(cap.column for cap in PROFILE_CAPS)
_UNBOUNDED: dict[str, Any] = dict.fromkeys(_CAPS[:-1])  # `max_orders_per_minute` is NOT NULL
#: The bootstrap `Default`: trading off, every nullable cap unbounded.
_DEFAULT = dataclasses.replace(_TRADES, trading_enabled=False, **_UNBOUNDED)
_BLOCKS = dataclasses.replace(_TRADES, blocked_symbols=("DOGEUSDT",))
_ALL = dataclasses.replace(_BLOCKS, all_symbols=True, allowed_symbols=None)


def _set(values: AccountProfileValues, **changes: Any) -> AccountProfileValues:
    return dataclasses.replace(values, **changes)


@pytest.mark.parametrize("column", _CAPS)
@pytest.mark.parametrize(
    ("old", "new", "looser"),
    [
        (Decimal(5), Decimal(6), True),
        (Decimal(5), None, True),
        (None, Decimal(5), False),
        (Decimal(6), Decimal(5), False),
        (Decimal(5), Decimal(5), False),
        (Decimal(5), Decimal("5.0000000000000000001"), True),  # a float sees no change
    ],
    ids=["raised", "set-to-null", "null-to-set", "lowered", "equal", "decimal-not-float"],
)
def test_a_looser_cap_is_any_cap_raised_or_removed_on_a_profile_that_can_trade(
    column: str, old: Decimal | None, new: Decimal | None, looser: bool
) -> None:
    before, after = _set(_TRADES, **{column: old}), _set(_TRADES, **{column: new})
    assert looser_caps(before, after) == ((column,) if looser else ())


def test_two_looser_caps_are_named_in_profile_caps_order() -> None:
    after = _set(_TRADES, max_orders_per_minute=31, max_position_notional_usd=None)
    assert looser_caps(_TRADES, after) == ("max_position_notional_usd", "max_orders_per_minute")


def test_a_profile_that_cannot_trade_counts_every_cap_as_zero() -> None:
    """Decision D11: it sizes nothing. A move onto the bootstrap `Default` loosens nothing, its caps
    unbounded or not; turning trading on loosens every cap and turning it off none; `enabled` false
    counts as `trading_enabled` false."""
    assert looser_caps(_TRADES, _DEFAULT) == ()
    for cannot in (_set(_TRADES, trading_enabled=False), _set(_TRADES, enabled=False)):
        assert not can_trade(cannot)
        assert looser_caps(cannot, _TRADES) == _CAPS
        assert looser_caps(_TRADES, cannot) == ()
    assert can_trade(_TRADES)


def test_no_previous_default_bounds_nothing_above_zero() -> None:
    assert looser_caps(None, _TRADES) == _CAPS
    assert looser_caps(None, _DEFAULT) == ()


@pytest.mark.parametrize(
    ("before", "after", "widens"),
    [
        (_BLOCKS, _set(_BLOCKS, allowed_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT")), True),
        (_BLOCKS, _set(_BLOCKS, allowed_symbols=("BTCUSDT", "ETHUSDT", "*USDT")), True),
        (_BLOCKS, _set(_BLOCKS, all_symbols=True, allowed_symbols=None), True),
        (_BLOCKS, _set(_BLOCKS, blocked_symbols=None), True),
        (_BLOCKS, _set(_BLOCKS, allowed_symbols=("BTCUSDT",)), False),
        (_BLOCKS, _set(_BLOCKS, blocked_symbols=("DOGEUSDT", "PEPEUSDT")), False),
        (_BLOCKS, _BLOCKS, False),
        (_BLOCKS, _set(_ALL, trading_enabled=False), False),
        (_set(_BLOCKS, trading_enabled=False), _BLOCKS, True),
        (_set(_BLOCKS, trading_enabled=False), _ALL, True),
        (_ALL, _set(_ALL, blocked_symbols=None), True),
        (_ALL, _set(_BLOCKS, allowed_symbols=("BTCUSDT",)), False),
    ],
    ids=[
        "entry-added", "pattern-added", "flag-set", "block-removed", "entry-removed",
        "block-added", "unchanged", "inert-after", "inert-before", "inert-before-all-symbols",
        "all-symbols-block-removed",
        "all-symbols-narrowed",
    ],
)  # fmt: skip
def test_a_replace_widens_the_symbols_only_of_a_profile_that_can_trade(
    before: AccountProfileValues, after: AccountProfileValues, widens: bool
) -> None:
    """Entries compare as written (a pattern is an entry); under `all_symbols` only a block
    removed widens."""
    assert widens_symbols(before, after) is widens


_BOUND = st.none() | st.decimals(min_value=0, max_value=10**6, places=3)
_VALUES = st.builds(
    lambda bounds, enabled, trading: _set(
        _TRADES, enabled=enabled, trading_enabled=trading, **dict(zip(_CAPS, bounds, strict=True))
    ),
    st.tuples(*[_BOUND] * len(_CAPS)),
    st.booleans(),
    st.booleans(),
)


def _rank(values: AccountProfileValues | None, column: str) -> tuple[int, Decimal]:
    """The oracle's order: no bound above every number, a profile that cannot trade at zero."""
    if values is None or not (values.enabled and values.trading_enabled):
        return (0, Decimal(0))
    bound = getattr(values, column)
    return (1, Decimal(0)) if bound is None else (0, Decimal(bound))


@settings(max_examples=300, deadline=None)
@given(before=st.none() | _VALUES, after=_VALUES)
def test_looser_caps_is_the_per_cap_oracle(
    before: AccountProfileValues | None, after: AccountProfileValues
) -> None:
    wanted = tuple(c for c in _CAPS if _rank(after, c) > _rank(before, c))
    assert looser_caps(before, after) == wanted


@settings(max_examples=300, deadline=None)
@given(a=_VALUES, b=_VALUES)
def test_no_cap_is_looser_both_ways(a: AccountProfileValues, b: AccountProfileValues) -> None:
    assert not set(looser_caps(a, b)) & set(looser_caps(b, a))
