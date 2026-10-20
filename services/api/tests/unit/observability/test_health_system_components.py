"""E42-T05 (#966 BK-15): the `health` frame on `{env}.system` carries `components[]` as
`23-ws-protocol.md` 15.9 says ("Health components"): the names of `GET /admin/health`, an unknown
name passed through, `not_deployed` sent as `healthy` with the detail `not deployed`, and
`last_good_at` when there is one. Every expected body is written out here, never derived from the
publisher; the role cut is `ws.system_filter.system_view`, whose tables are not read."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api.health_report import render_report
from candleviewer.app import create_app
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bus.models import Topic
from candleviewer.health_wiring import HealthSystemPublisher
from candleviewer.observability.health_probes import (
    ComponentHealth,
    ComponentState,
    HealthRegistry,
    HealthSnapshot,
    NotDeployedProbe,
    ProbeResult,
)
from candleviewer.ws.system_filter import system_view

_SCHEMAS = json.loads(
    (Path(__file__).resolve().parents[5] / "docs" / "plan" / "ws-schema.json").read_text("utf-8")
)["schemas"]
#: §15.9's `components`: closed items, the four states, `detail` and `last_good_at` optional.
_COMPONENTS = Draft202012Validator(
    _SCHEMAS["cv://ws/v1/system.schema.json"]["properties"]["components"]
)
T0 = datetime(2026, 10, 20, 1, 30, tzinfo=UTC)
_MIN, _HOUR = timedelta(minutes=1), timedelta(hours=1)


def _principal(*roles: str) -> PrincipalSnapshot:
    return PrincipalSnapshot(uuid.UUID(int=0x966), frozenset(roles), frozenset(), ())


OWNER, MANAGER, VIEWER = _principal("owner"), _principal("manager"), _principal("viewer")


def _part(name: str, state: str, detail: str, last_good_at: str | None = None) -> dict[str, str]:
    """One expected `components[]` item; `last_good_at` is left out until there is one."""
    part = {"name": name, "state": state, "detail": detail}
    return part if last_good_at is None else part | {"last_good_at": last_good_at}


class _Bus:
    def __init__(self) -> None:
        self.sent: list[tuple[Topic, dict[str, Any]]] = []

    async def publish(self, topic: Topic, event: Any) -> None:
        self.sent.append((topic, event))


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class _Probe:
    timeout = 1.0

    def __init__(self, name: str, state: ComponentState, detail: str = "") -> None:
        self.name, self.state, self.detail = name, state, detail

    async def check(self) -> ProbeResult:
        return ProbeResult(self.state, self.detail)


def _snapshot(*components: ComponentHealth) -> HealthSnapshot:
    return HealthSnapshot(ComponentState.DOWN, components, T0)


async def _frame(snap: HealthSnapshot) -> dict[str, Any]:
    bus = _Bus()
    await HealthSystemPublisher(bus, "demo")(snap)
    topic, frame = bus.sent[0]
    assert topic == Topic(env="demo", domain="system")
    return frame


def _report(snap: HealthSnapshot) -> dict[str, Any]:
    return render_report(
        snap, version="v", git_sha="s", environment="demo", uptime_seconds=1, clock_offset_ms=None
    )


#: One component of each state, one that was never healthy, a not_deployed one, a name no client
#: knows, and a `last_good_at` with microseconds (how the registry's own clock writes it).
_MIXED = _snapshot(
    ComponentHealth("postgres", ComponentState.HEALTHY, 3, "", T0),
    ComponentHealth("questdb", ComponentState.DEGRADED, 8, "lagging", T0 - _MIN),
    ComponentHealth("disk", ComponentState.WARNING, 2, "used 91%", T0),
    ComponentHealth("bybit_rest", ComponentState.DOWN, 900, "probe timeout", T0 - _HOUR),
    ComponentHealth("bybit_private_ws", ComponentState.DOWN, 1, "closed", None),
    ComponentHealth("oms", ComponentState.NOT_DEPLOYED, 0, "module not deployed", T0),
    ComponentHealth("made_up_probe", ComponentState.HEALTHY, 1, "", T0.replace(microsecond=123456)),
)
_MIXED_SENT = [
    _part("postgres", "healthy", "", "2026-10-20T01:30:00Z"),
    _part("questdb", "degraded", "lagging", "2026-10-20T01:29:00Z"),
    _part("disk", "warning", "used 91%", "2026-10-20T01:30:00Z"),
    _part("bybit_rest", "down", "probe timeout", "2026-10-20T00:30:00Z"),
    _part("bybit_private_ws", "down", "closed"),  # never healthy: no last_good_at
    _part("oms", "healthy", "not deployed", "2026-10-20T01:30:00Z"),
    _part("made_up_probe", "healthy", "", "2026-10-20T01:30:00.123456Z"),
]


async def test_the_frame_carries_every_component_as_the_rest_report_names_it() -> None:
    frame = await _frame(_MIXED)
    assert frame["components"] == _MIXED_SENT
    assert (frame["kind"], frame["health"]) == ("health", "down")  # the block it always had


async def test_snapshot_and_delta_agree_the_frame_names_what_the_rest_report_names() -> None:
    frame, report = await _frame(_MIXED), _report(_MIXED)
    assert [c["name"] for c in frame["components"]] == [c["name"] for c in report["components"]]
    by_name = {c["name"]: c for c in report["components"]}
    for sent in frame["components"]:
        rest = by_name[sent["name"]]
        if rest["state"] != "not_deployed":  # the one word the frame maps
            assert (sent["state"], sent["detail"]) == (rest["state"], rest["detail"])
        assert sent.get("last_good_at") == rest["last_good_at"]  # one text, or absent for null


@pytest.mark.parametrize("detail", ["module not deployed", "ingestion stopped", ""])
async def test_not_deployed_is_sent_as_healthy_with_the_contract_detail_whatever_its_own(
    detail: str,
) -> None:
    snap = HealthSnapshot(
        ComponentState.HEALTHY,
        (ComponentHealth("recorder", ComponentState.NOT_DEPLOYED, 0, detail, T0),),
        T0,
    )
    frame = await _frame(snap)
    assert frame["components"] == [
        _part("recorder", "healthy", "not deployed", "2026-10-20T01:30:00Z")
    ]
    assert frame["health"] == "healthy"  # as it ranks for `overall`
    assert _report(snap)["components"][0]["state"] == "not_deployed"  # REST keeps its own word


@pytest.mark.parametrize("state", list(ComponentState))
async def test_every_probe_state_is_sent_as_a_state_of_the_contract_enum(
    state: ComponentState,
) -> None:
    """A state `HealthRegistry` gains later fails here until the frame maps it."""
    frame = await _frame(_snapshot(ComponentHealth("x", state, 0, "d", T0)))
    _COMPONENTS.validate(frame["components"])


async def _snapshot_and_delta() -> tuple[dict[str, Any], dict[str, Any]]:
    """Two frames of one registry: the first, then the one after Postgres went down."""
    bus, clock = _Bus(), _Clock(T0)
    registry = HealthRegistry(on_snapshot=HealthSystemPublisher(bus, "demo"), clock=clock)
    postgres = _Probe("postgres", ComponentState.HEALTHY)
    for probe in (
        postgres,
        _Probe("bybit_private_ws", ComponentState.DOWN, "private ws closed"),
        NotDeployedProbe("oms"),
        _Probe("made_up_probe", ComponentState.HEALTHY),
    ):
        registry.register(probe)
    await registry.refresh()
    clock.at = T0 + timedelta(seconds=30)
    postgres.state, postgres.detail = ComponentState.DOWN, "postgres unreachable"
    await registry.refresh()
    first, delta = (frame for _, frame in bus.sent)
    return first, delta


_FIRST = [
    _part("postgres", "healthy", "", "2026-10-20T01:30:00Z"),
    _part("bybit_private_ws", "down", "private ws closed"),
    _part("oms", "healthy", "not deployed", "2026-10-20T01:30:00Z"),
    _part("made_up_probe", "healthy", "", "2026-10-20T01:30:00Z"),
]
#: Postgres keeps the time it was last healthy, so its tile can be marked stale; the ones still
#: healthy move on to the new tick.
_DELTA = [
    _part("postgres", "down", "postgres unreachable", "2026-10-20T01:30:00Z"),
    _part("bybit_private_ws", "down", "private ws closed"),
    _part("oms", "healthy", "not deployed", "2026-10-20T01:30:30Z"),
    _part("made_up_probe", "healthy", "", "2026-10-20T01:30:30Z"),
]


def _without_detail(parts: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{k: v for k, v in part.items() if k != "detail"} for part in parts]


async def test_the_owner_gets_the_snapshot_and_the_delta_whole_with_every_detail() -> None:
    first, delta = await _snapshot_and_delta()
    for frame, expected in ((first, _FIRST), (delta, _DELTA)):
        assert frame["components"] == expected
        assert system_view(frame, OWNER) is frame  # nothing cut, nothing copied
        _COMPONENTS.validate(frame["components"])


@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
async def test_a_manager_or_viewer_gets_name_state_and_last_good_at_never_detail(
    who: PrincipalSnapshot,
) -> None:
    first, delta = await _snapshot_and_delta()
    for frame, expected in ((first, _FIRST), (delta, _DELTA)):
        view = system_view(frame, who)
        assert view is not None
        assert view["components"] == _without_detail(expected)  # the unknown name is kept too
        assert (view["kind"], view["health"]) == ("health", frame["health"])
        assert "unreachable" not in json.dumps(view) and "not deployed" not in json.dumps(view)


async def test_the_apps_own_probes_are_named_by_the_frame_as_the_rest_report_names_them() -> None:
    """The composition: placeholders, real probes and the module probes `create_app` registers."""
    snap = await create_app().state.health_registry.refresh()
    frame, report = await _frame(snap), _report(snap)
    assert [c["name"] for c in frame["components"]] == [c["name"] for c in report["components"]]
    undeployed = {c["name"] for c in report["components"] if c["state"] == "not_deployed"}
    assert undeployed  # the unbuilt modules are there to map
    for part in frame["components"]:
        assert part["state"] != "not_deployed"
        assert (part["detail"] == "not deployed") == (part["name"] in undeployed)
