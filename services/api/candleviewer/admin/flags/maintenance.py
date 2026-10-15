"""Maintenance mode control plane (E42-T03, module M21).

Enforcement is synchronous code, never a statechart (C-2.21): `MaintenanceGate` is a
process-wide boolean that the order-acceptance check (`api.order_entry_gate`) consults before
any OMS work, so refusing orders is structural, not best effort. The gate is engaged while
`maintenance.mode` **or** `killswitch.order_entry` is on, and while either is unknown: it starts
engaged and stays engaged when the store cannot be read (fail closed, D1).

`MaintenanceController` keeps the gate in step:
- `gate_hook` runs first on `FlagWriter`'s change hook, from the committed row, so a write that
  turns maintenance on closes the gate before the write returns; the push runs next, and
  `effects_hook` last, so a slow side effect never delays the notice;
- `run` re-reads both flags with a fresh store read every `REFRESH_S` (5 s), so a change made
  directly in the database is applied within 5 s without a restart;
- the gate is applied without waiting on anything: a write bumps a generation, and a poll that
  read before that write drops its reading instead of overwriting the newer committed value;
  polls and side effects are serialised by one lock.

Side effects run only on a value actually read as `True` from the store or committed by a write,
never on the fail-closed reading: entering maintenance cancels running emulated algos through
`AlgoCanceller` and pauses the recorder only when `maintenance.keep_recorder` is false. Each has
a timeout, and an entry that fails is retried on the next poll. Native exchange stop-losses are
never touched: no port here can reach them (C-2.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

import structlog

from candleviewer.admin.flags.catalogue import MAINTENANCE_KEEP_RECORDER, MAINTENANCE_MODE
from candleviewer.admin.flags.metrics import maintenance_mode_gauge
from candleviewer.admin.flags.resolver import StoredFlag, resolve
from candleviewer.admin.flags.service import KILLSWITCH_TTL_S, FlagService
from candleviewer.admin.flags.writes import ChangeHook

KILL_ORDER_ENTRY: Final = "killswitch.order_entry"
GATE_FLAGS: Final = (MAINTENANCE_MODE, KILL_ORDER_ENTRY)
REFRESH_S: Final = KILLSWITCH_TTL_S
EFFECT_TIMEOUT_S: Final = 5.0


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class OrderEntryPausedError(Exception):
    """Order acceptance is refused while the gate is engaged (`403 trading_disabled`)."""


class MaintenanceGate:
    """Synchronous and lock-free: one boolean, read on every order acceptance."""

    def __init__(self) -> None:
        self._engaged = True  # engaged until both flags have been read (fail closed)
        maintenance_mode_gauge.set(1)

    @property
    def engaged(self) -> bool:
        return self._engaged

    def set(self, engaged: bool) -> None:
        self._engaged = engaged
        maintenance_mode_gauge.set(1 if engaged else 0)

    def check(self) -> None:
        if self._engaged:
            raise OrderEntryPausedError("order entry is paused")


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
        effect_timeout_s: float = EFFECT_TIMEOUT_S,
    ) -> None:
        self._service, self.gate = service, gate
        self._algos, self._recorder, self._sleep = algos, recorder, sleep
        self._timeout = effect_timeout_s
        self._lock = asyncio.Lock()
        self._generation = 0
        #: `None` = unknown, which keeps the gate engaged.
        self._values: dict[str, bool | None] = dict.fromkeys(GATE_FLAGS)
        self._entered = False
        self._recorder_paused = False

    def _apply(self) -> None:
        self.gate.set(any(value is not False for value in self._values.values()))

    async def gate_hook(self, key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        if key in self._values:  # no await: applied before the write returns
            self._generation += 1
            self._values[key] = after.value is True
            self._apply()

    async def effects_hook(self, key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        if key == MAINTENANCE_MODE:
            async with self._lock:
                await self._effects(after.value is True)

    async def refresh(self) -> None:
        async with self._lock:
            generation = self._generation
            self._service.invalidate()  # one fresh load for both flags
            readings: dict[str, bool | None] = {}
            for key in GATE_FLAGS:
                spec = self._service.registry[key]
                stored = await self._service.stored(spec)
                readings[key] = (
                    None if stored is None else bool(resolve(spec, stored, user_id=None))
                )
            if generation == self._generation:  # a write applied meanwhile is newer: keep it
                self._values.update(readings)
                self._apply()
            maintenance = self._values[MAINTENANCE_MODE]
            if maintenance is None:
                logger().warning("maintenance_store_unavailable")  # engaged; no side effect
                return
            await self._effects(maintenance)

    async def _effects(self, on: bool) -> None:
        if on and not self._entered:
            await self._enter()
            self._entered = True  # only after every entry effect succeeded
        elif not on:
            self._entered = False
            if self._recorder_paused and self._recorder is not None:
                async with asyncio.timeout(self._timeout):
                    await self._recorder.resume("maintenance.disabled")
                self._recorder_paused = False

    async def _enter(self) -> None:
        if self._algos is None:
            logger().warning("maintenance_algo_cancel_unavailable")
        else:
            async with asyncio.timeout(self._timeout):
                cancelled = await self._algos.cancel_running_algos("maintenance.enabled")
            logger().info("maintenance_algos_cancelled", count=cancelled)
        keep = bool(await self._service.value(MAINTENANCE_KEEP_RECORDER))
        if not keep and not self._recorder_paused and self._recorder is not None:
            async with asyncio.timeout(self._timeout):
                await self._recorder.pause("maintenance.enabled")
            self._recorder_paused = True

    async def run(self) -> None:
        """Re-read both flags every `REFRESH_S` until cancelled (a supervised task)."""
        while True:
            try:
                await self.refresh()
            except Exception:  # a failed side effect must not stop the poll; retried next tick
                logger().exception("maintenance_refresh_failed")
            await self._sleep(REFRESH_S)


def chain_hooks(*hooks: ChangeHook) -> ChangeHook:
    """One `FlagWriter` change hook running `hooks` in order (gate, then push, then effects).
    A failing hook is logged and the next still runs."""

    async def chained(key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        for hook in hooks:
            try:
                await hook(key, before, after)
            except Exception:
                logger().exception("feature_flag_hook_failed", key=key)

    return chained
