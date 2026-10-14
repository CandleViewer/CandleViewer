"""Pure mapping helpers of the workspaces repository (E15-T01): rows, payloads, conflict mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories import workspaces_codec as codec
from candleviewer.storage.repositories.workspaces import LayoutFields, PaneFields, WorkspaceFields

_T = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _pane(slot: int = 0) -> PaneFields:
    return PaneFields(slot, "chart", "BTCUSDT", "time:1m", None, (), {"settings": {}}, "auto")


def _lay_fields(*panes: PaneFields) -> LayoutFields:
    return LayoutFields("L", "1x1", None, True, False, False, None, False, panes)


def test_lay_row_maps_empty_grid_spec_to_none_and_decodes_json_text() -> None:
    head = {
        "id": "i", "workspace_id": "w", "name": "L", "grid_preset": "1x1", "grid_spec": "{}",
        "crosshair_sync": True, "level_sync": False, "symbol_sync": False, "hotkey_slot": None,
        "is_default": False, "created_at": _T, "updated_at": _T,
    }  # fmt: skip
    assert codec.lay_row(head, ()).grid_spec is None
    spec = {"version": 1, "root": {"type": "leaf", "slot": 0}}
    assert codec.lay_row({**head, "grid_spec": spec}, ()).grid_spec == spec


def test_pane_row_stringifies_preset_ids_and_decodes_config() -> None:
    m = {
        "slot_index": 2, "pane_kind": "dom", "symbol": None, "interval_code": None,
        "chart_template_id": None, "indicator_preset_ids": [], "pane_config": '{"a":1}',
        "scale_mode": "log",
    }  # fmt: skip
    assert codec.pane_row(m) == PaneFields(2, "dom", None, None, None, (), {"a": 1}, "log")


def test_lay_params_store_named_presets_as_empty_spec() -> None:
    assert codec.lay_params(_lay_fields())["grid_spec"] == "{}"
    custom = LayoutFields("c", "custom", {"b": 1, "a": 2}, True, False, False, 3, True, ())
    assert codec.lay_params(custom)["grid_spec"] == '{"a":2,"b":1}'
    assert set(codec.lay_params(custom)) == {
        "name", "grid_preset", "grid_spec", "crosshair_sync", "level_sync", "symbol_sync",
        "hotkey_slot", "is_default",
    }  # fmt: skip


def test_pane_payload_mints_fresh_ids_and_is_canonical_json() -> None:
    first = json.loads(codec.pane_payload((_pane(0), _pane(1))))
    second = json.loads(codec.pane_payload((_pane(0), _pane(1))))
    assert [p["slot_index"] for p in first] == [0, 1]
    assert {p["id"] for p in first}.isdisjoint({p["id"] for p in second})
    assert set(first[0]) == {
        "id", "slot_index", "pane_kind", "symbol", "interval_code", "chart_template_id",
        "indicator_preset_ids", "pane_config", "scale_mode",
    }  # fmt: skip
    assert codec.pane_payload(()) == "[]"


def test_json_refuses_nan_and_infinity() -> None:
    with pytest.raises(ValueError, match="Out of range"):
        codec.canonical({"p": float("nan")})


class _Orig(Exception):
    def __init__(self, sqlstate: str, constraint: str | None) -> None:
        super().__init__("boom")
        self.sqlstate = sqlstate
        self.constraint_name = constraint


@pytest.mark.parametrize(
    ("constraint", "rule", "field"),
    [
        ("ux_ws_name", "name_taken", "name"),
        ("ux_lay_name", "name_taken", "name"),
        ("ux_lay_slot", "hotkey_slot_taken", "hotkey_slot"),
        ("ux_ws_default", "concurrent_update", None),
        ("ux_lay_default", "concurrent_update", None),
    ],
)
def test_unique_violations_map_by_constraint_name(
    constraint: str, rule: str, field: str | None
) -> None:
    got = codec.map_integrity(IntegrityError("s", {}, _Orig("23505", constraint)))
    assert got is not None and (got.rule, got.field) == (rule, field)


def test_other_integrity_errors_are_not_mapped() -> None:
    assert codec.map_integrity(IntegrityError("s", {}, _Orig("23505", "ux_lp_slot"))) is None
    assert codec.map_integrity(IntegrityError("s", {}, _Orig("23503", "ux_ws_name"))) is None
    assert codec.map_integrity(IntegrityError("s", {}, _Orig("23505", None))) is None


def test_constraint_name_is_read_from_the_driver_exception_cause() -> None:
    class _Wrapper(Exception):
        sqlstate = "23505"

    wrapper = _Wrapper("dup")
    wrapper.__cause__ = _Orig("23505", "ux_lay_slot")
    got = codec.map_integrity(IntegrityError("s", {}, wrapper))
    assert got is not None and got.rule == "hotkey_slot_taken"


@pytest.mark.parametrize(("old", "new"), [(1, True), (1, 1.0), (True, 1), (0, False), (1.0, 1)])
def test_same_distinguishes_number_kinds_in_pane_config(old: object, new: object) -> None:
    def fields(n: object) -> LayoutFields:
        pane = PaneFields(0, "chart", None, None, None, (), {"settings": {"n": n}}, "auto")
        return _lay_fields(pane)

    assert codec.same_fields(fields(old), fields(old))
    assert not codec.same_fields(fields(old), fields(new))


def test_same_distinguishes_number_kinds_in_grid_spec_and_workspace_fields() -> None:
    def lay(v: object) -> LayoutFields:
        return LayoutFields("c", "custom", {"a": v}, True, False, False, None, False, ())

    assert not codec.same_fields(lay(1), lay(True)) and codec.same_fields(lay(1), lay(1))
    as_float: Any = 0.0  # a float where an int belongs: must not equal the int
    base = WorkspaceFields("n", False, "t", 0)
    assert not codec.same_fields(base, WorkspaceFields("n", False, "t", as_float))
    assert not codec.same_fields(base, WorkspaceFields("n", True, "t", 0))
