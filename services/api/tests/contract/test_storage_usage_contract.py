"""Contract (E16-T07): the recorder's `StorageUsage` mirror is exactly the OpenAPI
`StorageUsage` of `GET /recording/storage` (`22-api-openapi.yaml`; the route is E16-T08):
the documented example round-trips and every field set matches the schema."""

from __future__ import annotations

from typing import Any

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.recorder.models import StorageUsage

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
