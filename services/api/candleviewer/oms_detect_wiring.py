"""The stuck-order detector's composition (E29-T08 #916, PR A; 24-internal-schemas.md Sec.8.13,
Sec.15.5; 21-database-schema.md Sec.3.10.2; 20-architecture.md Sec.6.2 and Sec.12.1; the ruling of
record on #916, BQ-2 to BQ-6 and BQ-11).

The OMS runtime (`oms_wiring`) builds it in one block of its composition, on the order lane, after
the private-stream consumer, where its stores carry the detector's own (`DetectStores`, none on a
composition with no Postgres). `build_stuck_detection` binds the detector's ports:

* its reads, its `system_events` rows (through the redaction serializer every row passes) and the
  account reads `bybit_rate_remaining` needs, all on a pool of its own (`oms-detect`,
  `DETECT_POOL_SIZE` connections, no overflow), never the OMS pool the submit path writes through
  (the ticket's performance notes): `DetectStores`, which `oms_wiring.build_detect_stores` builds,
  as that module alone names the OMS's principal-free account reads (C-12.4);
* the write-ahead `oms.incident` record through the lane's own audit writer, as `system:oms`
  (`IncidentAuditRecords`, C-2.9);
* the bus topic `{env}.oms.incident`: the lane hands each incident to the serving loop
  (`Serving.notify`), where `BusIncidents` publishes it on the in-process bus, never awaited by the
  scan, at most `MAX_PUBLISHING` in flight, each bounded (C-2.18);
* the reconciliation standing's read-only accessor (`stale_accounts`, BQ-2), the pager and the
  metrics.

`DetectRuntime` starts the scan's task on the lane, which scans nothing until the runtime is
`ready`, and closes it: the task cancelled and awaited, then the pool released, on the lane, and the
publishes in flight cancelled on the serving loop (`stop_detection`, the runtime's
`stuck_detector` closer, inserted by name). `stalled` is what `/readyz` reads (20 Sec.6.2).

`RateRemaining` emits `bybit_rate_remaining{endpoint_group}` (BQ-11): at each scrape, per
`RateLane`, the fewest spare tokens across the environment's accounts that hold a key, read from the
lane's trading port without taking one (`TradingPort.headroom`), no account label; NaN while it
knows no account. The scan refreshes the accounts at most every `RATE_REFRESH_S`.

No flag gates any of it (C-4.14). Logs carry ids, kinds and outcomes only (C-12.6).
"""

from __future__ import annotations

import asyncio
import functools
import math
import random
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

import structlog

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import AccountRef, RateLane
from candleviewer.observability import spawn
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.incidents import (
    AUDIT_ACTION,
    BUS_DOMAIN,
    BUS_NAME,
    OmsIncident,
    audit_state,
    event_details,
    event_kind,
)
from candleviewer.oms.stuck_detector import (
    SCAN_JITTER_S,
    AlertPager,
    DetectorMetrics,
    IncidentSinks,
    StaleAccounts,
    StuckDetector,
    Thresholds,
)
from candleviewer.oms_stream_wiring import SYSTEM_ACTOR, AuditEmitter, Notify
from candleviewer.settings import Settings
from candleviewer.storage.repositories.stuck import StuckReadStore

__all__ = [
    "DETECT_POOL_NAME",
    "DETECT_POOL_SIZE",
    "MAX_PUBLISHING",
    "MAX_RATE_ACCOUNTS",
    "PUBLISH_TIMEOUT_S",
    "RATE_LANES",
    "RATE_REFRESH_S",
    "BusIncidents",
    "DetectRuntime",
    "DetectStores",
    "IncidentAuditRecords",
    "IncidentEventRows",
    "RateRemaining",
    "ServedIncidentBus",
    "build_stuck_detection",
    "stop_detection",
    "thresholds_of",
]

#: The detector's pool (`oms-detect` in `pg_stat_activity`): one scan reads at a time, and its
#: `system_events` rows and the rate gauge's account reads take the other; no overflow.
DETECT_POOL_NAME: Final = "oms-detect"
DETECT_POOL_SIZE: Final = 2
#: The bus publishes in flight on the serving loop, and each one's bound (C-2.18).
MAX_PUBLISHING: Final = 64
PUBLISH_TIMEOUT_S: Final = 2.0
#: How often the scan re-reads the environment's accounts for `bybit_rate_remaining`, and the most
#: it reads (C-2.18).
RATE_REFRESH_S: Final = 30.0
MAX_RATE_ACCOUNTS: Final = 256
_RATE_GAUGE: Final = "bybit_rate_remaining"
#: The gauge's `endpoint_group`s: the closed `RateLane` set (24 Sec.8.7), each child bound at once.
RATE_LANES: Final[tuple[RateLane, ...]] = get_args(RateLane.__value__)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def thresholds_of(settings: Settings) -> Thresholds:
    """24 Sec.8.13's thresholds from the settings: `CV_OMS_INFLIGHT_STUCK_S`,
    `CV_OMS_PENDING_STUCK_S` and `CV_NATIVE_SL_DEADLINE_MS`; `unknown` is one cycle (30 s)."""
    return Thresholds(
        in_flight_s=settings.oms_inflight_stuck_s,
        pending_s=settings.oms_pending_stuck_s,
        naked_s=settings.native_sl_deadline_ms / 1000,
    )


