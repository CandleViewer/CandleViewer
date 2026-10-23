"""A profile body's schema refusals, its first pass and its mapper to the domain profile (E28-T02
#906, slices B1a and B1b).

No I/O. The generated model and the audit registry are imported here because tests are not
import-linted; the module under test imports neither (M13 may not).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.accounts.profile_input import (
    FIRST_PASS_RULES,
    SCHEMA_RULES,
    ProfileFieldError,
    check_profile_input,
    field_path,
    map_profile_input,
    schema_errors,
)
from candleviewer.accounts.profiles import AccountProfile, profile_values
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


def test_the_stop_in_r_rule_reads_only_the_unit_and_replaces_only_its_entry() -> None:
    (value,) = _model_errors(_with(stop_loss={"unit": "ticks", "value": "1e3"}))
    assert (value.field, value.rule) == ("stop_loss.value", "string_pattern_mismatch")
    in_r = _with(stop_loss={"unit": "r_multiple", "value": "1e3"})
    assert _schema(in_r) == [value, _STOP_IN_R]  # the model's entry for the value stays
    ticks = _with(stop_loss={"unit": "ticks", "value": "r_multiple"})
    assert _schema(ticks) == [value]  # a value that says r_multiple is not the unit


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


#: Every member but `sizing` at a value that is not its default, and the fields they land in.
_NON_DEFAULT_BODY: dict[str, Any] = json.loads("""
    {"is_default": true, "enabled": false, "trading_enabled": true, "margin_mode": "isolated",
     "position_mode": "hedge", "all_symbols": true, "blocked_symbols": ["DOGEUSDT"],
     "default_time_in_force": "PostOnly", "reduce_only_default": true, "slippage_tolerance_bps": 0,
     "stop_loss": {"unit": "atr", "value": "15", "atr_period": 21, "atr_multiple": "3.5",
                   "fallback_pct": "4.5"},
     "take_profit": {"unit": "ticks", "value": "30"},
     "take_profit_ladder": [{"qty_pct": "30", "r": "1.5"}, {"qty_pct": "20.5", "r": "3"}],
     "risk_caps": {"max_position_notional_usd": "5000", "max_position_pct_equity": "12.5",
                   "max_daily_loss_usd": "250", "max_daily_loss_pct": "2.5",
                   "max_open_positions": 4, "max_concurrent_orders": 40,
                   "max_leverage_cap": "9.5", "max_orders_per_minute": 45}}
    """)
_NON_DEFAULT_FIELDS: dict[str, Any] = json.loads("""
    {"is_default": true, "enabled": false, "trading_enabled": true, "margin_mode": "isolated",
     "position_mode": "hedge", "all_symbols": true, "denied_symbols": ["DOGEUSDT"],
     "time_in_force_default": "PostOnly", "reduce_only_default": true, "slippage_tolerance_bps": 0,
     "sl_offset_value": "15", "sl_offset_unit": "atr", "sl_atr_period": 21,
     "sl_atr_multiple": "3.5", "fallback_sl_offset_pct": "0.045",
     "tp_offset_value": "30", "tp_offset_unit": "ticks",
     "tp_ladder": [{"qty_pct": "0.3", "r": "1.5"}, {"qty_pct": "0.205", "r": "3"}],
     "max_position_notional": "5000", "max_position_pct_equity": "0.125",
     "max_daily_loss": "250", "max_daily_loss_pct": "0.025", "max_open_positions": 4,
     "max_concurrent_orders": 40, "max_leverage_cap": "9.5", "max_orders_per_minute": 45}
    """)


@pytest.mark.parametrize(
    ("mode", "member", "field"),
    [
        ("fixed_qty", "qty", "fixed_qty"),
        ("fixed_notional", "notional_usd", "fixed_notional"),
        ("risk_based", "risk_per_trade_usd", "risk_fixed_amount"),
    ],
)
def test_every_member_maps_to_its_own_domain_field(mode: str, member: str, field: str) -> None:
    fields = {"sizing_mode": mode, "fixed_qty": None} | {field: "42.5"} | _NON_DEFAULT_FIELDS
    sizing = {"mode": mode, member: "42.5"}
    assert _map(_with(sizing=sizing, **_NON_DEFAULT_BODY)) == _profile(**fields)


@pytest.mark.parametrize("member", ["is_default", "all_symbols", "reduce_only_default"])
def test_each_flag_set_alone_lands_in_its_own_field(member: str) -> None:
    # The every-member bodies set these three flags alike; one alone tells them apart.
    assert _map(_with(**{member: True})) == _profile(**{member: True})


def test_the_version_and_updated_at_of_the_store_pass_through() -> None:
    mapped = map_profile_input(_BASE, profile_id=_PID, account_id=_AID, version=7, updated_at=99)
    assert (mapped.version, mapped.updated_at) == (7, 99)


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


@pytest.mark.parametrize(
    "edit", [{"leverage": "101"}, {"leverage": "0"}, {"require_native_stop": False}]
)
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


# -- B1b: the first pass. Rulings (a) to (c) are #906's, of 2026-10-22 13:26Z; P14 is #906's,
# rulings of 2026-10-22 13:26Z (C0) and 2026-10-23 01:46Z (lone surrogate; recorded as
# issuecomment-6357453369) -------------------------------------------------------------------------

_E20 = "1" + "0" * 20  # a numeric(38,18) member, or a rung's `r`, is below it (rulings (a), (b))
#: Each member's bounds, copied here and not imported: (low, above, high, below, places). `above`
#: reads "above `low`" (else "at least"), `below` reads "below `high`" (else "at most").
_TABLE: dict[str, tuple[str, bool, str, bool, int]] = {
    "leverage": ("1", False, "100", False, 2),
    "risk_caps.max_leverage_cap": ("1", False, "100", False, 2),
    "sizing.qty": ("0", True, _E20, True, 18),
    "sizing.notional_usd": ("0", True, _E20, True, 18),
    "sizing.risk_per_trade_usd": ("0", True, _E20, True, 18),
    "take_profit.value": ("0", True, _E20, True, 18),
    "risk_caps.max_position_notional_usd": ("0", True, _E20, True, 18),
    "risk_caps.max_daily_loss_usd": ("0", True, _E20, True, 18),
    "sizing.min_leg_notional_usd": ("0", False, _E20, True, 18),
    "stop_loss.value": ("0", True, _E20, True, 18),
    "sizing.pct": ("0", True, "100", False, 6),
    "sizing.risk_per_trade_pct": ("0", True, "100", False, 6),
    "risk_caps.max_position_pct_equity": ("0", True, "100", False, 6),
    "stop_loss.fallback_pct": ("0", True, "100", True, 6),
    "risk_caps.max_daily_loss_pct": ("0.1", False, "50", False, 6),
    "stop_loss.atr_multiple": ("0", True, "1000000", True, 4),
    "take_profit_ladder[0].qty_pct": ("0", True, "100", False, 18),
    "take_profit_ladder[0].r": ("0", True, _E20, True, 18),
}
_IN_PERCENT = {"unit": "percent", "value": "1"}  # a stop whose value takes 18 places
_SIZED = {"qty": "fixed_qty", "notional_usd": "fixed_notional", "pct": "pct_equity"}
_OWN = ProfileFieldError(
    "is_default", "default_has_own_operation", "The default binding has its own operation."
)
_NO_C0 = ProfileFieldError(
    "name",
    "not_allowed",
    "name takes no control character (U+0000 to U+001F) or unpaired surrogate.",
)
_NEEDS_STOP = "risk_based sizing needs a stop_loss: the stop defines the risk."
_EITHER = "risk_based sizing needs sizing.risk_per_trade_pct or sizing.risk_per_trade_usd."
_ONE = "risk_based sizing takes one of sizing.risk_per_trade_pct and sizing.risk_per_trade_usd."
_NO_LIST = "all_symbols allows every listed symbol, so allowed_symbols stays empty."
_WHOLE_LEG = "The take-profit rungs take at most the whole leg: their qty_pct sum to at most 100."
_ABOVE_CAP = "leverage must be at most risk_caps.max_leverage_cap."


def _home(path: str, value: str) -> dict[str, Any]:
    """`_BASE` with the member at `path` set to `value`, and nothing else that can fail."""
    parent, _, member = path.rpartition(".")
    if parent == "sizing":
        mode = _SIZED.get(member, "fixed_qty" if member == "min_leg_notional_usd" else "risk_based")
        sizing = {"mode": mode, **({"qty": "1"} if mode == "fixed_qty" else {}), member: value}
        return _with(sizing=sizing, stop_loss=_IN_PERCENT)
    if parent == "take_profit_ladder[0]":
        return _with(take_profit_ladder=[{"qty_pct": "1", "r": "1", member: value}])
    if not parent:
        return _with(leverage=value)
    homes = {"stop_loss": _IN_PERCENT, "take_profit": {"unit": "ticks"}, "risk_caps": {}}
    return _with(leverage="1", **{parent: {**homes[parent], member: value}})  # 1: under any cap


def _at(edge: str, places: int, step: int) -> str:
    """`edge` moved by `step` units of its `places`-th decimal place, in integers (no rounding)."""
    return format(Decimal(f"{int(Decimal(edge).scaleb(places)) + step}E-{places}"), "f")


def _first(body: dict[str, Any], stored: bool | None = None) -> list[tuple[str, str, Any]]:
    """The first pass's `(field, rule, limit)` entries: a create, or a replace over `stored`."""
    return [(e.field, e.rule, e.limit) for e in check_profile_input(body, stored_is_default=stored)]


