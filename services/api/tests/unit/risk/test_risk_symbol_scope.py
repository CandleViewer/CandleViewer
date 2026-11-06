"""The gate's symbol rule is `accounts.profiles.SymbolScope`'s verdict (E39-T01, #908 BQ-3).

A profile's `*USDT` pattern must mean at the risk gate what it means at a profile save and in the
order validator: one matcher, so an allow-list of patterns never refuses every symbol, and a block
list still wins over an allow-list (SR-E28-06, PF-T07).
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.accounts.profiles import SymbolEntries, SymbolScope
from candleviewer.risk import RiskRefusal
from tests.unit.risk._risk_builders import caps, instrument, order, run

_USDC = {"quote_coin": "USDC", "settle_coin": "USDC"}


def _verdict(prof: dict[str, Any], **inst: Any) -> tuple[bool, str | None]:
    decision = run(order(instrument=instrument(**inst)), c=caps(prof=prof)).decision
    if not decision.allowed:
        assert decision.code is RiskRefusal.SYMBOL_NOT_ALLOWED
    return decision.allowed, decision.cap


def _allow(*entries: str) -> dict[str, Any]:
    return {"all_symbols": False, "allowed_symbols": frozenset(entries)}


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "1000PEPEUSDT"])
def test_symbol_wildcard_allow_admits_a_matching_usdt_perpetual(symbol: str) -> None:
    assert _verdict(_allow("*USDT"), symbol=symbol) == (True, None)


@pytest.mark.parametrize(
    "inst",
    [
        {"symbol": "BTCPERP"},  # the suffix does not match
        {"symbol": "USDT"},  # a pattern never matches the whole symbol
        {"symbol": "BTCUSDT", **_USDC},  # not a USDT perpetual
        {"symbol": "BTCUSDT", "status": "closed"},  # not trading
    ],
)
def test_symbol_wildcard_allow_refuses_every_other_instrument(inst: dict[str, Any]) -> None:
    assert _verdict(_allow("*USDT"), **inst) == (False, "allowed_symbols")


def test_symbol_exact_allow_admits_only_its_symbol() -> None:
    assert _verdict(_allow("BTCUSDT"), symbol="BTCUSDT") == (True, None)
    assert _verdict(_allow("BTCUSDT"), symbol="ETHUSDT") == (False, "allowed_symbols")


def test_symbol_match_is_case_sensitive_like_the_profile_layer() -> None:
    assert _verdict(_allow("btcusdt", "*usdt"), symbol="BTCUSDT") == (False, "allowed_symbols")


def test_symbol_empty_allow_list_admits_nothing() -> None:  # D11
    assert _verdict(_allow(), symbol="BTCUSDT") == (False, "allowed_symbols")


@pytest.mark.parametrize("denied", ["BTCUSDT", "*USDT", "*CUSDT"])
def test_symbol_deny_wins_over_a_wildcard_allow(denied: str) -> None:
    prof = _allow("*USDT", "BTCUSDT") | {"blocked_symbols": frozenset({denied})}
    assert _verdict(prof, symbol="BTCUSDT") == (False, "blocked_symbols")


def test_symbol_deny_wins_over_all_symbols() -> None:
    assert _verdict({"blocked_symbols": frozenset({"*USDT"})}, symbol="ETHUSDT") == (
        False,
        "blocked_symbols",
    )


@pytest.mark.parametrize(
    "prof",
    [
        _allow("*"),  # a bare wildcard is no pattern
        {"blocked_symbols": frozenset({"btcusdt"})},  # lower case
        {"blocked_symbols": frozenset({" BTCUSDT"})},  # padded
        _allow("BTCUSDT") | {"blocked_symbols": frozenset({"**USDT"})},
    ],
)
def test_symbol_entry_outside_the_profile_grammar_refuses_every_symbol(
    prof: dict[str, Any],
) -> None:
    assert _verdict(prof, symbol="BTCUSDT") == (False, "allowed_symbols")


def test_symbol_deny_pattern_fails_closed_on_any_instrument() -> None:
    prof = _allow("BTCUSDT") | {"blocked_symbols": frozenset({"*USDT"})}
    assert _verdict(prof, symbol="BTCUSDT", **_USDC) == (False, "blocked_symbols")


_BAD = ("*usdt", "*")  # outside the profile grammar: either one refuses every symbol
_ENTRIES = st.frozensets(
    st.sampled_from(
        ["BTCUSDT", "ETHUSDT", "*USDT", "*CUSDT", "*BTCUSDT", "*PERP", "BTCPERP", "USDT", *_BAD]
    ),
    max_size=4,
)
_INSTRUMENTS = st.fixed_dictionaries(
    {
        "symbol": st.sampled_from(["BTCUSDT", "ETHUSDT", "USDT", "BTCPERP", "SOLUSDC"]),
        "quote_coin": st.sampled_from(["USDT", "USDC"]),
        "settle_coin": st.sampled_from(["USDT", "USDC"]),
        "status": st.sampled_from(["trading", "closed", "pre_launch"]),
    }
)


@given(st.booleans(), _ENTRIES, _ENTRIES, _INSTRUMENTS)
def test_symbol_rule_equals_symbol_scope_verdict(
    all_symbols: bool,
    allowed: frozenset[str],
    blocked: frozenset[str],
    inst: dict[str, Any],
) -> None:
    scope = SymbolScope(all_symbols, SymbolEntries.of(allowed), SymbolEntries.of(blocked))
    if (allowed | blocked) & set(_BAD):
        scope = SymbolScope(False, SymbolEntries.of(()), SymbolEntries.of(()))  # fails closed
    target = instrument(**inst)
    prof = {"all_symbols": all_symbols, "allowed_symbols": allowed, "blocked_symbols": blocked}
    expected_cap = None
    if not scope.admits(target):
        expected_cap = "allowed_symbols"
    elif not scope.allows(target):
        expected_cap = "blocked_symbols"
    assert _verdict(prof, **inst) == (scope.allows(target), expected_cap)
