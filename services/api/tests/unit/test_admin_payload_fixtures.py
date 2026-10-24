"""E42-Q01 (#962): the admin fixtures' payloads are states the server can send. Each validates
against the contract's model and dumps back to itself, and is held to its producer: the registry's
names, the roll-up of `overall` and the keys `render_report` sends; the overview service's slices
and fields, and the detail the fan-out gives a failed slice.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from candleviewer.admin.overview.fanout import SliceFanOut, SliceResult
from candleviewer.admin.overview.ports import AccountCounts, UserCounts
from candleviewer.admin.overview.service import OverviewSnapshot, StorageHeadroom, TradingState
from candleviewer.admin.overview.slices import AdminSlice
from candleviewer.api._generated.openapi_models import AdminOverview, HealthReport
from candleviewer.api.health_report import render_report
from candleviewer.health_wiring import SECRETS
from candleviewer.observability import health_probes as probes
from candleviewer.observability.redaction import redact_text

_PAYLOADS = Path(__file__).resolve().parents[1] / "fixtures" / "admin" / "payloads"
_DEGRADED, _OUTAGE = "health_degraded.json", "health_outage.json"
_DOWN, _HANG = "overview_recorder_down.json", "overview_recorder_hang.json"
_MODELS: dict[str, type[BaseModel]] = {
    _DEGRADED: HealthReport,
    _OUTAGE: HealthReport,
    _DOWN: AdminOverview,
    _HANG: AdminOverview,
}
#: Every payload is held to its producer's tests, by its model: a payload added to `_MODELS` is
#: in one of these, and `test_every_payload_is_held_to_a_producer` fails one that is in neither.
_HEALTH = [name for name, model in _MODELS.items() if model is HealthReport]
_OVERVIEWS = [name for name, model in _MODELS.items() if model is AdminOverview]
#: The names a `HealthRegistry` built as `app.py` builds one reports: the ten required components
#: and the five more `app.py` registers. A real `GET /admin/health` sends all fifteen.
_PROBES = (probes.HOT_TIER_WRITE_BEHIND, probes.INGESTION, SECRETS, probes.BARS, probes.BARS_WRITER)
_REGISTRY_NAMES = {*probes.REQUIRED_COMPONENTS, *_PROBES}
#: The overview's slices as the service reads them, and what each holds when it is `ok`.
_SLICES = {f.name for f in fields(OverviewSnapshot)} - {"generated_at"}
_OK_VALUES: dict[str, Any] = dict(
    users=UserCounts, accounts=AccountCounts, storage=StorageHeadroom, trading=TradingState
)
_AT = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _load(name: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((_PAYLOADS / name).read_text(encoding="utf-8")))


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _secret_shaped(value: Any) -> list[str]:
    return [s for s in _strings(value) if redact_text(s) != s]


def _server_keys() -> tuple[set[str], set[str]]:
    """The keys of a report and of one of its components, as `render_report` sends them."""
    healthy = probes.ComponentState.HEALTHY
    snap = probes.HealthSnapshot(healthy, (probes.ComponentHealth("x", healthy, 1, "", None),), _AT)
    report = render_report(
        snap, version="v", git_sha="s", environment="demo", uptime_seconds=1, clock_offset_ms=None
    )
    return set(report), set(report["components"][0])


def test_every_payload_on_disk_has_a_model() -> None:
    assert sorted(p.name for p in _PAYLOADS.glob("*.json")) == sorted(_MODELS)


def test_every_payload_is_held_to_a_producer() -> None:
    assert sorted([*_HEALTH, *_OVERVIEWS]) == sorted(_MODELS)


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_a_payload_is_a_body_of_its_model(name: str) -> None:
    data = _load(name)
    dumped = _MODELS[name].model_validate(data).model_dump(mode="json", exclude_unset=True)
    assert dumped == data


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_no_payload_value_is_secret_shaped(name: str) -> None:
    assert _secret_shaped(_load(name)) == []


def test_the_scan_finds_a_secret_shaped_value_nested_in_a_payload() -> None:
    nested = {"components": [{"detail": "password: not-a-value-1"}]}
    assert _secret_shaped(nested) == ["password: not-a-value-1"]


@pytest.mark.parametrize("name", _HEALTH)
def test_a_health_payloads_overall_is_the_worst_component_state(name: str) -> None:
    worst = probes.worst_of([probes.ComponentState(c["state"]) for c in _load(name)["components"]])
    assert _load(name)["overall"] == worst


@pytest.mark.parametrize("name", _HEALTH)
def test_every_component_of_a_health_payload_is_a_registry_name(name: str) -> None:
    assert {c["name"] for c in _load(name)["components"]} - _REGISTRY_NAMES == set()


@pytest.mark.parametrize("name", _HEALTH)
def test_a_health_payload_reports_every_required_component(name: str) -> None:
    assert set(probes.REQUIRED_COMPONENTS) - {c["name"] for c in _load(name)["components"]} == set()


@pytest.mark.parametrize("name", _HEALTH)
def test_a_health_payload_has_the_report_keys_the_server_sends(name: str) -> None:
    assert set(_load(name)) == _server_keys()[0]  # `alerts_active` is left out, as the server does


@pytest.mark.parametrize("name", _HEALTH)
def test_every_component_of_a_health_payload_has_the_keys_the_server_sends(name: str) -> None:
    keys = _server_keys()[1]
    assert [c["name"] for c in _load(name)["components"] if set(c) != keys] == []


@pytest.mark.parametrize("name", _HEALTH)
def test_a_component_was_last_good_as_the_registry_stamps_it(name: str) -> None:
    """The registry stamps `last_good_at` on a healthy or not_deployed run only: a component in
    any other state was last good at an earlier run, or never, and one in either was good now."""
    report = _load(name)
    now = datetime.fromisoformat(report["server_time"])
    good = {"healthy", "not_deployed"}
    stamped = {
        c["name"]: None if c["last_good_at"] is None else datetime.fromisoformat(c["last_good_at"])
        for c in report["components"]
    }
    now_good = {c["name"] for c in report["components"] if stamped[c["name"]] == now}
    assert now_good == {c["name"] for c in report["components"] if c["state"] in good}
    assert [n for n, at in stamped.items() if at is not None and at > now] == []


def test_the_degraded_payloads_only_component_not_healthy_is_the_degraded_private_stream() -> None:
    not_healthy = {
        c["name"]: c["state"] for c in _load(_DEGRADED)["components"] if c["state"] != "healthy"
    }
    assert not_healthy == {"bybit_private_ws": "degraded"}


def test_the_degraded_payloads_private_stream_names_sub_002() -> None:
    private = next(c for c in _load(_DEGRADED)["components"] if c["name"] == "bybit_private_ws")
    assert "sub_002" in private["detail"]


@pytest.mark.parametrize(("name", "overall"), [(_DEGRADED, "degraded"), (_OUTAGE, "down")])
def test_a_health_payloads_overall_is_the_state_of_its_case(name: str, overall: str) -> None:
    assert _load(name)["overall"] == overall


@pytest.mark.parametrize("name", _OVERVIEWS)
def test_an_overview_payloads_slices_are_ok_but_the_recorders_error(name: str) -> None:
    statuses = {k: v["status"] for k, v in _load(name).items() if isinstance(v, dict)}
    assert statuses == dict.fromkeys(_SLICES, "ok") | {"recorder": "error"}


@pytest.mark.parametrize("slice_name", _OK_VALUES)
@pytest.mark.parametrize("name", _OVERVIEWS)
def test_an_ok_slice_carries_every_field_the_service_reads(name: str, slice_name: str) -> None:
    read = {f.name for f in fields(_OK_VALUES[slice_name])}
    assert set(_load(name)[slice_name]) == {"status", "generated_at"} | read


_Source = Callable[[], Awaitable[None]]


async def _fails() -> None:
    raise OSError("fixture")


async def _never_answers() -> None:
    await asyncio.Event().wait()


@pytest.mark.parametrize(("name", "source"), [(_DOWN, _fails), (_HANG, _never_answers)])
async def test_the_recorder_slice_is_what_the_fan_out_makes(name: str, source: _Source) -> None:
    made: SliceResult[None] = await SliceFanOut(now=lambda: _AT).read(AdminSlice.RECORDER, source)
    sent = {"status": made.status, "detail": made.detail, "generated_at": "2026-10-22T12:00:00Z"}
    assert _load(name)["recorder"] == sent