def _range(path: str, word: str, bound: str) -> ProfileFieldError:
    return ProfileFieldError(path, "range", f"{path} must be {word} {bound}.", Decimal(bound))


def _places(path: str, places: int) -> ProfileFieldError:
    message = f"{path} takes at most {places} decimal places."
    return ProfileFieldError(path, "precision", message, Decimal(places))


def _edges() -> list[tuple[str, str, list[ProfileFieldError]]]:
    """Test 20's rows: each member on, just past, and just inside each bound; at its places limit
    and past it; and past a bound and its places limit at once (both entries, `range` first)."""
    rows: list[tuple[str, str, list[ProfileFieldError]]] = []
    for path, (low, above, high, below, places) in _TABLE.items():
        past_low = _range(path, "above" if above else "at least", low)
        past_high = _range(path, "below" if below else "at most", high)
        rows += [
            (path, low, [_range(path, "above", low)] if above else []),
            (path, _at(low, places, -1), [past_low]),
            (path, _at(low, places, 1), []),
            (path, high, [_range(path, "below", high)] if below else []),
            (path, _at(high, places, 1), [past_high]),
            (path, _at(high, places, -1), []),
            (path, _at("1", places, 1), []),
            (path, _at("1", places + 1, 1), [_places(path, places)]),
            (path, _at(low, places + 1, -1), [past_low, _places(path, places)]),
            (path, _at(high, places + 1, 1), [past_high, _places(path, places)]),
        ]
    return rows


