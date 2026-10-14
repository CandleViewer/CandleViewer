"""Specification of the /drawings validation primitives (E14-T01 slice C1a, #357).

Covers vocabulary, points, geometry, style, sanitising and anchors. Request/batch models are
in the stacked C1b slice; HTTP-level behaviour belongs to the router slice.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from candleviewer.api import drawings_models as dm
from candleviewer.api.drawings_models import (
    POINT_COUNTS,
    TOOLS,
    DrawingGeometryIn,
    DrawingPointIn,
    DrawingStyleIn,
    anchors,
    sanitize_text,
)

T0 = "2026-01-01T00:00:00Z"
STRIPPED = [
    *map(chr, range(0x20)),
    *map(chr, range(0x7F, 0xA0)),
    *map(chr, (0x2028, 0x2029, 0x061C, 0x200E, 0x200F)),
    *map(chr, range(0x202A, 0x202F)),
    *map(chr, range(0x2066, 0x206A)),
]
# Independent copy of the contract table so the suite does not trust POINT_COUNTS itself.
_ONE: tuple[str, ...] = ("horizontal_line", "vertical_line", "text", "anchored_vwap")
_TWO: tuple[str, ...] = (
    "trendline",
    "ray",
    "extended_line",
    "rectangle",
    "ellipse",
    "fib_retracement",
)
_TWO += ("fib_timezone", "gann_fan", "arrow", "callout", "measure", "price_range", "date_range")
_THREE: tuple[str, ...] = ("parallel_channel", "triangle", "fib_extension", "pitchfork")
_THREE += ("long_position", "short_position")
EXPECTED: dict[str, tuple[int, int]] = {
    **dict.fromkeys(_ONE, (1, 1)),
    **dict.fromkeys(_TWO, (2, 2)),
    **dict.fromkeys(_THREE, (3, 3)),
    "brush": (2, 500),
    "polyline": (2, 100),
}


def pt(i: int = 0) -> dict[str, str]:
    return {"t": f"2026-01-01T00:{i % 60:02d}:00Z", "p": "1.5"}


def geo(**extra: Any) -> dict[str, Any]:
    return {"points": [pt(0), pt(1)], **extra}


def bad(data: Any, model: type[BaseModel] = DrawingGeometryIn) -> list[tuple[str, str]]:
    with pytest.raises(ValidationError) as ei:
        model.model_validate(data)
    return [(".".join(map(str, e["loc"])), e["type"]) for e in ei.value.errors()]


def test_tools_vocabulary_is_the_25_contract_tools_in_order() -> None:
    assert len(TOOLS) == 25 and len(set(TOOLS)) == 25
    assert TOOLS[0] == "trendline" and TOOLS[-1] == "anchored_vwap"


def test_point_counts_table_matches_the_contract_for_every_tool() -> None:
    assert POINT_COUNTS == EXPECTED and set(POINT_COUNTS) == set(TOOLS)


def test_geometry_minimal_accepts_points_and_defaults_optionals_to_none() -> None:
    g = DrawingGeometryIn.model_validate(geo())
    assert (g.extend_left, g.extend_right, g.levels, g.bands, g.text) == (None,) * 5


def test_geometry_extend_flags_accept_booleans_only() -> None:
    DrawingGeometryIn.model_validate(geo(extend_left=False, extend_right=True))
    assert bad(geo(extend_left=1)) == [("extend_left", "bool_type")]


@pytest.mark.parametrize("key", ["extend_left", "extend_right", "levels", "bands", "text"])
def test_geometry_optional_key_explicit_null_is_rejected(key: str) -> None:
    assert bad(geo(**{key: None})) == [(key, "null_not_allowed")]


@pytest.mark.parametrize(
    ("levels", "rule"),
    [
        ([0.5, 0.5], "duplicate_level"),
        ([1, 1.0], "duplicate_level"),
        ([], "too_short"),
        (list(range(25)), "too_long"),
        ([1001], "less_than_equal"),
        ([-1001], "greater_than_equal"),
        ([float("nan")], "greater_than_equal"),
        ([float("inf")], "less_than_equal"),
    ],
)
def test_levels_invalid_values_are_rejected_with_rule(levels: list[float], rule: str) -> None:
    assert [r for _, r in bad(geo(levels=levels))] == [rule]


def test_levels_boundaries_are_accepted() -> None:
    assert len(DrawingGeometryIn.model_validate(geo(levels=[*range(-12, 12)])).levels or ()) == 24
    DrawingGeometryIn.model_validate(geo(levels=[-1000, 1000]))


def test_levels_json_nan_literal_is_rejected() -> None:
    raw = json.dumps(geo()).replace('"points"', '"levels": [NaN], "points"')
    with pytest.raises(ValidationError):
        DrawingGeometryIn.model_validate_json(raw)


@pytest.mark.parametrize(
    ("bands", "rule"),
    [
        ([], "too_short"),
        ([1, 2, 3, 1], "too_long"),
        ([1, 1], "duplicate_band"),
        ([0], "greater_than_equal"),
        ([4], "less_than_equal"),
    ],
)
def test_bands_invalid_values_are_rejected_with_rule(bands: list[int], rule: str) -> None:
    assert [r for _, r in bad(geo(bands=bands))] == [rule]


def test_bands_all_three_unique_are_accepted() -> None:
    assert DrawingGeometryIn.model_validate(geo(bands=[3, 1, 2])).bands == (3, 1, 2)


def test_geometry_unknown_key_and_missing_points_are_rejected() -> None:
    assert bad(geo(x=1)) == [("x", "extra_forbidden")]
    assert bad({}) == [("points", "missing")]


def test_geometry_unknown_point_key_is_rejected() -> None:
    d = geo()
    d["points"][0]["z"] = 1
    assert bad(d) == [("points.0.z", "extra_forbidden")]


@pytest.mark.parametrize("ch", STRIPPED)
def test_sanitize_removes_each_listed_character(ch: str) -> None:
    assert sanitize_text(f"a{ch}b", allow_newline=False) == "ab"
    assert sanitize_text(f"a{ch}b", allow_newline=True) == (f"a{ch}b" if ch == "\n" else "ab")


def test_sanitize_keeps_everything_else_untouched() -> None:
    s = "  Ünï cødé 😀 \u00a0\u200b\u2060 x  "  # nbsp, ZWSP, word-joiner are not listed
    assert sanitize_text(s, allow_newline=False) == s


@given(st.text())
def test_sanitize_is_idempotent(s: str) -> None:
    for nl in (True, False):
        once = sanitize_text(s, allow_newline=nl)
        assert sanitize_text(once, allow_newline=nl) == once


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs"), blacklist_characters=STRIPPED)
    )
)
def test_sanitize_changes_nothing_when_no_listed_characters(s: str) -> None:
    assert sanitize_text(s, allow_newline=False) == s


def test_text_is_sanitised_keeping_newline_before_length_checks() -> None:
    g = DrawingGeometryIn.model_validate(geo(text="l1\nl2\x00" + "‮" * 2000))
    assert g.text == "l1\nl2"


def test_text_length_boundary_is_1000_code_points() -> None:
    DrawingGeometryIn.model_validate(geo(text="😀" * 1000))
    assert bad(geo(text="x" * 1001)) == [("text", "string_too_long")]


def test_text_empty_after_sanitising_is_text_required() -> None:
    assert bad(geo(text="\x00‮")) == [("text", "text_required")]


def test_text_lone_surrogate_is_invalid_unicode_and_non_string_rejected() -> None:
    assert bad(geo(text="a\ud800")) == [("text", "invalid_unicode")]
    assert bad(geo(text=5)) == [("text", "string_type")]


@pytest.mark.parametrize("p", ["0", "-0", "-1.5", "123456789012345", "0.000000000001"])
def test_point_price_valid_decimals_are_accepted(p: str) -> None:
    assert DrawingPointIn.model_validate({"t": T0, "p": p}).p == p


@pytest.mark.parametrize(
    "p",
    [
        *("01", "00.1", "+1", "1e5", "1E5", "NaN", "Infinity", "-Infinity", ".5", "1.", "", "1,5"),
        *("1.1234567890123", "1234567890123456", " 1", "1 ", 1.5, 1),
    ],
)
def test_point_price_invalid_decimals_and_numbers_are_rejected(p: object) -> None:
    assert bad({"t": T0, "p": p}, DrawingPointIn)[0][0] == "p"


@pytest.mark.parametrize(
    "t", ["2000-01-01T00:00:00Z", "2099-12-31T23:59:59.999Z", "2024-02-29T00:00:00.1Z"]
)
def test_point_time_valid_values_are_accepted(t: str) -> None:
    assert DrawingPointIn.model_validate({"t": t, "p": "1"}).t == t


@pytest.mark.parametrize(
    "t",
    [
        *("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+01:00", "2026-01-01T00:00:00"),
        *("2026-01-01T00:00:00.1234Z", "2026-01-01T00:00:00.Z", "1999-12-31T23:59:59Z"),
        *("2100-01-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-02-29T00:00:00Z"),
        *("2026-04-31T00:00:00Z", "2026-13-01T00:00:00Z", "2026-01-01T24:00:00Z"),
        *("2026-01-01T00:00:60Z", "2026-01-01 00:00:00Z", "2026-01-01T00:00:00z", "", 1767225600),
    ],
)
def test_point_time_invalid_values_are_rejected(t: object) -> None:
    assert bad({"t": t, "p": "1"}, DrawingPointIn)[0][0] == "t"


def test_point_time_feb_30_reports_invalid_timestamp_rule() -> None:
    assert bad({"t": "2026-02-30T00:00:00Z", "p": "1"}, DrawingPointIn) == [
        ("t", "invalid_timestamp")
    ]


@pytest.mark.parametrize("c", ["#000000", "#aBc123", "#FFFFFF"])
def test_style_colour_valid_is_accepted(c: str) -> None:
    s = DrawingStyleIn.model_validate({"colour": c, "fill_colour": c})
    assert (s.colour, s.fill_colour) == (c, c)


@pytest.mark.parametrize("c", ["000000", "#fff", "#gggggg", "#0000000", "red", ""])
def test_style_colour_invalid_is_rejected(c: str) -> None:
    assert bad({"colour": c}, DrawingStyleIn) == [("colour", "string_pattern_mismatch")]


def test_style_fill_colour_may_be_explicit_null() -> None:
    s = DrawingStyleIn.model_validate({"fill_colour": None})
    assert s.model_dump(exclude_unset=True) == {"fill_colour": None}


@pytest.mark.parametrize(
    ("style", "field"),
    [
        ({"fill_opacity": 1.1}, "fill_opacity"),
        ({"fill_opacity": -0.1}, "fill_opacity"),
        ({"fill_opacity": float("nan")}, "fill_opacity"),
        ({"width": 0}, "width"),
        ({"width": 9}, "width"),
        ({"width": 1.5}, "width"),
        ({"dash": "dashdot"}, "dash"),
        ({"font_size": 7}, "font_size"),
        ({"font_size": 49}, "font_size"),
        ({"colour": None}, "colour"),
        ({"label": "x"}, "label"),
    ],
)
def test_style_invalid_values_and_unknown_keys_are_rejected(
    style: dict[str, Any], field: str
) -> None:
    assert bad(style, DrawingStyleIn)[0][0] == field


@pytest.mark.parametrize(
    "style",
    [
        {"fill_opacity": 0, "width": 8, "dash": "dotted", "font_size": 8},
        {"fill_opacity": 1, "width": 1, "dash": "solid", "font_size": 48},
    ],
)
def test_style_boundaries_are_accepted(style: dict[str, Any]) -> None:
    DrawingStyleIn.model_validate(style)


_P = st.from_regex(dm._P_PATTERN, fullmatch=True)


@given(_P)
def test_point_price_pattern_accepts_and_preserves_the_exact_string(p: str) -> None:
    assert DrawingPointIn.model_validate({"t": T0, "p": p}).p == p


_T = st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2099, 12, 31, 23, 59, 59)).map(
    lambda x: f"{x:%Y-%m-%dT%H:%M:%S}.{x.microsecond // 1000:03d}Z"
)


@given(st.lists(_T, min_size=2, max_size=20))
def test_anchors_are_min_and_max_of_point_times(ts: list[str]) -> None:
    lo, hi = anchors([DrawingPointIn(t=t, p="1") for t in ts])
    parsed = [datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) for t in ts]
    assert (lo, hi) == (min(parsed), max(parsed)) and lo.tzinfo is not None


def test_anchors_follow_unordered_points() -> None:
    pts = [
        DrawingPointIn(t=t, p="1") for t in ("2026-01-01T00:00:05.5Z", T0, "2026-01-01T00:00:09Z")
    ]
    assert anchors(pts) == (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 9, tzinfo=UTC),
    )
