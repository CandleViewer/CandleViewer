"""The profile's second validation pass (E28-T02 #906, slices B2a to B2c): its warnings,
`all_symbols` and `no_symbols`, its refusals against the exchange's limits, and when it reads them.

A read judges the symbol lists alone; a write also judges what the exchange lists, through the
matcher the order path uses (PF-T07), and is refused only for what it introduces (#906, rulings of
2026-10-22 14:22Z and 14:39Z, recorded as issuecomment-6360499465). It reads the catalogue of the
account's environment (C-2.11), here a fake port, only when some listing could refuse it. No I/O
beyond the recorded corpus, the contract and the T01 profile fixtures. The generated model, the
contract and the audit registry are imported here because tests are not import-linted; the module
under test imports none of them.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Mapping
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.profile_input import ProfileFieldError
from candleviewer.accounts.profile_validator import (
    INSTRUMENT_DEADLINE_S,
    INSTRUMENT_MAX_AGE_S,
    SECOND_PASS_RULES,
    InstrumentLimitsUnavailable,
    ProfileWarning,
    SecondPassResult,
    check_exchange_limits,
    judge_exchange_limits,
    profile_warnings,
)
from candleviewer.accounts.profiles import AccountProfile, SymbolEntries, SymbolScope
from candleviewer.api._generated.openapi_models import ProfileWarning as ProfileWarningContract
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import PROFILE_SAVE_REFUSED_REASONS
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Environment
from candleviewer.exchange.bybit.instruments import parse_instrument, parse_instruments
from tests._corpus import rest

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
#: Limits tighter than any other row's: were BTCPERP ever judged, the matrix would show it.
_TIGHT = dict(max_leverage="1", min_order_qty="1000", qty_step="1000", min_notional="1000000")
#: Named patches of the recorded catalogue (C-13.5), inserted in this order, not the symbols', so a
#: pass that forgets to sort is caught. BTCUSDT is as recorded: 100x, 0.001 lots, 5 USDT. BTCPERP
#: is BTCUSDT made a trading USDC perpetual (#4209 R1C-01) with tight limits: neither a warning
#: nor the pass ever judges it.
_PATCHES: Final[dict[str, dict[str, str]]] = {
    "SOLUSDT": dict(max_leverage="20.00", min_order_qty="0.1", qty_step="0.1", min_notional="10"),
    "LUNAUSDT": dict(status="closed", max_leverage="10.00"),
    "ETHUSDT": dict(max_leverage="50.00", min_order_qty="0.01", qty_step="0.01"),
    "BTCUSDT": {},
    "BTCPERP": dict(symbol="BTCPERP", quote_coin="USDC", settle_coin="USDC", **_TIGHT),
}


def _listing() -> MappingProxyType[str, Instrument]:
    rows = rest("rest/instruments_before.json")["result"]["list"]
    parsed = parse_instruments(rows, fetched_at_us=0)
    assert parsed.rejected == ()
    recorded = {i.symbol: i.model_dump() for i in parsed.instruments}
    recorded["BTCPERP"] = recorded["BTCUSDT"]  # the row BTCPERP is derived from
    patched = {s: {**recorded[s], **p} for s, p in _PATCHES.items()}
    return MappingProxyType({s: Instrument.model_validate(v) for s, v in patched.items()})


_LISTED: Final = _listing()
_NO_SYMBOLS: Final = "Allows no symbol, so it sizes nothing."
_ALL_SYMBOLS: Final = "Allows every listed symbol — consider restricting."


def _profile(mode: str = "fixed_notional", **changes: Any) -> AccountProfile:
    """A T01 fixture that allows nothing and caps leverage at 100x, with `changes`."""
    raw = json.loads((_FIXTURES / f"{mode}.json").read_text(encoding="utf-8"))
    base = {**raw, "allowed_symbols": [], "max_leverage_cap": "100"}
    return AccountProfile.model_validate({**base, **changes})


def _codes(warnings: tuple[ProfileWarning, ...]) -> list[tuple[str, str]]:
    return [(w.code, w.field) for w in warnings]


_ALL_BY_FLAG = [("all_symbols", "all_symbols")]
_ALL_BY_LIST = [("all_symbols", "allowed_symbols")]
_NONE_BY_BLOCK = [("no_symbols", "blocked_symbols")]
_NONE_BY_LIST = [("no_symbols", "allowed_symbols")]
#: (changes, the read's warnings). The last row pins which read rule names the field.
_READS = [
    pytest.param({"all_symbols": True}, _ALL_BY_FLAG, id="flag"),
    pytest.param({"allowed_symbols": ["*USDT", "BTCUSDT"]}, _ALL_BY_LIST, id="universal"),
    pytest.param(
        {"allowed_symbols": ["*USDT"], "denied_symbols": ["BTCUSDT"]},
        _ALL_BY_LIST,
        id="universal_less_a_symbol",
    ),
    pytest.param({}, _NONE_BY_LIST, id="empty"),
    pytest.param(
        {"allowed_symbols": ["BTCUSDT"], "denied_symbols": ["*USDT"]},
        _NONE_BY_BLOCK,
        id="universal_blocked",
    ),
    pytest.param(
        {"all_symbols": True, "denied_symbols": ["*USDT"]}, _NONE_BY_BLOCK, id="flag_less_universal"
    ),
    pytest.param({"allowed_symbols": ["BTCUSDT", "*HUSDT"]}, [], id="a_symbol_and_a_pattern"),
    pytest.param({"denied_symbols": ["*USDT"]}, _NONE_BY_BLOCK, id="empty_and_universal_blocked"),
    # #4209 R1C-02: only `*USDT` blocked blocks everything; another blocked pattern does not.
    pytest.param(
        {"all_symbols": True, "denied_symbols": ["*HUSDT"]}, _ALL_BY_FLAG, id="flag_less_a_pattern"
    ),
    pytest.param(
        {"allowed_symbols": ["*USDT"], "denied_symbols": ["*HUSDT"]},
        _ALL_BY_LIST,
        id="universal_less_a_pattern",
    ),
]
_ONE_CHARACTER = [f"*{c}USDT" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"]
_TRADING = ["SOLUSDT", "ETHUSDT", "BTCUSDT"]
#: (changes, a write's warnings against `_LISTED`, whose trading symbols are SOL, ETH and BTC).
#: The fourth row pins that the allow side is judged before the block list, as a read judges it.
_WRITES = [
    pytest.param({"allowed_symbols": ["*CUSDT", "*HUSDT", "*LUSDT"]}, _ALL_BY_LIST, id="together"),
    pytest.param({"allowed_symbols": _ONE_CHARACTER}, _ALL_BY_LIST, id="36_suffixes"),
    pytest.param({"allowed_symbols": _TRADING}, _ALL_BY_LIST, id="by_name"),
    pytest.param(
        {"allowed_symbols": _TRADING, "denied_symbols": ["BTCUSDT"]},
        _ALL_BY_LIST,
        id="by_name_less_a_symbol",
    ),
    pytest.param(
        {"allowed_symbols": ["BTCUSDT"], "denied_symbols": ["BTCUSDT"]},
        _NONE_BY_BLOCK,
        id="the_one_entry_blocked",
    ),
    pytest.param({"allowed_symbols": ["*AUSDT"]}, _NONE_BY_LIST, id="only_a_closed_symbol"),
    pytest.param(
        {"all_symbols": True, "denied_symbols": _TRADING}, _NONE_BY_BLOCK, id="flag_less_all_three"
    ),
    pytest.param({"allowed_symbols": _TRADING[:2]}, [], id="two_of_three"),
]


@pytest.mark.parametrize(("changes", "expected"), _READS)
def test_a_read_warns_from_the_profile_alone(
    changes: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    assert _codes(profile_warnings(_profile(**changes))) == expected


@pytest.mark.parametrize(("changes", "expected"), _WRITES)
def test_a_write_also_warns_from_what_the_exchange_lists(
    changes: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    assert _codes(profile_warnings(_profile(**changes), _LISTED)) == expected


@pytest.mark.parametrize(("changes", "expected"), _READS)
def test_a_write_keeps_every_read_warning(
    changes: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    """A write keeps the read's `no_symbols`, field included, and the read's `all_symbols` stands
    unless the listing shows that nothing is allowed (no row here does)."""
    assert _codes(profile_warnings(_profile(**changes), _LISTED)) == expected


@pytest.mark.parametrize(
    "listed", [{}, {"LUNAUSDT": _LISTED["LUNAUSDT"]}], ids=["empty", "nothing_trading"]
)
def test_a_listing_with_nothing_trading_adds_no_warning(listed: dict[str, Instrument]) -> None:
    """No vacuous `all_symbols`, and no `no_symbols`, from a listing that judges nothing."""
    assert profile_warnings(_profile(allowed_symbols=["BTCUSDT"]), listed) == ()


def test_a_warning_is_its_contract_entry() -> None:
    (nothing,) = profile_warnings(_profile())
    (everything,) = profile_warnings(_profile(all_symbols=True))
    entries = [nothing.to_dict(), everything.to_dict()]
    assert entries == [
        {"code": "no_symbols", "message": _NO_SYMBOLS, "field": "allowed_symbols"},
        {"code": "all_symbols", "message": _ALL_SYMBOLS, "field": "all_symbols"},
    ]
    for entry in entries:
        assert ProfileWarningContract.model_validate(entry).model_dump(exclude_unset=True) == entry


@pytest.mark.parametrize(
    ("value", "member"),
    [
        (ProfileWarning("no_symbols", _NO_SYMBOLS, "allowed_symbols"), "field"),
        (SymbolEntries.of(["*USDT"]), "suffixes"),
        (SymbolScope.of(_profile()), "all_symbols"),
        (SecondPassResult((), ()), "errors"),
    ],
    ids=["warning", "entries", "scope", "result"],
)
def test_the_matcher_and_the_answers_are_frozen(value: object, member: str) -> None:
    """#4209 R1C-05: nothing changes a compiled symbol list or an answer once it is built."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, member, None)