@pytest.mark.parametrize(("path", "value", "expected"), _edges())
def test_each_decimal_member_is_refused_just_past_its_bounds(
    path: str, value: str, expected: list[ProfileFieldError]
) -> None:
    body = _home(path, value)
    assert check_profile_input(body, stored_is_default=None) == expected
    if not expected:  # a body the pass accepts maps, and every value of it fits its column
        profile_values(_map(body))


@pytest.mark.parametrize("path", _TABLE)
def test_trailing_zeros_count_for_no_decimal_place(path: str) -> None:
    at_the_limit = _at("1", _TABLE[path][4], 1)
    assert _first(_home(path, at_the_limit + "0" * 40)) == []


def test_a_stop_in_ticks_is_a_whole_number_of_ticks() -> None:
    in_ticks = _with(stop_loss={"unit": "ticks", "value": "1.5"})
    assert check_profile_input(in_ticks, stored_is_default=None) == [_places("stop_loss.value", 0)]
    for stop in (
        {"unit": "ticks", "value": "15.000"},
        {"unit": "percent", "value": "1.5"},
        {"unit": "atr", "value": "1.5", "atr_multiple": "2"},
    ):
        assert _first(_with(stop_loss=stop)) == []
    target = {"unit": "ticks", "value": "1.5"}  # ruling (c): no whole ticks, even beside a stop
    assert _first(_with(stop_loss={"unit": "ticks", "value": "10"}, take_profit=target)) == []


