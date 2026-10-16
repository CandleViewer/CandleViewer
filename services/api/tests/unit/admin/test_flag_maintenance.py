"""E42-T03: maintenance mode refuses order acceptance before any OMS work once the write returns,
notifies every session, cancels emulated algos only on a real `True`, retries a failed entry,
and keeps the gate in step with the database through fresh polls."""

from __future__ import annotations

import asyncio
import inspect
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
    FlagValue,
    FlagWriter,
    MaintenanceController,
    MaintenanceGate,
    chain_hooks,
    default_registry,
)
from candleviewer.admin.flags.maintenance import EFFECT_TIMEOUT_S, REFRESH_S
from candleviewer.admin.flags.metrics import EXPORTED_NAMES, maintenance_mode_gauge
from candleviewer.admin.flags.push import FlagPush, Session
from candleviewer.admin.flags.writes import WRITE_AWAIT_TIMEOUT_S
from candleviewer.api.order_entry_gate import OrderEntryGate, order_entry_refusal
from candleviewer.audit.access import AuditPrincipal
from tests.unit.admin.flag_fakes import Clock, FakeAudit, FakeFlagStore, FakeStepUp, FakeUsers

_OWNER = AuditPrincipal(user_id=UUID(int=1), username="owner", permissions=frozenset({"*"}))
_ACCOUNT = UUID(int=2)


class _Algos:
    def __init__(self, failures: int = 0, hang: bool = False) -> None:
        self.calls: list[str] = []
        self.failures, self.hang = failures, hang

    async def cancel_running_algos(self, reason: str) -> int:
        self.calls.append(reason)
        if self.hang:
            await asyncio.Event().wait()
        if self.failures:
            self.failures -= 1
            raise RuntimeError("algo engine down")
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
        return [Session(_OWNER.user_id, frozenset({"owner"}), self.frames.append)]


class _Rig:
    def __init__(
        self, algos: _Algos | None = None, effect_timeout_s: float = EFFECT_TIMEOUT_S
    ) -> None:
        self.store, self.clock, self.sessions = FakeFlagStore(), Clock(), _Sessions()
        self.service = FlagService(default_registry(), self.store, clock=self.clock)
        self.algos, self.recorder, self.audit = algos or _Algos(), _Recorder(), FakeAudit()
        self.sleeps: list[float] = []
        push = FlagPush(self.service, self.sessions)
        self.controller = MaintenanceController(
            self.service,
            MaintenanceGate(),
            notify=push.notify_maintenance,
            audit=self.audit,
            algos=self.algos,
            recorder=self.recorder,
            sleep=self._sleep,
            effect_timeout_s=effect_timeout_s,
        )
        hook = chain_hooks(
            self.controller.gate_hook, push.flag_changed, self.controller.effects_hook
        )
        self.writer = FlagWriter(
            self.service, self.audit, FakeStepUp(), FakeUsers(), on_change=hook
        )
        self.stop_after = 1

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.now += seconds
        if len(self.sleeps) >= self.stop_after:
            raise asyncio.CancelledError

    async def start(self) -> _Rig:
        await self.store.ensure(self.service.registry.values())
        await self.controller.refresh()
        return self

    async def toggle(self, key: str, value: bool) -> None:
        await self.writer.set(
            key,
            _OWNER,
            value=value,
            reason="maintenance window",
            expected_updated_at=self.store.rows[key].updated_at,
        )

    def db(self, key: str, value: FlagValue) -> None:
        self.store.rows[key] = replace(self.store.rows[key], value=value)

    def announced(self) -> list[tuple[str, str]]:
        """Every maintenance notice reason and `maintenance.*` audit actor, in order."""
        notices = [("notice", f["reason"]) for f in self.sessions.frames if f["kind"] == "notice"]
        audits = [(a, r["actor_label"]) for a, r in self.audit.records if a.startswith("maint")]
        return notices + audits


def _orders_app(gate: MaintenanceGate, oms_calls: list[str]) -> FastAPI:
    app, entry_gate = FastAPI(), OrderEntryGate(gate)

    @app.post("/orders")
    async def accept() -> JSONResponse:
        refused = order_entry_refusal(entry_gate, _ACCOUNT)
        if refused is not None:
            return refused
        oms_calls.append("submit")
        return JSONResponse({"accepted": True}, status_code=202)

    return app


