"""Composition helpers for E04-T04 health: event writer, WS publisher, real probes.

QA #1668. Kept out of `health_probes` so that module stays I/O-free. Probe
`detail` strings never include DSNs, hosts or raw exception text.

The `health` frame (E42-T05, #966 BK-15). `HealthSystemPublisher` builds one per snapshot and hands
it to its `direct_sinks`. `create_app` appends `GatewayHub.broadcast_system` to them, the path of
the mesh gate's notices (`net.system_topic`, E27-T02), so each authenticated socket is sent the
frame cut for its role (`ws.system_filter`, `23-ws-protocol.md` 15.9). Nothing subscribes to the
`{env}.system` bus topic, so the frame is not published there.

How a snapshot becomes a frame is this module's mapping, not the contract's. The frame must be a
valid `system` frame (`cv://ws/v1/system.schema.json`):

- `components[]`: every probe under its `GET /admin/health` name; `not_deployed` is sent as
  `healthy` with the detail `not deployed`; `last_good_at` once there is one. The filter cuts
  `detail` for a Manager or a Viewer.
- `exchange.public_ws` and `exchange.private_ws`: the word of the connection phase a probe reports
  (`register_public_ws_probe`: healthy at `open`, else degraded with the phase as its detail).
  `open` is `connected` and `connecting` is `connecting`; `degraded` (backing off, or blocked by the
  connection budget) and `closed` are `disconnected`. The manager has no phase for a book rebuild,
  so `resyncing` is never sent. A detail that names no phase (a probe timeout, a probe error) says
  nothing of the connection, so it gives no word.
- `exchange.rest`: the word of the component's state: healthy is `healthy`, degraded and warning
  are `degraded`, down is `down`. `rate_limited` is not sent: no probe states it.
- A component that is `not_deployed` or missing leaves its key out, never a made-up
  `disconnected`; with no key left, `exchange` is left out.
- `clock_offset_ms` is an integer in the schema, so it is the measured offset of the ClockGuard
  (`ctx.ingestion.clock`, attached after the app is built, so read when the frame is built) when it
  has one, and left out otherwise: never a null, and never the 0 that `ingestion.clock_offset_ms`
  answers before a guard is attached.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Protocol

import structlog
from sqlalchemy import insert, select, text

from candleviewer.db.models import system_events
from candleviewer.ingestion.connection import (
    PHASE_CLOSED,
    PHASE_CONNECTING,
    PHASE_DEGRADED,
    PHASE_OPEN,
    ConnectionManager,
)
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


#: `ConnectionManager.state()` -> the 15.9 word of `exchange.public_ws` and `private_ws` (the module
#: docstring says why each phase maps as it does).
_WS_WORD: Final[Mapping[str, str]] = MappingProxyType(
    {
        PHASE_OPEN: "connected",
        PHASE_CONNECTING: "connecting",
        PHASE_DEGRADED: "disconnected",
        PHASE_CLOSED: "disconnected",
    }
)
#: A component's state -> the 15.9 word of `exchange.rest`. `not_deployed` is absence: no word.
_REST_WORD: Final[Mapping[ComponentState, str]] = MappingProxyType(
    {
        ComponentState.HEALTHY: "healthy",
        ComponentState.DEGRADED: "degraded",
        ComponentState.WARNING: "degraded",
        ComponentState.DOWN: "down",
    }
)


def _ws_word(c: ComponentHealth | None) -> str | None:
    """`exchange.public_ws` or `private_ws`: `connected` for a healthy connection, else the word of
    the phase its probe names in `detail`; None, so the key is left out, for a component that is
    missing or not deployed and for a detail that names no phase."""
    if c is None or c.state is ComponentState.NOT_DEPLOYED:
        return None
    if c.state is ComponentState.HEALTHY:
        return _WS_WORD[PHASE_OPEN]
    return _WS_WORD.get(c.detail)


def _rest_word(c: ComponentHealth | None) -> str | None:
    """`exchange.rest`: the word of the state, None for a component missing or not deployed."""
    return None if c is None else _REST_WORD.get(c.state)


def _exchange(by_name: Mapping[str, ComponentHealth]) -> dict[str, str]:
    """The `exchange` block: a key for each component that has a word, none for the rest."""
    words = {
        "public_ws": _ws_word(by_name.get("bybit_public_ws")),
        "private_ws": _ws_word(by_name.get("bybit_private_ws")),
        "rest": _rest_word(by_name.get("bybit_rest")),
    }
    return {key: word for key, word in words.items() if word is not None}


#: `23-ws-protocol.md` 15.9, "Health components": `not_deployed` exists only in the REST report. The
#: frame sends it as the `healthy` it ranks as for `overall`, with this detail.
_NOT_DEPLOYED_DETAIL = "not deployed"


def _component(c: ComponentHealth) -> dict[str, str]:
    """One `components[]` item of the `health` frame: the component as `GET /admin/health` names
    it, so a snapshot read over REST and the frames pushed here agree. A name no client knows is
    passed through, never dropped. `detail` is the Owner's alone (the cut in `ws.system_filter`
    leaves it out for a Manager or Viewer), and `last_good_at`, the REST report's text, is left out
    until the component has been healthy once."""
    undeployed = c.state is ComponentState.NOT_DEPLOYED
    item = {
        "name": c.name,
        "state": ComponentState.HEALTHY.value if undeployed else c.state.value,
        "detail": _NOT_DEPLOYED_DETAIL if undeployed else c.detail,
    }
    if c.last_good_at is not None:
        item["last_good_at"] = c.last_good_at.isoformat().replace("+00:00", "Z")
    return item


def _health_frame(snap: HealthSnapshot, clock_offset_ms: object) -> dict[str, object]:
    """The `health` frame of `snap`: the overall word and every component, an `exchange` block when
    a component gives it a key, and `clock_offset_ms` only when it is an integer."""
    frame: dict[str, object] = {
        "kind": "health",
        "health": snap.overall.value,
        "components": [_component(c) for c in snap.components],
    }
    if exchange := _exchange({c.name: c for c in snap.components}):
        frame["exchange"] = exchange
    if isinstance(clock_offset_ms, int) and not isinstance(clock_offset_ms, bool):
        frame["clock_offset_ms"] = clock_offset_ms
    return frame


class _OffsetSource(Protocol):
    """The slice of `ingestion.clock.ClockGuard` the frame reads."""

    def offset_ms_or_none(self) -> int | None: ...


class HealthSystemPublisher:
    """Hands the `health` frame of each snapshot to `direct_sinks`, as `SystemTopicPublisher` does
    its notices: late-bound, since the hub is built after the registry this is the callback of.
    A sink that raises is logged and never stops the others, or the health tick.

    `clock_guard` returns the ClockGuard, or None while none is attached (`attach_clock` runs after
    the app is built); the frame reads its measured offset each time it is built."""

    def __init__(self, *, clock_guard: Callable[[], _OffsetSource | None] = lambda: None) -> None:
        self.direct_sinks: list[Callable[[dict[str, object]], object]] = []
        self._clock_guard = clock_guard

    async def __call__(self, snap: HealthSnapshot) -> None:
        guard = self._clock_guard()
        frame = _health_frame(snap, None if guard is None else guard.offset_ms_or_none())
        for sink in self.direct_sinks:
            try:
                sink(frame)
            except Exception:
                logger().exception("health_wiring: direct sink failed")


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


#: E27-T02: M2 component; DOWN whenever M2 reads DEGRADED: the KEK unavailable (trading latched
#: off), or since #889 the audit export signing key alone (export unavailable, trading not). S6b's
#: paging rule on `cv_audit_signing_key_unavailable_state` settles what pages (ADR-0039).
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
