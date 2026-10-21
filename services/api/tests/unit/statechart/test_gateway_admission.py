"""The gateway's injected admission (E50-T63, C-2.21). `Gateway(admission=...)` asks
`admit(machine_key, event_type)` synchronously before it delivers anything; a refusal raises
`GatewayDegradedError`, counted `degraded` in `cv_machine_send_refused_total` and answered 503 at
the API edge. `statechart_wiring.LatchAdmission` refuses the gated events of a machine the
`ChainTripLatch` holds (replay: PREPARE, PLAY, STEP, SEEK, SET_SPEED), so a latched session can
still be paused, cancelled and destroyed; a latched key of a kind with no gated set refuses every
event (fail closed). `ALWAYS_ADMIT`, the default, admits everything. The order path keeps exactly
one gate: the OMS facade's own latch (its gateway is built with `ALWAYS_ADMIT`)."""

from __future__ import annotations

import concurrent.futures
import json
from collections import OrderedDict
from collections.abc import Awaitable
from typing import Any

import pytest
from prometheus_client import generate_latest
from starlette.requests import Request

from candleviewer.app import create_app
from candleviewer.observability.metrics import Metrics
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.gateway import (
    ALWAYS_ADMIT,
    REASON_DEGRADED,
    Decision,
    Gateway,
    GatewayDegradedError,
    GatewayError,
)
from candleviewer.statechart.persistence import ChainTripLatch, DegradedLatchError, MachineKey
from candleviewer.statechart.plugins import CvMetricsPlugin
from candleviewer.statechart_wiring import GATED_EVENTS, LatchAdmission
from tests.unit.oms.order_rig import ACCOUNT, build_rig

KEY = MachineKey("replay", "0a000000-0000-4000-8000-000000000001", "demo")
NAME = f"replay:{KEY.entity_id}"
#: The latch's reasons, as `Restorer` writes them (`chain_trips=N: <last chain error>`).
TRIPPED = "chain_trips=1"
TRIPPED_DETAIL = "chain_trips=1: ChainBudgetExceeded"


class FakeInterp:
    """Records what reached it: a refused send never does."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    def send(self, event: Any, *, wait: bool = False) -> Awaitable[None]:
        self.sent.append(event)

        async def receipt() -> None:
            return None

        return receipt()

    def send_threadsafe(self, event: Any) -> concurrent.futures.Future[None]:
        self.sent.append(event)
        fut: concurrent.futures.Future[None] = concurrent.futures.Future()
        fut.set_result(None)
        return fut


class Rig:
    def __init__(self, admission: Any = None, *, machine_key: MachineKey | None = KEY) -> None:
        self.latch = ChainTripLatch()
        self.metrics = Metrics("dev")
        self.gateway = (
            Gateway() if admission == "default" else Gateway(admission=admission or self.latched)
        )
        self.interp = FakeInterp()
        self.machine_key = machine_key

    @property
    def latched(self) -> LatchAdmission:
        return LatchAdmission(self.latch)

    async def register(self, kind: str = "replay") -> None:
        recorder = CvMetricsPlugin(machine_kind=kind, metrics=self.metrics)
        self.gateway.register(
            NAME, self.interp, kind=kind, lane="control", metrics=recorder,
            machine_key=self.machine_key,
        )  # fmt: skip

    def refused(self, reason: str) -> float:
        total = 0.0
        for line in generate_latest(self.metrics.registry).decode().splitlines():
            if line.startswith("cv_machine_send_refused_total{") and f'reason="{reason}"' in line:
                total += float(line.rsplit(" ", 1)[1])
        return total


async def test_a_latched_machine_refuses_a_gated_command_and_counts_it_degraded() -> None:
    """Scenario 10: refused with `GatewayDegradedError` before delivery, counted `degraded`."""
    rig = Rig()
    await rig.register()
    rig.latch.latch(KEY, TRIPPED_DETAIL)
    with pytest.raises(GatewayDegradedError) as refused:
        await rig.gateway.send(NAME, {"type": "PLAY"})
    assert isinstance(refused.value, GatewayError) and refused.value.status_code == 503
    assert "ChainBudgetExceeded" not in str(refused.value)  # the latch's reason stays in the log
    assert rig.interp.sent == [] and rig.refused(REASON_DEGRADED) == 1.0


async def test_the_cross_thread_path_is_gated_too() -> None:
    rig = Rig()
    await rig.register()
    rig.latch.latch(KEY, TRIPPED)
    with pytest.raises(GatewayDegradedError):
        rig.gateway.send_threadsafe(NAME, "SEEK")
    assert rig.interp.sent == [] and rig.refused(REASON_DEGRADED) == 1.0


@pytest.mark.parametrize("event", ["PAUSE", "CANCEL", "DESTROY", "KILL", "RANGE_END"])
async def test_a_latched_session_can_still_be_stopped_and_destroyed(event: str) -> None:
    """Only the replay kind's gated events are refused: stopping a session is never blocked."""
    rig = Rig()
    await rig.register()
    rig.latch.latch(KEY, TRIPPED)
    await rig.gateway.send(NAME, {"type": event})
    assert rig.interp.sent == [{"type": event}] and rig.refused(REASON_DEGRADED) == 0.0