# --- The detector's stores, on its own pool -------------------------------------------------------


class EventWriter(Protocol):
    async def write(self, event: SystemEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class DetectStores:
    """What the detector reads and writes on its own pool, and the pool's release: its reads, its
    `system_events` rows, and for `bybit_rate_remaining` the environment's account ids and each
    one's trading account (an active key, not deleted), which no route reaches."""

    reads: StuckReadStore
    events: EventWriter
    account_ids: Callable[[Environment], Awaitable[Sequence[UUID]]]
    resolve: Callable[[AccountId], Awaitable[AccountRef]]
    release: Callable[[], Coroutine[Any, Any, None]]


# --- The sinks' adapters (24 Sec.8.13 "Where an incident goes") -----------------------------------


class IncidentAuditRecords:
    """`IncidentRecords`: `oms.incident` (24 Sec.15.5), written ahead through the lane's own
    audit writer as `system:oms`, the incident's fields its `after_state`; durable or it raises."""

    def __init__(self, emitter: AuditEmitter, *, environment: str) -> None:
        self._emitter, self._environment = emitter, environment

    async def write(
        self,
        found: OmsIncident,
        *,
        object_kind: Literal["order", "exchange_account"],
        object_id: str,
    ) -> None:
        await self._emitter.emit(
            AUDIT_ACTION, actor_label=SYSTEM_ACTOR, actor_user_id=None, object_kind=object_kind,
            object_id=object_id, outcome="success", severity=found.severity, reason=found.kind,
            after_state=dict(audit_state(found)), request_id=None, env=self._environment,
        )  # fmt: skip


class IncidentEventRows:
    """`IncidentEvents`: one `system_events` row (21 Sec.3.10.2): component `oms`, kind
    `incident_<kind>`, the kind's fixed sentence, the ids in `details`."""

    def __init__(self, writer: EventWriter) -> None:
        self._writer = writer

    async def write(self, found: OmsIncident) -> None:
        await self._writer.write(
            SystemEvent(
                component="oms",
                kind=event_kind(found.kind),
                severity=found.severity,
                message=found.detail,
                details=event_details(found),
            )
        )


class BusIncidents:
    """The serving loop's half of the bus hop: each incident on `{env}.oms.incident`, one task a
    publish, at most `MAX_PUBLISHING` in flight (one past it dropped, logged), each bounded at
    `PUBLISH_TIMEOUT_S`. `offer` runs on the serving loop (`Serving.notify`), never awaited."""

    def __init__(self, bus: Bus, *, environment: Environment) -> None:
        self._bus = bus
        self._topic = Topic(env=environment, domain=BUS_DOMAIN, symbol=BUS_NAME)
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def topic(self) -> Topic:
        return self._topic

    def offer(self, found: OmsIncident) -> None:
        if len(self._tasks) >= MAX_PUBLISHING:
            _log().error("oms_incident_bus_dropped", kind=found.kind, cap=MAX_PUBLISHING)
            return
        task = spawn(self._publish(found), name="oms-incident-publish")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _publish(self, found: OmsIncident) -> None:
        try:
            async with asyncio.timeout(PUBLISH_TIMEOUT_S):
                await self._bus.publish(self._topic, found)
        except Exception as exc:
            _log().error("oms_incident_publish_failed", kind=found.kind, error=type(exc).__name__)

    async def aclose(self) -> None:
        """Cancels the publishes still in flight and waits for them, on the serving loop."""
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class ServedIncidentBus:
    """`IncidentBus` on the lane: the incident handed to the serving loop's `BusIncidents`."""

    def __init__(self, bus: BusIncidents, serving: Notify) -> None:
        self._bus, self._serving = bus, serving

    def offer(self, found: OmsIncident) -> None:
        self._serving.notify(self._bus.offer, found)


# --- bybit_rate_remaining (BQ-11) -----------------------------------------------------------------


class Headroom(Protocol):
    """`RateHeadroomPort.headroom`, the lane's trading port's; it takes no token."""

    def headroom(self, account: AccountRef, lane: RateLane) -> Any: ...


class RateRemaining:
    """`bybit_rate_remaining{endpoint_group}` (module docstring): read at each scrape, from any
    thread, over the accounts the scan last read, a tuple replaced whole."""

    def __init__(
        self,
        metrics: Metrics,
        port: Headroom,
        *,
        environment: Environment,
        account_ids: Callable[[Environment], Awaitable[Sequence[UUID]]],
        resolve: Callable[[AccountId], Awaitable[AccountRef]],
        monotonic: Callable[[], float],
        refresh_s: float = RATE_REFRESH_S,
    ) -> None:
        self._port, self._env = port, environment
        self._accounts, self._resolve, self._monotonic = account_ids, resolve, monotonic
        self._refresh_s = refresh_s
        self._refs: tuple[AccountRef, ...] = ()
        self._read_at: float | None = None
        spec = next(spec for spec in CATALOGUE if spec.name == _RATE_GAUGE)
        gauge = metrics.gauge(spec.name, spec.help, spec.labels, max_series=spec.max_series)
        for lane in RATE_LANES:
            set_function = getattr(gauge.labels(lane), "set_function", None)
            if set_function is not None:
                set_function(functools.partial(self.remaining, lane))

    def remaining(self, lane: RateLane) -> float:
        """The fewest spare tokens of `lane` across the accounts; NaN with none, or when the port
        cannot read them (never raised into a scrape)."""
        refs = self._refs
        if not refs:
            return math.nan
        try:
            return float(min(self._port.headroom(ref, lane).tokens for ref in refs))
        except Exception:
            return math.nan

    async def refresh(self) -> None:
        """The scan's chore: the environment's accounts that resolve to a trading account (an
        active key, not deleted), at most every `refresh_s`; one the binding refuses or cannot read
        is not counted."""
        now = self._monotonic()
        if self._read_at is not None and now - self._read_at < self._refresh_s:
            return
        self._read_at = now
        refs: list[AccountRef] = []
        for account_id in list(await self._accounts(self._env))[:MAX_RATE_ACCOUNTS]:
            try:
                refs.append(await self._resolve(AccountId(account_id)))
            except Exception as exc:
                _log().debug("oms_rate_account_skipped", reason=type(exc).__name__)
        self._refs = tuple(refs)


# --- The runtime's handle -------------------------------------------------------------------------


class Scanner(Protocol):
    """`StuckDetector` as its handle runs it: the loop and its stall."""

    async def run(self) -> None: ...

    def stalled(self) -> bool: ...


class DetectRuntime:
    """What `build_stuck_detection` composed: the scan, its task on the lane, its stores and the
    serving loop's publisher."""

    def __init__(
        self, detector: Scanner, stores: DetectStores, bus: BusIncidents, pager: AlertPager
    ) -> None:
        self.detector, self.stores, self.bus, self._pager = detector, stores, bus, pager
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Starts the scan's task on the running loop, the lane's (it scans once `ready`)."""
        if self._task is None:
            self._task = spawn(self.detector.run(), name="oms-stuck-detector")
            self._task.add_done_callback(self._ended)

    def stalled(self) -> bool:
        return self.detector.stalled()

    def _ended(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        _log().critical("oms_detector_ended", error=None if error is None else type(error).__name__)
        try:
            self._pager.raise_alert("page", "oms_detector_ended", machine_kind="oms.stuck_detector")
        except Exception as exc:  # the CRITICAL line above stays the page of record
            _log().error("oms_detector_page_failed", error=type(exc).__name__)

    async def aclose(self) -> None:
        """On the lane: the scan's task cancelled and awaited, then the pool released."""
        task, self._task = self._task, None
        try:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            await self.stores.release()


class LaneCalls(Protocol):
    def call(self, coro: Coroutine[Any, Any, Any], *, timeout_s: float | None = ...) -> Any: ...


class ServingCalls(Protocol):
    async def call(self, coro: Coroutine[Any, Any, Any], *, timeout_s: float = ...) -> Any: ...


async def stop_detection(lane: LaneCalls, serving: ServingCalls, detect: DetectRuntime) -> None:
    """The runtime's `stuck_detector` closer: the lane's half first, then the publishes in flight
    on the serving loop, each whatever the other did."""
    try:
        await lane.call(detect.aclose())
    finally:
        await serving.call(detect.bus.aclose())


def build_stuck_detection(
    *,
    environment: Environment,
    stores: DetectStores,
    thresholds: Thresholds,
    stale: StaleAccounts,
    emitter: AuditEmitter,
    bus: Bus,
    serving: Notify,
    pager: AlertPager,
    metrics: Metrics,
    rate: Headroom,
    ready: Callable[[], bool],
    monotonic: Callable[[], float],
    now: Callable[[], datetime],
) -> DetectRuntime:
    """The detector over its stores and sinks (module docstring), built and not started."""
    counted = DetectorMetrics(metrics)
    publisher = BusIncidents(bus, environment=environment)
    sinks = IncidentSinks(
        records=IncidentAuditRecords(emitter, environment=environment),
        events=IncidentEventRows(stores.events),
        bus=ServedIncidentBus(publisher, serving),
        pager=pager,
        metrics=counted,
    )
    remaining = RateRemaining(
        metrics, rate, environment=environment, account_ids=stores.account_ids,
        resolve=stores.resolve, monotonic=monotonic,
    )  # fmt: skip
    jitter = random.SystemRandom()
    detector = StuckDetector(
        stores.reads, environment=environment, thresholds=thresholds, stale=stale, sinks=sinks,
        metrics=counted, ready=ready, monotonic=monotonic, now=now,
        jitter=lambda: jitter.uniform(0.0, SCAN_JITTER_S), chores=(remaining.refresh,),
    )  # fmt: skip
    return DetectRuntime(detector, stores, publisher, pager)
