"""Unit tests for the workspace request model (E15-T01 S2a)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.api import workspaces_models as wm
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.workspaces_models import WorkspaceIn

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "candleviewer/migrations/versions/0022_workspaces.py"
)


def errs(model: Any, body: dict[str, Any]) -> list[dict[str, str]]:
    with pytest.raises(ValidationError) as ei:
        model.model_validate(body)
    return format_errors(ei.value)


def rules(model: Any, body: dict[str, Any]) -> set[tuple[str, str]]:
    return {(e["field"], e["rule"]) for e in errs(model, body)}


# --- enums == DDL CHECK lists ---------------------------------------------------------------
def _ddl() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _check_list(ddl: str, name: str) -> tuple[str, ...]:
    m = re.search(rf"CONSTRAINT {name}\s+CHECK \(\w+ IN \(([^)]*)\)", ddl)
    assert m, name
    return tuple(re.findall(r"'([^']+)'", m.group(1)))


@pytest.mark.parametrize(
    ("check", "values"),
    [("lp_kind", wm.PANE_KINDS), ("lp_scale", wm.SCALE_MODES), ("lay_preset", wm.GRID_PRESETS)],
)
def test_enum_equals_db_check_list(check: str, values: tuple[str, ...]) -> None:
    assert _check_list(_ddl(), check) == values


def test_slot_and_hotkey_bounds_equal_db_checks() -> None:
    ddl = _ddl()
    assert "slot_index BETWEEN 0 AND 15" in ddl
    assert "hotkey_slot BETWEEN 1 AND 9" in ddl


# --- names ----------------------------------------------------------------------------------
def test_name_is_sanitised_then_trimmed() -> None:
    assert WorkspaceIn.model_validate({"name": " ‮Sca\x00lp "}).name == "Scalp"


def test_name_empty_after_sanitise_is_string_too_short() -> None:
    got = errs(WorkspaceIn, {"name": " \x00 "})
    assert got[0]["rule"] == "string_too_short"


def test_name_raw_length_over_40_with_control_char_is_string_too_long() -> None:
    assert ("name", "string_too_long") in rules(WorkspaceIn, {"name": "a" * 40 + "\x00"})


def test_name_exactly_40_is_accepted() -> None:
    assert len(WorkspaceIn.model_validate({"name": "a" * 40}).name) == 40


def test_name_lone_surrogate_is_invalid_unicode() -> None:
    assert ("name", "invalid_unicode") in rules(WorkspaceIn, {"name": "\ud800"})


def test_workspace_defaults_and_db_values_keys() -> None:
    v = WorkspaceIn.model_validate({"name": "A"}).db_values()
    assert v == {
        "name": "A", "is_default": False, "icon_token": "workspace.default", "sort_order": 0,
    }  # fmt: skip


@pytest.mark.parametrize("key", ["is_default", "icon_token", "sort_order"])
def test_workspace_explicit_null_is_rejected(key: str) -> None:
    assert (key, "null_not_allowed") in rules(WorkspaceIn, {"name": "A", key: None})


@pytest.mark.parametrize(
    "extra", [{"icon_token": "https://x"}, {"sort_order": 32768}, {"sort_order": -1}, {"x": 1}]
)
def test_workspace_bad_fields_rejected(extra: dict[str, Any]) -> None:
    errs(WorkspaceIn, {"name": "A", **extra})


def test_non_string_name_is_a_type_error_not_a_crash() -> None:
    assert errs(WorkspaceIn, {"name": 5})
