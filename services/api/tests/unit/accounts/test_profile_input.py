"""A profile body's schema refusals and its mapper to the domain profile (E28-T02 #906, slice B1a).

No I/O. The generated model and the audit registry are imported here because tests are not
import-linted; the module under test imports neither (M13 may not).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from candleviewer.accounts.profile_input import (
    SCHEMA_RULES,
    ProfileFieldError,
    field_path,
    map_profile_input,
    schema_errors,
)
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.api._generated.openapi_models import AccountProfileInput
from candleviewer.audit.actions import PROFILE_SAVE_REFUSED_REASONS

_PID = UUID("0b5f6d0e-28a1-4c1e-9e01-000000000001")
_AID = UUID("0b5f6d0e-28a1-4c1e-9e01-000000000002")
_BASE: dict[str, Any] = {"name": "p", "leverage": "5", "sizing": {"mode": "fixed_qty", "qty": "1"}}
_OFF = "Every order carries a native stop-loss, so it cannot be turned off."
_STOP_OFF = ProfileFieldError("require_native_stop", "native_stop_mandatory", _OFF)
_IN_R = "The stop defines R, so stop_loss.unit cannot be r_multiple."
_STOP_IN_R = ProfileFieldError("stop_loss.unit", "stop_defines_r", _IN_R)
#: What `_BASE` maps to: every default of section 5, written out and not read from the mapper.
_DEFAULTS: dict[str, Any] = {"profile_id": _PID, "account_id": _AID} | json.loads("""
    {"name": "p", "is_default": false, "enabled": true, "trading_enabled": false, "version": 1,
     "sizing_mode": "fixed_qty", "fixed_qty": "1", "fixed_notional": null, "pct_equity": null,
     "risk_pct_equity": null, "risk_fixed_amount": null, "min_leg_notional": "0", "leverage": "5",
     "margin_mode": "cross", "position_mode": "one_way", "require_native_sl": true,
     "sl_offset_value": "10", "sl_offset_unit": "ticks", "sl_atr_period": 14,
     "sl_atr_multiple": "2", "fallback_sl_offset_pct": "0.02", "tp_offset_value": null,
     "tp_offset_unit": null, "tp_ladder": [], "max_position_notional": null,
     "max_position_pct_equity": null, "max_daily_loss": null, "max_daily_loss_pct": null,
     "max_open_positions": null, "max_concurrent_orders": null, "max_leverage_cap": null,
     "max_orders_per_minute": 30, "all_symbols": false, "allowed_symbols": [],
     "denied_symbols": [], "reduce_only_default": false, "time_in_force_default": "GTC",
     "slippage_tolerance_bps": 10, "updated_at": 1}
    """)


def _with(**members: Any) -> dict[str, Any]:
    return {**_BASE, **members}


def _map(body: dict[str, Any]) -> AccountProfile:
    return map_profile_input(body, profile_id=_PID, account_id=_AID, version=1, updated_at=1)


def _profile(**changes: Any) -> AccountProfile:
    """`_BASE`'s profile with `changes` (domain field names, JSON values) applied."""
    return AccountProfile.model_validate({**_DEFAULTS, **changes})


def _model_errors(raw: object) -> list[ProfileFieldError]:
    """The generated model's refusals of `raw`, rendered as the router will (spec section 3)."""
    try:
        AccountProfileInput.model_validate(raw)
    except ValidationError as exc:
        found = exc.errors(include_url=False, include_input=False, include_context=False)
        return [ProfileFieldError(field_path(e["loc"]), e["type"], e["msg"]) for e in found]
    return []


def _schema(raw: object) -> list[ProfileFieldError]:
    return schema_errors(raw, _model_errors(raw))


def test_require_native_stop_false_is_refused_as_native_stop_mandatory() -> None:
    raw = _with(require_native_stop=False)
    model = ProfileFieldError("require_native_stop", "literal_error", "Input should be True")
    assert _model_errors(raw) == [model]  # the real model refuses it as a type: B1 replaces that
    assert _schema(raw) == [_STOP_OFF]


