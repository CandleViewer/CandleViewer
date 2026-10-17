"""Composition helpers for E04-T04 health: event writer, WS publisher, real probes.

QA #1668. Kept out of `health_probes` so that module stays I/O-free. Probe
`detail` strings never include DSNs, hosts or raw exception text.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import insert, select, text

from candleviewer.bus.models import Topic
from candleviewer.db.models import system_events
from candleviewer.ingestion.connection import PHASE_OPEN, ConnectionManager
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.health_probes import (
    BARS,
    BARS_WRITER,
    HOT_TIER_WRITE_BEHIND,
    INGESTION,
    CallableProbe,
    ComponentHealth,
    ComponentState,
    HealthRegistry,
    HealthSnapshot,
    ProbeResult,
    SystemEvent,
)
from candleviewer.storage.repositories.incident_grouping import (
    INCIDENT_SEVERITIES,
    incident_occurrence,
)
from candleviewer.storage.repositories.incidents_sqlalchemy import record_occurrence


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


_DISK_WARN = 0.90
_DISK_DOWN = 0.97


class _UowFactory(Protocol):
    def unit_of_work(self) -> Any: ...


class _Publisher(Protocol):
    async def publish(self, topic: Topic, event: Any) -> None: ...


#: The audit serializer `system_events.details` pass through, injected by the composition root
#: (`candleviewer.admin.wiring.system_event_redactor`): this module may not import M19 (C-3.3).
DetailsRedactor = Callable[[dict[str, Any]], dict[str, Any] | None]


class PgSystemEventWriter:
    """Persists one `system_events` row per event (a health state transition, a TOTP clock skew).

    E42-T05: `details` pass through the same redaction serializer as audit
    (`24-internal-schemas.md` 15.4), and an `error` or `critical` event materialises its incident
    in the same unit of work (`21-database-schema.md` 3.10.2a): the event row and its incident
    commit together or not at all, the incident stamped with the row's own `event_ts`. The
    normalising and redacting are done before the transaction opens."""

    def __init__(self, repo: _UowFactory, *, redact_details: DetailsRedactor) -> None:
        self._repo = repo
        self._redact_details = redact_details

    async def write(self, event: SystemEvent) -> None:
        details = self._redact_details(dict(event.details)) or {}
        incident = (
            incident_occurrence(
                component=event.component,
                kind=event.kind,
                severity=event.severity,
                message=event.message,
            )
            if event.severity in INCIDENT_SEVERITIES
            else None
        )
        async with self._repo.unit_of_work() as uow:
            row = await uow.session.execute(
                insert(system_events)
                .values(
                    component=event.component,
                    kind=event.kind,
                    severity=event.severity,
                    message=event.message,
                    details=details,
                    correlation_id=event.correlation_id,
                )
                .returning(system_events.c.event_ts)
            )
            if incident is not None:
                await record_occurrence(uow.session, incident, seen_at=row.scalar_one())
            await uow.commit()


class PgSystemEventReader:
    """Reads `system_events` rows in a window (E04-S02 support bundle), newest first."""

    def __init__(self, repo: _UowFactory) -> None:
        self._repo = repo

    async def __call__(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        async with self._repo.unit_of_work() as uow:
            res = await uow.session.execute(
                select(
                    system_events.c.event_ts,
                    system_events.c.component,
                    system_events.c.kind,
                    system_events.c.severity,
                    system_events.c.message,
                )
                .where(system_events.c.event_ts.between(start, end))
                .order_by(system_events.c.event_ts.desc())
                .limit(5000)
            )
            return [
                {
                    "event_ts": r.event_ts.isoformat(),
                    "component": r.component,
                    "kind": r.kind,
                    "severity": str(r.severity),
                    "message": r.message,
                }
                for r in res
            ]


def _exchange_word(c: ComponentHealth | None) -> str:
    if c is None or c.state is ComponentState.NOT_DEPLOYED:
        return "not_deployed"
    return "connected" if c.state is ComponentState.HEALTHY else c.state.value


class HealthSystemPublisher:
    """Publishes the `health`/`exchange` block to `{env}.system` per snapshot."""

    def __init__(self, bus: _Publisher, env: str) -> None:
        self._bus = bus
        self._topic = Topic(env=env, domain="system")

    async def __call__(self, snap: HealthSnapshot) -> None:
        by_name = {c.name: c for c in snap.components}
        payload: dict[str, object] = {
            "kind": "health",
            "health": snap.overall.value,
            "exchange": {
                "public_ws": _exchange_word(by_name.get("bybit_public_ws")),
                "private_ws": _exchange_word(by_name.get("bybit_private_ws")),
                "rest": _exchange_word(by_name.get("bybit_rest")),
            },
            # None until E08 time sync lands; never a fabricated 0.
            "clock_offset_ms": None,
        }
        await self._bus.publish(self._topic, payload)


def register_real_probes(
    registry: HealthRegistry,
    *,
    pg_repo: _UowFactory,
    questdb_host: str,
    questdb_port: int,
    parquet_root: str,
    disk_path: str,
) -> None:
    """Replace placeholders for postgres/questdb/parquet_store/disk."""
    # Resolved once: a CWD-relative probe would measure whichever volume the CWD is on.
    abs_disk_path = os.path.abspath(disk_path)

    async def postgres() -> ProbeResult:
        try:
            async with pg_repo.unit_of_work() as uow:
                await uow.session.execute(text("SELECT 1"))
        except Exception:
            return ProbeResult(ComponentState.DOWN, "postgres unreachable")
        return ProbeResult(ComponentState.HEALTHY)

    async def questdb() -> ProbeResult:
        try:
            _r, w = await asyncio.wait_for(
                asyncio.open_connection(questdb_host, questdb_port), timeout=1.0
            )
        except Exception:
            return ProbeResult(ComponentState.DOWN, "questdb unreachable")
        w.close()
        return ProbeResult(ComponentState.HEALTHY)

    async def parquet() -> ProbeResult:
        ok = await asyncio.to_thread(lambda: os.path.isdir(parquet_root))
        if not ok:
            return ProbeResult(ComponentState.DOWN, "parquet root missing")
        return ProbeResult(ComponentState.HEALTHY)

    async def disk() -> ProbeResult:
        try:
            u = await asyncio.to_thread(shutil.disk_usage, abs_disk_path)
        except OSError:
            return ProbeResult(ComponentState.DOWN, "disk path unavailable")
        ratio = u.used / u.total if u.total else 1.0
        detail = f"used {ratio * 100:.0f}%"
        if ratio >= _DISK_DOWN:
            return ProbeResult(ComponentState.DOWN, detail)
        if ratio >= _DISK_WARN:
            return ProbeResult(ComponentState.WARNING, detail)
        return ProbeResult(ComponentState.HEALTHY, detail)

    for name, fn in (
        ("postgres", postgres),
        ("questdb", questdb),
        ("parquet_store", parquet),
        ("disk", disk),
    ):
        registry.register(CallableProbe(name, fn, timeout=1.5))


class WriteBehindLike(Protocol):
    """Structural view of `ingestion.write_behind.WriteBehindBuffer` (#1918)."""

    @property
    def degraded(self) -> bool: ...

    @property
    def evicted(self) -> int: ...


def hot_tier_write_behind_state(buffers: Sequence[WriteBehindLike]) -> ProbeResult:
    """#1918: degraded (never down — ingest stays live) while any hot-tier
    write-behind is failing; the detail names evictions so lost rows show."""
    failing = sum(1 for b in buffers if b.degraded)
    evicted = sum(b.evicted for b in buffers)
    if not buffers:
        return ProbeResult(ComponentState.NOT_DEPLOYED, "ingestion not wired")
    if failing:
        return ProbeResult(
            ComponentState.DEGRADED, f"{failing} writer(s) retrying; evicted {evicted}"
        )
    return ProbeResult(ComponentState.HEALTHY, f"evicted {evicted}")


def register_write_behind_probe(
    registry: HealthRegistry, buffers: Callable[[], Sequence[WriteBehindLike]]
) -> None:
    async def probe() -> ProbeResult:
        return hot_tier_write_behind_state(buffers())

    registry.register(CallableProbe(HOT_TIER_WRITE_BEHIND, probe, timeout=1.0))


def ingestion_state(report: HealthReport) -> ProbeResult:
    """#1919: DEGRADED (never down) while the feed is impaired; detail = reason tokens."""
    if report.status is HealthStatus.STOPPED:
        return ProbeResult(ComponentState.NOT_DEPLOYED, "ingestion stopped")
    if report.status is HealthStatus.DEGRADED:
        return ProbeResult(ComponentState.DEGRADED, report.detail)
    return ProbeResult(ComponentState.HEALTHY)


def register_ingestion_probe(registry: HealthRegistry, health: Callable[[], HealthReport]) -> None:
    async def probe() -> ProbeResult:
        return ingestion_state(health())

    registry.register(CallableProbe(INGESTION, probe, timeout=1.0))


#: E27-T02: M2 component; DOWN while the KEK is unavailable (trading latched off).
SECRETS = "secrets"


def register_secrets_probe(registry: HealthRegistry, health: Callable[[], HealthReport]) -> None:
    async def probe() -> ProbeResult:
        report = health()
        if report.status is HealthStatus.DEGRADED:
            return ProbeResult(ComponentState.DOWN, report.detail)
        if report.status is HealthStatus.STOPPED:
            return ProbeResult(ComponentState.NOT_DEPLOYED, "secrets stopped")
        return ProbeResult(ComponentState.HEALTHY, "")

    registry.register(CallableProbe(SECRETS, probe, timeout=1.0))


def register_bars_probe(registry: HealthRegistry, health: Callable[[], HealthReport]) -> None:
    """E12-T03: `bars` component. DEGRADED with a `BarsHealthReason` token when a state blob
    was discarded and its series cold-started; same mapping as ingestion (#1919)."""

    async def probe() -> ProbeResult:
        report = health()
        if report.status is HealthStatus.STOPPED:
            return ProbeResult(ComponentState.NOT_DEPLOYED, "bars stopped")
        if report.status is HealthStatus.DEGRADED:
            return ProbeResult(ComponentState.DEGRADED, report.detail)
        return ProbeResult(ComponentState.HEALTHY)

    registry.register(CallableProbe(BARS, probe, timeout=1.0))


def register_bars_writer_probe(
    registry: HealthRegistry, state: Callable[[], tuple[bool, str] | None]
) -> None:
    """#2031: `bars_writer`. `state()` is None when bars are not wired (flag off) -> NOT_DEPLOYED;
    else `(degraded, detail)`, DEGRADED with `bars_writer_degraded` after rows were dropped."""

    async def probe() -> ProbeResult:
        current = state()
        if current is None:
            return ProbeResult(ComponentState.NOT_DEPLOYED, "bars not enabled")
        degraded, detail = current
        if degraded:
            return ProbeResult(ComponentState.DEGRADED, detail)
        return ProbeResult(ComponentState.HEALTHY)

    registry.register(CallableProbe(BARS_WRITER, probe, timeout=1.0))


def register_public_ws_probe(
    registry: HealthRegistry, ws: Callable[[], ConnectionManager | None]
) -> None:
    """#1919: `bybit_public_ws` (system topic `exchange.public_ws`) shows the real phase."""

    async def probe() -> ProbeResult:
        mgr = ws()
        if mgr is None:
            return ProbeResult(ComponentState.NOT_DEPLOYED, "public ws not wired")
        phase = mgr.state()
        if phase == PHASE_OPEN:
            return ProbeResult(ComponentState.HEALTHY, phase)
        return ProbeResult(ComponentState.DEGRADED, phase)

    registry.register(CallableProbe("bybit_public_ws", probe, timeout=1.0))
