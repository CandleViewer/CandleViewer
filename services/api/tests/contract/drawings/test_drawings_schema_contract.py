"""E14-Q04 (#431) `/drawings` schema rules through the real `create_app()` (conftest): the tool
enum, `additionalProperties: false`, required fields, cursor/limit pagination, the `layout_id`
filter and the verbatim `label` round-trip. Requests and responses are checked against
`22-api-openapi.yaml` by `_drawings_contract`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from _drawings_contract import MIN_POINTS, MISSING, SCHEMAS, SPEC, SYMBOLS, TOOLS, Api, drawing

from tests.contract.rbac.rbac_harness import user_id_of

OWNER = "owner"


def test_every_tool_has_a_point_count_rule_to_build_its_fixture_from() -> None:
    assert sorted(MIN_POINTS) == sorted(TOOLS), "a DrawingTool value lost its point-count rule"


@pytest.mark.parametrize("tool", TOOLS)
def test_every_enum_tool_is_accepted_and_read_back(api: Api, tool: str) -> None:
    """Decision record 1 (#357): descoped tools stay in the enum, so every value is writable."""
    made = api.create(OWNER, tool=tool)
    assert made["tool"] == tool and made["geometry"] == drawing(tool)["geometry"]
    assert api.listed(OWNER) == [made]


def test_a_tool_outside_the_enum_is_422(api: Api) -> None:
    r = api.send(OWNER, "createDrawing", drawing() | {"tool": "scribble"}, invalid=True)
    assert r.status_code == 422 and [e["field"] for e in r.json()["errors"]] == ["tool"]
    assert api.listed(OWNER) == []


@pytest.mark.parametrize("where", [(), ("geometry",), ("geometry", "points", 0), ("style",)])
def test_an_undeclared_field_is_422_never_ignored(api: Api, where: tuple[Any, ...]) -> None:
    """Gherkin "an unknown field is silently accepted": `additionalProperties: false` holds on
    `DrawingInput` and on every object inside it."""
    body = node = drawing(style={"colour": "#5B8DEF"})
    for key in where:
        node = node[key]
    node["pixels"] = 12
    r = api.send(OWNER, "createDrawing", body, invalid=True)
    field = ".".join(str(k) for k in (*where, "pixels"))
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, "extra_forbidden")]
    assert api.listed(OWNER) == [] and api.repo.rows == {}  # no row created


@pytest.mark.parametrize("missing", SCHEMAS["DrawingInput"]["required"])
def test_a_missing_required_field_is_422_in_the_standard_envelope(api: Api, missing: str) -> None:
    body = {k: v for k, v in drawing().items() if k != missing}
    problem = api.send(OWNER, "createDrawing", body, invalid=True).json()
    assert (problem["status"], problem["code"]) == (422, "validation_failed")
    assert [(e["field"], e["rule"]) for e in problem["errors"]] == [(missing, "missing")]
    assert api.listed(OWNER) == []


def test_cursor_paging_is_complete_and_ordered_and_meta_is_consistent(api: Api) -> None:
    mine = sorted(api.create(OWNER)["id"] for _ in range(5))
    api.create(OWNER, symbol=SYMBOLS[1])
    seen: list[str] = []
    params: dict[str, Any] = {"symbol": SYMBOLS[0], "limit": 2}
    while True:
        page = api.send(OWNER, "listDrawings", params=params).json()
        meta, seen = page["meta"], seen + [d["id"] for d in page["items"]]
        assert meta["count"] == len(page["items"]) <= 2
        assert meta["has_more"] is (meta["next_cursor"] is not None)
        if not meta["has_more"]:
            break
        params["cursor"] = meta["next_cursor"]
    assert seen == mine  # ascending ids, each once, none of the other symbol


def test_a_cursor_from_another_symbols_page_is_rejected_not_reinterpreted(api: Api) -> None:
    for _ in range(2):
        api.create(OWNER, symbol=SYMBOLS[1])
    page = api.send(OWNER, "listDrawings", params={"symbol": SYMBOLS[1], "limit": 1}).json()
    params = {"symbol": SYMBOLS[0], "cursor": page["meta"]["next_cursor"]}
    r = api.send(OWNER, "listDrawings", params=params)
    assert (r.status_code, r.json()["code"]) == (400, "invalid_cursor")


def test_limit_has_the_documented_default_and_bounds(api: Api) -> None:
    limit = SPEC["components"]["parameters"]["Limit"]["schema"]
    ops = [{"op": "create", "drawing": drawing()}] * (limit["default"] + 1)
    assert api.send(OWNER, "batchUpsertDrawings", {"operations": ops}).status_code == 200
    meta = api.send(OWNER, "listDrawings", params={"symbol": SYMBOLS[0]}).json()["meta"]
    assert (meta["count"], meta["has_more"]) == (limit["default"], True)
    assert len(api.listed(OWNER, limit=limit["maximum"])) == limit["default"] + 1
    for bad in (limit["minimum"] - 1, limit["maximum"] + 1):
        params = {"symbol": SYMBOLS[0], "limit": bad}
        assert api.send(OWNER, "listDrawings", params=params).status_code == 422


def test_list_holds_both_scopes_and_an_unknown_layout_filter_is_404(api: Api) -> None:
    """`GET ?layout_id` asks the layout store (E15-T01): a live layout of the caller narrows the
    list; once it is gone, like any unknown id, the filter is 404 and a write naming it is 422."""
    layout = str(uuid.uuid4())
    api.repo.layouts[layout] = str(user_id_of(OWNER))  # live while its drawing is stored
    scoped, unscoped = api.seed(OWNER, layout_id=layout), api.seed(OWNER)
    assert sorted(d["id"] for d in api.listed(OWNER)) == sorted([scoped, unscoped])
    narrowed = api.send(OWNER, "listDrawings", params={"symbol": SYMBOLS[0], "layout_id": layout})
    assert [d["id"] for d in narrowed.json()["items"]] == [scoped]
    del api.repo.layouts[layout]  # the layout is deleted (the fake does not cascade)
    for unknown in (layout, MISSING):
        params = {"symbol": SYMBOLS[0], "layout_id": unknown}
        r = api.send(OWNER, "listDrawings", params=params)
        assert (r.status_code, r.json()["code"]) == (404, "not_found")
    refused = api.send(OWNER, "createDrawing", drawing(layout_id=layout)).json()["errors"]
    assert [(e["field"], e["rule"]) for e in refused] == [("layout_id", "layout_not_found")]


LABELS = {"spaces": "  not trimmed  ", "nfd_nfc": "e\u0301 \u00e9",
          "scripts": "\u05e9\u05dc\u05d5\u05dd \u0394 \u65e5\u672c \U0001f642",
          "max_ascii": "x" * 120, "max_astral": "\U0001f642" * 120}  # fmt: skip


@pytest.mark.parametrize("label", LABELS.values(), ids=LABELS.keys())
def test_label_round_trips_verbatim(api: Api, label: str) -> None:
    """SCR-036 names a drawing from `label`: no trim, no normalisation, 120 code points."""
    made = api.create(OWNER, label=label)
    put = api.send(OWNER, "updateDrawing", drawing(label=label[::-1]), drawing_id=made["id"])
    got = (made["label"], put.json()["label"], api.listed(OWNER)[0]["label"])
    assert got == (label, label[::-1], label[::-1])
    too_long = api.send(OWNER, "createDrawing", drawing(label=label + "x" * 121), invalid=True)
    assert (too_long.status_code, too_long.json()["errors"][0]["field"]) == (422, "label")
