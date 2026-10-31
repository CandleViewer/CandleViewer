"""Aggregated component health (E04-T04, ADR-0014 section 7).

`HealthProbe` implementations are registered per module; a background ticker
refreshes a cached snapshot so request handlers never run probes (the screen
that diagnoses an outage must not deepen it). Probes run concurrently with
per-probe timeouts and isolated failures; `overall` is the worst state by an
explicit rank. `detail` strings are operator-facing: probes must never put
connection strings, credentials or raw exchange payloads in them.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

import structlog

from candleviewer.observability.context import spawn


class ComponentState(StrEnum):
    """Machine-readable state word. Rank: down > warning > degraded > healthy.

    `not_deployed` is honest absence (module not built yet); it ranks as
    `healthy` for `overall` so unbuilt modules do not turn the board red.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    WARNING = "warning"
    DOWN = "down"
    NOT_DEPLOYED = "not_deployed"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK: dict[ComponentState, int] = {
    ComponentState.NOT_DEPLOYED: 0,
    ComponentState.HEALTHY: 0,
    ComponentState.DEGRADED: 1,
    ComponentState.WARNING: 2,
    ComponentState.DOWN: 3,
}


def worst_of(states: Sequence[ComponentState]) -> ComponentState:
    """Worst state; empty or all-not_deployed collapses to `healthy`."""
    worst = ComponentState.HEALTHY
    for s in states:
        if s.rank > worst.rank:
            worst = s
    return worst


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    state: ComponentState
    latency_ms: int
    detail: str
    last_good_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What a probe returns; the runner adds name/latency/last_good_at."""

    state: ComponentState
    detail: str = ""


@runtime_checkable
class HealthProbe(Protocol):
    name: str
    timeout: float

    async def check(self) -> ProbeResult: ...


class NotDeployedProbe:
    """Placeholder for a module that is not built yet."""

    timeout = 1.0

    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> ProbeResult:
        return ProbeResult(ComponentState.NOT_DEPLOYED, "module not deployed")


class CallableProbe:
    """Adapts an async callable returning a `ProbeResult`."""

    def __init__(
        self, name: str, fn: Callable[[], Awaitable[ProbeResult]], timeout: float = 2.0
    ) -> None:
        self.name = name
        self.timeout = timeout
        self._fn = fn

    async def check(self) -> ProbeResult:
        return await self._fn()


#: #1918: hot-tier write-behind health component / `/readyz` check name.
HOT_TIER_WRITE_BEHIND = "hot_tier_write_behind"
#: #1919: ingestion feed health component / `/readyz` check name.
INGESTION = "ingestion"
#: E12-T03: bar builder set health component (`bars_*` state blobs).
BARS = "bars"
#: #2031: bar row writer (`BarWriter.degraded`: rows dropped or buffer saturated).
BARS_WRITER = "bars_writer"

#: Components named by the ticket; unbuilt ones get a `not_deployed` probe.
REQUIRED_COMPONENTS: tuple[str, ...] = (
    "postgres",
    "questdb",
    "parquet_store",
    "bybit_public_ws",
    "bybit_private_ws",
    "bybit_rest",
    "oms",
    "rule_engine",
    "recorder",
    "disk",
)

#: `system_events.component` CHECK values (21-database-schema.md 3.10.2).
EVENT_COMPONENT: dict[str, str] = {
    "postgres": "db",
    "questdb": "db",
    "parquet_store": "db",
    "bybit_public_ws": "exchange",
    "bybit_private_ws": "exchange",
    "bybit_rest": "exchange",
    "oms": "oms",
    "rule_engine": "rules",
    "recorder": "recorder",
    "disk": "api",
    "hot_tier_write_behind": "db",
    "ingestion": "exchange",
    "bars": "bars",
}
_SEVERITY: dict[ComponentState, str] = {
    ComponentState.HEALTHY: "info",
    ComponentState.NOT_DEPLOYED: "info",
    ComponentState.DEGRADED: "warning",
    ComponentState.WARNING: "warning",
    ComponentState.DOWN: "error",
}


@dataclass(frozen=True, slots=True)
class SystemEvent:
    component: str
    kind: str
    severity: str
    message: str
    details: dict[str, str]
    correlation_id: str | None = None


class SystemEventWriter(Protocol):
    async def write(self, event: SystemEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    overall: ComponentState
    components: tuple[ComponentHealth, ...]
    taken_at: datetime


def _log_observer_failed(which: str, exc: Exception) -> None:
    structlog.get_logger(__name__).warning(
        "health_observer_failed", observer=which, error=type(exc).__name__
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class HealthRegistry:
    """Registry + cached concurrent runner with edge-triggered event writes."""

    def __init__(
        self,
        *,
        events: SystemEventWriter | None = None,
        clock: Callable[[], datetime] = _utcnow,
        on_snapshot: Callable[[HealthSnapshot], Awaitable[None]] | None = None,
        probe_deadline_s: float = 1.5,
    ) -> None:
        self._probes: dict[str, HealthProbe] = {}
        self._events = events
        self._clock = clock
        self._on_snapshot = on_snapshot
        self._deadline = probe_deadline_s
        self._last_good: dict[str, datetime] = {}
        self._prev: dict[str, ComponentState] = {}
        self._snapshot: HealthSnapshot | None = None
        self._task: asyncio.Task[None] | None = None
        self._refresh_failing = False  # logs a failure streak once, not every tick
        self.duration_observer: Callable[[str, float], None] | None = None
        self.state_observer: Callable[[str, ComponentState], None] | None = None

    def register(self, probe: HealthProbe) -> None:
        self._probes[probe.name] = probe

    def register_placeholders(self, names: Sequence[str] = REQUIRED_COMPONENTS) -> None:
        for n in names:
            self._probes.setdefault(n, NotDeployedProbe(n))

    def snapshot(self) -> HealthSnapshot | None:
        return self._snapshot

    async def _run_one(self, probe: HealthProbe) -> ComponentHealth:
        start = time.perf_counter()
        limit = min(probe.timeout, self._deadline)
        try:
            res = await asyncio.wait_for(probe.check(), timeout=limit)
        except TimeoutError:
            res = ProbeResult(ComponentState.DEGRADED, "probe timeout")
        except Exception as exc:  # isolation: never leak exception text
            res = ProbeResult(ComponentState.DOWN, f"probe error: {type(exc).__name__}")
        elapsed = time.perf_counter() - start
        now = self._clock()
        if res.state in (ComponentState.HEALTHY, ComponentState.NOT_DEPLOYED):
            self._last_good[probe.name] = now
        if self.duration_observer is not None:
            try:
                self.duration_observer(probe.name, elapsed)
            except Exception as exc:  # a metrics hook must not fail the probe or the refresh
                _log_observer_failed("duration", exc)
        return ComponentHealth(
            name=probe.name,
            state=res.state,
            latency_ms=int(elapsed * 1000),
            detail=res.detail,
            last_good_at=self._last_good.get(probe.name),
        )

    async def refresh(self) -> HealthSnapshot:
        probes = list(self._probes.values())
        results = await asyncio.gather(*(self._run_one(p) for p in probes))
        snap = HealthSnapshot(
            overall=worst_of([r.state for r in results]),
            components=tuple(results),
            taken_at=self._clock(),
        )
        await self._record_transitions(results)
        self._snapshot = snap
        if self._on_snapshot is not None:
            # publisher failure must not stop the ticker
            with contextlib.suppress(Exception):
                await self._on_snapshot(snap)
        return snap

    async def _record_transitions(self, results: Sequence[ComponentHealth]) -> None:
        for r in results:
            if self.state_observer is not None:
                try:
                    self.state_observer(r.name, r.state)
                except Exception as exc:  # a metrics hook must not freeze the snapshot
                    _log_observer_failed("state", exc)
            prev = self._prev.get(r.name)
            self._prev[r.name] = r.state
            if prev is None or prev == r.state or self._events is None:
                continue  # edge-triggered: first observation and steady state write nothing
            recovered = r.state == ComponentState.HEALTHY
            detail = f": {r.detail}" if r.detail else ""
            event = SystemEvent(
                component=EVENT_COMPONENT.get(r.name, "api"),
                kind="health_recovered" if recovered else "health_degraded",
                severity=_SEVERITY[r.state],
                message=f"{r.name} {prev.value} -> {r.state.value}{detail}",
                details={"probe": r.name, "from": prev.value, "to": r.state.value},
            )
            # event sink failure must not break probing
            with contextlib.suppress(Exception):
                await self._events.write(event)

    def start(self, interval_s: float = 1.0) -> None:
        if self._task is None:
            self._task = spawn(self._loop(interval_s), name="health-probe-ticker")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _mark_refresh_failed(self) -> None:
        """Stop serving a stale HEALTHY snapshot as current after a failed refresh.

        Reuses the module's existing vocabulary: a probe that cannot answer is reported
        DEGRADED (as for a timeout), so overall is raised to at least DEGRADED. Components and
        `taken_at` stay as last observed (honest about what was measured); the next successful
        refresh replaces the snapshot and clears the flag. No snapshot yet means the endpoint
        already has nothing to serve. The marked snapshot is published too, so WS clients do not
        keep the last healthy frame.
        """
        snap = self._snapshot
        if snap is None:
            return
        marked = replace(snap, overall=worst_of([snap.overall, ComponentState.DEGRADED]))
        if marked == snap:
            return
        self._snapshot = marked
        if self._on_snapshot is not None:
            with contextlib.suppress(Exception):  # publisher failure must not stop the ticker
                await self._on_snapshot(marked)

    async def _loop(self, interval_s: float) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as exc:  # CancelledError is BaseException and still propagates
                if not self._refresh_failing:
                    structlog.get_logger(__name__).error(
                        "health_refresh_failed", error=type(exc).__name__
                    )
                self._refresh_failing = True
                await self._mark_refresh_failed()
            else:
                self._refresh_failing = False
            await asyncio.sleep(interval_s)
