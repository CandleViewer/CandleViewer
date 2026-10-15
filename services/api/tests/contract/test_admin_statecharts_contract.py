"""Contract (E42-T07, contract slice): the statechart inspector read API. Three owner-only
`GET` operations (`admin:read`), keyed by the `machines.{entity}.state` entity grammar of E17-T08,
answered from persisted snapshots, `machine_events` and the `cv_machine_*` metrics, never from a
live interpreter. The export carries every registered chart in its Stately projection with its
`machine_hash`. Additive only (C-6.3): new operations, one path parameter and new schemas; the
operations are allow-listed as contract-first until the route slice serves them."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.statechart import Registry, export_stately, machine_hash

_SPEC = load_openapi_spec()
_PATHS: dict[str, Any] = _SPEC["paths"]
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_KEY = _SPEC["components"]["parameters"]["MachineKey"]
_TESTS = Path(__file__).resolve().parents[1]
_MATRIX = yaml.safe_load((_TESTS / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_PENDING = json.loads(
    (_TESTS / "unit/architecture/composition_allowlist.json").read_text(encoding="utf-8")
)["openapi_pending"]
_OPS = {
    "/admin/statecharts": {"200", "401", "403"},
    "/admin/statecharts/{machineKey}": {"200", "401", "403", "404"},
    "/admin/statecharts/{machineKey}/export": {"200", "401", "403", "404"},
}
_OWNER_ONLY = {
    "owner": "allow",
    "manager_with_grant": "403",
    "manager_without_grant": "403",
    "viewer": "403",
    "unauthenticated": "401",
}


def _text(path: str) -> str:
    return " ".join(_PATHS[path]["get"]["description"].split())


def _example(path: str) -> dict[str, Any]:
    content = _PATHS[path]["get"]["responses"]["200"]["content"]["application/json"]
    value: dict[str, Any] = next(iter(content["examples"].values()))["value"]
    return value


@pytest.mark.parametrize(("path", "codes"), list(_OPS.items()))
def test_operations_are_owner_reads_allow_listed_until_served(path: str, codes: set[str]) -> None:
    operation = _PATHS[path]["get"]
    assert operation["x-rbac"] == {"permissions": ["admin:read"], "scope": "none"}
    assert codes <= set(operation["responses"])
    row = _MATRIX["operations"][f"GET {path}"]
    assert (row["state"], row["outcomes"]) == ("not_mounted", _OWNER_ONLY)
    assert _PENDING[f"GET {path}"]["ticket"] == "E42-T07"


@pytest.mark.parametrize(
    ("key", "ok"),
    [
        ("kill_switch", True),
        ("order:0a000000-0000-4000-8000-000000000001", True),
        ("book:BTCUSDT", True),
        ("order:0A000000-0000-4000-8000-000000000001", False),
        ("Order:0a000000-0000-4000-8000-000000000001", False),
        ("order:", False),
        ("order:a:b", False),
        ("order/x", False),
    ],
)
def test_machine_key_follows_the_entity_grammar(key: str, ok: bool) -> None:
    assert bool(re.fullmatch(_KEY["schema"]["pattern"], key)) is ok


def test_read_path_never_touches_a_live_interpreter() -> None:
    assert "never holds, builds or queries an `Interpreter`" in _text("/admin/statecharts")
    assert "no instance is read" in _text("/admin/statecharts/{machineKey}/export")


def test_export_refuses_algo_keys_and_names_the_bare_kinds() -> None:
    text = _text("/admin/statecharts/{machineKey}/export")
    assert "An `algo:{id}` key is `404 not_found`" in text
    assert "(`oco`, `iceberg`, `twap` or `chase`)" in text


def test_self_scoped_kinds_stay_self_scoped_for_the_owner() -> None:
    text = _text("/admin/statecharts")
    assert "`alert`, `replay` and `session` stay self-scoped for every role" in text
    assert "same `404 not_found`" in _text("/admin/statecharts/{machineKey}")


def test_counters_are_required_and_nullable() -> None:
    machine = _SCHEMAS["StatechartMachine"]
    assert {"deferred_depth", "dropped_receipts", "chain_trips", "machine_hash"} <= set(
        machine["required"]
    )
    for name in ("deferred_depth", "dropped_receipts"):
        assert machine["properties"][name]["type"] == ["integer", "null"]


@pytest.mark.parametrize(
    ("path", "model"),
    [
        ("/admin/statecharts/{machineKey}", api.StatechartMachineDetail),
        ("/admin/statecharts/{machineKey}/export", api.StatechartExport),
    ],
)
def test_examples_round_trip_through_the_generated_models(
    path: str, model: type[BaseModel]
) -> None:
    example = _example(path)
    assert model.model_validate(example).model_dump(mode="json", exclude_unset=True) == example


def test_list_example_rows_are_valid_machines() -> None:
    example = _example("/admin/statecharts")
    for row in example["items"]:
        assert api.StatechartMachine.model_validate(row).model_dump(mode="json") == row
    assert example["metrics"]["status"] == "error"


def test_generated_models_mirror_the_new_schemas() -> None:
    for model, name in (
        (api.StatechartMachine, "StatechartMachine"),
        (api.StatechartMachineDetail, "StatechartMachineDetail"),
        (api.StatechartExport, "StatechartExport"),
    ):
        assert set(model.model_fields) == set(_SCHEMAS[name]["properties"])


def test_every_registered_chart_round_trips_through_the_export_shape() -> None:
    registry = Registry()
    assert len(registry.keys()) == 20
    for kind in registry.keys():
        chart = registry.get(kind)
        body = {
            "machine_kind": kind,
            "machine_hash": machine_hash(chart),
            "stately": export_stately(chart),
        }
        assert api.StatechartExport.model_validate(body).model_dump(mode="json") == body
