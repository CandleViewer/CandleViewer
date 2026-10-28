"""`WatchlistIn`, `duplicate_errors` and `unknown_errors` (E08-T07, #4706): 22 `WatchlistInput`'s
limits, its closed shape and its list rules, the name trimmed as E08-D07 §4.3 compares it and
refused with a control or format character as an account-profile name is, with no I/O. How the
router answers them: test_watchlists_api.py."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.api.watchlists_models import (
    DEFAULT_COLUMNS,
    MAX_COLUMNS,
    MAX_SYMBOLS,
    WatchlistIn,
    duplicate_errors,
    unknown_errors,
)

#: E08-D07 §4.1's column ids (the nine defaults that have one, then the eight optional ones).
_D07_COLUMNS = (
    "symbol last chg_24h_pct turnover_24h funding_rate next_funding oi_chg_24h_pct spread_bps rec "
    "volume_24h open_interest_value mark_price index_price bid1_price ask1_price high_24h low_24h"
).split()


def _ok(**over: Any) -> WatchlistIn:
    return WatchlistIn.model_validate({"name": "Majors", "symbols": ["BTCUSDT"]} | over)


def _rules(body: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ValidationError) as err:
        WatchlistIn.model_validate(body)
    return [(".".join(map(str, e["loc"])), e["type"]) for e in err.value.errors()]


@pytest.mark.parametrize(
    ("sent", "kept"),
    [("M", "M"), ("é" * 80, "é" * 80), (" Majors ", "Majors"), ("\tAlts\n", "Alts"),
     (" " + "x" * 80 + " ", "x" * 80), ("\nMajors\n", "Majors")],
)  # fmt: skip
def test_a_name_is_trimmed_then_held_to_1_to_80_characters(sent: str, kept: str) -> None:
    """E08-D07 §4.3 compares names trimmed, so " Majors " is the name "Majors" (`ux_wl_name`)."""
    assert _ok(name=sent).name == kept


@pytest.mark.parametrize(
    ("name", "rule"),
    [("", "string_too_short"), ("   ", "string_too_short"), ("x" * 81, "string_too_long"),
     ("Ma\u202ejors", "not_allowed"), ("Ma\njors", "not_allowed"), ("Ma\x1bjors", "not_allowed"),
     ("Ma\u200bjors", "not_allowed"), ("a\x00b", "not_allowed"), (7, "string_type")],
)  # fmt: skip
def test_a_name_outside_the_contract_is_refused_on_name(name: object, rule: str) -> None:
    """A control or format character (Unicode Cc or Cf: U+202E, a newline, ESC, U+200B, and
    U+0000, which Postgres `text` cannot hold) is refused as in an account-profile name, judged
    on the trimmed name: a newline at an end is trimmed first."""
    assert _rules({"name": name, "symbols": []}) == [("name", rule)]


def test_200_symbols_are_a_list_and_201_are_too_many_whatever_they_hold() -> None:
    symbols = [f"S{i}USDT" for i in range(MAX_SYMBOLS)]
    assert len(_ok(symbols=symbols).symbols) == MAX_SYMBOLS
    assert _rules({"name": "n", "symbols": [*symbols, "x"]}) == [("symbols", "too_many_symbols")]


@pytest.mark.parametrize("symbol", ["btcusdt", "BTCPERP", "BTCUSDC", "BUSDT", "X" * 21 + "USDT"])
def test_a_symbol_off_the_symbol_pattern_is_refused_at_its_index(symbol: str) -> None:
    assert _rules({"name": "n", "symbols": ["ETHUSDT", symbol]}) == [
        ("symbols.1", "string_pattern_mismatch")
    ]


def test_the_body_is_closed_and_columns_left_out_or_null_are_the_d07_defaults() -> None:
    """`version` is server-assigned: it comes back through `If-Match`, never in the body. A
    `columns` left out or `null` stores E08-D07 §4.1's nine defaults; `[]` stores none."""
    assert _rules({"name": "n", "symbols": [], "version": 3}) == [("version", "extra_forbidden")]
    assert _rules({"name": "n"}) == [("symbols", "missing")]
    assert _ok().stored_columns() == _ok(columns=None).stored_columns() == DEFAULT_COLUMNS
    assert DEFAULT_COLUMNS == tuple(_D07_COLUMNS[:9]) and _ok(columns=[]).stored_columns() == ()


def test_columns_are_at_most_32_ids_of_22s_pattern_and_d07s_are_taken_in_order() -> None:
    """22 bounds them from E08-D07: its §4.1 ids pass, and so does one it does not name yet (D8:
    ids are stored strings, a reader skips one it does not know)."""
    assert _ok(columns=_D07_COLUMNS[::-1]).columns == _D07_COLUMNS[::-1]
    assert _ok(columns=["a_new_column"]).columns == ["a_new_column"]
    most, longest = [f"c{i}" for i in range(MAX_COLUMNS)], "c" * 32
    assert len(_ok(columns=most).stored_columns()) == 32
    assert _ok(columns=[longest]).stored_columns() == (longest,)
    many = [*most, "c32"]
    assert _rules({"name": "n", "symbols": [], "columns": many}) == [("columns", "too_long")]
    twice = ["last", "chg_24h_pct", "last"]
    assert _rules({"name": "n", "symbols": [], "columns": twice}) == [
        ("columns", "duplicate_column")
    ]
    for bad, rule in (("Last", "string_pattern_mismatch"), ("a\x00", "string_pattern_mismatch"),
                      (longest + "c", "string_too_long")):  # fmt: skip
        assert _rules({"name": "n", "symbols": [], "columns": [bad]}) == [("columns.0", rule)]


def test_duplicates_and_unknown_symbols_are_on_symbols_in_list_order_naming_the_symbol() -> None:
    """22 names the list rules on `symbols`; each message names its symbol. A duplicate needs
    no catalogue; only `unknown_symbol` asks `listed`."""
    listed = frozenset({"BTCUSDT", "ETHUSDT"}).__contains__
    symbols = ["BTCUSDT", "XRPUSDT", "BTCUSDT", "ETHUSDT", "XRPUSDT"]
    pairs = [(e["field"], e["rule"], e["message"].split()[0]) for e in duplicate_errors(symbols)]
    assert pairs == [("symbols", "duplicate_symbol", "BTCUSDT"),
                     ("symbols", "duplicate_symbol", "XRPUSDT")]  # fmt: skip
    unknown = unknown_errors(["XRPUSDT", "ETHUSDT", "DOGEUSDT"], listed)
    assert [(e["field"], e["rule"], e["message"].split()[0]) for e in unknown] == [
        ("symbols", "unknown_symbol", "XRPUSDT"),
        ("symbols", "unknown_symbol", "DOGEUSDT"),
    ]
    assert duplicate_errors(["BTCUSDT", "ETHUSDT"]) == unknown_errors(["BTCUSDT"], listed) == []