# -- B2b: the refusals against the exchange's limits (#906, `ProfileRejected`'s second pass) ----

_N, _Q = "fixed_notional", "fixed_qty"
_SOL, _ETH, _BTC, _LUNA, _XRP = "SOLUSDT", "ETHUSDT", "BTCUSDT", "LUNAUSDT", "XRPUSDT"
_ALLOW, _BLOCK, _LEV, _QTY = "allowed_symbols", "denied_symbols", "leverage", "fixed_qty"
_CAP, _ALL = "max_position_notional", {"all_symbols": True}


def _instrument(symbol: str, **limits: Any) -> Instrument:
    """`_LISTED[symbol]` with `limits` changed."""
    return Instrument.model_validate({**_LISTED[symbol].model_dump(), **limits})


def _refusals(result: SecondPassResult) -> str:
    """The refusals in order, written short: `rule SYM limit, SYM limit; rule ...`, a symbol
    without its `USDT` and a limit as rendered; an unlisted entry by its index."""

    def entry(error: ProfileFieldError) -> str:
        if error.symbol is None:  # `symbol_not_listed`
            return error.field.removeprefix("allowed_symbols")
        return f"{error.symbol.removesuffix('USDT')} {error.to_dict()['limit']}"

    groups = groupby(result.errors, key=lambda error: error.rule)
    return "; ".join(f"{rule} {', '.join(map(entry, errors))}" for rule, errors in groups)


