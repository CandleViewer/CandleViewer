"""A stored profile's REST document (E28-T02 #906, slice D1b): every member at every depth, each
decimal as stored (C6), the times (C7), a read's warnings, the account's environment and the weak
`ETag`, then the round trip through B1's first pass and mapper (D1 spec, section 3.3).

No I/O. The contract, the generated model and B1 are imported here because tests are not
import-linted; the module under test reads none of them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_input import check_profile_input, map_profile_input
from candleviewer.accounts.profile_validator import profile_warnings
from candleviewer.accounts.profiles import AccountProfile, profile_from_row
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.profile_projection import (
    plain,
    profile_body,
    profile_document,
    profile_etag,
    rfc3339,
)
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileRow,
    AccountProfileValues,
)
from tests.contract._admin_support import SPEC, validate_example

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_CREATED = 1_792_486_800_000_000  # 2026-10-20T09:00:00Z, the row's `created_at`
#: C6 as a read writes it: no exponent and no trailing fractional zero.
_PLAIN = re.compile(r"-?[0-9]+(\.[0-9]*[1-9])?")


def _fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def _profile(fixture: str = "risk_based", **changes: Any) -> AccountProfile:
    return AccountProfile.model_validate({**_fixture(fixture), **changes})


def _replayed(doc: dict[str, Any]) -> dict[str, Any]:
    """The document's `profile` as D2 feeds a body to B1: the generated model's `exclude_unset`
    dump."""
    body = api.AccountProfileInput.model_validate(doc["profile"])
    return body.model_dump(mode="json", exclude_unset=True)


def _maps_back(body: dict[str, Any], p: AccountProfile) -> None:
    """B1's first pass takes `body` as a replace of `p`, and its mapper gives `p` back."""
    assert check_profile_input(body, stored_is_default=p.is_default) == []
    ids = {"profile_id": p.profile_id, "account_id": p.account_id}
    assert map_profile_input(body, **ids, version=p.version, updated_at=p.updated_at) == p


#: The `risk_based` fixture's document, every member written out (the D1 spec's B1).
_RISK_BASED: dict[str, Any] = json.loads("""
    {"id": "0b5f6d0e-28a1-4c1e-9e01-000000000001",
     "exchange_account_id": "7d3c9a10-28a1-4c1e-9e01-0000000000a1", "version": 3,
     "created_at": "2026-10-20T09:00:00.000000Z", "updated_at": "2026-09-11T13:11:02.110000Z",
     "warnings": [],
     "profile": {
       "name": "Risk 1%", "is_default": true, "enabled": true, "trading_enabled": true,
       "leverage": "5", "margin_mode": "cross", "position_mode": "one_way",
       "sizing": {"mode": "risk_based", "qty": null, "notional_usd": null, "pct": null,
                  "risk_per_trade_pct": "1", "risk_per_trade_usd": null,
                  "min_leg_notional_usd": "5"},
       "stop_loss": {"unit": "ticks", "value": "20", "atr_period": 14, "atr_multiple": "2",
                     "fallback_pct": "2"},
       "take_profit": null,
       "take_profit_ladder": [{"qty_pct": "50", "r": "1"}, {"qty_pct": "50", "r": "2"}],
       "risk_caps": {"max_position_notional_usd": "50000", "max_position_pct_equity": null,
                     "max_daily_loss_usd": "1000", "max_daily_loss_pct": "3",
                     "max_open_positions": 3, "max_concurrent_orders": 20,
                     "max_leverage_cap": "10", "max_orders_per_minute": 30},
       "all_symbols": false, "allowed_symbols": ["BTCUSDT", "ETHUSDT"], "blocked_symbols": [],
       "require_native_stop": true, "default_time_in_force": "GTC",
       "reduce_only_default": false, "slippage_tolerance_bps": 10}}
    """)


