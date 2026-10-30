"""E42-T05 (#966 BK-15), QA gap 2 on a pushed frame. A health snapshot, through the hub's
`broadcast_system` as `create_app` wires it, queues a `system` frame on each authenticated socket,
cut for its role (`23-ws-protocol.md` 15.9): the Owner's whole, with every component's `detail`; a
Manager's and a Viewer's with each component's `name`, `state` and `last_good_at` only; none for a
principal with no role. The real `/ws` router and `GatewayHub` run on the test's loop behind a fake
socket (the SR-188 rig of `test_system_topic_roles.py`): no threads, no sleeps. Every frame a
socket is sent passes this directory's schema harness (`_seq_support.validate`)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.health_wiring import HealthSystemPublisher, register_public_ws_probe
from candleviewer.ingestion.connection import PHASE_DEGRADED, PHASE_OPEN
from candleviewer.observability.health_probes import (
    ComponentState,
    HealthRegistry,
    NotDeployedProbe,
)
from tests.unit.observability._health_frames import Clock, Guard, Probe, envelope, part
from tests.unit.ws._seq_support import validate
from tests.unit.ws.test_system_topic_roles import _DEADLINE_S, _as, _Rig, _Socket

T0 = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)


class _Manager:
    """The public WS's `ConnectionManager`, in the phase the test sets."""

    phase = PHASE_OPEN

    def state(self) -> str:
        return self.phase


def _registry(
    publisher: HealthSystemPublisher,
) -> tuple[HealthRegistry, _Manager, Clock]:
    """A registry as `create_app` builds one: the public WS probe, Postgres, REST (degraded), and
    the unbuilt modules as `not_deployed` placeholders."""
    clock, manager = Clock(T0), _Manager()
    registry = HealthRegistry(on_snapshot=publisher, clock=clock)
    register_public_ws_probe(registry, lambda: cast(Any, manager))
    for probe in (
        Probe("postgres", ComponentState.HEALTHY),
        NotDeployedProbe("bybit_private_ws"),
        Probe("bybit_rest", ComponentState.DEGRADED, "slow"),
        NotDeployedProbe("oms"),
    ):
        registry.register(probe)
    return registry, manager, clock


def _wired(rig: _Rig) -> tuple[HealthSystemPublisher, HealthRegistry, _Manager, Clock]:
    """The publisher and registry as the app wires them: the hub's `broadcast_system` is a sink."""
    publisher = HealthSystemPublisher(clock_guard=lambda: Guard(7))
    publisher.direct_sinks.append(rig.hub.broadcast_system)
    return (publisher, *_registry(publisher))


async def _frames(sock: _Socket) -> list[dict[str, Any]]:
    """Every `system` frame queued for `sock` before now (a ping is the barrier: its pong follows
    them in the one FIFO queue)."""
    sock.feed({"t": "ping", "id": "barrier"})
    frames: list[dict[str, Any]] = []
    while (frame := await sock.sent.get())["t"] != "pong":
        frames.append(frame)
    return [f for f in frames if f.get("ch") == "system"]


#: The first tick, as the Owner gets it. REST is degraded, so the overall word is too; the private
#: WS and `oms` are not deployed, so they are healthy "not deployed" components with no `exchange`
#: key of their own; the clock guard measured 7 ms.
_AT = "2026-10-20T03:00:00Z"
_PARTS = [
    part("bybit_public_ws", "healthy", "open", _AT),
    part("postgres", "healthy", "", _AT),
    part("bybit_private_ws", "healthy", "not deployed", _AT),
    part("bybit_rest", "degraded", "slow"),  # never healthy: no last_good_at
    part("oms", "healthy", "not deployed", _AT),
]
_WHOLE: dict[str, Any] = {
    "kind": "health",
    "health": "degraded",
    "components": _PARTS,
    "exchange": {"public_ws": "connected", "rest": "degraded"},
    "clock_offset_ms": 7,
}
#: What a Manager and a Viewer get of it: no component's `detail`.
_CUT: dict[str, Any] = _WHOLE | {
    "components": [{k: v for k, v in item.items() if k != "detail"} for item in _PARTS]
}