_SMALL_QTY = "min_order_qty ETH 0.01, SOL 0.1; qty_step ETH 0.01, SOL 0.1"
_EVERY_RULE = (
    "max_leverage ETH 50, SOL 20; min_order_qty ETH 0.01, SOL 0.1; qty_step ETH 0.01, SOL 0.1; "
    "min_notional BTC 5, ETH 5, SOL 10; symbol_not_listed [1]"
)
#: A create: (id, changes, the refusals). A row that sets `fixed_qty` sizes by it; the rest
#: size by notional (10x and a 20 000 USDT cap, or 2x and 5 000 USDT).
_MATRIX = [
    ("leverage_at_an_entrys_maximum", {_ALLOW: [_SOL], _LEV: "20"}, ""),
    ("leverage_above_an_entrys_maximum", {_ALLOW: [_SOL], _LEV: "20.01"}, "max_leverage SOL 20"),
    (
        "leverage_under_the_universal_pattern",
        {_ALLOW: ["*USDT"], _LEV: "25"},
        "max_leverage SOL 20",
    ),
    ("leverage_under_all_symbols", {**_ALL, _LEV: "60"}, "max_leverage ETH 50, SOL 20"),
    ("leverage_within_every_maximum", {**_ALL, _LEV: "20"}, ""),
    ("leverage_under_a_suffix_pattern", {_ALLOW: ["*HUSDT"], _LEV: "60"}, "max_leverage ETH 50"),
    ("a_pattern_matching_only_a_closed_symbol", {_ALLOW: ["*AUSDT"], _LEV: "60"}, ""),
    ("all_symbols_less_a_blocked_symbol", {**_ALL, _BLOCK: [_SOL], _LEV: "25"}, ""),
    (
        "a_pattern_less_a_blocked_pattern",
        {_ALLOW: ["*USDT"], _BLOCK: ["*LUSDT"], _LEV: "60"},
        "max_leverage ETH 50",
    ),
    ("an_entry_the_block_list_also_names", {_ALLOW: [_SOL], _BLOCK: [_SOL], _LEV: "25"}, ""),
    ("qty_at_the_minimum_on_the_step", {_ALLOW: [_SOL], _QTY: "0.1"}, ""),
    (
        "qty_below_the_minimum_off_the_step",
        {_ALLOW: [_SOL], _QTY: "0.05"},
        "min_order_qty SOL 0.1; qty_step SOL 0.1",
    ),
    ("qty_off_the_step_above_the_minimum", {_ALLOW: [_SOL], _QTY: "0.15"}, "qty_step SOL 0.1"),
    ("qty_a_multiple_of_a_finer_step", {_ALLOW: [_ETH], _QTY: "0.37"}, ""),
    ("qty_under_the_universal_pattern", {_ALLOW: ["*USDT"], _QTY: "0.001"}, _SMALL_QTY),
    ("qty_under_all_symbols", {**_ALL, _QTY: "0.001"}, _SMALL_QTY),
    (
        "qty_under_all_symbols_less_the_blocked",
        {**_ALL, _BLOCK: ["*HUSDT", _SOL], _QTY: "0.001"},
        "",
    ),
    ("qty_under_a_suffix_pattern", {_ALLOW: ["*HUSDT"], _QTY: "0.37"}, ""),
    ("a_cap_at_an_entrys_minimum_notional", {_ALLOW: [_SOL], _CAP: "10"}, ""),
    (
        "a_cap_below_an_entrys_minimum_notional",
        {_ALLOW: [_SOL], _CAP: "9.99"},
        "min_notional SOL 10",
    ),
    ("a_cap_below_every_minimum", {**_ALL, _CAP: "4"}, "min_notional BTC 5, ETH 5, SOL 10"),
    (
        "a_cap_below_one_minimum_under_a_pattern",
        {_ALLOW: ["*USDT"], _CAP: "5"},
        "min_notional SOL 10",
    ),
    ("a_cap_below_only_a_blocked_minimum", {**_ALL, _BLOCK: [_SOL], _CAP: "5"}, ""),
    ("no_position_cap", {**_ALL, _CAP: None, "max_position_pct_equity": "0.5"}, ""),
    ("an_entry_nothing_lists", {_ALLOW: [_XRP]}, "symbol_not_listed [0]"),
    ("an_entry_listed_but_not_trading", {_ALLOW: [_LUNA]}, "symbol_not_listed [0]"),
    # Beyond the spec's 33: listed and trading, but a USDC perpetual (#4209 R1C-01).
    ("an_entry_naming_a_usdc_perpetual", {_ALLOW: ["BTCPERP"]}, "symbol_not_listed [0]"),
    ("only_the_unlisted_entry_is_named", {_ALLOW: [_BTC, _XRP]}, "symbol_not_listed [1]"),
    ("a_pattern_matching_nothing_is_kept", {_ALLOW: ["*XRPUSDT"]}, ""),
    ("an_unlisted_block_entry_is_kept", {_ALLOW: [_BTC], _BLOCK: [_XRP]}, ""),
    (
        "an_unlisted_entry_also_blocked_is_named",
        {_ALLOW: [_XRP], _BLOCK: [_XRP]},
        "symbol_not_listed [0]",
    ),
    ("nothing_allowed", {}, ""),
    ("every_listed_symbol_blocked", {**_ALL, _BLOCK: ["*USDT"], _LEV: "60", _CAP: "4"}, ""),
    (
        "every_rule_at_once",
        {_ALLOW: ["*USDT", _XRP], _LEV: "60", _QTY: "0.001", _CAP: "4"},
        _EVERY_RULE,
    ),
]


