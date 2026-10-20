"""Contract (E16-T07): the recorder's `StorageUsage` mirror is exactly the OpenAPI
`StorageUsage` of `GET /recording/storage` (`22-api-openapi.yaml`; the route is E16-T08):
the documented example round-trips, every field set matches the schema, and `DiskBudget.report()`
validates."""

from __future__ import annotations

from typing import Any, get_args

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.recorder.metrics import recorder_disk_pressure_level
from candleviewer.recorder.models import DiskPressureLevel, StorageUsage
from tests.unit.recorder._budget_fakes import CAP, GB, TOTAL, FakeMeter, make_budget

_SPEC: dict[str, Any] = load_openapi_spec()
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


@pytest.mark.parametrize(
    ("free", "refused", "expected"),
    [
        (TOTAL // 2, False, (0, "open", None, False)),
        (TOTAL // 10, False, (2, "open", None, True)),
        (TOTAL * 4 // 100, False, (3, "closed", "disk_halt", True)),
        (TOTAL // 2, True, (3, "closed", "volume_refused", False)),
        (TOTAL * 4 // 100, True, (3, "closed", "volume_refused", True)),
    ],
    ids=["normal", "autostop", "halt", "refused_volume", "refused_volume_at_halt"],
)
async def test_report_names_the_level_gate_and_cap_of_its_own_sample(
    free: int, refused: bool, expected: tuple[int, str, str | None, bool]
) -> None:
    """Halt on the very first sample reports 3 at once; a refused volume does over a ladder at 0."""
    budget, _, _ = make_budget(FakeMeter(used=300 * GB, free=free))
    budget.recording_refused = refused
    await budget.sample_once()
    report = budget.report()
    assert report is not None and report.cap_bytes == CAP
    got = (report.level, report.write_gate, report.write_gate_reason, report.accelerate_retention)
    assert got == expected
    assert recorder_disk_pressure_level._value.get() == report.level  # the gauge reads the same
    api.StorageUsage.model_validate(report.model_dump(mode="json"))


async def test_accelerate_retention_outlives_the_level() -> None:
    """The flag is the ladder's own: it holds after level 2 releases (free 10 % -> 20 %)."""
    meter = FakeMeter(used=300 * GB, free=TOTAL // 10)
    budget, _, _ = make_budget(meter)
    await budget.sample_once()
    meter.free = TOTAL // 5
    await budget.sample_once()
    report = budget.report()
    assert report is not None
    assert (report.level, report.write_gate, report.accelerate_retention) == (0, "open", True)


def test_the_mirror_names_the_contract_closed_sets() -> None:
    fields = StorageUsage.model_fields
    reasons = get_args(get_args(fields["write_gate_reason"].annotation)[0])
    assert [int(level) for level in DiskPressureLevel] == _SCHEMA["level"]["enum"]
    assert list(get_args(fields["write_gate"].annotation)) == _SCHEMA["write_gate"]["enum"]
    assert [*reasons, None] == _SCHEMA["write_gate_reason"]["enum"]