async def test_one_health_snapshot_reaches_each_role_as_its_own_view() -> None:
    rig = _Rig()
    _, registry, _, _ = _wired(rig)
    async with asyncio.timeout(_DEADLINE_S):
        owner, manager, viewer = [
            await rig.connect(_as(uuid.uuid4(), role)) for role in ("owner", "manager", "viewer")
        ]
        nobody = await rig.connect(_as(uuid.uuid4()))  # the deny-all principal: no role
        await registry.refresh()
        got = [await _frames(sock) for sock in (owner, manager, viewer, nobody)]
        await rig.close()
    assert [[f["s"] for f in frames] for frames in got] == [[2], [2], [2], []]  # `s` 1: the snap
    assert got[0][0]["p"] == _WHOLE  # the Owner's, with every `detail`
    assert got[1][0]["p"] == got[2][0]["p"] == _CUT  # a Manager's and a Viewer's
    for frame in (got[0][0], got[1][0], got[2][0]):
        validate(frame)


async def test_the_next_tick_is_the_next_frame_and_marks_the_socket_that_dropped() -> None:
    rig = _Rig()
    _, registry, manager, clock = _wired(rig)
    async with asyncio.timeout(_DEADLINE_S):
        owner = await rig.connect(_as(uuid.uuid4(), "owner"))
        viewer = await rig.connect(_as(uuid.uuid4(), "viewer"))
        await registry.refresh()
        manager.phase, clock.at = PHASE_DEGRADED, T0 + timedelta(seconds=1)  # backing off
        await registry.refresh()
        owned, viewed = await _frames(owner), await _frames(viewer)
        await rig.close()
    assert [f["s"] for f in owned] == [f["s"] for f in viewed] == [2, 3]
    for frames in (owned, viewed):
        assert frames[1]["p"]["exchange"] == {"public_ws": "disconnected", "rest": "degraded"}
        validate(frames[1])
    dropped = {"name": "bybit_public_ws", "state": "degraded", "last_good_at": _AT}
    assert owned[1]["p"]["components"][0] == dropped | {"detail": "degraded"}
    # last healthy at the first tick, so the tile can be marked stale
    assert viewed[1]["p"]["components"][0] == dropped


async def test_a_raising_sink_does_not_stop_the_push_or_the_tick() -> None:
    def broken(frame: dict[str, object]) -> None:
        raise RuntimeError("a sink that cannot take the frame")

    rig = _Rig()
    publisher, registry, _, _ = _wired(rig)
    publisher.direct_sinks.insert(0, broken)  # ahead of the hub's
    async with asyncio.timeout(_DEADLINE_S):
        owner = await rig.connect(_as(uuid.uuid4(), "owner"))
        with capture_logs() as logs:
            await registry.refresh()
            await registry.refresh()  # the ticker goes on
        frames = await _frames(owner)
        await rig.close()
    assert [f["s"] for f in frames] == [2, 3]
    failed = [e["event"] for e in logs if e["event"].startswith("health_wiring")]
    assert failed == ["health_wiring: direct sink failed"] * 2


class _AppSocket:
    """An authenticated socket on the app's own hub: it keeps what `push_system` is handed."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.push_system = frames.append
        self.lifecycle = SimpleNamespace(authenticated=True)


async def test_the_app_pushes_each_health_tick_to_the_sockets_of_its_own_hub() -> None:
    app = create_app()
    frames: list[dict[str, Any]] = []
    app.state.ws_hub._live.add(_AppSocket(frames))
    snap = await app.state.health_registry.refresh()
    (frame,) = frames
    validate(envelope(frame))
    assert frame["kind"] == "health"
    assert [c["name"] for c in frame["components"]] == [c.name for c in snap.components]
    # nothing deployed gives `exchange` a word, and no guard has measured the clock
    assert "exchange" not in frame and "clock_offset_ms" not in frame


async def test_the_apps_offset_is_the_guards_measured_one_read_when_the_frame_is_built() -> None:
    app = create_app()
    frames: list[dict[str, Any]] = []
    app.state.ws_hub._live.add(_AppSocket(frames))
    ingestion = app.state.app_context.ingestion
    assert ingestion.clock_offset_ms() == 0  # the default nothing measured: it must never be sent
    await app.state.health_registry.refresh()
    ingestion.clock = Guard(5)  # attached after the app is built (`attach_clock`)
    await app.state.health_registry.refresh()
    ingestion.clock = Guard(None)  # attached, nothing measured yet
    await app.state.health_registry.refresh()
    assert [f.get("clock_offset_ms") for f in frames] == [None, 5, None]
    assert ["clock_offset_ms" in f for f in frames] == [False, True, False]