@pytest.mark.parametrize(("changes", "expected"), [pytest.param(*r[1:], id=r[0]) for r in _MATRIX])
def test_the_second_pass_matrix(changes: dict[str, Any], expected: str) -> None:
    """A create: each listed, trading USDT perpetual the profile allows, judged once a rule, rule
    by rule and then by symbol; then each allow entry naming none, by its index. Every rule it
    answers is one of `SECOND_PASS_RULES`, the audited set (#4263 R1S-02)."""
    profile = _profile(_Q if _QTY in changes else _N, **changes)
    result = judge_exchange_limits(profile, _LISTED, stored=None)
    assert _refusals(result) == expected
    assert {error.rule for error in result.errors} <= SECOND_PASS_RULES


def test_each_refusal_reads_as_the_editors_copy() -> None:
    """SCR-131's copy: the instrument, its limit and the profile's own figure, written plainly
    (a 25.00x leverage reads 25x, #4263 R1C-04)."""
    changes = {_ALLOW: [_SOL, _XRP], _LEV: "25.00", _QTY: "0.05", _CAP: "9.5"}
    errors = judge_exchange_limits(_profile(_Q, **changes), _LISTED, stored=None).errors
    assert [(e.field, e.message) for e in errors] == [
        ("leverage", "SOLUSDT allows at most 20x — your 25x would be rejected."),
        ("sizing.qty", "SOLUSDT takes at least 0.1 per order — your 0.05 would be rejected."),
        ("sizing.qty", "SOLUSDT takes quantities in steps of 0.1 — your 0.05 would be rejected."),
        (
            "risk_caps.max_position_notional_usd",
            "SOLUSDT takes at least 10 USDT per order — your 9.5 USDT position cap would refuse"
            " every one.",
        ),
        ("allowed_symbols[1]", "XRPUSDT is not a listed, trading USDT perpetual."),
    ]
    assert errors[-1].to_dict() == {
        "field": "allowed_symbols[1]",
        "rule": "symbol_not_listed",
        "message": "XRPUSDT is not a listed, trading USDT perpetual.",
    }


def test_the_quantity_refusals_each_name_their_own_limit() -> None:
    """#4263 R1C-01: where an instrument's minimum and step differ, `min_order_qty` names the
    minimum and `qty_step` the step, in the entry and in its copy."""
    listed = {_SOL: _instrument(_SOL, min_order_qty=Decimal("0.2"), qty_step=Decimal("0.05"))}
    profile = _profile(_Q, **{_ALLOW: [_SOL], _QTY: "0.12"})
    errors = judge_exchange_limits(profile, listed, stored=None).errors
    rejected = "— your 0.12 would be rejected."
    assert [(e.rule, e.to_dict()["limit"], e.message) for e in errors] == [
        ("min_order_qty", "0.2", f"SOLUSDT takes at least 0.2 per order {rejected}"),
        ("qty_step", "0.05", f"SOLUSDT takes quantities in steps of 0.05 {rejected}"),
    ]


def test_the_contract_example_is_what_the_second_pass_answers() -> None:
    """Ruling B9: the recorded SOLUSDT row with one field patched (the fixture README's provenance
    line) answers `ProfileRejected`'s `leverageAboveExchangeMax`, entry for entry."""
    rows = rest("rest/instruments_before.json")["result"]["list"]
    row = copy.deepcopy(next(r for r in rows if r["symbol"] == _SOL))
    assert row["leverageFilter"]["maxLeverage"] == "100.00"
    row["leverageFilter"]["maxLeverage"] = "20.00"
    listed = {_SOL: parse_instrument(row, fetched_at_us=0)}
    result = judge_exchange_limits(
        _profile(allowed_symbols=[_SOL], leverage="25"), listed, stored=None
    )
    spec: Any = load_openapi_spec()
    rejected = spec["components"]["responses"]["ProfileRejected"]["content"]
    example = rejected["application/problem+json"]["examples"]["leverageAboveExchangeMax"]
    assert [e.to_dict() for e in result.errors] == example["value"]["errors"]


def test_a_step_too_fine_to_divide_by_counts_as_off_the_step() -> None:
    """1 over a step of 1E-300 is a 301-digit quotient, past `_EXACT`'s 200, so the remainder is
    NaN, which is off the step: a refusal, never an exception."""
    listed = {_SOL: _instrument(_SOL, qty_step=Decimal("1E-300"))}
    result = judge_exchange_limits(_profile(_Q, **{_ALLOW: [_SOL], _QTY: "1"}), listed, stored=None)
    assert [(e.rule, e.limit) for e in result.errors] == [("qty_step", Decimal("1E-300"))]


