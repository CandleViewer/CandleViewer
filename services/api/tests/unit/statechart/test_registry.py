"""Unit tests for `candleviewer.statechart.registry` (E50-T01).

Covers the ticket's three Gherkin acceptance criteria plus the loader
surface (`Registry`, `hash`, `export_stately`) and a schema-negative case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.statechart import (
    DuplicateMachineKeyError,
    MachineNotFoundError,
    MachineSchemaError,
    Registry,
    UnknownKeyError,
    UnresolvedTargetError,
    export_stately,
    machine_hash,
    validate,
)
from candleviewer.statechart.registry import default_registry

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        (_FIXTURES / f"{name}.machine.json").read_text(encoding="utf-8")
    )
    return result


def test_valid_min_passes_validate() -> None:
    validate(_load("valid_min"))  # no raise


def test_unknown_key_anywhere_is_rejected_including_inline_invoke_src() -> None:
    """Acceptance criterion 1: unknown key inside a nested `invoke.src`."""
    chart = _load("bad_nested_key")
    with pytest.raises(UnknownKeyError) as exc:
        validate(chart)
    message = str(exc.value)
    assert "bad_nested_key" in message
    assert "entryy" in message
    assert "invoke" in message  # path names the invoke.src descent


def test_relative_target_is_rejected_before_create_machine() -> None:
    """Acceptance criterion 2 (first case): a relative '.child' target."""
    chart = _load("bad_relative_target")
    with pytest.raises(UnresolvedTargetError) as exc:
        validate(chart)
    assert ".child" in str(exc.value)


def test_unknown_absolute_target_is_rejected() -> None:
    """Acceptance criterion 2 (second case): '#b01.nope' resolves nowhere."""
    chart = _load("bad_unknown_target")
    with pytest.raises(UnresolvedTargetError) as exc:
        validate(chart)
    assert "#b01.nope" in str(exc.value)


def test_missing_mandatory_policy_keys_fail_schema_validation() -> None:
    chart = _load("bad_missing_policy")
    with pytest.raises(MachineSchemaError):
        validate(chart)


def test_machine_hash_is_stable_under_key_reordering() -> None:
    """Acceptance criterion 3: same chart, keys reordered -> same sha256."""
    chart = _load("valid_min")
    reordered = json.loads(json.dumps(dict(reversed(list(chart.items())))))
    reordered["states"] = dict(reversed(list(chart["states"].items())))
    assert machine_hash(chart) == machine_hash(reordered)


def test_machine_hash_changes_when_content_changes() -> None:
    chart = _load("valid_min")
    mutated = json.loads(json.dumps(chart))
    mutated["maxIterations"] = 51
    assert machine_hash(chart) != machine_hash(mutated)


def test_export_stately_strips_cv_policy_keys_but_keeps_shape() -> None:
    chart = _load("valid_min")
    stately = export_stately(chart)
    assert "strictConfig" not in stately
    assert "strict" not in stately
    assert "strictTargets" not in stately
    assert stately["id"] == "valid_min"
    assert set(stately["states"]) == set(chart["states"])


def test_export_stately_round_trips_states_recursively() -> None:
    chart = _load("bad_nested_key")  # has a nested invoke.src machine
    stately = export_stately(chart)
    inline = stately["states"]["working"]["invoke"]["src"]
    assert "strict" not in inline
    assert set(inline["states"]) == {"a", "b"}


def test_default_registry_is_one_registry_over_the_committed_charts() -> None:
    assert default_registry() is default_registry()
    assert default_registry().keys() == Registry().keys()


class TestRegistryLoader:
    def test_registry_loads_machines_dir_and_lists_keys(self, tmp_path: Path) -> None:
        machines_dir = tmp_path / "machines"
        machines_dir.mkdir()
        (machines_dir / "b01.valid_min.machine.json").write_text(
            json.dumps(_load("valid_min")), encoding="utf-8"
        )
        registry = Registry(machines_dir)
        assert registry.keys() == ["valid_min"]
        assert registry.get("valid_min")["id"] == "valid_min"

    def test_registry_rejects_bad_chart_at_construction_time(self, tmp_path: Path) -> None:
        machines_dir = tmp_path / "machines"
        machines_dir.mkdir()
        (machines_dir / "bad.machine.json").write_text(
            json.dumps(_load("bad_relative_target")), encoding="utf-8"
        )
        with pytest.raises(UnresolvedTargetError):
            Registry(machines_dir)

    def test_registry_unknown_key_raises_machine_not_found(self, tmp_path: Path) -> None:
        machines_dir = tmp_path / "machines"
        machines_dir.mkdir()
        registry = Registry(machines_dir)
        with pytest.raises(MachineNotFoundError):
            registry.get("nope")

    def test_registry_missing_machines_dir_is_empty(self, tmp_path: Path) -> None:
        registry = Registry(tmp_path / "does_not_exist")
        assert registry.keys() == []

    def test_registry_hash_and_export_stately_delegate(self, tmp_path: Path) -> None:
        machines_dir = tmp_path / "machines"
        machines_dir.mkdir()
        (machines_dir / "b01.valid_min.machine.json").write_text(
            json.dumps(_load("valid_min")), encoding="utf-8"
        )
        registry = Registry(machines_dir)
        assert registry.hash("valid_min") == machine_hash(_load("valid_min"))
        assert registry.export_stately("valid_min") == export_stately(_load("valid_min"))

    def test_registry_rejects_duplicate_machine_ids(self, tmp_path: Path) -> None:
        machines_dir = tmp_path / "machines"
        machines_dir.mkdir()
        chart = _load("valid_min")
        (machines_dir / "a.machine.json").write_text(json.dumps(chart), encoding="utf-8")
        (machines_dir / "b.machine.json").write_text(json.dumps(chart), encoding="utf-8")
        with pytest.raises(DuplicateMachineKeyError):
            Registry(machines_dir)
