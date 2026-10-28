"""E08-T09 (#4708) PR 1, the contract-first slice: `/scanner*` in `22-api-openapi.yaml` answering
E08-D08's gap ledger (D08-G1 to G10), with `21` section 3.8.7 and `24` section 15.5. It checks the
closed filter, the scan's additive changes, the criteria descriptor, the four preset operations
and their statuses, the pane kind and the docs that name the table and the audit actions. Nothing
serves these operations yet: every check reads the plan documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec

SPEC: dict[str, Any] = load_openapi_spec()
SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
PLAN = Path(__file__).resolve().parents[5] / "docs" / "plan"
_BASE, _S = "urn:cv:22-api-openapi", "/components/schemas/"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))

#: E08-D08 section 3.1, in its order; Regime is the one class set.
CRITERIA = [
    "price_change_pct_24h",
    "turnover_24h",
    "funding_rate",
    "oi_change_pct_24h",
    "spread_bps",
    "tape_speed_zscore",
    "range_pct_24h",
    "regime",
]
#: The `sort` enum and `ScannerRow` fields as published before this slice (C-6.3: additive only).
OLD_SORT = ["volume_24h", "price_change_pct_24h", "cvd", "tape_speed", "open_interest"]
OLD_SORT += ["liquidation_intensity"]
OLD_ROW = ["symbol", "last_price", "price_change_pct_24h", "volume_24h", "open_interest", "cvd"]
OLD_ROW += ["tape_speed", "liquidation_intensity", "recording", "coverage"]
OLD_PANE_KINDS = ["chart", "dom", "tape", "profile", "cvd", "oi", "deep_stats", "regime"]
OLD_PANE_KINDS += ["positions", "journal", "watchlist", "alerts"]
PRESET_INPUT_FIELDS = ["filter", "is_default", "name", "sort"]
SERVER_MANAGED = ("id", "version", "unavailable_criteria", "created_at", "updated_at")
WRITES = ("createScannerPreset", "updateScannerPreset", "deleteScannerPreset")
#: operationId -> every status it declares; there is no preset GET by id.
STATUSES = {
    "runScanner": {"200", "401", "403", "422", "429", "503"},
    "listScannerCriteria": {"200", "401", "403", "422", "503"},
    "listScannerPresets": {"200", "401", "403", "422", "503"},
    "createScannerPreset": {"201", "401", "403", "409", "413", "422", "503"},
    "updateScannerPreset": {"200", "401", "403", "404", "409", "413", "422", "503"},
    "deleteScannerPreset": {"204", "401", "403", "404", "422", "503"},
}
RBAC = {
    "runScanner": {"permissions": ["marketdata:read"], "scope": "none"},
    "listScannerCriteria": {"permissions": ["marketdata:read"], "scope": "none"},
    "listScannerPresets": {"permissions": ["marketdata:read"], "scope": "self"},
    **{op: {"permissions": ["workspaces:write"], "scope": "self"} for op in WRITES},
}


def _errors(pointer: str, doc: Any) -> list[str]:
    """The messages `doc` fails with against the schema at `pointer` in the contract."""
    ref, checker = {"$ref": f"{_BASE}#{pointer}"}, Draft202012Validator.FORMAT_CHECKER
    validator = Draft202012Validator(ref, registry=_REGISTRY, format_checker=checker)
    return sorted(e.message for e in validator.iter_errors(doc))


def _operations() -> dict[str, dict[str, Any]]:
    return {
        op["operationId"]: op
        for path, item in SPEC["paths"].items() if path.startswith("/scanner")
        for method, op in item.items() if method in ("get", "put", "post", "delete", "patch")
    }  # fmt: skip


def _param(op: str, name: str) -> dict[str, Any]:
    (param,) = [p for p in _operations()[op]["parameters"] if p.get("name") == name]
    return dict(param)


def _example() -> dict[str, Any]:
    body = SPEC["paths"]["/scanner/presets"]["post"]["requestBody"]["content"]
    (example,) = body["application/json"]["examples"].values()
    return dict(example["value"])


def _prose(description: str) -> str:
    return " ".join(description.split())


def test_the_six_operations_are_the_whole_scanner_surface() -> None:
    assert sorted(_operations()) == sorted(STATUSES)
    assert "get" not in SPEC["paths"]["/scanner/presets/{presetId}"]


@pytest.mark.parametrize(("op", "statuses"), sorted(STATUSES.items()))
def test_each_operation_declares_exactly_its_statuses(op: str, statuses: set[str]) -> None:
    assert set(_operations()[op]["responses"]) == statuses


@pytest.mark.parametrize(("op", "rbac"), sorted(RBAC.items()))
def test_each_operation_declares_its_permission_and_scope(op: str, rbac: dict[str, Any]) -> None:
    assert _operations()[op]["x-rbac"] == rbac


@pytest.mark.parametrize("op", WRITES)
def test_every_preset_write_takes_the_csrf_token(op: str) -> None:
    assert {"$ref": "#/components/parameters/CsrfToken"} in _operations()[op]["parameters"]


def test_filter_is_closed_over_the_eight_d08_criteria_in_order() -> None:
    schema = SCHEMAS["ScannerFilter"]
    assert (schema["additionalProperties"], list(schema["properties"])) == (False, CRITERIA)
    refs = {k: v["$ref"].rsplit("/", 1)[1] for k, v in schema["properties"].items()}
    assert refs == dict.fromkeys(CRITERIA[:-1], "ScannerRange") | {"regime": "ScannerClassSet"}


@pytest.mark.parametrize(
    "doc",
    [
        {},
        {"funding_rate": {"min": "-0.0001", "max": "0.0005"}},
        {"turnover_24h": {"min": "50000000"}, "regime": {"classes": ["trend_up", "range"]}},
    ],
)
def test_filter_accepts_decimal_bounds_and_a_class_set(doc: dict[str, Any]) -> None:
    assert _errors(f"{_S}ScannerFilter", doc) == []


@pytest.mark.parametrize(
    "doc",
    [
        {"volatility": {"min": "1"}},  # not a criterion (D08 section 3.2: 24 h range %)
        {"funding_rate": {}},  # range_empty
        {"funding_rate": {"min": 1}},  # a bound is a decimal string (C6)
        {"funding_rate": {"min": "1e-3"}},
        {"funding_rate": {"min": "1", "step": "2"}},
        {"regime": {"classes": []}},  # classes_empty
        {"regime": {"classes": ["Trend Up"]}},
        {"regime": {"classes": ["range", "range"]}},
    ],
)
def test_filter_refuses_what_the_schema_can_see(doc: dict[str, Any]) -> None:
    assert _errors(f"{_S}ScannerFilter", doc) != []


def test_scan_states_the_422_rules_and_the_strict_range() -> None:
    text = _prose(_operations()["runScanner"]["description"])
    for rule in ("invalid_json", "unknown_criterion", "range_empty", "invalid_decimal"):
        assert f"`{rule}`" in text
    assert "`range_inverted` (`min` greater than or equal to `max`" in text  # D08-G6
    assert "`filters.<criterion id>`" in text


def test_scan_is_capped_at_200_and_not_paged() -> None:
    limit = _param("runScanner", "limit")["schema"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 200, 100)
    meta = SCHEMAS["ScannerMeta"]["allOf"]
    assert meta[0] == {"$ref": f"#{_S}DataMeta"}
    assert sorted(meta[1]["required"]) == ["capped", "inputs"]
    ok = _operations()["runScanner"]["responses"]["200"]["content"]["application/json"]
    assert ok["schema"]["properties"]["meta"] == {"$ref": f"#{_S}ScannerMeta"}
    text = _prose(_operations()["runScanner"]["description"])
    assert "`meta.next_cursor` is always `null`" in text


def test_scan_bounds_cache_cold_evaluations_and_refuses_beyond_them() -> None:
    text = _prose(_operations()["runScanner"]["description"])
    assert "share one evaluation (single-flight)" in text
    assert "refused at once with `429 rate_limited` and `Retry-After`, never queued" in text


def test_preset_unique_violations_map_to_409_not_500() -> None:
    schema = (PLAN / "21-database-schema.md").read_text(encoding="utf-8")
    table = schema[schema.index("#### 3.8.7 `scanner_presets`") :]
    table = " ".join(table[: table.index("### 3.9 ")].split())
    assert "`ux_sp_name` maps to `409` rule `name_taken`" in table
    assert "Postgres `lower()`" in table


def test_input_freshness_names_each_input() -> None:
    item = SCHEMAS["ScannerInputFreshness"]
    assert sorted(item["required"]) == ["as_of", "input", "stale"]
    assert item["properties"]["input"]["enum"] == ["tickers", "open_interest", "orderflow_metrics"]


def test_sort_keeps_its_values_and_default_and_adds_every_range_criterion() -> None:
    assert _param("runScanner", "sort")["schema"] == {"$ref": f"#{_S}ScannerSortKey"}
    key = SCHEMAS["ScannerSortKey"]
    assert key["enum"][: len(OLD_SORT)] == OLD_SORT and key["default"] == "volume_24h"
    assert set(CRITERIA[:-1]) <= set(key["enum"]) and "regime" not in key["enum"]


def test_row_keeps_its_fields_and_adds_one_per_criterion() -> None:
    row = SCHEMAS["ScannerRow"]
    assert row["required"] == ["symbol", "coverage"]
    assert list(row["properties"])[: len(OLD_ROW)] == OLD_ROW
    assert set(CRITERIA) <= set(row["properties"])
    assert {"price_path_24h", "skipped_criteria"} <= set(row["properties"])
    assert row["properties"]["price_path_24h"]["maxItems"] == 24


def test_criterion_descriptor_carries_what_the_client_badges_and_skips() -> None:
    schema = SCHEMAS["ScannerCriterion"]
    needed = ["id", "label", "kind", "unit", "estimated", "needs_recording", "sortable"]
    assert sorted(schema["required"]) == sorted([*needed, "available"])
    assert "classes" in schema["properties"]


def test_a_criterion_with_no_source_is_declared_and_refused_not_skipped() -> None:
    # Orchestrator ruling (2026-10-28): no source yet means `available: false`, never a skip.
    assert SCHEMAS["ScannerCriterion"]["properties"]["available"]["type"] == "boolean"
    text = _prose(_operations()["runScanner"]["description"])
    assert "`criterion_unavailable`" in text
    assert "`available: false`" in _prose(
        SCHEMAS["ScannerPreset"]["properties"]["unavailable_criteria"]["description"]
    )


def test_every_sort_key_declares_its_availability_and_preset_writes_refuse_one() -> None:
    ok = _operations()["listScannerCriteria"]["responses"]["200"]
    body = ok["content"]["application/json"]["schema"]
    assert body["required"] == ["items", "sort_keys"]
    assert body["properties"]["sort_keys"]["items"] == {"$ref": f"#{_S}ScannerSortKeyStatus"}
    status = SCHEMAS["ScannerSortKeyStatus"]
    assert (sorted(status["required"]), status["properties"]["available"]["type"]) == (
        ["available", "id"],
        "boolean",
    )
    create = _prose(_operations()["createScannerPreset"]["description"])
    assert "`criterion_unavailable` on `filter.<criterion id>` or `sort`" in create


def test_preset_input_is_closed_with_name_1_to_80() -> None:
    schema = SCHEMAS["ScannerPresetInput"]
    props = schema["properties"]
    assert (schema["additionalProperties"], sorted(props)) == (False, PRESET_INPUT_FIELDS)
    assert schema["required"] == ["name", "filter"]
    assert (props["name"]["minLength"], props["name"]["maxLength"]) == (1, 80)
    assert props["filter"] == {"$ref": f"#{_S}ScannerFilter"}
    assert _errors(f"{_S}ScannerPresetInput", _example()) == []


@pytest.mark.parametrize("field", [*SERVER_MANAGED, "results", "items", "user_id"])
def test_preset_input_refuses_a_server_managed_field_or_results(field: str) -> None:
    assert _errors(f"{_S}ScannerPresetInput", _example() | {field: []}) != []


def test_preset_response_reports_unavailable_criteria_and_never_results() -> None:
    schema = SCHEMAS["ScannerPreset"]
    fields = [*PRESET_INPUT_FIELDS, *SERVER_MANAGED]
    assert sorted(schema["required"]) == sorted(schema["properties"]) == sorted(fields)
    assert "additionalProperties" not in schema  # readers: C-6.3


def test_refusal_order_checks_the_body_before_the_owner_scoped_lookup() -> None:
    text = _prose(_operations()["updateScannerPreset"]["description"])
    order = text[text.index("Evaluation order for `/scanner/presets*`") :]
    steps = ["`401`", "`403` (permission", "`413`", "`422` (path, query, body", "`404` (missing"]
    positions = [order.index(step) for step in [*steps, "`409`", "the write"]]
    assert positions == sorted(positions)  # so a foreign id is answered as a missing one is


def test_pane_kind_adds_scanner_after_the_published_kinds() -> None:
    assert SCHEMAS["PaneKind"]["enum"] == [*OLD_PANE_KINDS, "scanner"]


def test_the_table_and_the_audit_actions_are_documented() -> None:
    schema = (PLAN / "21-database-schema.md").read_text(encoding="utf-8")
    table = schema[schema.index("#### 3.8.7 `scanner_presets`") :]
    for fragment in ("user_id     uuid NOT NULL", "filter      jsonb NOT NULL", "version"):
        assert fragment in table
    assert "CREATE UNIQUE INDEX ux_sp_name    ON scanner_presets (user_id, lower(name));" in table
    assert "| `scanner_presets`  " in schema  # the C-5.9 classification row
    internal = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    for action in ("created", "updated", "deleted"):
        assert f"`scanner_preset.{action}`," in closed  # registered by PR 2a (audit/actions.py)
        assert f"`scanner_preset.{action}` (not registered yet" not in closed
