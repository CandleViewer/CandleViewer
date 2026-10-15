"""Numeric precision floor for drawing ``levels`` / ``fill_opacity`` (issue 2434, E14-T01).

A non-zero |x| < 1e-6 is refused as ``number_out_of_range``; zero is allowed and ``-0.0`` is
stored as ``0.0``. WHY: jsonb prints tiny values as very long plain decimals on read-back.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from candleviewer.api.drawings_models import BatchIn, DrawingIn, format_errors
from candleviewer.storage.repositories.drawings_sqlalchemy import _json

PTS = [{"t": "2026-01-01T00:00:00Z", "p": "1.5"}, {"t": "2026-01-01T00:01:00Z", "p": "2"}]
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


def test_zero_is_allowed_for_levels_and_opacity() -> None:
    assert DrawingIn.model_validate(fib([0, 0.5])).geometry.levels == (0, 0.5)
    assert DrawingIn.model_validate(styled(0)).style.fill_opacity == 0


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


@pytest.mark.parametrize("spelling", ["0e-999999", "-0e5", "0.0e0", "-0.0", "0." + "0" * 400 + "1"])
def test_zero_spellings_store_a_short_token_for_opacity(spelling: str) -> None:
    out = stored(
        json.dumps({**styled(0)}).replace('"fill_opacity": 0', f'"fill_opacity": {spelling}')
    )
    assert out.endswith('{"fill_opacity":0.0}')


def test_underflowing_exponent_is_stored_as_a_short_token() -> None:
    raw = json.dumps(fib([0])).replace('"levels": [0]', '"levels": [1e-99999999999, 1]')
    out = stored(raw)
    assert '"levels":[0.0,1]' in out


@pytest.mark.parametrize("levels", [[0.0, -0.0], [0, -0.0], [-0.0, 0]])
def test_zero_spellings_remain_duplicate_levels(levels: list[float]) -> None:
    assert bad(fib(levels)) == [("geometry.levels", "duplicate_level")]


def test_floor_runs_before_the_duplicate_check() -> None:
    assert bad(fib([1e-9, 1e-9])) == [("geometry.levels.0", RULE)]


@pytest.mark.parametrize("x", [1e-6, 1.234567e-6, 999.999999, -1000.0, -1e-6])
def test_readback_size_of_accepted_levels_stays_near_written_size(x: float) -> None:
    written = len(json.dumps(x))
    assert len(format(Decimal(repr(x)), "f")) <= 2 * written + 8
    levels = DrawingIn.model_validate(fib([x])).db_values()["geometry"]["levels"]
    assert len(_json({"levels": levels})) <= 2 * len(json.dumps({"levels": [x]}))


def test_readback_size_of_smallest_accepted_opacity_is_bounded() -> None:
    x = 1e-6
    assert len(format(Decimal(repr(x)), "f")) <= 2 * len(repr(x)) + 4
    v = DrawingIn.model_validate(styled(x)).db_values()["style"]
    assert len(_json(v)) <= 2 * len('{"fill_opacity":1e-06}')


def test_readback_size_of_a_full_levels_array_stays_bounded() -> None:
    levels = [1e-6 * (i + 1) for i in range(24)]
    g = DrawingIn.model_validate(fib(levels)).db_values()["geometry"]
    written = len(json.dumps(levels, separators=(",", ":")))
    assert len(_json({"levels": g["levels"]})) <= 2 * written + 20
    assert max(len(format(Decimal(repr(x)), "f")) for x in levels) <= 30
