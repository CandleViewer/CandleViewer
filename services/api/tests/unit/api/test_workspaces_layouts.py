"""Unit + property tests for the grid tree and `LayoutIn` (E15-T01 S2b-ii)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.api.drawings_models import format_errors
from candleviewer.api.workspaces_models import LayoutIn


def pane(slot: int = 0, **kw: Any) -> dict[str, Any]:
    return {"slot_index": slot, "pane_kind": "chart", **kw}


def layout(panes: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
    return {"name": "L", "panes": [pane()] if panes is None else panes, **kw}


def errs(model: Any, body: dict[str, Any]) -> list[dict[str, str]]:
    with pytest.raises(ValidationError) as ei:
        model.model_validate(body)
    return format_errors(ei.value)


def rules(model: Any, body: dict[str, Any]) -> set[tuple[str, str]]:
    return {(e["field"], e["rule"]) for e in errs(model, body)}


# --- layout ---------------------------------------------------------------------------------
def test_layout_defaults_and_db_values_keys() -> None:
    v = LayoutIn.model_validate({"name": "L", "panes": []}).db_values()
    assert list(v) == [
        "name", "grid_preset", "grid_spec", "crosshair_sync", "level_sync", "symbol_sync",
        "hotkey_slot", "is_default", "panes",
    ]  # fmt: skip
    assert v["grid_spec"] is None and v["panes"] == ()


def test_layout_panes_required_and_max_16() -> None:
    assert errs(LayoutIn, {"name": "L"})
    assert errs(LayoutIn, layout([pane(i % 16) for i in range(17)]))


@pytest.mark.parametrize("key", ["grid_preset", "crosshair_sync", "level_sync", "symbol_sync",
                                 "is_default"])  # fmt: skip
def test_layout_explicit_null_is_rejected(key: str) -> None:
    assert (key, "null_not_allowed") in rules(LayoutIn, layout(**{key: None}))


@pytest.mark.parametrize("slot", [0, 10])
def test_hotkey_slot_bounds_rejected(slot: int) -> None:
    assert errs(LayoutIn, layout(hotkey_slot=slot))
    assert LayoutIn.model_validate(layout(hotkey_slot=9)).hotkey_slot == 9


def test_duplicate_slot_names_the_later_pane() -> None:
    e = errs(LayoutIn, layout([pane(3), pane(1), pane(3)]))
    assert [(x["field"], x["rule"]) for x in e] == [("panes.2.slot_index", "duplicate_slot")]
    assert "panes.0" in e[0]["message"]


def test_layout_panes_sorted_by_slot_in_db_values() -> None:
    v = LayoutIn.model_validate(layout([pane(5), pane(1), pane(3)])).db_values()
    assert [p["slot_index"] for p in v["panes"]] == [1, 3, 5]


@given(st.lists(st.integers(0, 15), min_size=1, max_size=16, unique=True).flatmap(st.permutations))
@settings(max_examples=60, deadline=None)
def test_any_permutation_of_a_valid_pane_set_validates(slots: list[int]) -> None:
    got = LayoutIn.model_validate(layout([pane(s) for s in slots]))
    assert sorted(p.slot_index for p in got.panes) == sorted(slots)


@given(
    st.lists(st.integers(0, 15), min_size=2, max_size=15, unique=True),
    st.data(),
)
@settings(max_examples=60, deadline=None)
def test_repeated_slot_fails_naming_exactly_the_later_pane(base: list[int], data: Any) -> None:
    panes = data.draw(st.permutations(base))
    src = data.draw(st.integers(0, len(panes) - 1))
    dup_at = data.draw(st.integers(src + 1, len(panes)))
    panes = [*panes[:dup_at], panes[src], *panes[dup_at:]]
    e = errs(LayoutIn, layout([pane(s) for s in panes]))
    assert [(x["field"], x["rule"]) for x in e] == [
        (f"panes.{dup_at}.slot_index", "duplicate_slot")
    ]


# --- grid spec ------------------------------------------------------------------------------
def leaf(s: int) -> dict[str, Any]:
    return {"type": "leaf", "slot": s}


def split(kind: str, *kids: dict[str, Any], sizes: list[float] | None = None) -> dict[str, Any]:
    return {"type": kind, "children": list(kids), "sizes": sizes or [1 / len(kids)] * len(kids)}


def custom(root: dict[str, Any], slots: list[int]) -> dict[str, Any]:
    return layout(
        [pane(s) for s in slots], grid_preset="custom", grid_spec={"version": 1, "root": root}
    )


def test_custom_layout_with_valid_tree_round_trips() -> None:
    root = split(
        "row", leaf(0), split("column", leaf(1), {"type": "tabset", "children": [leaf(2)]})
    )
    got = LayoutIn.model_validate(custom(root, [0, 1, 2])).db_values()["grid_spec"]
    assert got["root"]["children"][1]["children"][1] == {
        "type": "tabset", "children": [{"type": "leaf", "slot": 2}], "active": 0,
    }  # fmt: skip


def test_custom_without_spec_is_grid_spec_required() -> None:
    assert rules(LayoutIn, layout(grid_preset="custom")) == {("grid_spec", "grid_spec_required")}


def test_named_preset_with_spec_is_grid_spec_not_allowed() -> None:
    body = layout(grid_spec={"version": 1, "root": leaf(0)})
    assert rules(LayoutIn, body) == {("grid_spec", "grid_spec_not_allowed")}


def test_single_leaf_root_is_valid() -> None:
    LayoutIn.model_validate(custom(leaf(0), [0]))


def test_tree_depth_six_ok_seven_too_deep() -> None:
    def chain(d: int) -> dict[str, Any]:  # depth d, leaves numbered 0..d-1
        node = leaf(0)
        for i in range(1, d):
            node = split("row", node, leaf(i))
        return node

    LayoutIn.model_validate(custom(chain(6), list(range(6))))
    got = rules(LayoutIn, custom(chain(7), list(range(7))))
    assert any(r == "tree_too_deep" for _, r in got)


def test_tree_over_64_nodes_is_too_large() -> None:
    kids = [split("row", leaf(0), leaf(1), leaf(2)) for _ in range(16)]
    root = {"type": "column", "children": kids, "sizes": [1 / 16] * 16}
    assert ("grid_spec.root", "tree_too_large") in rules(LayoutIn, custom(root, [0, 1, 2]))


def test_tree_over_16_leaves_is_too_large() -> None:
    root = split("row", *[leaf(i % 16) for i in range(16)])
    root2 = split("column", root, split("row", leaf(0), leaf(1)))
    assert ("grid_spec.root", "tree_too_large") in rules(LayoutIn, custom(root2, list(range(16))))


def test_unknown_and_duplicate_leaf_slots() -> None:
    got = rules(LayoutIn, custom(split("row", leaf(0), leaf(7)), [0]))
    assert got == {("grid_spec.root.children.1.slot", "unknown_slot")}
    got = rules(LayoutIn, custom(split("row", leaf(0), leaf(0)), [0]))
    assert got == {("grid_spec.root.children.1.slot", "duplicate_leaf")}


def test_sizes_mismatch_sum_and_range() -> None:
    bad = {"type": "row", "children": [leaf(0), leaf(1)], "sizes": [0.5, 0.25, 0.25]}
    assert ("grid_spec.root.sizes", "sizes_mismatch") in rules(LayoutIn, custom(bad, [0, 1]))
    assert ("grid_spec.root.sizes", "sizes_sum") in rules(
        LayoutIn, custom(split("row", leaf(0), leaf(1), sizes=[0.5, 0.4]), [0, 1])
    )
    LayoutIn.model_validate(custom(split("row", leaf(0), leaf(1), sizes=[0.3, 0.7]), [0, 1]))
    assert errs(LayoutIn, custom(split("row", leaf(0), leaf(1), sizes=[0.0, 1.0]), [0, 1]))
    assert errs(LayoutIn, custom(split("row", leaf(0), leaf(1), sizes=[1.5, -0.5]), [0, 1]))


def test_tabset_active_out_of_range() -> None:
    ts = {"type": "tabset", "children": [leaf(0)], "active": 1}
    assert ("grid_spec.root.active", "active_out_of_range") in rules(LayoutIn, custom(ts, [0]))


def test_grid_structural_limits() -> None:
    assert errs(LayoutIn, custom({"type": "row", "children": [leaf(0)], "sizes": [1.0]}, [0]))
    assert errs(LayoutIn, custom({"type": "tabset", "children": []}, [0]))
    assert errs(LayoutIn, layout(grid_preset="custom", grid_spec={"version": 2, "root": leaf(0)}))
    assert errs(LayoutIn, custom({"type": "bogus"}, [0]))


def test_hostile_54kb_body_yields_a_bounded_error_count() -> None:
    # 16 panes x 32 keys x 32 `{}` items. Each key's array fails fast on its first item, so the
    # worst case is one error per key: 16 * 32 = 512 (before: 67,584 = 16 * 32 * 32 * 4).
    body = layout(
        [
            pane(i, pane_config={"settings": {f"k{j}": [{}] * 32 for j in range(32)}})
            for i in range(16)
        ]
    )
    with pytest.raises(ValidationError) as ei:
        LayoutIn.model_validate(body)
    assert ei.value.error_count() <= 16 * 32


def test_grid_children_fail_fast() -> None:
    bad = {"type": "row", "children": [{"type": "x"}] * 16, "sizes": [1 / 16] * 16}
    with pytest.raises(ValidationError) as ei:
        LayoutIn.model_validate(custom(bad, [0]))
    assert ei.value.error_count() <= 2


@pytest.mark.parametrize("version", [True, 1.0, "1", 2])
def test_grid_version_must_be_the_integer_one(version: Any) -> None:
    body = layout(grid_preset="custom", grid_spec={"version": version, "root": leaf(0)})
    assert errs(LayoutIn, body)