@pytest.mark.parametrize("value", [1, 1.0, 0, 0.0, "true", "false", None, [], {}])
def test_require_native_stop_that_is_not_a_boolean_is_a_type_error(value: object) -> None:
    (yes,) = _model_errors(_with(require_native_stop="yes"))
    assert yes.rule == "literal_error"
    assert _schema(_with(require_native_stop=value)) == [yes]  # one entry, the model's own type


@pytest.mark.parametrize("extra", [{}, {"require_native_stop": True}])
def test_require_native_stop_true_or_left_out_is_no_schema_refusal(extra: dict[str, Any]) -> None:
    assert schema_errors(_with(**extra), []) == []


def test_a_stop_in_r_multiple_is_refused_as_stop_defines_r() -> None:
    raw = _with(stop_loss={"unit": "r_multiple", "value": "2"})
    assert _schema(raw) == [_STOP_IN_R]
    assert _schema({**raw, "require_native_stop": False}) == [_STOP_IN_R, _STOP_OFF]


@pytest.mark.parametrize(
    ("member", "message"),
    [
        ("stop_loss", "stop_loss is an object; leave it out for its default."),
        ("risk_caps", "risk_caps is an object; leave it out for no caps."),
    ],
)
def test_null_stop_loss_or_risk_caps_is_refused_as_a_type(member: str, message: str) -> None:
    (sizing,) = _model_errors(_with(sizing=None))
    assert sizing.rule == "model_type"
    assert _schema(_with(**{member: None})) == [ProfileFieldError(member, sizing.rule, message)]
    both = _with(sizing=None, stop_loss=None, risk_caps=None, require_native_stop=False)
    fields = ["sizing", "stop_loss", "risk_caps", "require_native_stop"]  # the model's, then ours
    assert [e.field for e in _schema(both)] == fields


def test_the_model_keeps_its_own_entries_beside_the_named_ones() -> None:
    (margin,) = _model_errors(_with(margin_mode="portfolio"))
    assert (margin.field, margin.rule) == ("margin_mode", "literal_error")
    raw = _with(margin_mode="portfolio", stop_loss={"unit": "r_multiple"})
    assert _schema({**raw, "require_native_stop": False}) == [margin, _STOP_IN_R, _STOP_OFF]


@pytest.mark.parametrize(
    "raw",
    [[], "x", _with(stop_loss="ticks"), _with(stop_loss={"unit": "price"}), _with(risk_caps=[])],
)
def test_raw_checks_leave_every_other_shape_to_the_model(raw: object) -> None:
    errors = _model_errors(raw)
    assert errors  # the model refuses it, and B1 neither adds to that nor takes from it
    assert schema_errors(raw, []) == []
    assert schema_errors(raw, errors) == errors


def test_the_create_example_maps_to_its_domain_profile() -> None:
    body = json.loads("""
        {"name": "Alice — 0.5R", "trading_enabled": true, "leverage": "10",
         "margin_mode": "isolated",
         "sizing": {"mode": "risk_based", "risk_per_trade_pct": "0.5", "min_leg_notional_usd": "5"},
         "stop_loss": {"unit": "atr", "atr_period": 14, "atr_multiple": "1.5"},
         "take_profit": {"unit": "r_multiple", "value": "2"},
         "risk_caps": {"max_position_notional_usd": "60000", "max_daily_loss_pct": "3",
                       "max_open_positions": 3, "max_concurrent_orders": 20,
                       "max_leverage_cap": "10"},
         "allowed_symbols": ["BTCUSDT", "ETHUSDT"]}
        """)  # the `riskBased` example of `createAccountProfile`
    expected = json.loads("""
        {"name": "Alice — 0.5R", "trading_enabled": true, "leverage": "10", "fixed_qty": null,
         "margin_mode": "isolated", "sizing_mode": "risk_based", "risk_pct_equity": "0.005",
         "min_leg_notional": "5", "sl_offset_unit": "atr", "sl_atr_multiple": "1.5",
         "tp_offset_unit": "r_multiple", "tp_offset_value": "2", "max_position_notional": "60000",
         "max_daily_loss_pct": "0.03", "max_open_positions": 3, "max_concurrent_orders": 20,
         "max_leverage_cap": "10", "allowed_symbols": ["BTCUSDT", "ETHUSDT"]}
        """)
    assert _map(body) == _profile(**expected)


