"""Maintenance mode control plane (E42-T03, module M21).

`maintenance.mode` is a kill-switch-class flag. Enforcement is synchronous code, never a
statechart (C-2.21): `MaintenanceGate` is a process-wide boolean that the order-acceptance
dependency consults before any OMS work, so refusing orders is structural, not best effort.

`MaintenanceController` keeps the gate in step with the flag:
- `on_flag_changed` is chained before the push on `FlagWriter`'s change hook, so a write that
  turns maintenance on closes the gate before the write returns (the 200 ms bound);
- `run` re-reads the flag at least every 5 s, so a change made directly in the database (or by
  another process) is picked up without a restart;
- the gate starts closed and stays closed while the store cannot be read: the flag's
  restrictive value is "engaged" (fail closed).

Turning maintenance on cancels running emulated algos through `AlgoCanceller` and pauses the
recorder only when `maintenance.keep_recorder` is false. Native exchange stop-losses are never
touched: no port here can reach them (C-2.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

import structlog

from candleviewer.admin.flags.catalogue import MAINTENANCE_KEEP_RECORDER, MAINTENANCE_MODE
from candleviewer.admin.flags.service import KILLSWITCH_TTL_S, FlagService
from candleviewer.observability.metrics import Gauge

maintenance_mode_gauge = Gauge("cv_maintenance_mode", "1 while maintenance mode is on, else 0.")
REFRESH_S: Final = KILLSWITCH_TTL_S


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class OrderEntryPausedError(Exception):
    """Order acceptance is refused while maintenance mode is on (`403 trading_disabled`)."""


class MaintenanceGate:
    """Synchronous and lock-free: one boolean, read on every order acceptance."""

    def __init__(self) -> None:
        self._engaged = True  # closed until the flag has been read (fail closed)

    @property
    def engaged(self) -> bool:
        return self._engaged

    def set(self, engaged: bool) -> None:
        self._engaged = engaged
        maintenance_mode_gauge.set(1 if engaged else 0)

    def check(self) -> None:
        if self._engaged:
            raise OrderEntryPausedError("maintenance mode is on")


class AlgoCanceller(Protocol):
    async def cancel_running_algos(self, reason: str) -> int:
        """Cancel every running emulated algo (B4-B7); never a native exchange stop."""


class RecorderControl(Protocol):
    async def pause(self, reason: str) -> None: ...

    async def resume(self, reason: str) -> None: ...


class MaintenanceController:
    def __init__(
        self,
        service: FlagService,
        gate: MaintenanceGate,
        *,
        algos: AlgoCanceller | None = None,
        recorder: RecorderControl | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._service, self.gate = service, gate
        self._algos, self._recorder, self._sleep = algos, recorder, sleep
        self._recorder_paused = False
        self._entered = False

    async def on_flag_changed(self, key: str) -> None:
        if key == MAINTENANCE_MODE:
            await self.refresh()

    async def refresh(self) -> None:
        engaged = bool(await self._service.value(MAINTENANCE_MODE))
        self.gate.set(engaged)
        if engaged and not self._entered:
            self._entered = True  # the gate's fail-closed start is not an entry; this is
            await self._enter()
        elif not engaged:
            self._entered = False
            if self._recorder_paused and self._recorder is not None:
                await self._recorder.resume("maintenance.disabled")
                self._recorder_paused = False

    async def _enter(self) -> None:
        if self._algos is None:
            logger().warning("maintenance_algo_cancel_unavailable")
        else:
            cancelled = await self._algos.cancel_running_algos("maintenance.enabled")
            logger().info("maintenance_algos_cancelled", count=cancelled)
        keep = bool(await self._service.value(MAINTENANCE_KEEP_RECORDER))
        if not keep and self._recorder is not None:
            await self._recorder.pause("maintenance.enabled")
            self._recorder_paused = True

    async def run(self) -> None:
        """Re-read the flag every `REFRESH_S` until cancelled (a supervised task)."""
        while True:
            try:
                await self.refresh()
            except Exception:  # a failed side effect must not stop the refresh loop
                logger().exception("maintenance_refresh_failed")
            await self._sleep(REFRESH_S)


def chain_hooks(*hooks: Callable[[str], Awaitable[None]]) -> Callable[[str], Awaitable[None]]:
    """One `FlagWriter` change hook running `hooks` in order (the gate first, then the push).
    A failing hook is logged and the next still runs, so a failed algo cancel never stops the
    maintenance notice."""

    async def chained(key: str) -> None:
        for hook in hooks:
            try:
                await hook(key)
            except Exception:
                logger().exception("feature_flag_hook_failed", key=key)

    return chained
