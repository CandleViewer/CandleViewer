"""Contract (E42-T07, contract slice): the statechart inspector read API. Three owner-only `GET`
operations (`admin:read`) keyed by the `machines.{entity}.state` entity grammar of E17-T08 and
answered from verified snapshots, `machine_events` and `cv_machine_*` metrics, never from a live
interpreter. The claims taken from `23-ws-protocol.md` §6.4 are pinned against that table, so the
three `..._ws_6_4` tests fail until E17-T08's contract (#2438) is on the base. Additive (C-6.3)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from candleviewer.statechart import Registry, export_stately, machine_hash
from candleviewer.statechart.schema import MACHINE_SCHEMA
from tests.contract._admin_support import (
    OWNER_ONLY,
    ROOT,
    SPEC,
    capability_rows,
    example_cases,
    grants,
    text,
    validate_example,
    x_rbac,
)

_PATHS: dict[str, Any] = SPEC["paths"]
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_KEY: str = SPEC["components"]["parameters"]["MachineKey"]["schema"]["pattern"]
_TESTS = ROOT / "services/api/tests"
_MATRIX = yaml.safe_load((_TESTS / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_PENDING = json.loads(
    (_TESTS / "unit/architecture/composition_allowlist.json").read_text(encoding="utf-8")
)["openapi_pending"]
_LIST, _DETAIL, _EXPORT = (
    "/admin/statecharts",
    "/admin/statecharts/{machineKey}",
    "/admin/statecharts/{machineKey}/export",
)
_OPS = {_LIST: {"200", "401", "403"}, _DETAIL: {"200", "401", "403", "404"}}
_OPS[_EXPORT] = _OPS[_DETAIL]
_EXAMPLES = example_cases([(path, "get") for path in _OPS])
_POLICY = {
    "strictConfig",
    "strict",
    "strictTargets",
    "actionErrorPolicy",
    "guardErrorPolicy",
    "spawnBlockingTimeout",
}
_UUID = "0a000000-0000-4000-8000-000000000001"
_REF = "#/components/schemas/"


def _text(path: str) -> str:
    return text(_PATHS[path]["get"]["description"])


def _ok(path: str) -> Any:
    return _PATHS[path]["get"]["responses"]["200"]["content"]["application/json"]


def _ws_6_4() -> tuple[dict[str, list[str]], str]:
    """`23-ws-protocol.md` §6.4: per-kind rows `B -> [entity, machine_kind, id format, scope,
    context_summary keys]` and the section text."""
    doc = (ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
    head = re.search(r"^### 6\.4 .*`machines\.\{entity\}\.state`.*$", doc, re.MULTILINE)
    assert head, "23-ws-protocol.md has no §6.4 `machines.{entity}.state` yet: merge #2438 first"
    section = doc[head.end() :].split("\n## ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 6 and re.fullmatch(r"B\d+(\u2013B\d+)?", cells[0]):
            rows[cells[0]] = cells[1:]
    return rows, text(section)


@pytest.mark.parametrize(("path", "codes"), list(_OPS.items()))
def test_operations_are_owner_reads_allow_listed_until_served(path: str, codes: set[str]) -> None:
    operation = _PATHS[path]["get"]
    assert operation["x-rbac"] == {"permissions": ["admin:read"], "scope": "none"}
    assert codes <= set(operation["responses"])
    row = _MATRIX["operations"][f"GET {path}"]
    assert (row["state"], row["outcomes"]) == ("not_mounted", OWNER_ONLY)
    assert _PENDING[f"GET {path}"]["ticket"] == "E42-T07"


def test_security_program_row_48c_is_owner_only_admin_read() -> None:
    cells = capability_rows()["48c"]
    operations = {"listStatecharts", "getStatechart", "exportStatechart"}
    assert grants(cells[1]) == ({"admin:read"}, operations)
    assert all(x_rbac(operation) == ["admin:read"] for operation in operations)
    assert cells[2:] == ["✔", "✖", "✖"]


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_example_validates_against_its_response_schema(
    case: str, pointer: str, value: Any
) -> None:
    validate_example(pointer, value)


def test_list_response_shape() -> None:
    page, part = _ok(_LIST)["schema"]["allOf"]
    assert page == {"$ref": f"{_REF}Page"}
    assert part["required"] == ["items", "kinds", "snapshots", "metrics"]
    assert part["properties"] == {
        "items": {"type": "array", "items": {"$ref": f"{_REF}StatechartMachine"}},
        "kinds": {"type": "array", "items": {"$ref": f"{_REF}StatechartKindSummary"}},
        "snapshots": {"$ref": f"{_REF}AdminSliceStatus"},
        "metrics": {"$ref": f"{_REF}AdminSliceStatus"},
    }


def test_schema_required_sets_and_environment() -> None:
    machine, kinds = _SCHEMAS["StatechartMachine"], _SCHEMAS["StatechartKindSummary"]
    assert set(machine["required"]) == set(machine["properties"])
    assert set(kinds["required"]) == set(kinds["properties"])
    assert {"lock_matches", "updated_at"} <= set(machine["required"])
    assert "dropped_receipts" not in machine["properties"]
    assert kinds["properties"]["dropped_receipts"]["type"] == ["integer", "null"]
    assert _SCHEMAS["StatechartMachineDetail"]["required"] == ["snapshots"]
    assert _SCHEMAS["StatechartExport"]["required"] == ["machine_kind", "machine_hash", "stately"]
    for schema in (machine, kinds):
        assert schema["properties"]["environment"] == {"$ref": f"{_REF}Environment"}
    scalars = _SCHEMAS["StatechartMachineDetail"]["properties"]["context_summary"]
    assert scalars["additionalProperties"] == {"type": ["string", "number", "boolean", "null"]}


def test_generated_models_mirror_the_new_schemas_and_examples_round_trip() -> None:
    for name in ("StatechartMachine", "StatechartKindSummary", "StatechartMachineDetail"):
        model: type[BaseModel] = getattr(api, name)
        assert set(model.model_fields) == set(_SCHEMAS[name]["properties"])
    for path, model in ((_DETAIL, api.StatechartMachineDetail), (_EXPORT, api.StatechartExport)):
        (example,) = [e["value"] for e in _ok(path)["examples"].values()]
        assert model.model_validate(example).model_dump(mode="json", exclude_unset=True) == example
    (listed,) = [e["value"] for e in _ok(_LIST)["examples"].values()]
    for row in listed["items"]:
        assert api.StatechartMachine.model_validate(row).model_dump(mode="json") == row
    for row in listed["kinds"]:
        assert api.StatechartKindSummary.model_validate(row).model_dump(mode="json") == row


def test_read_path_rules() -> None:
    listing, detail = _text(_LIST), _text(_DETAIL)
    assert "never holds, builds or queries an `Interpreter`" in listing
    assert "no instance is read" in _text(_EXPORT)
    assert "ordered by `machine_kind`, `machine_key`, then `environment`, ascending" in listing
    assert "singletons `kill_switch` and `live_gate` run once per environment" in listing
    assert {"$ref": "#/components/parameters/EnvironmentQuery"} in _PATHS[_LIST]["get"][
        "parameters"
    ]
    (environment,) = _PATHS[_DETAIL]["get"]["parameters"]
    assert (environment["name"], environment["required"]) == ("environment", True)
    seal = "HMAC envelope"
    assert seal in listing and seal in detail and "`persistence.open_sealed`, CV-C53" in detail
    assert "is shown. A snapshot that fails is left out of `items` and `kinds`" in listing
    assert "`snapshots` is `error` with the fixed reason" in listing


@pytest.mark.parametrize(
    ("key", "ok"),
    [
        ("kill_switch", True),
        (f"order:{_UUID}", True),
        ("book:BTCUSDT", True),
        (f"order:{_UUID.upper()}", False),
        (f"Order:{_UUID}", False),
        ("book:BTCUSD", False),
        ("book:B", False),
        ("order:", False),
        ("order:a:b", False),
        ("order/x", False),
    ],
)
def test_machine_key_follows_the_entity_grammar(key: str, ok: bool) -> None:
    assert bool(re.fullmatch(_KEY, key)) is ok


def test_machine_key_symbol_is_the_ws_13_symbol() -> None:
    ws = (ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
    symbol = re.search(r'"symbol": \{ "type": "string", "pattern": "\^([^"$]+)\$" \}', ws)
    assert symbol and _KEY.endswith(f"|{symbol[1]}))?$")


def test_export_is_the_chart_minus_exactly_the_six_policy_keys() -> None:
    """AC3: the export round-trips through the authoring `MACHINE_SCHEMA` minus the six CV policy
    keys; only those keys differ and `id`, `initial` and `states` are preserved."""
    authoring = copy.deepcopy(MACHINE_SCHEMA)
    authoring["required"] = [key for key in authoring["required"] if key not in _POLICY]
    authoring["properties"] = {k: v for k, v in authoring["properties"].items() if k not in _POLICY}
    validator = Draft202012Validator(authoring)
    registry = Registry()
    assert len(registry.keys()) == 20
    for kind in registry.keys():
        chart = registry.get(kind)
        stately = export_stately(chart)
        assert set(chart) - set(stately) == _POLICY
        assert stately == {key: value for key, value in chart.items() if key not in _POLICY}
        for key in ("id", "initial", "states"):
            assert stately.get(key) == chart.get(key)
        validator.validate(stately)
        body = {"machine_kind": kind, "machine_hash": machine_hash(chart), "stately": stately}
        assert api.StatechartExport.model_validate(body).model_dump(mode="json") == body
    named = _text(_EXPORT).split("removes exactly the six CV policy keys (", 1)[1].split(")")[0]
    assert set(re.findall(r"`(\w+)`", named)) == _POLICY


def test_machine_key_grammar_matches_ws_6_4() -> None:
    rows, _ = _ws_6_4()
    ids = {"uuid": _UUID, "symbol": "BTCUSDT"}
    for entity, _kind, id_format, _scope, _keys in rows.values():
        prefix = entity.strip("`").split(":", 1)[0]
        key = prefix if id_format == "singleton" else f"{prefix}:{ids[id_format]}"
        assert re.fullmatch(_KEY, key), key


def test_scope_and_public_id_claims_match_ws_6_4() -> None:
    rows, section = _ws_6_4()
    user_scoped = {row[1].strip("`") for row in rows.values() if row[3].startswith("its user")}
    assert user_scoped == {"alert", "replay", "session"}
    assert "`alert`, `replay` and `session` stay self-scoped for every role" in _text(_LIST)
    assert "Owner included" in section
    listed = {int(n) for b in rows for n in re.findall(r"\d+", b)}
    assert listed | set(range(4, 8)) | {8, 9, 13, 15} == set(range(1, 21))
    assert not listed & {8, 9, 13, 15}
    assert "B8, B9, B13 and B15 have none yet" in _text(_LIST)
    assert rows["B4\u2013B7"][1] == "`oco`, `iceberg`, `twap`, `chase`"
    assert "(`oco`, `iceberg`, `twap` or `chase`)" in _text(_EXPORT)


def test_context_summary_example_keys_are_allowed_by_ws_6_4() -> None:
    rows, _ = _ws_6_4()
    (example,) = [e["value"] for e in _ok(_DETAIL)["examples"].values()]
    kind = f"`{example['machine']['machine_kind']}`"
    (allowed,) = [row[4] for row in rows.values() if row[1] == kind]
    assert set(example["context_summary"]) <= set(re.findall(r"`(\w+)`", allowed))
