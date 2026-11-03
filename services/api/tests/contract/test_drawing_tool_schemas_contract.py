"""Drawing tool schemas (E14-C01, #540, ADR-0045 Decision 3): 24 §1.7 matches the code and `22`.

The tables in `24-internal-schemas.md` §1.7 are parsed and compared with `drawings_models.py`
(tool list and order, point counts, which tools take `text` / `levels` / `bands`, the option
field names, the bounds) and with the OpenAPI `DrawingTool` / `DrawingGeometry`, so a drift in
any of the three fails here. One fixture drawing per tool must also pass `DrawingIn`.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from candleviewer.api import drawings_models as dm
from tests.contract._admin_support import ROOT

_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_22 = yaml.safe_load((ROOT / "docs/plan/22-api-openapi.yaml").read_text(encoding="utf-8"))


def _section() -> str:
    start = _24.index("### 1.7 Drawing geometry")
    return _24[start : _24.index("\n---\n", start)]


def _rows(section: str, header: str) -> list[list[str]]:
    """Cells of the table whose header row starts with ``header``, minus header and rule."""
    lines = section.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith(header))
    out: list[list[str]] = []
    for ln in lines[first + 2 :]:
        if not ln.startswith("|"):
            break
        out.append([c.strip() for c in re.split(r"(?<!\\)\|", ln)[1:-1]])
    return out


def _tool_table() -> dict[str, tuple[str, str, str, str]]:
    rows = _rows(_section(), "| Tool ")
    return {r[0].strip("`"): (r[1], r[2], r[3], r[4]) for r in rows}


def _field_table() -> dict[str, tuple[str, str]]:
    rows = _rows(_section(), "| Field ")
    return {r[0].strip("`"): (r[1], r[2]) for r in rows}


def _count(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}..{hi}"


def test_tool_table_lists_the_25_tools_in_contract_order() -> None:
    assert list(_tool_table()) == list(dm.TOOLS)
    assert len(dm.TOOLS) == 25


def test_tool_table_point_counts_match_point_counts() -> None:
    table = _tool_table()
    assert {t: v[0] for t, v in table.items()} == {t: _count(*dm.POINT_COUNTS[t]) for t in dm.TOOLS}


@pytest.mark.parametrize(
    ("col", "tools"),
    [
        (1, dm._TEXT_TOOLS),
        (2, dm._LEVEL_TOOLS),
        (3, dm._BAND_TOOLS),
    ],
)
def test_tool_table_option_columns_match_the_tool_sets(col: int, tools: frozenset[str]) -> None:
    flagged = {t for t, v in _tool_table().items() if v[col] == "yes"}
    assert flagged == set(tools)
    assert all(v[col] in {"yes", "no"} for v in _tool_table().values())


def test_field_table_names_the_option_fields_of_the_model() -> None:
    fields = set(_field_table())
    model = set(dm.DrawingGeometryIn.model_fields)
    assert {f for f in fields if "[" not in f} == model
    assert {"points[].t", "points[].p"} <= fields


def test_field_table_allowed_on_matches_the_tool_sets() -> None:
    allowed = {k: v[1] for k, v in _field_table().items()}
    for key, tools in (
        ("levels", dm._LEVEL_TOOLS),
        ("bands", dm._BAND_TOOLS),
        ("text", dm._TEXT_TOOLS),
    ):
        assert set(re.findall(r"`(\w+)`", allowed[key])) == set(tools)


def test_field_table_bounds_match_the_code() -> None:
    f = {k: v[0] for k, v in _field_table().items()}
    assert "1..500" in f["points"] and dm.POINT_COUNTS["brush"][1] == 500
    assert "1..24 unique" in f["levels"] and "[-1000, 1000]" in f["levels"]
    assert "1..3 unique" in f["bands"] and "{1, 2, 3}" in f["bands"]
    assert f"1..{dm._MAX_TEXT} code points" in f["text"]
    assert "1e-6" in f["levels"] and dm._MIN_MAGNITUDE == 1e-6


def test_code_bounds_are_the_documented_ones() -> None:
    ok = _valid("fib_retracement")
    dm.DrawingIn.model_validate({**ok, "geometry": {**ok["geometry"], "levels": [1000, -1000]}})
    for bad in ([1001], [0.5, 0.5], [float(i) for i in range(25)], [5e-7]):
        with pytest.raises(ValueError):
            dm.DrawingIn.model_validate({**ok, "geometry": {**ok["geometry"], "levels": bad}})


def test_openapi_drawing_tool_enum_and_geometry_keys_match() -> None:
    schemas: dict[str, Any] = _22["components"]["schemas"]
    assert schemas["DrawingTool"]["enum"] == list(dm.TOOLS)
    props = schemas["DrawingGeometry"]["properties"]
    assert set(props) == set(dm.DrawingGeometryIn.model_fields)
    assert props["points"]["maxItems"] == 500 and props["levels"]["maxItems"] == 24
    assert props["bands"]["maxItems"] == 3 and props["text"]["maxLength"] == dm._MAX_TEXT
    point = schemas["DrawingPoint"]["properties"]
    assert point["t"]["pattern"] == dm._T_PATTERN and point["p"]["pattern"] == dm._P_PATTERN


def _valid(tool: str) -> dict[str, Any]:
    lo, _ = dm.POINT_COUNTS[tool]
    points = [{"t": f"2026-09-13T12:0{i}:00Z", "p": f"{100 + i}.5"} for i in range(lo)]
    geometry: dict[str, Any] = {"points": points}
    if tool in dm._TEXT_TOOLS:
        geometry["text"] = "note"
    if tool in dm._LEVEL_TOOLS:
        geometry["levels"] = [0, 0.5, 1]
    if tool in dm._BAND_TOOLS:
        geometry["bands"] = [1, 2]
    return {"symbol": "BTCUSDT", "tool": tool, "geometry": geometry}


@pytest.mark.parametrize("tool", dm.TOOLS)
def test_one_fixture_drawing_per_tool_passes_the_schema(tool: str) -> None:
    drawing = dm.DrawingIn.model_validate(_valid(tool))
    assert len(drawing.geometry.points) == dm.POINT_COUNTS[tool][0]


@pytest.mark.parametrize("tool", dm.TOOLS)
def test_each_tool_refuses_a_point_count_outside_its_documented_range(tool: str) -> None:
    lo, hi = dm.POINT_COUNTS[tool]
    ok = _valid(tool)
    too_many = [{"t": "2026-09-13T12:00:00Z", "p": "1"}] * (hi + 1)
    with pytest.raises(ValueError):
        dm.DrawingIn.model_validate({**ok, "geometry": {**ok["geometry"], "points": too_many}})
    if lo > 1:
        few = ok["geometry"]["points"][: lo - 1]
        with pytest.raises(ValueError):
            dm.DrawingIn.model_validate({**ok, "geometry": {**ok["geometry"], "points": few}})
