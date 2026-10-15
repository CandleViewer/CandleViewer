"""Contract (E42-T01, contract slice a): `AdminOverview` (`GET /admin/overview`) and
`CapacityReport` (`GET /admin/capacity`) carry the partial-result block `AdminSliceStatus` on
every slice, the projection basis and the recorded sub-account tier. The change is additive only
(C-6.3): every pre-existing property is unchanged and nothing new is required. The generated
models mirror the schema field sets exactly, and the documented examples round-trip through them
without losing a field."""

from __future__ import annotations

from typing import Any

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
_SUBACCOUNTS = _SCHEMAS["SubaccountCapacity"]

_INT, _NUM, _BOOL = {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
_I64, _DAYS = {"type": "integer", "format": "int64"}, {"type": ["number", "null"]}
#: Each slice's properties exactly as they stood before E42-T01 (main 6200a73f).
_BEFORE: dict[tuple[str, str], dict[str, Any]] = {
    ("overview", "users"): {"total": _INT, "active": _INT, "without_mfa": _INT},
    ("overview", "accounts"): {
        "total": _INT,
        "enabled": _INT,
        "keys_expiring_30d": _INT,
        "keys_invalid": _INT,
    },
    ("overview", "recorder"): {
        "symbols_recording": _INT,
        "symbols_degraded": _INT,
        "lag_seconds_p99": _NUM,
    },
    ("overview", "storage"): {"used_bytes": _I64, "free_bytes": _I64, "days_until_full": _DAYS},
    ("overview", "trading"): {
        "live_enabled": _BOOL,
        "kill_switch_engaged": _BOOL,
        "open_positions": _INT,
    },
    ("capacity", "ingestion"): {
        "messages_per_sec": _NUM,
        "queue_depth": _INT,
        "dropped_last_hour": _INT,
    },
}
_PARTS = {"overview": _OVERVIEW, "capacity": _CAPACITY}
_MIRRORS: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (api.Users, _OVERVIEW["users"]),
    (api.Accounts, _OVERVIEW["accounts"]),
    (api.Recorder, _OVERVIEW["recorder"]),
    (api.Storage, _OVERVIEW["storage"]),
    (api.Trading1, _OVERVIEW["trading"]),
    (api.Incidents, _OVERVIEW["incidents"]),
    (api.Storage1, _CAPACITY["storage"]),
    (api.Ingestion, _CAPACITY["ingestion"]),
    (api.SubaccountCapacity, _SUBACCOUNTS),
]


def _example(path: str, name: str) -> dict[str, Any]:
    content = _SPEC["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]
    value: dict[str, Any] = content["examples"][name]["value"]
    return value


@pytest.mark.parametrize(
    "schema",
    [_OVERVIEW[p] for p in ("users", "accounts", "recorder", "storage", "trading", "incidents")]
    + [_CAPACITY["storage"], _CAPACITY["ingestion"], _SUBACCOUNTS],
)
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


@pytest.mark.parametrize(("key", "before"), list(_BEFORE.items()))
def test_pre_existing_properties_are_unchanged(
    key: tuple[str, str], before: dict[str, Any]
) -> None:
    props = _PARTS[key[0]][key[1]]["properties"]
    assert {name: props[name] for name in before} == before


def test_nothing_new_is_required() -> None:
    schemas = [_SCHEMAS[n] for n in ("AdminOverview", "CapacityReport", "AdminSliceStatus")]
    schemas += [_SUBACCOUNTS, *_OVERVIEW.values(), *_CAPACITY.values()]
    assert [s for s in schemas if "required" in s] == []


def test_projection_basis_and_tier_vocabularies() -> None:
    storage = _CAPACITY["storage"]["properties"]
    assert storage["projection_basis"]["enum"] == ["measured", "estimated", "nothing_recorded"]
    assert storage["estimated"] == _BOOL  # C10, optional: no default makes TS require it
    props = _SUBACCOUNTS["properties"]
    assert props["tier"]["enum"] == ["regular", "business_kyc", None]
    assert props["cap"]["type"] == ["integer", "null"]
    assert props["tier_source"]["enum"] == ["recorded", "unrecorded"]


@pytest.mark.parametrize(("model", "schema"), _MIRRORS, ids=[m.__name__ for m, _ in _MIRRORS])
def test_generated_models_mirror_the_schema_fields_exactly(
    model: type[BaseModel], schema: dict[str, Any]
) -> None:
    assert set(model.model_fields) == set(schema["properties"]) | _SLICE_FIELDS


@pytest.mark.parametrize(
    ("model", "path", "name"),
    [
        (api.AdminOverview, "/admin/overview", "degraded"),
        (api.CapacityReport, "/admin/capacity", "estimated"),
    ],
)
def test_documented_example_round_trips_without_field_loss(
    model: type[BaseModel], path: str, name: str
) -> None:
    example = _example(path, name)
    dumped = model.model_validate(example).model_dump(mode="json", exclude_unset=True)
    assert dumped == example


def test_overview_example_shows_every_slice_outcome() -> None:
    example = _example("/admin/overview", "degraded")
    statuses = {v["status"] for v in example.values() if isinstance(v, dict)}
    assert statuses == {"ok", "error", "unavailable"}
    assert example["recorder"] == {
        "status": "error",
        "detail": "timed out after 300 ms",
        "generated_at": "2026-10-15T18:00:05Z",
    }