def test_a_writes_warnings_come_with_the_pass() -> None:
    """The write's warnings, which see these entries together allow every listed symbol; a read's
    would not."""
    profile = _profile(allowed_symbols=["*CUSDT", "*HUSDT", "*LUSDT"])
    warnings = judge_exchange_limits(profile, _LISTED, stored=None).warnings
    assert [w.code for w in warnings] == ["all_symbols"]


def test_every_second_pass_rule_is_an_audited_reason() -> None:
    """Every refusal of the second pass is audited, beside the first pass's three."""
    assert SECOND_PASS_RULES <= PROFILE_SAVE_REFUSED_REASONS
    first = {"native_stop_mandatory", "above_leverage_cap", "cap_unbounded"}
    assert PROFILE_SAVE_REFUSED_REASONS - SECOND_PASS_RULES == first


@settings(max_examples=300, deadline=None)
@given(n=st.integers(1, 10**6), p=st.integers(0, 18), k=st.integers(1, 100), e=st.integers(0, 18))
@example(n=37, p=2, k=1, e=2)  # 0.37 on a step of 0.01
@example(n=15, p=2, k=1, e=1)  # 0.15 off a step of 0.1
@example(n=5, p=0, k=1, e=18)  # a whole quantity on the finest step a profile can hold
@example(n=10**20 - 1, p=0, k=1, e=18)  # a 38-digit quotient: 28 digits would not do (#4263 R1C-05)
def test_qty_step_is_refused_exactly_off_the_step(n: int, p: int, k: int, e: int) -> None:
    """H1: `n`E-`p` against a step of `k`E-`e`, judged by integers on a common scale."""
    scale = max(p, e)
    on_step = n * 10 ** (scale - p) % (k * 10 ** (scale - e)) == 0
    listed = {_SOL: _instrument(_SOL, qty_step=Decimal(f"{k}E-{e}"))}
    profile = _profile(_Q, **{_ALLOW: [_SOL], _QTY: Decimal(f"{n}E-{p}")})
    rules = [error.rule for error in judge_exchange_limits(profile, listed, stored=None).errors]
    assert ("qty_step" in rules) is not on_step


_AMOUNTS = st.decimals(Decimal("1E-18"), Decimal("1E+6"), places=18)


@pytest.mark.parametrize(("limit", "figure"), [("min_order_qty", _QTY), ("min_notional", _CAP)])
@settings(max_examples=300, deadline=None)
@given(pair=st.tuples(_AMOUNTS, _AMOUNTS) | _AMOUNTS.map(lambda v: (v, v)))
@example(pair=(Decimal("0.099999999999999999"), Decimal("0.1")))
def test_a_minimum_is_refused_exactly_below_it(
    limit: str, figure: str, pair: tuple[Decimal, Decimal]
) -> None:
    """H2: `fixed_qty` against `min_order_qty`, and the position cap against `min_notional`:
    refused when below the limit, and never at it or above (each rule is named for its limit)."""
    value, bound = pair
    listed = {_SOL: _instrument(_SOL, **{limit: bound})}
    profile = _profile(_Q, **{_ALLOW: [_SOL], figure: value})
    rules = [error.rule for error in judge_exchange_limits(profile, listed, stored=None).errors]
    assert (limit in rules) is (value < bound)


# -- Q4: a replace is judged for what it introduces ---------------------------------------------
# #906, rulings of 2026-10-22 14:22Z and 14:39Z and of 2026-10-23 07:04Z (issuecomment-6360499465).

#: A stored profile `_LISTED` now refuses on every rule: SOL and ETH on each limit, LUNA (closed
#: since) and XRP (never listed) as entries.
_BREACHING: Final = {_ALLOW: [_SOL, _ETH, _LUNA, _XRP], _LEV: "60", _QTY: "0.001", _CAP: "4"}
#: Writes that introduce no scope and move no figure toward a limit: (stored, write) changes over
#: `_BREACHING`. Turning trading or the profile back on is one (07:04Z; #4263 R1C-02).
_REDUCTIONS: Final = [
    pytest.param({}, {"trading_enabled": False}, id="trading_off"),
    pytest.param({}, {"enabled": False}, id="disabled"),
    pytest.param({}, {_ALLOW: [_SOL, _LUNA, _XRP]}, id="an_allow_list_shrink"),
    pytest.param({}, {_BLOCK: [_ETH]}, id="a_block_list_grow"),
    pytest.param({}, {_LEV: "50"}, id="leverage_lowered"),
    pytest.param({}, {_CAP: "9"}, id="a_cap_raised"),
    pytest.param({}, {}, id="an_unchanged_re_save"),
    pytest.param({"trading_enabled": False}, {"trading_enabled": True}, id="trading_turned_on"),
    pytest.param({"enabled": False}, {"enabled": True}, id="enabled_turned_on"),
]


