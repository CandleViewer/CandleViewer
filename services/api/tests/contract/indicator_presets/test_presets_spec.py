"""E13-T03 (#427) contract-first slice: `/indicator-presets*` in `22-api-openapi.yaml`, with the
limits of the E13 threat model (`docs/security/threat-models/E13-indicators.md`: section 3, IR-08,
SR-E13-06 to SR-E13-08) and main-orchestrator's rulings as the #427 comment of 2026-10-20 records
them (Q1: `style` takes only `{}` until E13-D04; Q3: no GET by id; Q4: `is_favourite` only). It
checks the closed input and its limits, the standalone response, the four operations and their
statuses, and the bundle. Nothing serves them yet: every check reads 22."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.orderflow.indicators.catalogue import default_catalogue, validate_params

SPEC: dict[str, Any] = load_openapi_spec()
SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_BASE, _S = "urn:cv:22-api-openapi", "/components/schemas/"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))
INPUT, STYLE = f"{_S}IndicatorPresetInput", f"{_S}IndicatorPresetStyle"

# The limits the implementation PR enforces, from the threat model (section 3: name 80, 500 live
# presets per user, bundle import 200 presets; IR-08: the code pattern and 32; SR-E13-06: 64 keys),
# as literals: the constants module that holds them lands with that PR.
NAME_MAX = 80
CODE_MAX = 32
CODE_PATTERN = "^[a-z0-9_]{2,32}$"
KEYS_MAX = 64
PRESETS_PER_USER_MAX = 500
BUNDLE_IMPORT_PRESETS_MAX = 200

INPUT_FIELDS = ["indicator_code", "is_favourite", "name", "pane_target", "params", "style"]
SERVER_MANAGED = ("id", "owner_user_id", "is_builtin", "created_at", "updated_at", "deleted_at")
#: operationId -> every status it declares; there is no GET by id (ruling Q3).
STATUSES = {
    "listIndicatorPresets": {"200", "401", "403", "404", "422", "503"},
    "createIndicatorPreset": {"201", "401", "403", "404", "409", "413", "422", "503"},
    "updateIndicatorPreset": {"200", "401", "403", "404", "409", "413", "422", "503"},
    "deleteIndicatorPreset": {"204", "401", "403", "404", "422", "503"},
}


def _errors(pointer: str, doc: Any) -> list[str]:
    """The messages `doc` fails with against the schema at `pointer` in the contract."""
    ref, checker = {"$ref": f"{_BASE}#{pointer}"}, Draft202012Validator.FORMAT_CHECKER
    validator = Draft202012Validator(ref, registry=_REGISTRY, format_checker=checker)
    return sorted(e.message for e in validator.iter_errors(doc))


def _operations() -> dict[str, dict[str, Any]]:
    return {
        op["operationId"]: op
        for path, item in SPEC["paths"].items() if path.startswith("/indicator-presets")
        for method, op in item.items() if method in ("get", "put", "post", "delete", "patch")
    }  # fmt: skip


def _example() -> dict[str, Any]:
    body = SPEC["paths"]["/indicator-presets"]["post"]["requestBody"]["content"]
    (example,) = body["application/json"]["examples"].values()
    return dict(example["value"])


def _prose(description: str) -> str:
    """A description with its line breaks and runs of spaces folded to single spaces."""
    return " ".join(description.split())


def test_create_example_is_a_valid_v1_preset_input() -> None:
    example = _example()
    definition = default_catalogue().get(example["indicator_code"])
    assert definition is not None
    assert _errors(INPUT, example) == []
    assert validate_params(definition, example["params"]) == example["params"]  # all, canonical
    assert {"price": "overlay", "sub": "subpane"}.get(definition.pane) == example["pane_target"]


def test_preset_input_is_closed_with_the_implementation_limits() -> None:
    schema = SCHEMAS["IndicatorPresetInput"]
    props = schema["properties"]
    assert (schema["additionalProperties"], sorted(props)) == (False, INPUT_FIELDS)
    assert schema["required"] == ["name", "indicator_code", "params"]
    assert (props["name"]["minLength"], props["name"]["maxLength"]) == (1, NAME_MAX)
    code = props["indicator_code"]
    assert (code["maxLength"], code["pattern"]) == (CODE_MAX, CODE_PATTERN)
    assert props["params"]["maxProperties"] == KEYS_MAX
    assert (props["is_favourite"]["type"], props["is_favourite"]["default"]) == ("boolean", False)


@pytest.mark.parametrize("field", [*SERVER_MANAGED, "is_default", "compute"])
def test_preset_input_refuses_a_server_managed_or_unknown_field(field: str) -> None:
    assert _errors(INPUT, _example() | {field: None}) != []


@pytest.mark.parametrize("code", ["ema", "a1", "x" * CODE_MAX])
def test_indicator_code_pattern_accepts_a_registry_shaped_id(code: str) -> None:
    assert _errors(INPUT, _example() | {"indicator_code": code}) == []


@pytest.mark.parametrize("code", ["a", "x" * (CODE_MAX + 1), "ATR", "../x", "ema;drop", ""])
def test_indicator_code_pattern_refuses_anything_else(code: str) -> None:
    assert _errors(INPUT, _example() | {"indicator_code": code}) != []


def test_every_catalogue_indicator_id_fits_the_preset_indicator_code() -> None:
    ids = [definition.id for definition in default_catalogue()]
    assert ids and all(_errors(f"{INPUT}/properties/indicator_code", i) == [] for i in ids)


def test_pane_target_is_overlay_or_subpane_defaulting_to_overlay() -> None:
    pane = SCHEMAS["IndicatorPresetInput"]["properties"]["pane_target"]
    assert (pane["enum"], pane["default"]) == (["overlay", "subpane"], "overlay")
    assert SCHEMAS["IndicatorPreset"]["properties"]["pane_target"]["enum"] == pane["enum"]
    assert _errors(INPUT, _example() | {"pane_target": "main"}) != []


def test_style_schema_is_closed_with_at_most_64_keys() -> None:
    schema = SCHEMAS["IndicatorPresetStyle"]
    assert (schema["additionalProperties"], schema["maxProperties"]) == (False, KEYS_MAX)


def test_style_is_optional_and_empty_object_is_valid() -> None:
    field = SCHEMAS["IndicatorPresetInput"]["properties"]["style"]
    assert field["allOf"] == [{"$ref": f"#{STYLE}"}]  # optional: omitted means `{}`
    assert _errors(INPUT, {k: v for k, v in _example().items() if k != "style"}) == []
    assert _errors(INPUT, _example() | {"style": {}}) == []


@pytest.mark.parametrize(
    "style",
    [{"line": "#ff0000"}, {"line": "url(javascript:1)"}, {"__proto__": {"x": 1}}, {"w": 1e308}],
)
def test_style_refuses_every_key_until_e13_d04(style: dict[str, Any]) -> None:
    assert _errors(INPUT, _example() | {"style": style}) != []


def test_preset_response_is_a_standalone_open_object_requiring_every_field() -> None:
    schema = SCHEMAS["IndicatorPreset"]
    props = schema["properties"]
    assert "allOf" not in schema and "additionalProperties" not in schema  # readers: C-6.3
    stored = [f for f in SERVER_MANAGED if f != "deleted_at"]  # deleted rows are never served
    assert sorted(schema["required"]) == sorted(props) == sorted([*INPUT_FIELDS, *stored])
    assert (props["is_builtin"]["readOnly"], props["style"]) == (True, {"$ref": f"#{STYLE}"})
    server = {"id": "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c", "is_builtin": True}
    stamps = dict.fromkeys(("created_at", "updated_at"), "2026-10-20T12:00:00.000000Z")
    builtin = _example() | server | stamps | {"owner_user_id": None}
    assert _errors(f"{_S}IndicatorPreset", builtin) == []


def test_the_four_operations_are_the_whole_surface_with_no_read_by_id() -> None:
    assert sorted(_operations()) == sorted(STATUSES)
    assert "get" not in SPEC["paths"]["/indicator-presets/{presetId}"]


@pytest.mark.parametrize(("op", "statuses"), sorted(STATUSES.items()))
def test_each_operation_declares_exactly_its_statuses(op: str, statuses: set[str]) -> None:
    assert set(_operations()[op]["responses"]) == statuses


def test_refusal_order_checks_the_body_before_the_owner_scoped_lookup() -> None:
    text = _prose(_operations()["updateIndicatorPreset"]["description"])
    order = text[text.index("Evaluation order for `/indicator-presets*`") :]
    steps = ["`401`", "`403` (permission", "`413`", "`422` (path, query, body", "`404` (missing"]
    steps += ["`builtin_immutable`", "`immutable_field`", "`409`", "the write"]
    positions = [order.index(step) for step in steps]
    assert positions == sorted(positions)  # so a foreign id is answered as a missing one is


def test_copying_a_builtin_is_conditional_on_the_catalogue_listing_its_indicator() -> None:
    create = _prose(_operations()["createIndicatorPreset"]["description"])
    favourite = _prose(SCHEMAS["IndicatorPresetInput"]["properties"]["is_favourite"]["description"])
    copies = [next(s for s in text.split(". ") if "copy" in s) for text in (create, favourite)]
    assert all("`listIndicators`" in sentence for sentence in copies)


def test_bundle_presets_have_no_item_cap_so_a_full_export_validates() -> None:
    pointer = f"{_S}WorkspaceBundle/properties/indicator_presets"
    presets = SCHEMAS["WorkspaceBundle"]["properties"]["indicator_presets"]
    assert ("maxItems" in presets, presets["items"]) == (False, {"$ref": f"#{INPUT}"})
    assert _errors(pointer, [_example()] * PRESETS_PER_USER_MAX) == []


def test_bundle_states_its_200_item_and_1_mib_limits_as_import_only() -> None:
    text = _prose(SCHEMAS["WorkspaceBundle"]["properties"]["indicator_presets"]["description"])
    assert "never truncated to the import limits" in text
    assert f"beyond {BUNDLE_IMPORT_PRESETS_MAX} items or 1 MiB of preset JSON" in text
