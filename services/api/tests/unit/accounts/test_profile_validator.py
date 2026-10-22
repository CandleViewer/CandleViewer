"""The profile's warnings (E28-T02 #906, slice B2a): `all_symbols` and `no_symbols`.

A read judges the symbol lists alone; a write also judges what the exchange lists, through the
matcher the order path uses (PF-T07). No I/O beyond the recorded corpus and the T01 profile
fixtures. The generated model is imported here because tests are not import-linted; the module
under test does not import it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pytest

from candleviewer.accounts.profile_validator import ProfileWarning, profile_warnings
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.api._generated.openapi_models import ProfileWarning as ProfileWarningContract
from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instruments
from tests._corpus import rest

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
#: Named patches of the recorded catalogue (C-13.5), inserted in this order, not the symbols', so a
#: pass that forgets to sort is caught. BTCUSDT is as recorded: 100x, 0.001 lots, 5 USDT.
_PATCHES: Final[dict[str, dict[str, str]]] = {
    "SOLUSDT": dict(max_leverage="20.00", min_order_qty="0.1", qty_step="0.1", min_notional="10"),
    "LUNAUSDT": dict(status="closed", max_leverage="10.00"),
    "ETHUSDT": dict(max_leverage="50.00", min_order_qty="0.01", qty_step="0.01"),
    "BTCUSDT": {},
}


def _listing() -> MappingProxyType[str, Instrument]:
    rows = rest("rest/instruments_before.json")["result"]["list"]
    parsed = parse_instruments(rows, fetched_at_us=0)
    assert parsed.rejected == ()
    recorded = {i.symbol: i for i in parsed.instruments}
    patched = {s: {**recorded[s].model_dump(), **p} for s, p in _PATCHES.items()}
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
    """The read's warning and its field, whatever the listing would add."""
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