@pytest.mark.parametrize(("stored_changes", "changes"), _REDUCTIONS)
def test_a_pure_reduction_judges_nothing(
    stored_changes: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Q1: a write that allows nothing new and moves no figure toward a limit is never refused,
    though the same profile would be refused as a create."""
    stored = _profile(_Q, **{**_BREACHING, **stored_changes})
    profile = _profile(_Q, **{**_BREACHING, **stored_changes, **changes})
    assert judge_exchange_limits(profile, _LISTED, stored=None).errors
    assert judge_exchange_limits(profile, _LISTED, stored=stored).errors == ()


#: A stored profile that allows BTC (its 4 USDT cap already below BTC's minimum), still lists LUNA
#: (closed since) and lists SOL but blocks it.
_BEFORE: Final = {_ALLOW: [_BTC, _LUNA, _SOL], _BLOCK: [_SOL], _LEV: "60", _QTY: "0.001", _CAP: "4"}
_ETH_RULES = "max_leverage ETH 50; min_order_qty ETH 0.01; qty_step ETH 0.01; min_notional ETH 5"
_SOL_RULES = "max_leverage SOL 20; min_order_qty SOL 0.1; qty_step SOL 0.1; min_notional SOL 10"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param({_ALLOW: [_BTC, _LUNA, _SOL, _ETH]}, _ETH_RULES, id="a_new_symbol"),
        pytest.param({_ALLOW: [_BTC, _LUNA, _SOL, "*HUSDT"]}, _ETH_RULES, id="a_new_pattern"),
        pytest.param(
            {_ALLOW: [_XRP, _BTC, _LUNA, _SOL]}, "symbol_not_listed [0]", id="a_new_unlisted_entry"
        ),
        # #4263 R1C-03: the index in the new list, not among the new entries.
        pytest.param(
            {_ALLOW: [_BTC, _XRP, _LUNA, _SOL]}, "symbol_not_listed [1]", id="one_inserted_after"
        ),
        pytest.param({**_ALL, _ALLOW: []}, _ETH_RULES, id="all_symbols_turned_on"),
        pytest.param({_BLOCK: []}, _SOL_RULES, id="a_block_entry_removed"),
    ],
)
def test_introduced_scope_is_judged_for_every_rule(changes: dict[str, Any], expected: str) -> None:
    """Q2, (a): the instruments the write newly allows, on every rule, and each new entry naming
    no listed, trading USDT perpetual, at its index in the new list. BTC's cap and LUNA stand."""
    stored = _profile(_Q, **_BEFORE)
    result = judge_exchange_limits(_profile(_Q, **{**_BEFORE, **changes}), _LISTED, stored=stored)
    assert _refusals(result) == expected


#: A stored profile that allows every symbol and breaks no limit: 10x, 0.1 an order, 20 000 USDT.
_CLEAN: Final = {**_ALL, _QTY: "0.1"}
_BY_NOTIONAL: Final = {"sizing_mode": _N, _QTY: None, "fixed_notional": "1000"}


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        pytest.param({}, {_LEV: "25"}, "max_leverage SOL 20", id="leverage_raised"),
        pytest.param({}, {_QTY: "0.001"}, _SMALL_QTY, id="qty_lowered"),
        pytest.param({}, {_QTY: "0.15"}, "qty_step SOL 0.1", id="qty_raised"),
        pytest.param(
            _BY_NOTIONAL,
            {"sizing_mode": _Q, _QTY: "0.05", "fixed_notional": None},
            "min_order_qty SOL 0.1; qty_step SOL 0.1",
            id="qty_newly_set",
        ),
        pytest.param({}, {_CAP: "4"}, "min_notional BTC 5, ETH 5, SOL 10", id="a_cap_lowered"),
        pytest.param({_CAP: None}, {_CAP: "9.99"}, "min_notional SOL 10", id="a_cap_newly_set"),
        pytest.param({_LEV: "60"}, {_LEV: "30"}, "", id="leverage_lowered_still_above"),
        pytest.param({_CAP: "4"}, {_CAP: "9"}, "", id="a_cap_raised_still_below"),
    ],
)
def test_a_figure_moved_toward_a_limit_judges_every_allowed_instrument(
    before: dict[str, Any], after: dict[str, Any], expected: str
) -> None:
    """Q3, (b): on an unchanged scope, leverage raised, `fixed_qty` changed or set, or the cap
    lowered or set, is judged on every instrument allowed ("10x to 25x on an unchanged SOLUSDT is
    still refused"); a figure moved away from its limit is not judged."""
    stored = _profile(_Q, **{**_CLEAN, **before})
    profile = _profile(_Q, **{**_CLEAN, **before, **after})
    assert _refusals(judge_exchange_limits(profile, _LISTED, stored=stored)) == expected


_POOL = [_BTC, _ETH, _SOL, _LUNA, _XRP, "BTCPERP", "*USDT", "*HUSDT", "*AUSDT"]


@st.composite
def _profiles(draw: st.DrawFn) -> AccountProfile:
    """A profile over `_LISTED`'s symbols, patterns and an unlisted one, its figures on both sides
    of the limits, sized by quantity or by notional."""
    every = draw(st.booleans())
    changes: dict[str, Any] = {
        "all_symbols": every,
        _ALLOW: [] if every else draw(st.lists(st.sampled_from(_POOL), max_size=4)),
        _BLOCK: draw(st.lists(st.sampled_from(_POOL), max_size=2)),
        _LEV: draw(st.sampled_from(["1", "20", "25", "50", "60"])),
        _CAP: draw(st.sampled_from([None, "4", "9.99", "10", "5000"])),
        "max_position_pct_equity": "0.5",
    }
    qty = draw(st.sampled_from([None, "0.001", "0.05", "0.1", "0.15"]))
    return _profile(_N, **changes) if qty is None else _profile(_Q, **changes, fixed_qty=qty)