def test_a_member_left_out_takes_its_contract_default() -> None:
    assert _map(_BASE) == _profile()


def test_a_null_is_read_as_a_member_left_out() -> None:
    top = dict.fromkeys("enabled margin_mode allowed_symbols blocked_symbols take_profit".split())
    sizing = {**_BASE["sizing"], "notional_usd": None, "min_leg_notional_usd": None}
    caps = {"max_open_positions": None, "max_orders_per_minute": None}
    assert _map(_with(**top, sizing=sizing, risk_caps=caps, stop_loss=None)) == _profile()


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"stop_loss": {"unit": "atr", "atr_multiple": "3"}},
        {"risk_caps": {"max_open_positions": 5, "max_leverage_cap": "10"}},
    ],
)
def test_the_defaults_are_those_of_the_generated_model(extra: dict[str, Any]) -> None:
    model = AccountProfileInput.model_validate(_with(**extra))
    sent, full = model.model_dump(mode="json", exclude_unset=True), model.model_dump(mode="json")
    assert sent != full  # the full dump carries every default the client left out
    assert _map(sent) == _map(full)


_WIDE = "99999999999999999999.999999999999999999"  # 38 digits: numeric(38,18) to the last digit
_WIDE_PCT = "999999999999999999.99999999999999999999"  # the same digits, two places down


@pytest.mark.parametrize(
    ("member", "value", "field", "expected"),
    [
        ("sizing", {"mode": "pct_equity", "pct": "25.5"}, "pct_equity", "0.255"),
        ("sizing", {"mode": "risk_based", "risk_per_trade_pct": "0.5"}, "risk_pct_equity", "0.005"),
        ("stop_loss", {"unit": "ticks", "fallback_pct": "2.5"}, "fallback_sl_offset_pct", "0.025"),
        ("risk_caps", {"max_position_pct_equity": "25"}, "max_position_pct_equity", "0.25"),
        ("risk_caps", {"max_daily_loss_pct": "3"}, "max_daily_loss_pct", "0.03"),
        ("take_profit_ladder", [{"qty_pct": "25", "r": "2"}], "tp_ladder.0.qty_pct", "0.25"),
        ("stop_loss", {"unit": "percent", "value": "1.5"}, "sl_offset_value", "0.015"),
        ("take_profit", {"unit": "percent", "value": "4"}, "tp_offset_value", "0.04"),
        ("stop_loss", {"unit": "ticks", "value": "20"}, "sl_offset_value", "20"),
        ("stop_loss", {"unit": "atr", "value": "20"}, "sl_offset_value", "20"),
        ("take_profit", {"unit": "ticks", "value": "30"}, "tp_offset_value", "30"),
        ("take_profit", {"unit": "atr", "value": "1.5"}, "tp_offset_value", "1.5"),
        ("take_profit", {"unit": "r_multiple", "value": "2"}, "tp_offset_value", "2"),
        # the shift moves the exponent only: a 28-digit context would round this one
        ("stop_loss", {"unit": "percent", "value": _WIDE}, "sl_offset_value", _WIDE_PCT),
    ],
)
def test_percents_map_to_fractions_and_other_units_do_not(
    member: str, value: object, field: str, expected: str
) -> None:
    got: Any = _map(_with(**{member: value}))
    for part in field.split("."):  # `tp_ladder.0.qty_pct` walks into the ladder
        got = got[int(part)] if part.isdigit() else getattr(got, part)
    assert got == Decimal(expected)