@pytest.mark.parametrize(
    ("mode", "sent", "expected"),
    [
        ("fixed_qty", {"qty": None}, [("qty", "required")]),
        ("fixed_notional", {}, [("notional_usd", "required")]),
        ("pct_equity", {"pct": None, "qty": "1"}, [("pct", "required"), ("qty", "not_allowed")]),
        ("fixed_qty", {"qty": "1", "pct": "5"}, [("pct", "not_allowed")]),
        (
            "fixed_notional",
            {"notional_usd": "1", "risk_per_trade_usd": "5"},
            [("risk_per_trade_usd", "not_allowed")],
        ),
        ("pct_equity", {"pct": "5", "risk_per_trade_usd": None}, []),
        ("risk_based", {"risk_per_trade_pct": "1", "qty": "1"}, [("qty", "not_allowed")]),
    ],
)
def test_sizing_takes_exactly_the_amount_of_its_mode(
    mode: str, sent: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    body = _with(sizing={"mode": mode, **sent}, stop_loss=_IN_PERCENT)
    verb = {"required": "needs", "not_allowed": "takes no"}
    assert [
        (e.field, e.rule, e.message) for e in check_profile_input(body, stored_is_default=None)
    ] == [(f"sizing.{m}", rule, f"{mode} sizing {verb[rule]} sizing.{m}.") for m, rule in expected]


_NEITHER = [ProfileFieldError("sizing.risk_per_trade_pct", "required", _EITHER)]
_BOTH = [ProfileFieldError("sizing.risk_per_trade_usd", "not_allowed", _ONE)]


@pytest.mark.parametrize(
    ("amounts", "expected"),
    [
        ({"risk_per_trade_pct": "1", "risk_per_trade_usd": "5"}, _BOTH),
        ({}, _NEITHER),
        ({"risk_per_trade_pct": None, "risk_per_trade_usd": None}, _NEITHER),
        ({"risk_per_trade_pct": None, "risk_per_trade_usd": "5"}, []),
        ({"risk_per_trade_pct": "1", "risk_per_trade_usd": None}, []),
    ],
)
def test_risk_based_sizing_takes_one_risk_amount(
    amounts: dict[str, Any], expected: list[ProfileFieldError]
) -> None:
    body = _with(sizing={"mode": "risk_based", **amounts}, stop_loss=_IN_PERCENT)
    assert check_profile_input(body, stored_is_default=None) == expected


def test_an_amount_that_is_not_allowed_is_not_range_checked() -> None:
    sizing = {"mode": "fixed_qty", "qty": "1", "notional_usd": "0", "pct": "100.0000001"}
    refused = [("sizing.notional_usd", "not_allowed", None), ("sizing.pct", "not_allowed", None)]
    assert _first(_with(sizing=sizing)) == refused
    both = {"mode": "risk_based", "risk_per_trade_pct": "0", "risk_per_trade_usd": "-5"}
    assert _first(_with(sizing=both, stop_loss=_IN_PERCENT)) == [
        ("sizing.risk_per_trade_pct", "range", 0),  # the one it keeps is still checked
        ("sizing.risk_per_trade_usd", "not_allowed", None),
    ]


def test_risk_based_sizing_needs_a_stop_loss() -> None:
    risk_based = {"mode": "risk_based", "risk_per_trade_pct": "1"}
    got = check_profile_input(_with(sizing=risk_based), stored_is_default=None)
    assert got == [ProfileFieldError("stop_loss", "required", _NEEDS_STOP)]
    assert _first(_with(sizing=risk_based, stop_loss={"unit": "ticks", "value": "10"})) == []
    assert _first(_BASE) == []  # another mode takes the default stop, 10 ticks


@pytest.mark.parametrize(
    ("stop", "member"),
    [
        ({"unit": "atr", "value": "10"}, "atr_multiple"),
        ({"unit": "ticks", "atr_multiple": "2"}, "value"),
        ({"unit": "percent", "fallback_pct": "3"}, "value"),
        ({"unit": "atr", "atr_multiple": "2"}, ""),
        ({"unit": "ticks", "value": "2"}, ""),
    ],
)
def test_a_stop_needs_the_member_its_unit_uses(stop: dict[str, str], member: str) -> None:
    got = check_profile_input(_with(stop_loss=stop), stored_is_default=None)
    message = f"A stop in {stop['unit']} needs stop_loss.{member}."
    assert got == (
        [ProfileFieldError(f"stop_loss.{member}", "required", message)] if member else []
    )


def test_all_symbols_takes_no_allow_list() -> None:
    body = _with(all_symbols=True, allowed_symbols=["BTCUSDT"])
    got = check_profile_input(body, stored_is_default=None)
    assert got == [ProfileFieldError("allowed_symbols", "not_allowed", _NO_LIST)]
    assert _first(_with(all_symbols=True, allowed_symbols=[])) == []
    assert _first(_with(all_symbols=False, allowed_symbols=["BTCUSDT"])) == []


def _ladder(*qty_pcts: str) -> dict[str, Any]:
    return _with(take_profit_ladder=[{"qty_pct": pct, "r": "2"} for pct in qty_pcts])


def test_the_rungs_take_at_most_the_whole_leg() -> None:
    got = check_profile_input(_ladder("60", "50"), stored_is_default=None)
    assert got == [ProfileFieldError("take_profit_ladder", "ladder_sum", _WHOLE_LEG, Decimal(100))]
    assert _first(_ladder("50", "50")) == []
    over = _ladder("99.999999999999999999", "0.000000000000000002")  # 100 and 1E-18
    assert _first(over) == [("take_profit_ladder", "ladder_sum", 100)]


def test_leverage_above_the_profiles_own_cap_is_above_leverage_cap() -> None:
    capped = {"max_leverage_cap": "10.00"}
    got = check_profile_input(_with(leverage="11", risk_caps=capped), stored_is_default=None)
    assert got == [ProfileFieldError("leverage", "above_leverage_cap", _ABOVE_CAP, Decimal(10))]
    assert got[0].to_dict()["limit"] == "10"  # the profile's own cap, its zeros stripped
    assert _first(_with(leverage="10", risk_caps=capped)) == []


def test_cross_member_rules_wait_for_valid_members() -> None:
    low_cap = _with(risk_caps={"max_leverage_cap": "0.5"})  # leverage 5 is above it
    assert _first(low_cap) == [("risk_caps.max_leverage_cap", "range", 1)]
    high = _with(leverage="100.5", risk_caps={"max_leverage_cap": "10"})
    assert _first(high) == [("leverage", "range", 100)]
    assert _first(_ladder("150")) == [("take_profit_ladder[0].qty_pct", "range", 100)]
    rungs = _ladder("90", "10.0000000000000000001")
    assert _first(rungs) == [("take_profit_ladder[1].qty_pct", "precision", 18)]


_CAPS = "A trading-enabled profile caps "
#: Section 4.2's P13 in order: the member each loss bound is named by, and its message.
_UNBOUNDED = {
    "max_position_notional_usd": _CAPS + "position size: set "
    "risk_caps.max_position_notional_usd or risk_caps.max_position_pct_equity.",
    "max_daily_loss_usd": _CAPS + "daily loss: set "
    "risk_caps.max_daily_loss_usd or risk_caps.max_daily_loss_pct.",
    "max_open_positions": _CAPS + "open positions: set risk_caps.max_open_positions.",
    "max_concurrent_orders": _CAPS + "concurrent orders: set risk_caps.max_concurrent_orders.",
    "max_leverage_cap": _CAPS + "leverage: set risk_caps.max_leverage_cap.",
}


def _unbounded(member: str) -> ProfileFieldError:
    return ProfileFieldError(f"risk_caps.{member}", "cap_unbounded", _UNBOUNDED[member])


@pytest.mark.parametrize(
    "caps", [{}, {"risk_caps": {}}, {"risk_caps": {"max_open_positions": None}}]
)
def test_a_trading_enabled_body_without_risk_caps_names_each_loss_bound(
    caps: dict[str, Any],
) -> None:
    got = check_profile_input(_with(trading_enabled=True, **caps), stored_is_default=None)
    assert got == [_unbounded(member) for member in _UNBOUNDED]  # R1C-08: never the CHECK's 500


_PAIRS = [
    ("max_position_notional_usd", "max_position_pct_equity"),
    ("max_daily_loss_usd", "max_daily_loss_pct"),
    ("max_open_positions",),
    ("max_concurrent_orders",),
    ("max_leverage_cap",),
]
_CAPPED: dict[str, Any] = json.loads("""
    {"max_position_notional_usd": "1000", "max_position_pct_equity": "10",
     "max_daily_loss_usd": "100", "max_daily_loss_pct": "2", "max_open_positions": 3,
     "max_concurrent_orders": 20, "max_leverage_cap": "10"}
    """)


@pytest.mark.parametrize("bound", _PAIRS)
def test_each_loss_bound_left_open_is_cap_unbounded(bound: tuple[str, ...]) -> None:
    open_bound = {**_CAPPED, **dict.fromkeys(bound)}  # null is no cap; absent is tested below
    body = _with(trading_enabled=True, risk_caps=open_bound)
    assert check_profile_input(body, stored_is_default=None) == [_unbounded(bound[0])]
    assert _first(_with(trading_enabled=True, risk_caps=_CAPPED)) == []
    for kept in bound if len(bound) == 2 else ():  # one member of a pair is enough
        caps = {k: v for k, v in _CAPPED.items() if k not in bound or k == kept}
        assert _first(_with(trading_enabled=True, risk_caps=caps)) == []


@pytest.mark.parametrize("flag", [{}, {"trading_enabled": False}])
def test_a_trading_disabled_body_needs_no_cap(flag: dict[str, Any]) -> None:
    assert _first(_with(**flag)) == []
    assert _first(_with(**flag, risk_caps={"max_open_positions": 3})) == []


@pytest.mark.parametrize("stored", [None, False, True])
@pytest.mark.parametrize("sent", [None, False, True])
def test_the_default_binding_has_its_own_operation(stored: bool | None, sent: bool | None) -> None:
    moves = {(None, True), (False, True), (True, None), (True, False)}  # (stored, sent)
    body = _BASE if sent is None else _with(is_default=sent)
    expected = [_OWN] if (stored, sent) in moves else []  # a create counts as false
    assert check_profile_input(body, stored_is_default=stored) == expected


def test_the_bootstrap_default_read_back_whole_is_a_valid_replace() -> None:
    read = json.loads("""
        {"name": "Default", "is_default": true, "enabled": true, "trading_enabled": false,
         "leverage": "1.00", "margin_mode": "cross", "position_mode": "one_way",
         "sizing": {"mode": "risk_based", "qty": null, "notional_usd": null, "pct": null,
                    "risk_per_trade_pct": "1.000000", "risk_per_trade_usd": null,
                    "min_leg_notional_usd": "0.000000000000000000"},
         "stop_loss": {"unit": "ticks", "value": "10.000000000000000000", "atr_period": 14,
                       "atr_multiple": "2.0000", "fallback_pct": "2.000000"},
         "take_profit": null, "take_profit_ladder": [], "all_symbols": false,
         "allowed_symbols": [], "blocked_symbols": [], "require_native_stop": true,
         "default_time_in_force": "GTC", "reduce_only_default": false, "slippage_tolerance_bps": 10}
        """)  # 0037's Default as D1 renders it, every column at its scale
    read["risk_caps"] = dict.fromkeys(_CAPPED) | {"max_orders_per_minute": 30}  # every cap null
    body = AccountProfileInput.model_validate(read).model_dump(mode="json", exclude_unset=True)
    assert _schema(read) == []
    assert check_profile_input(body, stored_is_default=True) == []
    risk = {"sizing_mode": "risk_based", "fixed_qty": None, "risk_pct_equity": "0.01"}
    assert _map(body) == _profile(name="Default", is_default=True, leverage="1", **risk)


#: One body with a failure of every kind the first pass lists, each value found nowhere else.
_MANY: dict[str, Any] = json.loads("""
    {"name": "Quartz\\u0000Zebra", "is_default": true, "trading_enabled": true,
     "leverage": "77.77", "all_symbols": true, "allowed_symbols": ["ZZTOPUSDT"],
     "sizing": {"mode": "risk_based", "qty": "4242.4242", "risk_per_trade_pct": "0.123456",
                "risk_per_trade_usd": "5150.55", "min_leg_notional_usd": "-2.71828"},
     "take_profit": {"unit": "ticks", "value": "0.00000000000000000042"},
     "take_profit_ladder": [{"qty_pct": "66.6", "r": "13.37"}, {"qty_pct": "55.5", "r": "-8.25"}],
     "risk_caps": {"max_daily_loss_pct": "77.7", "max_open_positions": 7,
                   "max_leverage_cap": "33.33"}}
    """)


def test_every_failure_of_the_pass_is_listed_in_order() -> None:
    got = check_profile_input(_MANY, stored_is_default=None)
    assert got == [
        _OWN,
        _NO_C0,
        _range("sizing.min_leg_notional_usd", "at least", "0"),
        _places("take_profit.value", 18),
        _range("risk_caps.max_daily_loss_pct", "at most", "50"),
        _range("take_profit_ladder[1].r", "above", "0"),  # a bad `r` holds no rule up
        ProfileFieldError("sizing.qty", "not_allowed", "risk_based sizing takes no sizing.qty."),
        ProfileFieldError("sizing.risk_per_trade_usd", "not_allowed", _ONE),
        ProfileFieldError("stop_loss", "required", _NEEDS_STOP),
        ProfileFieldError("allowed_symbols", "not_allowed", _NO_LIST),
        ProfileFieldError("take_profit_ladder", "ladder_sum", _WHOLE_LEG, Decimal(100)),
        ProfileFieldError("leverage", "above_leverage_cap", _ABOVE_CAP, Decimal("33.33")),
        _unbounded("max_position_notional_usd"),
        _unbounded("max_concurrent_orders"),
    ]
    assert {e.rule for e in got} == FIRST_PASS_RULES  # every rule it can answer with
    # P2 and P3 go member by member: leverage, sizing, the stop's three, then the target's value
    sizing = {"mode": "fixed_qty", "qty": "0", "min_leg_notional_usd": "-1"}
    stop = {"unit": "percent", "value": "0", "atr_multiple": "0", "fallback_pct": "0"}
    target = {"unit": "ticks", "value": "0"}
    zeros = _with(leverage="0", sizing=sizing, stop_loss=stop, take_profit=target)
    members = "leverage sizing.qty sizing.min_leg_notional_usd stop_loss.value".split()
    members += "stop_loss.atr_multiple stop_loss.fallback_pct take_profit.value".split()
    assert [field for field, *_ in _first(zeros)] == members


def _strings(node: object) -> list[str]:
    """Every string value in `node`, at any depth; keys are not values."""
    if isinstance(node, dict | list):
        return [s for v in (node.values() if isinstance(node, dict) else node) for s in _strings(v)]
    return [node] if isinstance(node, str) else []


def test_no_message_repeats_a_value_of_the_body() -> None:
    values = {*_strings(_MANY), "Quartz", "Zebra"} - {"risk_based", "ticks"}  # less its enums
    texts = [e.message for e in check_profile_input(_MANY, stored_is_default=None)]
    assert (len(values), len(texts)) == (16, 14)
    assert [(value, text) for value in values for text in texts if value in text] == []


def test_the_audited_rules_are_exactly_the_audit_reasons_b1_can_meet() -> None:
    assert FIRST_PASS_RULES == set(
        "required not_allowed range precision ladder_sum above_leverage_cap cap_unbounded "
        "default_has_own_operation".split()
    )
    audited = (SCHEMA_RULES | FIRST_PASS_RULES) & PROFILE_SAVE_REFUSED_REASONS
    assert audited == {"native_stop_mandatory", "above_leverage_cap", "cap_unbounded"}


#: What P14 refuses (a C0 control, a lone surrogate) and what it leaves be.
_REFUSED = ["Quartz\x00Zebra", "\x01", "tab\there", "line\n", "x\x1f", "\ud800", "a\udfffb"]
_TAKEN = ["a b", "del\x7f", "Alice — 0.5R", "\U0001f600"]


@pytest.mark.parametrize("name", [*_REFUSED, *_TAKEN])
def test_a_name_with_a_control_character_or_lone_surrogate_is_not_allowed(name: str) -> None:
    got = check_profile_input(_with(name=name), stored_is_default=None)
    refused = name in _REFUSED  # a 422, never a 500
    assert got == ([_NO_C0] if refused else [])


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"name": 7}, "name is not a string"),
        ({"sizing": {"mode": "pct_position", "pct": "5"}}, "sizing.mode is not a sizing mode"),
        ({"risk_caps": []}, "risk_caps is not an object"),
        ({"leverage": "1e3"}, "leverage is not a C6 decimal string"),
    ],
)
def test_a_body_the_model_did_not_check_is_a_type_error(edit: dict[str, Any], message: str) -> None:
    with pytest.raises(TypeError) as raised:
        check_profile_input(_with(**edit), stored_is_default=None)
    assert str(raised.value) == message  # names the member, never its value


