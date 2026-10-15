"""Contract (E16-T07): the recorder's `StorageUsage` mirror is exactly the OpenAPI
`StorageUsage` of `GET /recording/storage` (`22-api-openapi.yaml`; the route is E16-T08):
the documented example round-trips, every field set matches the schema, and `DiskBudget.report()`
validates."""

from __future__ import annotations

from typing import Any

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.recorder.models import StorageUsage
from tests.unit.recorder._budget_fakes import GB, FakeMeter, make_budget

_SPEC = load_openapi_spec()
_SCHEMA = _SPEC["components"]["schemas"]["StorageUsage"]["properties"]
_OPERATION = _SPEC["paths"]["/recording/storage"]["get"]
_EXAMPLE: dict[str, Any] = _OPERATION["responses"]["200"]["content"]["application/json"][
    "examples"
]["usage"]["value"]


def test_documented_example_round_trips_through_the_mirror() -> None:
    dumped = StorageUsage.model_validate(_EXAMPLE).model_dump(mode="json")
    assert api.StorageUsage.model_validate(dumped) == api.StorageUsage.model_validate(_EXAMPLE)


def test_mirror_fields_are_exactly_the_schema_fields() -> None:
    dumped = StorageUsage.model_validate(_EXAMPLE).model_dump(mode="json")
    assert set(dumped) == set(_SCHEMA)
    assert set(dumped["tiers"][0]) == set(_SCHEMA["tiers"]["items"]["properties"])
    assert set(dumped["symbols"][0]) == set(_SCHEMA["symbols"]["items"]["properties"])


async def test_disk_budget_report_validates_against_the_schema() -> None:
    meter = FakeMeter(used=300 * GB, symbols={"BTCUSDT": 200 * GB, "ETHUSDT": 100 * GB})
    budget, _, _ = make_budget(meter, pinned=frozenset({"BTCUSDT"}))
    await budget.sample_once()
    report = budget.report()
    assert report is not None
    payload = report.model_dump(mode="json")
    api.StorageUsage.model_validate(payload)
    assert set(payload) == set(_SCHEMA)
    assert [t["tier"] for t in payload["tiers"]] == ["questdb", "parquet", "postgres"]