async def test_orders_are_refused_right_after_the_write_returns_before_any_oms_work() -> None:
    rig = await _Rig().start()
    oms: list[str] = []
    transport = httpx.ASGITransport(app=_orders_app(rig.controller.gate, oms))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/orders")).status_code == 202
        await rig.toggle(MAINTENANCE_MODE, True)
        refused = await client.post("/orders")
    body = refused.json()
    assert (refused.status_code, body["code"]) == (403, "trading_disabled")
    assert (body["reason"], body["title"]) == ("maintenance", "Order entry refused")  # D5a
    assert oms == ["submit"]


@pytest.mark.perf
async def test_orders_are_refused_within_200_ms_of_the_write() -> None:
    rig = await _Rig().start()
    transport = httpx.ASGITransport(app=_orders_app(rig.controller.gate, []))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.monotonic()
        await rig.toggle(MAINTENANCE_MODE, True)
        assert (await client.post("/orders")).status_code == 403
        assert time.monotonic() - start < 0.2


async def test_entering_maintenance_cancels_algos_and_notifies_once() -> None:
    rig = await _Rig().start()
    await rig.toggle(MAINTENANCE_MODE, True)
    await rig.controller.refresh()  # the poll never re-announces a written transition
    assert rig.algos.calls == ["maintenance.enabled"]
    assert rig.announced() == [("notice", "maintenance.enabled"), ("maintenance.enabled", "owner")]


async def test_a_boot_that_finds_maintenance_on_announces_it_once() -> None:
    rig = _Rig()
    await rig.store.ensure(rig.service.registry.values())
    rig.db(MAINTENANCE_MODE, True)
    await rig.controller.refresh()  # boot: unknown to a stored true is a transition (D1c)
    await rig.controller.refresh()
    assert rig.algos.calls == ["maintenance.enabled"]
    enabled = [("notice", "maintenance.enabled"), ("maintenance.enabled", "system:maintenance")]
    assert rig.announced() == enabled


async def test_a_failed_announcement_audit_is_logged_and_the_poll_goes_on() -> None:
    rig = _Rig()
    await rig.store.ensure(rig.service.registry.values())
    rig.db(MAINTENANCE_MODE, True)
    rig.audit.emit = _raise  # type: ignore[method-assign]  # the audit store is down
    with capture_logs() as logs:
        await rig.controller.refresh()
    assert rig.controller.gate.engaged and rig.algos.calls == ["maintenance.enabled"]
    assert "maintenance_audit_failed" in [e["event"] for e in logs]