@settings(max_examples=300, deadline=None)
@given(stored=_profiles(), profile=_profiles())
def test_a_write_is_refused_only_for_what_it_introduces(
    stored: AccountProfile, profile: AccountProfile
) -> None:
    """Q4H: every refusal names an instrument the write newly allows, a rule whose figure moved
    toward its limit, or an entry `stored` did not hold: the create's refusals less the others,
    in the same order. A re-save of `stored` refuses nothing."""
    before = SymbolScope.of(stored)
    moved = {"max_leverage"} if profile.leverage > stored.leverage else set()
    if profile.fixed_qty != stored.fixed_qty:
        moved |= {"min_order_qty", "qty_step"}
    cap, was = profile.max_position_notional, stored.max_position_notional
    if cap is not None and (was is None or cap < was):
        moved.add("min_notional")

    def judged(error: ProfileFieldError) -> bool:
        if error.symbol is None:  # `symbol_not_listed`: an entry `stored` did not hold
            n = int(error.field.removeprefix("allowed_symbols[").removesuffix("]"))
            return profile.allowed_symbols[n] not in stored.allowed_symbols
        return error.rule in moved or not before.allows(_LISTED[error.symbol])

    create = judge_exchange_limits(profile, _LISTED, stored=None).errors
    got = judge_exchange_limits(profile, _LISTED, stored=stored).errors
    assert got == tuple(filter(judged, create))
    assert judge_exchange_limits(stored, _LISTED, stored=stored).errors == ()


# -- B2c: the catalogue of the account's environment, read only when a listing could refuse ------

_BOUNDS: Final = (900.0, 1.5)  # `ProfileRejected`'s 15 minutes; the save's deadline


@dataclasses.dataclass
class _Limits:
    """`InstrumentLimitsPort` double: records each read's bounds, then answers `listing` or raises
    `failure`."""

    environment: Environment
    listing: Mapping[str, Instrument] = dataclasses.field(default_factory=dict)
    failure: Exception | None = None
    calls: list[tuple[float, float]] = dataclasses.field(default_factory=list)

    async def listed(self, *, max_age_s: float, deadline_s: float) -> Mapping[str, Instrument]:
        self.calls.append((max_age_s, deadline_s))
        if self.failure is not None:
            raise self.failure
        return self.listing


def _unread(environment: Environment = "demo") -> _Limits:
    """A port that must never be read: a read raises, and is recorded."""
    return _Limits(environment, failure=AssertionError("the catalogue was read"))


async def test_the_limits_are_the_accounts_environments() -> None:
    """C-2.11: each account is judged by its own environment's catalogue. SOLUSDT allows 20x on
    the demo one (`_LISTED`) and 100x on the live one, as recorded."""
    rows = rest("rest/instruments_before.json")["result"]["list"]
    recorded = {i.symbol: i for i in parse_instruments(rows, fetched_at_us=0).instruments}
    profile = _profile(_N, **{_ALLOW: [_SOL], _LEV: "25"})
    demo, live = _Limits("demo", _LISTED), _Limits("live", recorded)
    refused = await check_exchange_limits(
        profile, environment="demo", instruments=demo, stored=None
    )
    passed = await check_exchange_limits(profile, environment="live", instruments=live, stored=None)
    assert _refusals(refused) == "max_leverage SOL 20" and passed.errors == ()
    assert demo.calls == live.calls == [_BOUNDS]


@pytest.mark.parametrize("changes", [{_ALLOW: [_SOL]}, {}], ids=["reads", "reads_nothing"])
async def test_another_environments_catalogue_is_never_read(changes: dict[str, Any]) -> None:
    """C-2.11: a demo account checked against the live catalogue is refused first, before any
    read, even by a write that would read nothing."""
    port = _unread("live")
    with pytest.raises(AccountNotFoundError) as refused:
        await check_exchange_limits(
            _profile(**changes), environment="demo", instruments=port, stored=None
        )
    assert refused.value.entity == "account" and port.calls == []


@pytest.mark.parametrize("stored", [None, {_LEV: "1"}], ids=["a_create", "leverage_raised"])
async def test_a_profile_that_allows_nothing_needs_no_catalogue(
    stored: dict[str, Any] | None,
) -> None:
    """D11: a profile that allows nothing reads no catalogue, so it always saves, even with a
    figure raised; it warns `no_symbols`."""
    profile, before = _profile(**{_LEV: "50"}), None if stored is None else _profile(**stored)
    port = _unread()
    result = await check_exchange_limits(
        profile, environment="demo", instruments=port, stored=before
    )
    assert result.errors == () and _codes(result.warnings) == _NONE_BY_LIST and port.calls == []


async def test_the_catalogue_is_at_most_15_minutes_old_within_the_deadline() -> None:
    """One read, for a listing fetched at most 900 s ago and within 1.5 s, judged as it answers."""
    profile, port = _profile(_N, **_ALL), _Limits("demo", _LISTED)
    result = await check_exchange_limits(profile, environment="demo", instruments=port, stored=None)
    assert port.calls == [_BOUNDS] == [(INSTRUMENT_MAX_AGE_S, INSTRUMENT_DEADLINE_S)]
    assert result == judge_exchange_limits(profile, _LISTED, stored=None)