def test_the_replay_gated_set_is_the_work_starting_events() -> None:
    assert GATED_EVENTS["replay"] == frozenset({"PREPARE", "PLAY", "STEP", "SEEK", "SET_SPEED"})


async def test_an_unlatched_machine_sends_as_before() -> None:
    rig = Rig()
    await rig.register()
    await rig.gateway.send(NAME, "PLAY")
    assert rig.interp.sent == ["PLAY"]


async def test_a_machine_registered_without_a_key_sends_as_before() -> None:
    rig = Rig(machine_key=None)
    await rig.register()
    rig.latch.latch(KEY, TRIPPED)
    await rig.gateway.send(NAME, "PLAY")
    assert rig.interp.sent == ["PLAY"]


async def test_a_gateway_built_with_always_admit_sends_a_latched_machines_command() -> None:
    rig = Rig("default")
    await rig.register()
    rig.latch.latch(KEY, TRIPPED)
    await rig.gateway.send(NAME, "PLAY")
    assert rig.interp.sent == ["PLAY"]
    assert ALWAYS_ADMIT.admit(KEY, "PLAY") == Decision(True, "")


async def test_a_latched_key_of_a_kind_with_no_gated_set_refuses_every_event() -> None:
    alert = MachineKey("alert", "0a000000-0000-4000-8000-000000000002", "demo")
    rig = Rig(machine_key=alert)
    await rig.register(kind="alert")
    rig.latch.latch(alert, TRIPPED)
    for event in ("ARM", "DESTROY", "KILL"):
        with pytest.raises(GatewayDegradedError):
            await rig.gateway.send(NAME, event)
    assert rig.interp.sent == []


def test_a_decision_is_frozen() -> None:
    decision = LatchAdmission(ChainTripLatch()).admit(KEY, "PLAY")
    assert decision == Decision(True, "")
    with pytest.raises(AttributeError):
        decision.admitted = False  # type: ignore[misc]  # frozen: the assignment must fail


async def test_the_api_edge_answers_a_degraded_refusal_503_problem() -> None:
    app = create_app()
    handler = app.exception_handlers[GatewayDegradedError]
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    response = await handler(request, GatewayDegradedError(NAME, "control"))
    body = json.loads(bytes(response.body))
    assert response.status_code == 503 and response.media_type == "application/problem+json"
    assert body["status"] == 503 and "degraded" in body["detail"]


async def test_the_order_path_has_exactly_one_gate_the_facades_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator ruling (03:41Z): the OMS gateway admits everything (`ALWAYS_ADMIT`), so a
    latched order's command is refused once, by the facade's own `admit_command`, before the
    gateway is asked; what the facade lets through, the gateway admits."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    rig = build_rig()
    asked: list[tuple[str, bool]] = []

    class Recording:
        def admit(self, key: MachineKey | None, event_type: str) -> Decision:
            decision = ALWAYS_ADMIT.admit(key, event_type)
            asked.append((event_type, decision.admitted))
            return decision

    try:
        assert rig.facade._gateway._admission is ALWAYS_ADMIT
        monkeypatch.setattr(rig.facade._gateway, "_admission", Recording())
        order = await rig.submitted()
        asked.clear()
        rig.facade._orders[order.id].interp.chain_trips = 1
        with pytest.raises(DegradedLatchError):
            await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
        assert asked == []  # refused by the facade alone: the gateway never saw it
        fault = {"reason": "socket closed"}
        await rig.facade.command(ACCOUNT, order.id, "TRANSPORT_FAULT", fault, actor="system")
        assert asked == [("TRANSPORT_FAULT", True)]
    finally:
        await rig.facade.stop()