@pytest.mark.parametrize("edit", [{}, {"risk_caps": None}, {"risk_caps": {}}])
def test_a_body_without_risk_caps_clears_every_cap(edit: dict[str, Any]) -> None:
    caps = {k: v for k, v in _map(_with(**edit)).model_dump().items() if k.startswith("max_")}
    assert caps == {k: 30 if k == "max_orders_per_minute" else None for k in caps}
    assert len(caps) == 8


def test_symbols_map_as_written_and_blocked_symbols_are_denied() -> None:
    mapped = _map(_with(allowed_symbols=["*USDT", "BTCUSDT"], blocked_symbols=["ETHUSDT"]))
    assert (mapped.allowed_symbols, mapped.denied_symbols) == (("*USDT", "BTCUSDT"), ("ETHUSDT",))
    empty = _map(_with(allowed_symbols=[], blocked_symbols=[]))
    assert (empty.allowed_symbols, empty.denied_symbols) == ((), ())


def test_trailing_zeros_never_reach_the_domain() -> None:
    sizing = {"mode": "fixed_qty", "qty": "1.50" + "0" * 4000}
    mapped = _map(_with(leverage="10." + "0" * 4000, sizing=sizing))
    assert (str(mapped.leverage), str(mapped.fixed_qty)) == ("10", "1.5")


@pytest.mark.parametrize("value", ["1e3", "7\n", " 7", "٣", "+7", ".5", "1.", "", True, 7, 7.5])
def test_a_value_the_generated_model_did_not_check_is_a_type_error(value: object) -> None:
    with pytest.raises(TypeError) as raised:
        _map(_with(leverage=value))
    assert str(raised.value) == "leverage is not a C6 decimal string"  # names the member only


@pytest.mark.parametrize(
    ("member", "value", "message"),
    [
        ("sizing", [], "sizing is not an object"),
        ("stop_loss", "ticks", "stop_loss is not an object"),
        ("take_profit_ladder", {}, "take_profit_ladder is not a list"),
        ("take_profit_ladder", [1], "a take_profit_ladder rung is not an object"),
    ],
)
def test_a_wrong_shape_is_a_type_error(member: str, value: object, message: str) -> None:
    with pytest.raises(TypeError, match=f"^{message}$"):
        _map(_with(**{member: value}))


@pytest.mark.parametrize("edit", [{"leverage": "101"}, {"require_native_stop": False}])
def test_a_body_the_domain_refuses_does_not_map(edit: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):  # a ValueError: the floor holds at the domain too
        _map(_with(**edit))


def test_an_error_is_its_problem_entry() -> None:
    plain = {"field": "leverage", "rule": "above_leverage_cap", "message": "m"}
    assert ProfileFieldError("leverage", "above_leverage_cap", "m").to_dict() == plain
    entry = ProfileFieldError("leverage", "above_leverage_cap", "m", Decimal("1E+2"))
    assert entry.to_dict() == {**plain, "limit": "100"}  # never `1E+2`
    named = ProfileFieldError("leverage", "above_leverage_cap", "m", Decimal(20), "SOLUSDT")
    assert named.to_dict() == {**plain, "limit": "20", "symbol": "SOLUSDT"}


def test_field_path_writes_list_indices_in_brackets() -> None:
    assert field_path(("take_profit_ladder", 3, "qty_pct")) == "take_profit_ladder[3].qty_pct"
    assert [field_path(loc) for loc in [(), ("sizing", "qty"), ("allowed_symbols", 2)]] == [
        "",
        "sizing.qty",
        "allowed_symbols[2]",
    ]


def test_native_stop_mandatory_is_the_only_audited_schema_rule() -> None:
    assert SCHEMA_RULES == {
        "native_stop_mandatory",
        "stop_defines_r",
        "literal_error",
        "model_type",
    }
    assert SCHEMA_RULES & PROFILE_SAVE_REFUSED_REASONS == {"native_stop_mandatory"}