@pytest.mark.parametrize(
    ("environment", "answered"),
    [(ExchangeEnv.LIVE, "live"), (ExchangeEnv.DEMO, "demo"), (ExchangeEnv.TESTNET, "testnet")],
)
def test_the_risk_based_fixture_reads_as_its_document(
    environment: ExchangeEnv, answered: str
) -> None:
    """The account's environment, so a client can badge it (the 16:00Z rider, C-2.11)."""
    p = _profile()
    doc = profile_document(p, created_at=_CREATED, environment=environment)
    assert doc == {**_RISK_BASED, "environment": answered}
    assert profile_etag(p) == 'W/"0b5f6d0e-28a1-4c1e-9e01-000000000001:3"'


def test_a_time_is_every_microsecond_in_utc() -> None:
    """C7 to the microsecond (#906 D1b, code lens R1C-01): no digit is dropped or rounded."""
    assert rfc3339(1_790_843_415_123_456) == "2026-10-01T08:30:15.123456Z"


def _at(doc: Any, path: tuple[str | int, ...]) -> Any:
    for step in path:
        doc = doc[step]
    return doc


@pytest.mark.parametrize(
    ("changes", "path", "answered"),
    [
        ({}, ("sizing", "risk_per_trade_pct"), "1"),  # 0.01
        (
            {"sizing_mode": "pct_equity", "risk_pct_equity": None, "pct_equity": "0.125"},
            ("sizing", "pct"),
            "12.5",
        ),
        ({"sl_offset_unit": "percent", "sl_offset_value": "0.015"}, ("stop_loss", "value"), "1.5"),
        ({"fallback_sl_offset_pct": "0.0275"}, ("stop_loss", "fallback_pct"), "2.75"),
        ({"tp_offset_unit": "percent", "tp_offset_value": "0.04"}, ("take_profit", "value"), "4"),
        ({}, ("take_profit_ladder", 0, "qty_pct"), "50"),  # 0.5
        ({"max_position_pct_equity": "0.25"}, ("risk_caps", "max_position_pct_equity"), "25"),
        ({}, ("risk_caps", "max_daily_loss_pct"), "3"),  # 0.03
        ({}, ("stop_loss", "value"), "20"),  # ticks
        ({"sl_offset_unit": "atr", "sl_offset_value": "1.5"}, ("stop_loss", "value"), "1.5"),
        (
            {"tp_offset_unit": "r_multiple", "tp_offset_value": "2.5"},
            ("take_profit", "value"),
            "2.5",
        ),
        ({"tp_offset_unit": "ticks", "tp_offset_value": "40"}, ("take_profit", "value"), "40"),
        ({"tp_offset_unit": "atr", "tp_offset_value": "0.75"}, ("take_profit", "value"), "0.75"),
        ({}, ("take_profit_ladder", 1, "r"), "2"),
    ],
)
def test_a_percent_is_the_percent_a_user_sees_and_other_units_are_as_stored(
    changes: dict[str, Any], path: tuple[str | int, ...], answered: str
) -> None:
    assert _at(profile_body(_profile(**changes)), path) == answered


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("1E+2", "100"),
        ("0E-18", "0"),
        ("1.500", "1.5"),
        ("1E-18", "0.000000000000000001"),
        ("12345678901234567890.123456789012345678", "12345678901234567890.123456789012345678"),
        ("10", "10"),
        ("100.00", "100"),
    ],
)
def test_a_decimal_is_every_stored_digit_with_no_exponent_or_trailing_zero(
    value: str, text: str
) -> None:
    """A `numeric(38,18)` holds 38 digits; `normalize()` would round at 28."""
    assert plain(Decimal(value)) == text


