"""Numeric precision floor for drawing ``levels`` / ``fill_opacity`` (issue 2434, E14-T01).

A non-zero |x| < 1e-6 is refused as ``number_out_of_range``; zero is allowed and ``-0.0`` is
stored as ``0.0``. WHY: jsonb prints tiny values as very long plain decimals on read-back.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import example, given, reject
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from candleviewer.api.drawings_models import BatchIn, DrawingIn, format_errors
from candleviewer.storage.repositories.drawings_sqlalchemy import _json

PTS = [{"t": "2026-01-01T00:00:00Z", "p": "1.5"}, {"t": "2026-01-01T00:01:00Z", "p": "2"}]
MAX_RENDERED = 25  # measured maximum plain-decimal length of an accepted value
RULE = "number_out_of_range"


def fib(levels: list[Any]) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "tool": "fib_retracement",
        "geometry": {"points": PTS, "levels": levels},
    }


def styled(opacity: Any) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "tool": "trendline",
        "geometry": {"points": PTS},
        "style": {"fill_opacity": opacity},
    }


def bad(data: Any, model: type[BaseModel] = DrawingIn) -> list[tuple[str, str]]:
    with pytest.raises(ValidationError) as ei:
        model.model_validate(data)
    return [(e["field"], e["rule"]) for e in format_errors(ei.value)]


def stored(raw_json: str) -> str:
    """model_validate_json -> db_values -> the repository's JSON text."""
    v = DrawingIn.model_validate_json(raw_json).db_values()
    return _json(v["geometry"]) + _json(v["style"])


def test_level_at_the_floor_is_accepted() -> None:
    assert DrawingIn.model_validate(fib([1e-6, -1e-6])).geometry.levels == (1e-6, -1e-6)


def test_level_below_the_floor_is_refused_with_item_path() -> None:
    assert bad(fib([0.5, 9.99e-7])) == [("geometry.levels.1", RULE)]


def test_negative_level_below_the_floor_is_refused() -> None:
    assert bad(fib([-9.99e-7])) == [("geometry.levels.0", RULE)]


def test_smallest_subnormal_level_is_refused() -> None:
    assert bad(fib([5e-324])) == [("geometry.levels.0", RULE)]


def test_fill_opacity_at_the_floor_is_accepted() -> None:
    assert DrawingIn.model_validate(styled(1e-6)).style.fill_opacity == 1e-6


def test_fill_opacity_below_the_floor_is_refused_with_path() -> None:
    assert bad(styled(9.99e-7)) == [("style.fill_opacity", RULE)]


def test_integer_zero_level_stays_an_int() -> None:
    levels = DrawingIn.model_validate(fib([0, 0.5])).db_values()["geometry"]["levels"]
    assert type(levels[0]) is int


def test_integer_zero_opacity_stays_an_int() -> None:
    v = DrawingIn.model_validate(styled(0)).db_values()["style"]["fill_opacity"]
    assert type(v) is int


def test_float_zero_level_stays_a_float_zero() -> None:
    levels = DrawingIn.model_validate(fib([0.0, 0.5])).db_values()["geometry"]["levels"]
    assert (type(levels[0]), str(levels[0])) == (float, "0.0")


def test_negative_zero_opacity_is_stored_as_positive_zero() -> None:
    v = DrawingIn.model_validate(styled(-0.0)).db_values()["style"]["fill_opacity"]
    assert str(v) == "0.0"


def test_negative_zero_level_is_stored_as_positive_zero() -> None:
    v = DrawingIn.model_validate(fib([-0.0, 1])).db_values()["geometry"]["levels"]
    assert [str(x) for x in v] == ["0.0", "1"]


def test_batch_create_op_reports_the_operation_index_for_opacity() -> None:
    ops = [{"op": "create", "drawing": styled(0.5)}, {"op": "create", "drawing": styled(1e-7)}]
    assert bad({"operations": ops}, BatchIn) == [("operations.1.drawing.style.fill_opacity", RULE)]


def test_batch_create_op_reports_the_operation_index_for_levels() -> None:
    ops = [{"op": "create", "drawing": fib([1e-9])}]
    assert bad({"operations": ops}, BatchIn) == [("operations.0.drawing.geometry.levels.0", RULE)]


def opacity_json(spelling: str) -> str:
    raw = json.dumps(styled(0)).replace('"fill_opacity": 0', f'"fill_opacity": {spelling}')
    assert f'"fill_opacity": {spelling}' in raw  # the substitution happened (not vacuous)
    return raw


def levels_json(spelling: str) -> str:
    raw = json.dumps(fib([0])).replace('"levels": [0]', f'"levels": [{spelling}, 1]')
    assert f'"levels": [{spelling}, 1]' in raw  # the substitution happened (not vacuous)
    return raw


@pytest.mark.parametrize("spelling", ["0e-999999", "-0e5", "0.0e0", "-0.0", "0." + "0" * 400 + "1"])
def test_zero_spellings_store_a_short_token_for_opacity(spelling: str) -> None:
    assert stored(opacity_json(spelling)).endswith('{"fill_opacity":0.0}')


def test_underflowing_exponent_is_stored_as_a_short_token() -> None:
    assert '"levels":[0.0,1]' in stored(levels_json("1e-99999999999"))


@pytest.mark.parametrize("spelling", ["0." + "1" * 5000, "999." + "9" * 9000])
def test_long_mantissa_levels_store_a_bounded_token(spelling: str) -> None:
    v = DrawingIn.model_validate_json(levels_json(spelling)).db_values()["geometry"]
    token = _json({"levels": v["levels"][:1]})[len('{"levels":[') : -2]
    assert len(token) <= MAX_RENDERED


@pytest.mark.parametrize("levels", [[0.0, -0.0], [0, -0.0], [-0.0, 0]])
def test_zero_spellings_remain_duplicate_levels(levels: list[float]) -> None:
    assert bad(fib(levels)) == [("geometry.levels", "duplicate_level")]


def test_floor_runs_before_the_duplicate_check() -> None:
    assert bad(fib([1e-9, 1e-9])) == [("geometry.levels.0", RULE)]


def rendered(x: float) -> int:
    return len(format(Decimal(repr(x)), "f"))


# band examples: refused (skipped) under the real floor; a weakened floor accepts
# them and they exceed MAX_RENDERED
@example(-1.0094174924396806e-07)
@example(-1.0094174924396806e-06)
@example(1e-06)
@example(-1e-06)
@given(x=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False))
def test_accepted_level_renders_within_the_bound(x: float) -> None:
    try:
        model = DrawingIn.model_validate(fib([x]))
    except ValidationError:
        reject()  # a refused value is not an example; never pass vacuously
    levels = model.db_values()["geometry"]["levels"]
    assert rendered(levels[0]) <= MAX_RENDERED


# band examples: refused (skipped) under the real floor; a weakened floor accepts
# them and they exceed MAX_RENDERED
@example(1.0094174924396806e-08)
@example(1e-06)
@given(x=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
def test_accepted_fill_opacity_renders_within_the_bound(x: float) -> None:
    try:
        model = DrawingIn.model_validate(styled(x))
    except ValidationError:
        reject()  # a refused value is not an example; never pass vacuously
    assert rendered(model.db_values()["style"]["fill_opacity"]) <= MAX_RENDERED


def test_smallest_subnormal_would_exceed_the_bound_negative_control() -> None:
    assert rendered(5e-324) > MAX_RENDERED