async def _raise(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("audit unavailable")


async def _hang(*args: Any, **kwargs: Any) -> None:
    await asyncio.Event().wait()


async def test_a_stalled_announcement_audit_is_cut_by_the_budget_and_the_poll_goes_on() -> None:
    rig = _Rig(effect_timeout_s=0.001)
    await rig.store.ensure(rig.service.registry.values())
    rig.db(MAINTENANCE_MODE, True)
    rig.audit.emit = _hang  # type: ignore[method-assign]  # the audit store stalls
    with capture_logs() as logs:
        async with asyncio.timeout(5):  # a missing bound fails here instead of hanging the suite
            await rig.controller.refresh()
    assert rig.controller.gate.engaged and rig.algos.calls == ["maintenance.enabled"]
    assert "maintenance_audit_failed" in [e["event"] for e in logs]


async def test_a_database_release_is_announced_and_unknown_or_false_readings_are_not() -> None:
    rig = await _Rig().start()  # boot reads false: nothing to announce
    rig.store.down = True
    await rig.controller.refresh()
    rig.store.down, rig.clock.now = False, rig.clock.now + 1  # the store's 1 s retry
    rig.db(MAINTENANCE_MODE, "on")  # an unreadable row
    await rig.controller.refresh()
    assert rig.announced() == [] and rig.controller.gate.engaged
    rig.db(MAINTENANCE_MODE, True)
    await rig.controller.refresh()
    rig.db(MAINTENANCE_MODE, False)
    await rig.controller.refresh()
    assert [a for a in rig.announced() if a[0] != "notice"] == [
        ("maintenance.enabled", "system:maintenance"),
        ("maintenance.disabled", "system:maintenance"),
    ]


async def test_the_gate_starts_engaged_and_opens_once_both_flags_are_read() -> None:
    assert MaintenanceGate().refusal(_ACCOUNT) is not None
    rig = await _Rig().start()
    assert rig.controller.gate.refusal(_ACCOUNT) is None
    assert not rig.controller.gate.engaged


async def test_the_order_kill_switch_also_engages_the_gate() -> None:
    rig = await _Rig().start()
    await rig.toggle("killswitch.order_entry", True)
    assert rig.controller.gate.engaged
    assert rig.algos.calls == []


@pytest.mark.parametrize("outage", [True, False])
async def test_a_fail_closed_reading_engages_the_gate_without_side_effects(outage: bool) -> None:
    rig = await _Rig().start()
    rig.store.down = outage
    rig.db(MAINTENANCE_MODE, True if outage else "on")  # an outage, or one unreadable row
    with capture_logs() as logs:
        await rig.controller.refresh()
    assert rig.controller.gate.engaged
    assert rig.algos.calls == [] and rig.recorder.calls == []
    assert "maintenance_state_unknown" in [e["event"] for e in logs]


async def test_a_database_change_is_picked_up_by_the_next_poll() -> None:
    rig = await _Rig().start()
    rig.db(MAINTENANCE_MODE, True)
    with pytest.raises(asyncio.CancelledError):
        await rig.controller.run()
    assert rig.sleeps == [REFRESH_S]
    assert rig.controller.gate.engaged and rig.algos.calls == ["maintenance.enabled"]


async def test_a_poll_that_read_before_a_write_never_overwrites_it() -> None:
    rig = await _Rig().start()
    rig.store.hold = asyncio.Event()
    poll = asyncio.create_task(rig.controller.refresh())
    await asyncio.sleep(0)
    rig.store.hold.set()
    rig.store.hold = None
    await rig.controller.gate_hook(
        MAINTENANCE_MODE, None, replace(rig.store.rows[MAINTENANCE_MODE], value=True)
    )
    await poll
    assert rig.controller.gate.engaged


async def test_a_failed_entry_is_retried_on_the_next_poll() -> None:
    rig = await _Rig(algos=_Algos(failures=1)).start()
    rig.db(MAINTENANCE_MODE, True)
    rig.stop_after = 2
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await rig.controller.run()
    assert rig.algos.calls == ["maintenance.enabled", "maintenance.enabled"]
    assert "maintenance_refresh_failed" in [e["event"] for e in logs]


async def test_a_hung_algo_engine_is_cut_by_its_own_budget_and_retried_by_the_next_poll() -> None:
    assert 2 * EFFECT_TIMEOUT_S <= WRITE_AWAIT_TIMEOUT_S  # fits if the store and lock are prompt
    default = inspect.signature(MaintenanceController).parameters["effect_timeout_s"].default
    assert default == EFFECT_TIMEOUT_S  # the controller built without an argument follows it
    rig = await _Rig(algos=_Algos(hang=True), effect_timeout_s=0.001).start()
    with capture_logs() as logs:
        await rig.toggle(MAINTENANCE_MODE, True)  # the write returns and the notice is out
    assert rig.controller.gate.engaged
    assert any(f["kind"] == "notice" for f in rig.sessions.frames)
    assert "feature_flag_hook_failed" in [e["event"] for e in logs]  # cut by its own budget
    rig.algos.hang = False
    await rig.controller.refresh()  # the next poll retries the entry the budget cut
    assert rig.algos.calls == ["maintenance.enabled"] * 2


async def test_the_recorder_pauses_only_when_keep_recorder_is_false() -> None:
    rig = await _Rig().start()
    await rig.toggle(MAINTENANCE_MODE, True)
    await rig.toggle(MAINTENANCE_MODE, False)
    assert rig.recorder.calls == []
    await rig.toggle(MAINTENANCE_KEEP_RECORDER, False)
    await rig.toggle(MAINTENANCE_MODE, True)
    await rig.toggle(MAINTENANCE_MODE, False)
    assert rig.recorder.calls == ["pause:maintenance.enabled", "resume:maintenance.disabled"]


async def test_without_an_algo_port_the_gap_is_logged_once() -> None:
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    controller = MaintenanceController(
        service, MaintenanceGate(), notify=lambda on: None, audit=FakeAudit()
    )
    with capture_logs() as logs:
        await controller.refresh()
        await controller.refresh()
    assert [e["event"] for e in logs] == ["maintenance_algo_cancel_unavailable"]


async def test_the_gate_gauge_is_exported_and_follows_the_gate() -> None:
    assert "cv_maintenance_mode" in EXPORTED_NAMES
    rig = await _Rig().start()
    await rig.toggle(MAINTENANCE_MODE, True)
    assert maintenance_mode_gauge._value.get() == 1
    await rig.toggle(MAINTENANCE_MODE, False)
    assert maintenance_mode_gauge._value.get() == 0
