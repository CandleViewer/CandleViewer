"""Contract (E42-T01, contract slice a): `AdminOverview` / `CapacityReport` carry `AdminSliceStatus`
on every slice, additively (C-6.3: the nine pre-existing groups keep their wire shape, nothing new
is required); the generated models mirror the schema fields and every example round-trips."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_SLICE = [{"$ref": "#/components/schemas/AdminSliceStatus"}]
_SLICE_FIELDS = {"status", "detail", "generated_at"}
_OVERVIEW = _SCHEMAS["AdminOverview"]["properties"]
_CAPACITY = _SCHEMAS["CapacityReport"]["properties"]
_SUB = _SCHEMAS["SubaccountCapacity"]
_OV_SLICES = ("users", "accounts", "recorder", "storage", "trading", "incidents")

_I, _N, _B, _S = ({"type": t} for t in ("integer", "number", "boolean", "string"))
_I64, _DAYS = {"type": "integer", "format": "int64"}, {"type": ["number", "null"]}
_UUID = {"type": "string", "format": "uuid"}
_SYMBOL_ITEM = {
    "type": "object",
    "properties": dict(symbol={"$ref": "#/components/schemas/Symbol"}),
}
_SYMBOL_ITEM["properties"] |= dict(used_bytes=_I64, daily_growth_bytes=_I64, pinned=_B)
_SYMBOL_ITEM["properties"]["retention_days"] = {"type": ["integer", "null"]}
#: The nine pre-existing groups as they stood before E42-T01 (main 6200a73f), wire shape only.
_BEFORE: dict[str, dict[str, Any]] = {
    "overview.users": dict.fromkeys(("total", "active", "without_mfa"), _I),
    "overview.accounts": dict.fromkeys(
        ("total", "enabled", "keys_expiring_30d", "keys_invalid"), _I
    ),
    "overview.recorder": {"symbols_recording": _I, "symbols_degraded": _I, "lag_seconds_p99": _N},
    "overview.storage": {"used_bytes": _I64, "free_bytes": _I64, "days_until_full": _DAYS},
    "overview.trading": {"live_enabled": _B, "kill_switch_engaged": _B, "open_positions": _I},
    "overview": {"incidents_open": _I},
    "capacity.storage": dict(used_bytes=_I64, free_bytes=_I64, daily_growth_bytes=_I64)
    | {"days_until_full": _DAYS, "per_symbol": {"type": "array", "items": _SYMBOL_ITEM}},
    "capacity.ingestion": {"messages_per_sec": _N, "queue_depth": _I, "dropped_last_hour": _I},
    "capacity.rate_budget[]": dict(exchange_account_id=_UUID, label=_S, limit_per_minute=_I)
    | {"peak_used_per_minute": _I, "utilisation_pct": _N},
}


def _shape(schema: dict[str, Any]) -> dict[str, Any]:
    """Wire shape only (type/format/enum/nullable/$ref, items, properties): prose may change."""
    out = {k: schema[k] for k in ("type", "format", "enum", "nullable", "$ref") if k in schema}
    if "items" in schema:
        out["items"] = _shape(schema["items"])
    if "properties" in schema:
        out["properties"] = {k: _shape(v) for k, v in schema["properties"].items()}
    return out


def _group(key: str) -> dict[str, Any]:
    if key == "overview":
        return _OVERVIEW
    part, _, name = key.partition(".")
    schema = (_OVERVIEW if part == "overview" else _CAPACITY)[name.removesuffix("[]")]
    return dict((schema["items"] if name.endswith("[]") else schema)["properties"])


def _slice_model(parent: type[BaseModel], field: str) -> type[BaseModel]:
    """A generated slice class reached by field name, never by a generator ordinal."""
    args = get_args(parent.model_fields[field].annotation)
    (model,) = [a for a in args if isinstance(a, type) and issubclass(a, BaseModel)]
    return model


def _example(path: str, name: str) -> dict[str, Any]:
    content = _SPEC["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]
    value: dict[str, Any] = content["examples"][name]["value"]
    return value


_SLICES = {f"overview.{f}": _OVERVIEW[f] for f in _OV_SLICES}
_SLICES |= {"capacity.storage": _CAPACITY["storage"], "capacity.ingestion": _CAPACITY["ingestion"]}
_SLICES |= {"capacity.subaccounts": _SUB}
_PARENTS: dict[str, type[BaseModel]] = {
    "overview": api.AdminOverview,
    "capacity": api.CapacityReport,
}
_MIRRORS: dict[str, tuple[type[BaseModel], dict[str, Any]]] = {
    "AdminOverview": (api.AdminOverview, _SCHEMAS["AdminOverview"]),
    "CapacityReport": (api.CapacityReport, _SCHEMAS["CapacityReport"]),
    "RateBudgetItem": (api.RateBudgetItem, _CAPACITY["rate_budget"]["items"]),
    **{
        key: (_slice_model(_PARENTS[key.partition(".")[0]], key.partition(".")[2]), schema)
        for key, schema in _SLICES.items()
    },
}
_EXAMPLES = [
    (api.AdminOverview, "/admin/overview", "degraded"),
    (api.CapacityReport, "/admin/capacity", "estimated"),
    (api.CapacityReport, "/admin/capacity", "empty"),
]


@pytest.mark.parametrize("schema", list(_SLICES.values()), ids=list(_SLICES))
def test_every_slice_carries_the_slice_status_block(schema: dict[str, Any]) -> None:
    assert schema["allOf"] == _SLICE


def test_rate_budget_list_has_its_own_slice_status() -> None:
    assert _CAPACITY["rate_budget_status"] == _SLICE[0]


def test_slice_status_block_states_the_three_outcomes() -> None:
    block = _SCHEMAS["AdminSliceStatus"]["properties"]
    assert set(block) == _SLICE_FIELDS
    assert block["status"]["enum"] == ["ok", "error", "unavailable"]
    assert block["detail"]["type"] == ["string", "null"]
    assert block["generated_at"]["format"] == "date-time"


@pytest.mark.parametrize(("key", "before"), list(_BEFORE.items()), ids=list(_BEFORE))
def test_pre_existing_properties_keep_their_wire_shape(key: str, before: dict[str, Any]) -> None:
    props = _group(key)
    assert {name: _shape(props[name]) if name in props else None for name in before} == before


def test_nothing_new_is_required() -> None:
    schemas = [_SCHEMAS[n] for n in ("AdminOverview", "CapacityReport", "AdminSliceStatus")]
    schemas += [_SUB, *_OVERVIEW.values(), *_CAPACITY.values()]
    assert [s for s in schemas if "required" in s] == []


def test_projection_basis_vocabulary() -> None:
    basis = _CAPACITY["storage"]["properties"]["projection_basis"]
    assert basis["enum"] == ["measured", "estimated", "nothing_recorded"]


def test_estimated_flag_is_an_optional_boolean() -> None:
    # OpenAPI header convention C10; no `default`, so the generated TS type keeps it optional.
    assert _shape(_CAPACITY["storage"]["properties"]["estimated"]) == _B


def test_tier_vocabulary_admits_null() -> None:
    assert _SUB["properties"]["tier"]["enum"] == ["regular", "business_kyc", None]


def test_cap_is_a_nullable_integer() -> None:
    assert _SUB["properties"]["cap"]["type"] == ["integer", "null"]


def test_tier_source_is_closed() -> None:
    assert _SUB["properties"]["tier_source"]["enum"] == ["recorded", "unrecorded"]


@pytest.mark.parametrize(("model", "schema"), list(_MIRRORS.values()), ids=list(_MIRRORS))
def test_generated_models_mirror_the_schema_fields_exactly(
    model: type[BaseModel], schema: dict[str, Any]
) -> None:
    expected = set(schema["properties"]) | (_SLICE_FIELDS if "allOf" in schema else set())
    assert set(model.model_fields) == expected


@pytest.mark.parametrize(("model", "path", "name"), _EXAMPLES, ids=[e[2] for e in _EXAMPLES])
def test_documented_example_round_trips_without_field_loss(
    model: type[BaseModel], path: str, name: str
) -> None:
    example = _example(path, name)
    assert model.model_validate(example).model_dump(mode="json", exclude_unset=True) == example


@pytest.mark.parametrize("name", ["estimated", "empty"], ids=["estimated", "empty"])
def test_capacity_examples_are_coherent(name: str) -> None:
    example = _example("/admin/capacity", name)
    storage, sub = example["storage"], example["subaccounts"]
    assert storage["estimated"] is (storage["projection_basis"] == "estimated")
    assert (sub["tier"] is None) is (sub["cap"] is None) is (sub["tier_source"] == "unrecorded")


def test_degraded_example_has_an_error_slice_with_a_detail() -> None:
    example = _example("/admin/overview", "degraded")
    assert example["recorder"]["status"] == "error"
    assert isinstance(example["recorder"]["detail"], str) and example["recorder"]["detail"]
    statuses = {v["status"] for v in example.values() if isinstance(v, dict)}
    assert statuses == {"ok", "error", "unavailable"}
