"""Specification of the /drawings request and batch models (E14-T01 slice C1b, #357).

Primitives (points, geometry, style, sanitising) are specified in test_drawings_models.py.
HTTP-level behaviour (413, 422 envelope) belongs to the router slice.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from candleviewer.api import drawings_models as dm
from candleviewer.api.drawings_models import (
    POINT_COUNTS,
    TOOLS,
    BatchIn,
    DrawingIn,
    format_errors,
)

T0 = "2026-01-01T00:00:00Z"
ID1 = "0190c2a0-0000-7000-8000-000000000001"
ID2 = "0190c2a0-0000-7000-8000-000000000002"
ID3 = "0190c2a0-0000-7000-8000-000000000003"
TOKEN = "2026-01-01T00:00:00.123456Z"  # noqa: S105  # updated_at concurrency token, not a secret
# Independent copy of the contract table so these tests do not trust POINT_COUNTS itself.
_COUNT_GROUPS: dict[tuple[int, int], tuple[str, ...]] = {
    (1, 1): ("horizontal_line", "vertical_line", "text", "anchored_vwap"),
    (2, 2): (
        *("trendline", "ray", "extended_line", "rectangle", "ellipse", "fib_retracement"),
        *("fib_timezone", "gann_fan", "arrow", "callout", "measure", "price_range", "date_range"),
    ),
    (3, 3): (
        *("parallel_channel", "triangle", "fib_extension", "pitchfork"),
        *("long_position", "short_position"),
    ),
    (2, 500): ("brush",),
    (2, 100): ("polyline",),
}
EXPECTED = {t: k for k, ts in _COUNT_GROUPS.items() for t in ts}


def pt(i: int = 0) -> dict[str, str]:
    return {"t": f"2026-01-01T00:{i % 60:02d}:00Z", "p": "1.5"}


def body(tool: str = "trendline", n: int | None = None, **over: Any) -> dict[str, Any]:
    g: dict[str, Any] = {"points": [pt(i) for i in range(EXPECTED[tool][0] if n is None else n)]}
    if tool in ("text", "callout"):
        g["text"] = "hello"
    return {"symbol": "BTCUSDT", "tool": tool, "geometry": g, **over}


def bad(data: Any, model: type[BaseModel] = DrawingIn) -> list[tuple[str, str]]:
    with pytest.raises(ValidationError) as ei:
        model.model_validate(data)
    return [(e["field"], e["rule"]) for e in format_errors(ei.value)]


@pytest.mark.parametrize("tool", TOOLS)
def test_drawing_point_count_bounds_per_tool(tool: str) -> None:
    lo, hi = EXPECTED[tool]
    for n in {lo, hi}:
        DrawingIn.model_validate(body(tool, n))
    for n in (lo - 1, hi + 1):
        assert ("geometry.points", "tool_point_count") in bad(body(tool, n))


def test_drawing_point_counts_agree_with_the_module_table() -> None:
    assert POINT_COUNTS == EXPECTED


def test_drawing_unknown_tool_is_rejected() -> None:
    assert bad({**body(), "tool": "x"})[0][0] == "tool"


@pytest.mark.parametrize("tool", TOOLS)
def test_geometry_tool_specific_keys_are_allowed_only_where_specified(tool: str) -> None:
    def with_key(**kv: Any) -> dict[str, Any]:
        d = body(tool)
        d["geometry"].update(kv)
        return d

    d = body(tool)
    if tool in ("text", "callout"):
        del d["geometry"]["text"]
        assert ("geometry.text", "text_required") in bad(d)
    else:
        assert ("geometry.text", "property_not_allowed_for_tool") in bad(with_key(text="x"))
    if tool.startswith("fib_"):
        assert DrawingIn.model_validate(with_key(levels=[0, 1])).geometry.levels == (0, 1)
    else:
        assert ("geometry.levels", "property_not_allowed_for_tool") in bad(with_key(levels=[0]))
    if tool == "anchored_vwap":
        DrawingIn.model_validate(with_key(bands=[1, 2]))
    else:
        assert ("geometry.bands", "property_not_allowed_for_tool") in bad(with_key(bands=[1]))
    DrawingIn.model_validate(with_key(extend_left=False, extend_right=True))


def test_symbol_pattern_and_length_limits() -> None:
    DrawingIn.model_validate(body(symbol="A" * 16 + "USDT"))  # exactly 20
    for s in ("A" * 17 + "USDT", "btcusdt", "USDT", "BTCUSD", "BTC-USDT", "BTCUSDT\n", "AUSDT"):
        assert bad(body(symbol=s))[0][0] == "symbol", s


def test_label_is_sanitised_before_length_checks_and_newline_is_stripped() -> None:
    assert DrawingIn.model_validate(body(label="a\n" + "‮" * 500 + "b")).label == "ab"


def test_label_empty_or_empty_after_sanitising_is_string_too_short() -> None:
    for v in ("", "‮\x00"):
        assert ("label", "string_too_short") in bad(body(label=v))


def test_label_length_boundary_is_120_code_points() -> None:
    assert DrawingIn.model_validate(body(label="😀" * 120)).label == "😀" * 120
    assert ("label", "string_too_long") in bad(body(label="😀" * 121))


def test_label_lone_surrogate_is_invalid_unicode_and_non_string_is_rejected() -> None:
    assert ("label", "invalid_unicode") in bad(body(label="a\ud800"))
    assert bad(body(label=5))[0][0] == "label"


def test_label_defaults_to_none_and_null_is_allowed() -> None:
    assert DrawingIn.model_validate(body()).label is None
    assert DrawingIn.model_validate(body(label=None)).label is None


def test_unknown_keys_are_rejected_at_every_level() -> None:
    for k in ("extra", "owner_user_id", "id"):
        assert bad({**body(), k: 1})[0][1] == "extra_forbidden"
    d = body()
    d["geometry"]["x"] = 1
    assert bad(d) == [("geometry.x", "extra_forbidden")]
    assert bad(body(style={"zz": 1})) == [("style.zz", "extra_forbidden")]


def test_required_fields_missing_are_reported() -> None:
    for k in ("symbol", "tool", "geometry"):
        d = body()
        del d[k]
        assert bad(d) == [(k, "missing")]


def test_defaults_match_the_contract() -> None:
    v = DrawingIn.model_validate(body()).db_values()
    assert (v["layout_id"], v["style"], v["label"]) == (None, {}, None)
    assert (v["locked"], v["visible"], v["z_index"]) == (False, True, 0)


def test_layout_id_is_only_typed_not_resolved() -> None:
    assert DrawingIn.model_validate(body(layout_id=ID1)).layout_id == UUID(ID1)
    assert bad(body(layout_id="nope"))[0][0] == "layout_id"


def test_flags_are_strict_booleans_and_z_index_is_a_smallint() -> None:
    assert bad(body(locked=1))[0][0] == "locked"
    assert bad(body(visible="true"))[0][0] == "visible"
    for z in (-32768, 32767):
        assert DrawingIn.model_validate(body(z_index=z)).z_index == z
    for bad_z in (-32769, 32768, 1.5):
        assert bad(body(z_index=bad_z))[0][0] == "z_index"


def test_drawing_model_is_frozen() -> None:
    with pytest.raises(ValidationError):
        DrawingIn.model_validate(body()).symbol = "ETHUSDT"


def test_db_values_keys_are_exactly_the_drawing_fields() -> None:
    assert set(DrawingIn.model_validate(body()).db_values()) == {
        *("symbol", "layout_id", "tool", "geometry", "style", "label"),
        *("locked", "visible", "z_index", "anchor_start", "anchor_end"),
    }


def test_db_values_geometry_contains_only_sent_keys_verbatim() -> None:
    assert DrawingIn.model_validate(body()).db_values()["geometry"] == {"points": [pt(0), pt(1)]}
    d = body("fib_retracement")
    d["geometry"].update(levels=[0, 0.618], extend_right=False, extend_left=True)
    assert DrawingIn.model_validate(d).db_values()["geometry"] == {
        "points": [pt(0), pt(1)],
        "extend_left": True,
        "extend_right": False,
        "levels": [0, 0.618],
    }
    d = body("anchored_vwap")
    d["geometry"]["bands"] = [2]
    assert DrawingIn.model_validate(d).db_values()["geometry"] == {"points": [pt(0)], "bands": [2]}
    assert DrawingIn.model_validate(body("callout")).db_values()["geometry"]["text"] == "hello"


def test_db_values_style_keeps_only_set_keys() -> None:
    v = DrawingIn.model_validate(body(style={"width": 2, "dash": "dashed"})).db_values()
    assert v["style"] == {"width": 2, "dash": "dashed"}


@given(st.lists(st.from_regex(dm._P_PATTERN, fullmatch=True), min_size=2, max_size=2))
def test_point_prices_round_trip_verbatim_through_db_values(ps: list[str]) -> None:
    d = body()
    d["geometry"]["points"] = [{"t": T0, "p": p} for p in ps]
    out = DrawingIn.model_validate(d).db_values()["geometry"]["points"]
    assert [x["p"] for x in out] == ps


def test_db_values_anchors_follow_unordered_points() -> None:
    d = body("brush", 3)
    d["geometry"]["points"] = [
        {"t": t, "p": "1"} for t in ("2026-01-01T00:00:05.5Z", "2026-01-01T00:00:01Z", T0)
    ]
    v = DrawingIn.model_validate(d).db_values()
    assert v["anchor_start"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert v["anchor_end"] == datetime(2026, 1, 1, 0, 0, 5, 500000, tzinfo=UTC)


# ------------------------------------------------------------------ batch
def create_op(i: str | None = ID1, **drawing: Any) -> dict[str, Any]:
    return {"op": "create", "drawing": drawing or body(), **({"id": i} if i else {})}


def update_op(i: str = ID1) -> dict[str, Any]:
    return {"op": "update", "id": i, "if_match": TOKEN, "drawing": body()}


def delete_op(i: str = ID1) -> dict[str, Any]:
    return {"op": "delete", "id": i, "if_match": TOKEN}


def test_batch_each_operation_shape_is_accepted() -> None:
    m = BatchIn.model_validate(
        {"operations": [create_op(None), create_op(ID2), update_op(ID3), delete_op(ID1[:-1] + "4")]}
    )
    assert [type(o).__name__ for o in m.operations] == [
        *("BatchCreateIn", "BatchCreateIn", "BatchUpdateIn", "BatchDeleteIn")
    ]


def test_batch_creates_without_ids_are_not_duplicates() -> None:
    BatchIn.model_validate({"operations": [create_op(None), create_op(None)]})


@pytest.mark.parametrize("make", [update_op, delete_op])
def test_batch_missing_if_match_is_rejected(make: Any) -> None:
    o = make()
    del o["if_match"]
    assert bad({"operations": [o]}, BatchIn) == [("operations.0.if_match", "missing")]


@pytest.mark.parametrize("v", ["2026-01-01T00:00:00", "garbage", 1767225600])
def test_batch_if_match_must_be_an_aware_datetime_string(v: object) -> None:
    o = {**delete_op(), "if_match": v}
    assert bad({"operations": [o]}, BatchIn)[0][0] == "operations.0.if_match"


def test_batch_ids_are_required_on_update_and_must_be_uuids_on_create() -> None:
    o = update_op()
    del o["id"]
    assert bad({"operations": [o]}, BatchIn) == [("operations.0.id", "missing")]
    assert bad({"operations": [create_op("nope")]}, BatchIn)[0][0] == "operations.0.id"


def test_batch_unknown_and_missing_op_are_rejected() -> None:
    assert bad({"operations": [{"op": "upsert"}]}, BatchIn) == [
        ("operations.0", "union_tag_invalid")
    ]
    assert bad({"operations": [{"id": ID1}]}, BatchIn) == [("operations.0", "union_tag_not_found")]


def test_batch_unknown_keys_are_rejected_at_op_and_body_level() -> None:
    assert bad({"operations": [{**delete_op(), "extra": 1}]}, BatchIn) == [
        ("operations.0.extra", "extra_forbidden")
    ]
    assert bad({"operations": [delete_op()], "x": 1}, BatchIn) == [("x", "extra_forbidden")]


def test_batch_nested_errors_use_dotted_path_without_union_tag() -> None:
    ops = [create_op(None), create_op(None, **{**body(), "tool": "nope"})]
    assert bad({"operations": ops}, BatchIn) == [("operations.1.drawing.tool", "literal_error")]


def test_batch_duplicate_ids_across_op_kinds_are_rejected() -> None:
    ops = [create_op(ID1), delete_op(ID2), update_op(ID1)]
    assert bad({"operations": ops}, BatchIn) == [("operations.2.id", "duplicate_id")]
    assert bad({"operations": [delete_op(), delete_op()]}, BatchIn) == [
        ("operations.1.id", "duplicate_id")
    ]


def test_batch_operation_count_bounds_are_1_to_200() -> None:
    assert len(BatchIn.model_validate({"operations": [create_op(None)] * 200}).operations) == 200
    assert bad({"operations": []}, BatchIn) == [("operations", "too_short")]
    assert bad({"operations": [create_op(None)] * 201}, BatchIn) == [("operations", "too_long")]


def test_batch_operations_missing_or_not_a_list_is_rejected() -> None:
    assert bad({}, BatchIn) == [("operations", "missing")]
    assert bad({"operations": "x"}, BatchIn)[0][0] == "operations"


# ------------------------------------------------------------------ format_errors
def test_format_errors_entries_have_exactly_field_rule_message_and_never_echo_input() -> None:
    with pytest.raises(ValidationError) as ei:
        DrawingIn.model_validate(body(symbol="SECRET-VALUE"))
    (e,) = format_errors(ei.value)
    assert set(e) == {"field", "rule", "message"} and "SECRET-VALUE" not in json.dumps(e)


def test_format_errors_is_limited_to_limit_entries() -> None:
    ops = [create_op(None, **body(symbol="x")) for _ in range(30)]
    with pytest.raises(ValidationError) as ei:
        BatchIn.model_validate({"operations": ops})
    assert len(format_errors(ei.value)) == 20
    assert len(format_errors(ei.value, limit=3)) == 3


def test_format_errors_prefix_root_and_numeric_segments() -> None:
    with pytest.raises(ValidationError) as ei:
        DrawingIn.model_validate(body(symbol="x"))
    assert format_errors(ei.value, prefix="drawing")[0]["field"] == "drawing.symbol"
    with pytest.raises(ValidationError) as ei:
        DrawingIn.model_validate([])
    assert format_errors(ei.value)[0]["field"] == ""
    d = body()
    d["geometry"]["points"][1]["p"] = "x"
    with pytest.raises(ValidationError) as ei:
        DrawingIn.model_validate(d)
    assert format_errors(ei.value)[0]["field"] == "geometry.points.1.p"


def test_module_size_constants_match_the_contract() -> None:
    sizes = (dm.MAX_BATCH_OPS, dm.MAX_SINGLE_BODY_BYTES, dm.MAX_BATCH_BODY_BYTES, dm.MAX_JSON_DEPTH)
    assert sizes == (200, 64 * 1024, 1024 * 1024, 16)
