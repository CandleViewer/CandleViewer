"""E42-T03: maintenance mode refuses order acceptance before any OMS work within 200 ms of the
write, notifies every session, cancels emulated algos only, and keeps the gate in step with a
change made directly in the database."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import replace
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from structlog.testing import capture_logs

from candleviewer.admin.flags import (
    MAINTENANCE_KEEP_RECORDER,
    MAINTENANCE_MODE,
    FlagService,
    FlagWriter,
    MaintenanceController,
    MaintenanceGate,
    OrderEntryPausedError,
    chain_hooks,
    default_registry,
)
from candleviewer.admin.flags.push import FlagPush, Session
from candleviewer.api.order_entry_gate import order_entry_refusal
from tests.unit.admin.flag_fakes import Clock, FakeAudit, FakeFlagStore

_OWNER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")


class _Algos:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def cancel_running_algos(self, reason: str) -> int:
        self.calls.append(reason)
        return 2


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def pause(self, reason: str) -> None:
        self.calls.append(f"pause:{reason}")

    async def resume(self, reason: str) -> None:
        self.calls.append(f"resume:{reason}")


class _Sessions:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def authenticated(self) -> Iterable[Session]:
        return [Session(_OWNER, frozenset({"owner"}), self.frames.append)]


async def _rig() -> tuple[FlagWriter, FakeFlagStore, MaintenanceController, _Algos, _Recorder]:
    store, gate, algos, recorder = FakeFlagStore(), MaintenanceGate(), _Algos(), _Recorder()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    controller = MaintenanceController(service, gate, algos=algos, recorder=recorder)
    hook = chain_hooks(controller.on_flag_changed, FlagPush(service, _Sessions()).flag_changed)
    return FlagWriter(service, FakeAudit(), on_change=hook), store, controller, algos, recorder


async def _toggle(writer: FlagWriter, store: FakeFlagStore, key: str, value: bool) -> None:
    await writer.set(
        key,
        actor_id=_OWNER,
        actor_label="owner",
        value=value,
        reason="maintenance window",
        expected_updated_at=store.rows[key].updated_at,
    )


def _orders_app(gate: MaintenanceGate, oms_calls: list[str]) -> FastAPI:
    app = FastAPI()

    @app.post("/orders")
    async def accept() -> JSONResponse:
        refused = order_entry_refusal(gate)
        if refused is not None:
            return refused
        oms_calls.append("submit")
        return JSONResponse({"accepted": True}, status_code=202)

    return app


async def test_maintenance_refuses_order_acceptance_within_200_ms_before_any_oms_work() -> None:
    writer, store, controller, algos, _ = await _rig()
    await controller.refresh()
    oms: list[str] = []
    transport = httpx.ASGITransport(app=_orders_app(controller.gate, oms))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/orders")).status_code == 202
        start = time.monotonic()
        await _toggle(writer, store, MAINTENANCE_MODE, True)
        refused = await client.post("/orders")
        assert time.monotonic() - start < 0.2
    assert refused.status_code == 403
    assert refused.json()["code"] == "trading_disabled"
    assert oms == ["submit"]
    assert algos.calls == ["maintenance.enabled"]


async def _bare() -> tuple[FlagService, FakeFlagStore]:
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    return service, store


async def test_the_gate_starts_closed_and_follows_the_flag() -> None:
    service, store = await _bare()
    controller = MaintenanceController(service, MaintenanceGate(), algos=_Algos())
    with pytest.raises(OrderEntryPausedError):
        controller.gate.check()
    await controller.refresh()
    controller.gate.check()
    store.down = True
    service.invalidate()
    await controller.refresh()
    assert controller.gate.engaged  # store unreachable: fail closed


async def test_a_change_made_in_the_database_is_picked_up_by_the_refresh_loop() -> None:
    service, store = await _bare()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
        service.invalidate()  # the 5 s kill-switch TTL elapsed
        if len(sleeps) == 2:
            raise RuntimeError("stop")

    controller = MaintenanceController(service, MaintenanceGate(), algos=_Algos(), sleep=sleep)
    with pytest.raises(RuntimeError):
        await controller.run()
    assert sleeps == [5.0, 5.0] and controller.gate.engaged


async def test_the_recorder_pauses_only_when_keep_recorder_is_false() -> None:
    writer, store, controller, _, recorder = await _rig()
    await controller.refresh()
    await _toggle(writer, store, MAINTENANCE_MODE, True)
    await _toggle(writer, store, MAINTENANCE_MODE, False)
    assert recorder.calls == []
    await _toggle(writer, store, MAINTENANCE_KEEP_RECORDER, False)
    await _toggle(writer, store, MAINTENANCE_MODE, True)
    await _toggle(writer, store, MAINTENANCE_MODE, False)
    assert recorder.calls == ["pause:maintenance.enabled", "resume:maintenance.disabled"]


async def test_a_failing_algo_cancel_still_closes_the_gate_and_pushes_the_notice() -> None:
    service, store = await _bare()
    sessions = _Sessions()

    class _Broken:
        async def cancel_running_algos(self, reason: str) -> int:
            raise RuntimeError("algo engine down")

    controller = MaintenanceController(service, MaintenanceGate(), algos=_Broken())
    await controller.refresh()
    hook = chain_hooks(controller.on_flag_changed, FlagPush(service, sessions).flag_changed)
    with capture_logs() as logs:
        await _toggle(
            FlagWriter(service, FakeAudit(), on_change=hook), store, MAINTENANCE_MODE, True
        )
    assert controller.gate.engaged
    assert any(f["kind"] == "notice" for f in sessions.frames)
    assert any(e["event"] == "feature_flag_hook_failed" for e in logs)


async def test_without_an_algo_port_the_gap_is_logged() -> None:
    service, store = await _bare()
    controller = MaintenanceController(service, MaintenanceGate())
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    with capture_logs() as logs:
        await controller.refresh()
        await controller.refresh()  # still on: entered once, not twice
    assert [e["event"] for e in logs] == ["maintenance_algo_cancel_unavailable"]


async def test_a_failing_refresh_never_stops_the_loop() -> None:
    service, store = await _bare()
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    calls: list[float] = []

    class _Broken:
        async def cancel_running_algos(self, reason: str) -> int:
            raise RuntimeError("algo engine down")

    async def sleep(seconds: float) -> None:
        calls.append(seconds)
        raise RuntimeError("stop")

    controller = MaintenanceController(service, MaintenanceGate(), algos=_Broken(), sleep=sleep)
    with capture_logs() as logs, pytest.raises(RuntimeError, match="stop"):
        await controller.run()
    assert calls == [5.0] and controller.gate.engaged
    assert "maintenance_refresh_failed" in [e["event"] for e in logs]
