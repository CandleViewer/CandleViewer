"""E42-Q01 (#962): the admin fixtures' health payloads and backups hold the states the plan uses.

Each payload is a body of the contract's model (`candleviewer.api._generated.openapi_models`):
it validates and dumps back to itself, so it carries no field the model does not know. The
backups' database half is `tests/integration/admin/test_admin_fixture_seed_pg.py`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from candleviewer.api._generated.openapi_models import AdminOverview, HealthReport
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.handles import BACKUPS

_PAYLOADS = Path(__file__).resolve().parents[1] / "fixtures" / "admin" / "payloads"
_MODELS: dict[str, type[BaseModel]] = {
    "health_degraded.json": HealthReport,
    "health_outage.json": HealthReport,
    "overview_recorder_down.json": AdminOverview,
}


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((_PAYLOADS / name).read_text(encoding="utf-8"))
    return loaded


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_a_payload_is_a_body_of_its_model(name: str) -> None:
    data = _load(name)
    dumped = _MODELS[name].model_validate(data).model_dump(mode="json", exclude_unset=True)
    assert dumped == data


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_no_payload_value_is_secret_shaped(name: str) -> None:
    values = list(_strings(_load(name)))
    assert [v for v in values if redact_text(v) != v] == []


def test_the_degraded_payload_has_sub_002s_private_stream_down() -> None:
    report = HealthReport.model_validate(_load("health_degraded.json"))
    states = {c.name: c.state for c in report.components or ()}
    assert (report.overall, states["ws.private.sub_002"]) == ("degraded", "down")


def test_the_outage_payload_is_down_overall() -> None:
    assert HealthReport.model_validate(_load("health_outage.json")).overall == "down"


def test_the_overview_has_only_the_recorder_unavailable() -> None:
    overview = _load("overview_recorder_down.json")
    slices = {k: v["status"] for k, v in overview.items() if isinstance(v, dict)}
    assert slices == dict.fromkeys(slices, "ok") | {"recorder": "unavailable"}


def test_the_latest_backup_failed_its_verification_and_an_older_one_is_verified() -> None:
    latest, older = sorted(BACKUPS, key=lambda b: b.age)
    assert (latest.status, latest.error, older.status) == (
        "failed",
        "checksum_mismatch",
        "verified",
    )