def test_the_bootstrap_default_reads_back_as_its_body() -> None:
    """0037's `Default` as Postgres answers it, every column at its scale (21 Sec.3.2.4); its
    body is a valid replace that maps back to it (B1b's follow-up)."""
    values = AccountProfileValues(
        name="Default", is_default=True, enabled=True, trading_enabled=False,
        leverage=Decimal("1.00"), margin_mode="cross", position_mode="one_way",
        sizing_mode="risk_based", size_fixed_qty=None, size_fixed_notional_usd=None,
        size_pct_equity=None, risk_pct_equity=Decimal("1.000000"), risk_fixed_amount_usd=None,
        min_leg_notional_usd=Decimal("0E-18"), sl_offset_value=Decimal("10.000000000000000000"),
        sl_offset_unit="ticks", sl_atr_period=14, sl_atr_multiple=Decimal("2.0000"),
        fallback_sl_offset_pct=Decimal("2.000000"), tp_offset_value=None, tp_offset_unit=None,
        tp_ladder=None, require_native_sl=True, max_position_notional_usd=None,
        max_position_pct_equity=None, max_daily_loss_usd=None, max_daily_loss_pct=None,
        max_open_positions=None, max_concurrent_orders=None, max_leverage_cap=None,
        max_orders_per_minute=30, all_symbols=False, allowed_symbols=None, blocked_symbols=None,
        reduce_only_default=False, time_in_force_default="GTC", slippage_tolerance_bps=10,
    )  # fmt: skip
    t, ids = datetime(2026, 10, 20, 9, tzinfo=UTC), _profile()
    row = AccountProfileRow(
        id=ids.profile_id, exchange_account_id=ids.account_id, version=1, values=values,
        created_by=None, updated_by=None, created_at=t, updated_at=t, deleted_at=None,
    )  # fmt: skip
    p = profile_from_row(row)
    doc = profile_document(p, created_at=_CREATED, environment=ExchangeEnv.DEMO)
    assert doc["profile"] == json.loads("""
        {"name": "Default", "is_default": true, "enabled": true, "trading_enabled": false,
         "leverage": "1", "margin_mode": "cross", "position_mode": "one_way",
         "sizing": {"mode": "risk_based", "qty": null, "notional_usd": null, "pct": null,
                    "risk_per_trade_pct": "1", "risk_per_trade_usd": null,
                    "min_leg_notional_usd": "0"},
         "stop_loss": {"unit": "ticks", "value": "10", "atr_period": 14, "atr_multiple": "2",
                       "fallback_pct": "2"},
         "take_profit": null, "take_profit_ladder": [],
         "risk_caps": {"max_position_notional_usd": null, "max_position_pct_equity": null,
                       "max_daily_loss_usd": null, "max_daily_loss_pct": null,
                       "max_open_positions": null, "max_concurrent_orders": null,
                       "max_leverage_cap": null, "max_orders_per_minute": 30},
         "all_symbols": false, "allowed_symbols": [], "blocked_symbols": [],
         "require_native_stop": true, "default_time_in_force": "GTC",
         "reduce_only_default": false, "slippage_tolerance_bps": 10}
        """)
    no_symbols = "Allows no symbol, so it sizes nothing."
    assert doc["warnings"] == [
        {"code": "no_symbols", "message": no_symbols, "field": "allowed_symbols"}
    ]
    _maps_back(_replayed(doc), p)


@pytest.mark.parametrize(
    ("fixture", "field"), [("pct_equity", "all_symbols"), ("fixed_notional", "allowed_symbols")]
)
def test_a_reads_warnings_are_profile_warnings_entries_and_closed(fixture: str, field: str) -> None:
    """A read judges the symbol lists alone (B2a), and each entry is a `ProfileWarning`, which
    takes no other member (`additionalProperties: false`, #4098 R1C-09)."""
    p = _profile(fixture)
    warnings = profile_document(p, created_at=_CREATED, environment=ExchangeEnv.LIVE)["warnings"]
    assert warnings == [w.to_dict() for w in profile_warnings(p)]
    assert [(w["code"], w["field"]) for w in warnings] == [("all_symbols", field)]
    for entry in warnings:
        validate_example("/components/schemas/ProfileWarning", entry)
        api.ProfileWarning.model_validate(entry)
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            validate_example("/components/schemas/ProfileWarning", {**entry, "extra": "x"})
        with pytest.raises(ValidationError, match="extra_forbidden"):
            api.ProfileWarning.model_validate({**entry, "extra": "x"})


def _dec(low: str, high: str, places: int) -> st.SearchStrategy[Decimal]:
    return st.decimals(Decimal(low), Decimal(high), places=places)