@settings(max_examples=300, deadline=None)
@given(
    path=st.sampled_from(list(_TABLE)),
    high=st.booleans(),
    step=st.integers(min_value=-3, max_value=3) | st.integers(),
)
def test_range_is_refused_exactly_outside_each_bound(path: str, high: bool, step: int) -> None:
    low, above, top, below, places = _TABLE[path]
    value = _at(top if high else low, places, step)
    over = Decimal(value) > Decimal(low) if above else Decimal(value) >= Decimal(low)
    under = Decimal(value) < Decimal(top) if below else Decimal(value) <= Decimal(top)
    got = [e.rule for e in check_profile_input(_home(path, value), stored_is_default=None)]
    assert got == ([] if over and under else ["range"])


@settings(max_examples=300, deadline=None)
@given(
    path=st.sampled_from(list(_TABLE)),
    places=st.integers(min_value=0, max_value=22),
    digits=st.integers(min_value=0),
    zeros=st.integers(min_value=0, max_value=3),
)
def test_precision_is_refused_exactly_past_each_members_places(
    path: str, places: int, digits: int, zeros: int
) -> None:
    significant = f"{digits % 10**places:0{places}d}"[:-1] + "7" if places else ""
    value = f"1.{significant}{'0' * zeros}" if places or zeros else "1"  # between 1 and 2
    got = [e.rule for e in check_profile_input(_home(path, value), stored_is_default=None)]
    assert got == (["precision"] if places > _TABLE[path][4] else [])


