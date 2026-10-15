"""Contract (E42-T07, contract slice): the statechart inspector read API. Three owner-only
`GET` operations (`admin:read`), keyed by the `machines.{entity}.state` entity grammar of E17-T08,
answered from persisted snapshots, `machine_events` and the `cv_machine_*` metrics, never from a
live interpreter. The export carries every registered chart in its Stately projection with its
`machine_hash`. Additive only (C-6.3): new operations, one path parameter and new schemas."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.statechart import Registry, export_stately, machine_hash

_SPEC = load_openapi_spec()
_PATHS: dict[str, Any] = _SPEC["paths"]
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_KEY = _SPEC["components"]["parameters"]["MachineKey"]
_ROOT = Path(__file__).resolve().parents[4]
_MATRIX = yaml.safe_load(
    (_ROOT / "services/api/tests/contract/rbac/matrix.yaml").read_text(encoding="utf-8")
)["operations"]
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


@pytest.mark.parametrize(("path", "codes"), list(_OPS.items()))
def test_operations_are_owner_reads_with_documented_refusals(path: str, codes: set[str]) -> None:
    operation = _PATHS[path]["get"]
    assert set(_PATHS[path]) <= {"get", "parameters"}
    assert operation["x-rbac"] == {"permissions": ["admin:read"], "scope": "none"}
    assert set(operation["responses"]) == codes
    row = _MATRIX[f"GET {path}"]
    assert (row["state"], row["outcomes"]) == ("not_mounted", _OWNER_ONLY)


@pytest.mark.parametrize(
    ("key", "ok"),
    [
        ("kill_switch", True),
        ("order:0a000000-0000-4000-8000-000000000001", True),
        ("book:BTCUSDT", True),
        ("Order:0a000000", False),
        ("order:", False),
        ("order:a:b", False),
        ("order/x", False),
    ],
)
def test_machine_key_follows_the_entity_grammar(key: str, ok: bool) -> None:
    assert bool(re.fullmatch(_KEY["schema"]["pattern"], key)) is ok


def test_read_path_never_touches_a_live_interpreter() -> None:
    text = _PATHS["/admin/statecharts"]["get"]["description"]
    assert "never holds, builds or queries an `Interpreter`" in text
    export = _PATHS["/admin/statecharts/{machineKey}/export"]["get"]["description"]
    assert "no instance is read" in export


def test_self_scoped_kinds_stay_self_scoped_for_the_owner() -> None:
    text = _PATHS["/admin/statecharts"]["get"]["description"]
    assert "`alert`, `replay` and `session` stay self-scoped for every role" in text
    assert "omitted, never redacted" in text
    detail = _PATHS["/admin/statecharts/{machineKey}"]["get"]["description"]
    assert "same `404 not_found`" in detail


def test_list_reports_its_sources_with_the_slice_status_block() -> None:
    page = _PATHS["/admin/statecharts"]["get"]["responses"]["200"]["content"]["application/json"]
    extra = page["schema"]["allOf"][1]["properties"]
    slice_ref = {"$ref": "#/components/schemas/AdminSliceStatus"}
    assert extra["snapshots"] == slice_ref and extra["metrics"] == slice_ref
    detail = _SCHEMAS["StatechartMachineDetail"]
    assert detail["required"] == ["snapshots"]
    assert detail["properties"]["recent_events"]["maxItems"] == 50


def test_generated_models_mirror_the_new_schemas() -> None:
    for model, name in (
        (api.StatechartMachine, "StatechartMachine"),
        (api.StatechartMachineDetail, "StatechartMachineDetail"),
        (api.StatechartExport, "StatechartExport"),
    ):
        assert set(model.model_fields) == set(_SCHEMAS[name]["properties"])
    machine = _SCHEMAS["StatechartMachine"]
    assert machine["required"] == [
        "machine_key",
        "machine_kind",
        "environment",
        "state",
        "machine_hash",
        "chain_trips",
        "degraded",
    ]


@pytest.mark.parametrize("kind", Registry().keys())
def test_every_registered_chart_round_trips_through_the_export_shape(kind: str) -> None:
    chart = Registry().get(kind)
    body = {
        "machine_kind": kind,
        "machine_hash": machine_hash(chart),
        "stately": export_stately(chart),
    }
    model = api.StatechartExport.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert "strictConfig" not in model.stately