_MAX_MONEY = "9" * 20 + "." + "9" * 18  # the largest numeric(38,18), below 1E+20
_MONEY = _dec("0.000000000000000001", _MAX_MONEY, 18)
_SHARE = _dec("0.00000001", "1", 8)  # a fraction whose percent has at most 6 places
_AMOUNTS = {
    "fixed_qty": ("fixed_qty",),
    "fixed_notional": ("fixed_notional",),
    "pct_equity": ("pct_equity",),
    "risk_based": ("risk_pct_equity", "risk_fixed_amount"),
}
_STOPS = {"ticks": _dec("1", "9" * 20, 0), "percent": _SHARE, "atr": _MONEY}
#: The contract's grammar, inside the domain's (`*` and 4 to 20 characters).
_SYMBOLS = st.lists(
    st.from_regex(r"(\*[A-Z0-9]{0,16}|[A-Z0-9]{2,16})USDT", fullmatch=True), max_size=3
)
#: From U+0020 up, no surrogate: B1b's P14 refuses a C0 control or a lone surrogate.
_NAMES = st.text(
    st.characters(min_codepoint=0x20, exclude_categories=["Cs"]), min_size=1, max_size=80
)
_US = st.integers(0, 253_402_300_799_999_999)  # 1970 to the end of 9999


@st.composite
def _profiles(draw: st.DrawFn) -> AccountProfile:
    """A profile a REST write can produce: the `risk_based` fixture with every member drawn inside
    the contract and its columns."""
    mode = draw(st.sampled_from(sorted(_AMOUNTS)))
    amount = draw(st.sampled_from(_AMOUNTS[mode]))
    sizing: dict[str, Decimal | None] = dict.fromkeys(m for ms in _AMOUNTS.values() for m in ms)
    sizing[amount] = draw(_SHARE if amount.endswith("equity") else _MONEY)
    stop = draw(st.sampled_from(sorted(_STOPS)))
    take = draw(st.sampled_from([None, "ticks", "percent", "r_multiple", "atr"]))
    target = _SHARE if take == "percent" else _MONEY  # a take-profit in percent is a share
    rungs: list[dict[str, Decimal]] = []
    left = 10**8  # a rung's share is k * 1E-8, and the shares sum to at most 1
    for k in draw(st.lists(st.integers(1, 10**8), max_size=10)):
        if k <= left:
            rungs.append({"qty_pct": Decimal(f"{k}E-8"), "r": draw(_MONEY)})
            left -= k
    trading, leverage = draw(st.booleans()), draw(_dec("1", "100", 2))
    # Trading bounds one cap of each pair at least, and the other three (decision D11).
    pairs = [(True, False), (False, True), (True, True)] + ([] if trading else [(False, False)])
    position, loss = draw(st.sampled_from(pairs)), draw(st.sampled_from(pairs))

    def maybe(strategy: st.SearchStrategy[Any]) -> Any:
        return draw(strategy) if trading or draw(st.booleans()) else None

    all_symbols = draw(st.booleans())
    return AccountProfile.model_validate(
        {
            **_fixture("risk_based"),
            **sizing,
            "name": draw(_NAMES),
            "is_default": draw(st.booleans()),
            "enabled": draw(st.booleans()),
            "trading_enabled": trading,
            "version": draw(st.integers(1, 2**31 - 1)),
            "sizing_mode": mode,
            "min_leg_notional": draw(_dec("0", _MAX_MONEY, 18)),
            "leverage": leverage,
            "margin_mode": draw(st.sampled_from(["cross", "isolated"])),
            "position_mode": draw(st.sampled_from(["one_way", "hedge"])),
            "sl_offset_value": draw(_STOPS[stop]),
            "sl_offset_unit": stop,
            "sl_atr_period": draw(st.integers(2, 200)),
            "sl_atr_multiple": draw(_dec("0.0001", "999999.9999", 4)),
            "fallback_sl_offset_pct": draw(_dec("0.00000001", "0.99999999", 8)),
            "tp_offset_value": None if take is None else draw(target),
            "tp_offset_unit": take,
            "tp_ladder": rungs,
            "max_position_notional": draw(_MONEY) if position[0] else None,
            "max_position_pct_equity": draw(_SHARE) if position[1] else None,
            "max_daily_loss": draw(_MONEY) if loss[0] else None,
            "max_daily_loss_pct": draw(_dec("0.001", "0.5", 8)) if loss[1] else None,  # SCR-131
            "max_open_positions": maybe(st.integers(1, 50)),
            "max_concurrent_orders": maybe(st.integers(1, 500)),
            "max_leverage_cap": maybe(_dec(str(leverage), "100", 2)),
            "max_orders_per_minute": draw(st.integers(1, 600)),
            "all_symbols": all_symbols,
            "allowed_symbols": () if all_symbols else draw(_SYMBOLS),
            "denied_symbols": draw(_SYMBOLS),
            "reduce_only_default": draw(st.booleans()),
            "time_in_force_default": draw(st.sampled_from(["GTC", "IOC", "FOK", "PostOnly"])),
            "slippage_tolerance_bps": draw(st.integers(0, 1000)),
            "updated_at": draw(_US),
        }
    )