@settings(max_examples=300, deadline=None)
@given(
    units=st.lists(st.integers(min_value=1, max_value=10**7), max_size=9),
    delta=st.integers(min_value=-2, max_value=2) | st.integers(-(10**8), 10**8),
)
def test_ladder_sum_is_refused_exactly_when_the_exact_sum_passes_100(
    units: list[int], delta: int
) -> None:
    whole = 100 * 10**6  # 100 percent, in millionths of a percent
    units = [*units, min(max(whole - sum(units) + delta, 1), whole)]  # the last rung, near 100
    rungs = [{"qty_pct": format(Decimal(f"{n}E-6"), "f"), "r": "1"} for n in units]
    got = check_profile_input(_with(take_profit_ladder=rungs), stored_is_default=None)
    assert [e.rule for e in got] == (["ladder_sum"] if sum(units) > whole else [])


def _c6(low: str, high: str, places: int) -> st.SearchStrategy[str]:
    """C6 strings from `low` to `high` at `places` places, as the generated model dumps them."""
    return st.decimals(Decimal(low), Decimal(high), places=places).map(lambda d: format(d, "f"))


_MAX = "9" * 20 + "." + "9" * 18  # the largest numeric(38,18)
_MONEY, _PCT = _c6("0.000000000000000001", _MAX, 18), _c6("0.000001", "100", 6)
#: No C0 and no surrogate: P14's own test pins both (the model refuses a surrogate).
_NAME_CHARACTERS = st.characters(min_codepoint=0x20, exclude_categories=["Cs"])


