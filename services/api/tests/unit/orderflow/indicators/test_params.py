"""`validate_params()`: the server's check of an indicator parameter object (E13-T02).

SR-E13-01: a value outside its bounds or off its step is refused, never clamped. IR-24: the
error names a JSON pointer into the public `params_schema` and the bound, never the rejected
value or an undeclared key. The result is complete (defaults written out) and canonical, so it
feeds a kernel and an instance identity directly.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from candleviewer.orderflow.errors import IndicatorParamError, InvalidParamsError
from candleviewer.orderflow.indicators import IndicatorSpec, build_kernel
from candleviewer.orderflow.indicators.catalogue import (
    SERVER_DEFINITIONS,
    V1_INDICATORS,
    IndicatorDef,
    validate_params,
)
from candleviewer.orderflow.indicators.limits import PERIOD_MAX, PERIOD_MIN

BY_ID = {d.id: d for d in V1_INDICATORS}
EMA, BOLLINGER, CVD, ZIGZAG, PSAR = (
    BY_ID[n] for n in ("ema", "bollinger", "cvd", "zigzag", "psar")
)
BAR_SPEC = "0" * 64
SEED = 20261019


def _refusal(definition: IndicatorDef, params: object) -> InvalidParamsError:
    with pytest.raises(InvalidParamsError) as caught:
        validate_params(definition, params)
    return caught.value


@pytest.mark.parametrize("definition", V1_INDICATORS, ids=lambda d: d.id)
def test_params_absent_ones_take_their_defaults(definition: IndicatorDef) -> None:
    assert validate_params(definition, {}) == definition.defaults()


@pytest.mark.parametrize("definition", list(SERVER_DEFINITIONS.values()), ids=lambda d: d.id)
def test_params_result_is_complete_and_in_its_kernel_domain(definition: IndicatorDef) -> None:
    kernel = definition.kernel
    assert kernel is not None
    params = validate_params(definition, {})
    build_kernel(definition.id, params, source=kernel.sources[0])


def test_params_whole_float_is_the_integer_so_ema_21_and_21_0_are_one_instance() -> None:
    whole, floating, decimal = (validate_params(EMA, {"n": n}) for n in (21, 21.0, Decimal("21")))
    assert whole == floating == decimal == {"n": 21}
    assert all(type(p["n"]) is int for p in (whole, floating, decimal))
    specs = [
        IndicatorSpec.of("ema", p, bar_spec_hash=BAR_SPEC, source="close")
        for p in (whole, floating)
    ]
    assert specs[0].spec_hash == specs[1].spec_hash


@pytest.mark.parametrize(
    ("value", "rule"), [(0, "minimum"), (-1, "minimum"), (5001, "maximum"), (10**9, "maximum")]
)
def test_params_period_out_of_bounds_is_refused_never_clamped(value: int, rule: str) -> None:
    error = _refusal(EMA, {"n": value})
    assert (error.pointer, error.rule) == ("/n", rule)
    assert str(error) == "n must be between 1 and 5000."  # the bound, never the value (IR-24)


@pytest.mark.parametrize("value", [PERIOD_MIN, 2, 4999, PERIOD_MAX])
def test_params_period_bounds_are_inclusive(value: int) -> None:
    assert validate_params(EMA, {"n": value}) == {"n": value}


@pytest.mark.parametrize(
    "value", [2.5, True, False, "21", None, [21], {"v": 21}, math.nan, math.inf]
)
def test_params_period_must_be_a_whole_number(value: object) -> None:
    error = _refusal(EMA, {"n": value})
    assert (error.pointer, error.rule, str(error)) == ("/n", "type", "n must be a whole number.")


@pytest.mark.parametrize("value", [0.1, 0.3, 2, 2.5, 9.9, 10, Decimal("7.7")])
def test_params_multiplier_on_its_decimal_step_is_accepted_exactly(value: float | Decimal) -> None:
    got = validate_params(BOLLINGER, {"mult": value})["mult"]
    assert got == Decimal(str(value))
    assert type(got) is Decimal


@pytest.mark.parametrize("value", [0.30000000000000004, 2.05, 0.15, Decimal("1.01")])
def test_params_multiplier_off_its_step_is_refused_not_rounded(value: float | Decimal) -> None:
    error = _refusal(BOLLINGER, {"mult": value})
    assert (error.pointer, error.rule, str(error)) == (
        "/mult",
        "multipleOf",
        "mult must be a multiple of 0.1.",
    )


@pytest.mark.parametrize(("value", "rule"), [(0, "minimum"), (0.05, "minimum"), (10.1, "maximum")])
def test_params_multiplier_out_of_bounds_is_refused(value: float, rule: str) -> None:
    error = _refusal(BOLLINGER, {"mult": value})
    assert (error.pointer, error.rule, str(error)) == (
        "/mult",
        rule,
        "mult must be between 0.1 and 10.",
    )


@pytest.mark.parametrize("value", [True, "2", None, math.nan, -math.inf])
def test_params_multiplier_must_be_a_number(value: object) -> None:
    error = _refusal(BOLLINGER, {"mult": value})
    assert (error.pointer, error.rule, str(error)) == ("/mult", "type", "mult must be a number.")


def test_params_zigzag_deviation_and_psar_acceleration_have_their_own_steps() -> None:
    assert validate_params(ZIGZAG, {"deviation_pct": 0.5})["deviation_pct"] == Decimal("0.5")
    assert _refusal(ZIGZAG, {"deviation_pct": 50.1}).rule == "maximum"
    assert _refusal(ZIGZAG, {"deviation_pct": 0.25}).rule == "multipleOf"
    assert validate_params(PSAR, {"step": 0.025})["step"] == Decimal("0.025")
    assert _refusal(PSAR, {"max_step": 0.0005}).rule == "minimum"


def test_params_enum_accepts_only_its_values() -> None:
    assert validate_params(CVD, {"anchor": "utc_day"}) == {"anchor": "utc_day"}
    for value in ("since_load", "SESSION", 1, None):
        error = _refusal(CVD, {"anchor": value})
        assert (error.pointer, error.rule) == ("/anchor", "enum")
        assert str(error) == "anchor must be one of: session, utc_day."


def test_params_an_undeclared_key_is_refused_without_naming_it() -> None:
    error = _refusal(EMA, {"n": 21, "compute": "server"})
    assert (error.pointer, error.rule) == ("", "additionalProperties")
    assert str(error) == "ema takes only these parameters: n."
    assert "compute" not in str(error)
    assert _refusal(EMA, {1: 21}).rule == "additionalProperties"
    assert str(_refusal(BY_ID["obv"], {"n": 3})) == "obv takes no parameters."


@pytest.mark.parametrize("params", [None, [], "n=21", 21, ("n", 21)])
def test_params_must_be_an_object(params: object) -> None:
    error = _refusal(EMA, params)
    assert (error.pointer, error.rule, str(error)) == ("", "type", "params must be an object.")


def test_params_refusal_is_a_typed_indicator_param_error() -> None:
    assert issubclass(InvalidParamsError, IndicatorParamError)
    assert issubclass(InvalidParamsError, ValueError)


@seed(SEED)
@settings(max_examples=100, deadline=None)
@given(st.integers(PERIOD_MIN, PERIOD_MAX))
def test_params_property_every_period_inside_the_bounds_is_accepted(value: int) -> None:
    assert validate_params(EMA, {"n": value}) == {"n": value}


@seed(SEED)
@settings(max_examples=100, deadline=None)
@given(st.integers(max_value=PERIOD_MIN - 1) | st.integers(min_value=PERIOD_MAX + 1))
def test_params_property_every_period_outside_the_bounds_is_refused(value: int) -> None:
    assert _refusal(EMA, {"n": value}).rule in {"minimum", "maximum"}


@seed(SEED)
@settings(max_examples=100, deadline=None)
@given(st.integers(1, 100))
def test_params_property_every_step_of_the_multiplier_range_is_exact(tenths: int) -> None:
    assert validate_params(BOLLINGER, {"mult": tenths / 10})["mult"] == Decimal(tenths) / 10