@settings(max_examples=300, deadline=None)
@given(p=_profiles(), created_at=_US, environment=st.sampled_from(ExchangeEnv))
def test_a_stored_profile_reads_as_a_body_that_maps_back_to_it(
    p: AccountProfile, created_at: int, environment: ExchangeEnv
) -> None:
    doc = profile_document(p, created_at=created_at, environment=environment)
    validate_example("/components/schemas/AccountProfile", doc)
    api.AccountProfile.model_validate(doc)
    _maps_back(_replayed(doc), p)


_DECIMAL = "#/components/schemas/Decimal"


def _decimal_paths(schema: dict[str, Any], at: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """The path of each member under `schema` that the contract makes a `Decimal` (a list's items
    are under `[]`)."""
    for name, member in schema.get("properties", {}).items():
        branches = [member, *member.get("oneOf", ()), member.get("items", {})]
        refs = {ref for b in branches if (ref := b.get("$ref"))}
        path = (*at, f"{name}[]" if "items" in member else name)
        if _DECIMAL in refs:
            yield path
        for ref in sorted(refs - {_DECIMAL}):
            yield from _decimal_paths(_SCHEMAS[ref.rsplit("/", 1)[1]], path)


def _leaves(node: Any, path: tuple[str, ...]) -> Iterator[Any]:
    if not path:
        yield node
    elif node is not None:
        name, rest = path[0], path[1:]
        for child in node[name[:-2]] if name.endswith("[]") else [node[name]]:
            yield from _leaves(child, rest)


_DECIMAL_PATHS = list(_decimal_paths(_SCHEMAS["AccountProfileInput"]))
_SHAPES: dict[tuple[str, ...], type[BaseModel]] = {
    (): api.AccountProfileInput,
    ("sizing",): api.ProfileSizing,
    ("stop_loss",): api.ProfileStopLoss,
    ("take_profit",): api.ProfileTakeProfit,
    ("take_profit_ladder[]",): api.ProfileTakeProfitRung,
    ("risk_caps",): api.ProfileRiskCaps,
}


@settings(max_examples=300, deadline=None)
@given(p=_profiles())
def test_every_member_is_answered_and_every_decimal_is_plain(p: AccountProfile) -> None:
    doc = profile_document(p, created_at=_CREATED, environment=ExchangeEnv.LIVE)
    assert set(doc) == set(api.AccountProfile.model_fields)
    body: Any = doc["profile"]
    assert isinstance(body["stop_loss"], dict) and isinstance(body["risk_caps"], dict)
    for path, model in _SHAPES.items():
        for node in _leaves(body, path):
            assert node is None or set(node) == set(model.model_fields), path
    assert len(_DECIMAL_PATHS) == 18  # the walk found them all
    for path in _DECIMAL_PATHS:
        for leaf in _leaves(body, path):
            assert leaf is None or _PLAIN.fullmatch(leaf), (path, leaf)