@st.composite
def _bodies(draw: st.DrawFn) -> dict[str, Any]:
    """A body inside the contract and the pass's bounds by construction, out to the column edges."""
    amount = draw(st.sampled_from([*_SIZED, "risk_per_trade_pct", "risk_per_trade_usd"]))
    unit, cap = draw(st.sampled_from(["ticks", "percent", "atr"])), draw(_c6("1", "100", 2))
    stop = {
        "unit": unit,
        "value": draw(_c6("1", "9" * 20, 0) if unit == "ticks" else _MONEY),
        "atr_period": draw(st.integers(min_value=2, max_value=200)),
        "atr_multiple": draw(_c6("0.0001", "999999.9999", 4)),
        "fallback_pct": draw(_c6("0.000001", "99.999999", 6)),
    }
    caps = {"max_open_positions": 50, "max_concurrent_orders": 500, "max_leverage_cap": cap}
    caps |= {"max_position_pct_equity": draw(_PCT), "max_daily_loss_usd": draw(_MONEY)}
    target = {"unit": st.sampled_from(["ticks", "percent", "r_multiple", "atr"]), "value": _MONEY}
    rung = {"qty_pct": _c6("0.000000000000000001", "10", 18), "r": _MONEY}
    trading = draw(st.booleans())
    return {
        "name": draw(st.text(_NAME_CHARACTERS, min_size=1, max_size=80)),
        "trading_enabled": trading,
        "leverage": draw(_c6("1", cap, 2)),
        "sizing": {
            "mode": _SIZED.get(amount, "risk_based"),
            amount: draw(_PCT if amount.endswith("pct") else _MONEY),
            "min_leg_notional_usd": draw(_c6("0", _MAX, 18)),
        },
        "stop_loss": stop,
        "take_profit": draw(st.none() | st.fixed_dictionaries(target)),
        "take_profit_ladder": draw(st.lists(st.fixed_dictionaries(rung), max_size=10)),
        "risk_caps": caps if trading or draw(st.booleans()) else {},
        **draw(st.sampled_from([{"all_symbols": True}, {"allowed_symbols": ["*USDT"]}, {}])),
    }


@example(raw=_with(name="\U0001f600" * 80))  # the longest name: 80 characters, 320 bytes
@settings(max_examples=300, deadline=None)
@given(raw=_bodies())
def test_every_body_within_the_contract_passes_and_maps_to_a_storable_profile(
    raw: dict[str, Any],
) -> None:
    assert _schema(raw) == []
    body = AccountProfileInput.model_validate(raw).model_dump(mode="json", exclude_unset=True)
    assert check_profile_input(body, stored_is_default=None) == []
    profile_values(_map(body))  # every value fits its column, so the store takes the profile