async def test_an_unavailable_catalogue_judges_nothing() -> None:
    """The port's 503 passes through untouched: nothing is judged or answered."""
    unavailable = InstrumentLimitsUnavailable("no fetch has confirmed the instrument catalogue")
    port = _Limits("demo", failure=unavailable)
    with pytest.raises(InstrumentLimitsUnavailable) as caught:
        await check_exchange_limits(
            _profile(_N, **_ALL), environment="demo", instruments=port, stored=None
        )
    assert caught.value is unavailable and port.calls == [_BOUNDS]


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({_ALLOW: [_BTC, _LUNA, _SOL, _ETH]}, id="a_new_symbol"),
        pytest.param({_ALLOW: [_BTC, _LUNA, _SOL, "*HUSDT"]}, id="a_new_pattern"),
        pytest.param({**_ALL, _ALLOW: []}, id="all_symbols_turned_on"),
        pytest.param({_BLOCK: []}, id="a_block_entry_removed"),
    ],
)
async def test_a_write_that_introduces_scope_reads_the_catalogue(changes: dict[str, Any]) -> None:
    """(a): a new allow entry, `all_symbols` turned on, or a block entry removed reads the
    catalogue once, and what the write introduces is refused."""
    stored, profile = _profile(_Q, **_BEFORE), _profile(_Q, **{**_BEFORE, **changes})
    port = _Limits("demo", _LISTED)
    result = await check_exchange_limits(
        profile, environment="demo", instruments=port, stored=stored
    )
    assert port.calls == [_BOUNDS] and result.errors
    assert result == judge_exchange_limits(profile, _LISTED, stored=stored)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param({}, {_LEV: "25"}, id="leverage_raised"),
        pytest.param({}, {_QTY: "0.15"}, id="qty_changed"),
        pytest.param(
            _BY_NOTIONAL,
            {"sizing_mode": _Q, _QTY: "0.05", "fixed_notional": None},
            id="qty_newly_set",
        ),
        pytest.param({}, {_CAP: "4"}, id="a_cap_lowered"),
        pytest.param({_CAP: None}, {_CAP: "9.99"}, id="a_cap_newly_set"),
    ],
)
async def test_a_figure_moved_toward_a_limit_reads_the_catalogue(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    """(b): leverage raised, `fixed_qty` changed or set, or the position cap lowered or set reads
    the catalogue once, and every allowed instrument is judged on the rule it moved."""
    stored = _profile(_Q, **{**_CLEAN, **before})
    profile = _profile(_Q, **{**_CLEAN, **before, **after})
    port = _Limits("demo", _LISTED)
    result = await check_exchange_limits(
        profile, environment="demo", instruments=port, stored=stored
    )
    assert port.calls == [_BOUNDS] and result.errors
    assert result == judge_exchange_limits(profile, _LISTED, stored=stored)


@pytest.mark.parametrize(("stored_changes", "changes"), _REDUCTIONS)
async def test_a_pure_reduction_reads_no_catalogue(
    stored_changes: dict[str, Any], changes: dict[str, Any]
) -> None:
    """A write that introduces no scope and moves no figure toward a limit never reads the
    catalogue, so it is never a 503: no refusal, and the read's warnings."""
    stored = _profile(_Q, **{**_BREACHING, **stored_changes})
    profile = _profile(_Q, **{**_BREACHING, **stored_changes, **changes})
    port = _unread()
    result = await check_exchange_limits(
        profile, environment="demo", instruments=port, stored=stored
    )
    assert result == SecondPassResult((), profile_warnings(profile)) and port.calls == []


@pytest.mark.parametrize("member", ["profile_id", "account_id"])
async def test_a_stored_profile_other_than_the_one_replaced_is_refused_unread(member: str) -> None:
    """#4263 R1S-01: `stored` must be the profile this write replaces. Another profile, or another
    account's, would lend the write scope it never held, so it is refused before any read, even
    where the write, against it, is a re-save that reads nothing."""
    profile = _profile(_Q, **_BREACHING)
    stored = profile.model_copy(update={member: UUID("0b5f6d0e-28a1-4c1e-9e01-0000000000ff")})
    port = _unread()
    with pytest.raises(AccountNotFoundError) as refused:
        await check_exchange_limits(profile, environment="demo", instruments=port, stored=stored)
    assert refused.value.entity == "profile" and port.calls == []


#: Each symbol `_POOL` names, a trading USDT perpetual whose limits every drawn figure breaks
#: (leverage 1 aside). With it, `{}`, which leaves every entry unlisted, and `_LISTED`.
_STRICT: Final = MappingProxyType(
    {
        s: Instrument.model_validate({**_LISTED[_BTC].model_dump(), "symbol": s, **_TIGHT})
        for s in (_BTC, _ETH, _SOL, _LUNA, _XRP, "BTCPERP")
    }
)


@settings(max_examples=300, deadline=None)
@given(stored=st.none() | _profiles(), profile=_profiles())
async def test_a_write_reads_the_catalogue_unless_no_listing_could_refuse_it(
    stored: AccountProfile | None, profile: AccountProfile
) -> None:
    """#4263's hand-off: a write is judged on the listing it reads, and one that reads none is
    refused by none, of the recorded listing, an empty one and one breaking every limit."""
    if stored is not None:  # the same profile, replaced
        same = {"profile_id": stored.profile_id, "account_id": stored.account_id}
        profile = profile.model_copy(update=same)
    port = _Limits("demo", _LISTED)
    result = await check_exchange_limits(
        profile, environment="demo", instruments=port, stored=stored
    )
    if port.calls:
        assert result == judge_exchange_limits(profile, _LISTED, stored=stored)
    else:
        assert result == SecondPassResult((), profile_warnings(profile))
        listings: list[Mapping[str, Instrument]] = [_LISTED, {}, _STRICT]
        for listed in listings:
            assert judge_exchange_limits(profile, listed, stored=stored).errors == ()
