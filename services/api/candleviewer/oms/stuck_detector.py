"""The stuck-order detector (E29-T08 #916; 24-internal-schemas.md Sec.8.13; the ruling of record on
#916, BQ-2 to BQ-6).

A plain host scan on the OMS's order lane, never a chart's `after:` (28 Sec.1.3 A2, BQ-5): every
`SCAN_INTERVAL_S` (5 s), each tick's phase jittered by up to `SCAN_JITTER_S`, a tick that falls due
while a scan still runs skipped, never queued, and each scan bounded at `SCAN_TIMEOUT_S`. It scans
nothing until the runtime is `ready`. It detects and records; it never sends, cancels, amends,
attaches, flattens or resolves anything (C-2.21): B1, the attach path and reconciliation stay the
enforcement, and it only reads the reconciliation standing (BQ-2).

**The judgement** (`order_kind`, `Dedupe`) is pure: 24 Sec.8.13's table over what a scan read, an
order's age the store's (the time since its latest `order_events` row, BQ-3), a position's and an
account's the time since the scan that first found it so (the episode's start, in memory, BQ-4).
A key is stuck when its age is strictly above its threshold. Each order has one incident at a time,
keyed by `order_link_id`: a kind that outranks the one raised (`unknown`) is raised at once, else
none again until `COOLDOWN_S` has passed while it stays stuck. A naked position raises once per
episode; an account at its first stale scan and once each `COOLDOWN_S` after. A complete read
forgets every key it no longer finds (its condition cleared); a failed read or one cut at its limit
forgets nothing. Each map holds at most `MAX_TRACKED` keys, the oldest forgotten past it, which
raises once more, never less (C-2.18). A key is marked raised only once its sinks ran, so a scan the
bound cuts leaves the rest for the next scan.

**The sinks** (`IncidentSinks`), in 24 Sec.8.13's order, each awaited step bounded at
`SINK_TIMEOUT_S`: the write-ahead `oms.incident` record; the log and the pager (`critical` pages,
`error` alerts); the metrics; the `system_events` row; and the bus, never awaited. An incident whose
record could not be written is logged CRITICAL and paged, and still logged, paged and counted, but
never reaches `system_events` or the bus.

No flag gates it (C-4.14). Logs carry ids, kinds and ages only (C-12.6).
"""

from __future__ import annotations

import asyncio
import functools
import math
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog
from pydantic import ValidationError

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.metrics import BoundedMetric, MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.repositories.stuck import (
    FINAL_STATES,
    NakedPositionRow,
    StuckOrderRow,
    StuckReadStore,
)

from .incidents import KINDS, ORDER_KINDS, RANK, IncidentKind, OmsIncident, OrderKind, incident

__all__ = [
    "COOLDOWN_S",
    "MAX_TRACKED",
    "PENDING_STATES",
    "SCAN_INTERVAL_S",
    "SCAN_JITTER_S",
    "SCAN_LIMIT",
    "SCAN_RESULTS",
    "SCAN_TIMEOUT_S",
    "SINK_TIMEOUT_S",
    "STALL_S",
    "UNKNOWN_CYCLE_S",
    "AlertPager",
    "Dedupe",
    "DetectorMetrics",
    "Finding",
    "IncidentBus",
    "IncidentEvents",
    "IncidentRecords",
    "IncidentSinks",
    "StaleAccounts",
    "StuckDetector",
    "Thresholds",
    "order_kind",
]

#: The scan's cadence, its jitter and its bound, in seconds (BQ-5): fixed values, not settings.
SCAN_INTERVAL_S: Final = 5.0
SCAN_JITTER_S: Final = 0.5
SCAN_TIMEOUT_S: Final = 4.0
#: The most rows one read returns (BQ-3): a read that returns this many may have been cut.
SCAN_LIMIT: Final = 200
#: How long an order or an account that stays stuck waits before it is raised again.
COOLDOWN_S: Final = 300.0
#: The keys each map holds (orders, position episodes, accounts), the oldest forgotten past it.
MAX_TRACKED: Final = 4096
#: Once `ready`, no scan ended for this long reads the runtime `degraded` (20 Sec.6.2).
STALL_S: Final = 30.0
#: Each awaited sink step's bound (C-2.18).
SINK_TIMEOUT_S: Final = 2.0
#: How often the loop looks for `ready` before its first scan.
READY_POLL_S: Final = 0.5
#: One reconciliation cycle: `OmsConfig.reconcile_interval_s` (24 Sec.16.1), the driver's
#: `reconcile_job.INTERVAL_S` (a test pins the two alike), the `unknown` threshold (BQ-3).
UNKNOWN_CYCLE_S: Final = 30.0
#: The persisted states of a pending cancel or amend (21 Sec.3.3.1).
PENDING_STATES: Final = frozenset({"pending_cancel", "pending_amend"})
SCAN_RESULTS: Final = ("ok", "failed", "skipped")
_PAGER_KIND: Final = "oms.stuck_detector"

type ScanResult = Literal["ok", "failed"]
#: An incident's kind as an order kind, where it is one.
_AS_ORDER: Final[Mapping[IncidentKind, OrderKind]] = {kind: kind for kind in ORDER_KINDS}
type PositionKey = tuple[UUID, str, int]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _seconds(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} is a number of seconds")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} is a finite number of seconds above 0")
    return float(value)


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Each kind's threshold in seconds (24 Sec.8.13's table): `CV_OMS_INFLIGHT_STUCK_S`, one
    reconciliation cycle, `CV_OMS_PENDING_STUCK_S` and `CV_NATIVE_SL_DEADLINE_MS`."""

    in_flight_s: float = 30.0
    unknown_s: float = UNKNOWN_CYCLE_S
    pending_s: float = 15.0
    naked_s: float = 3.0

    def __post_init__(self) -> None:
        for name in ("in_flight_s", "unknown_s", "pending_s", "naked_s"):
            object.__setattr__(self, name, _seconds(name, getattr(self, name)))


def order_kind(row: StuckOrderRow, thresholds: Thresholds) -> OrderKind | None:
    """The kind one order is stuck as, or None: a final row never is; an `unknown` row is only
    ever `unknown`, though its create is in flight too; a pending cancel or amend is `pending`;
    any other row whose create is in flight is `in_flight`; each only once its age is strictly
    above its threshold."""
    if row.state in FINAL_STATES:
        return None
    if row.state == "unknown":
        return "unknown" if row.age_s > thresholds.unknown_s else None
    if row.state in PENDING_STATES:
        return "pending" if row.age_s > thresholds.pending_s else None
    if row.in_flight:
        return "in_flight" if row.age_s > thresholds.in_flight_s else None
    return None


@dataclass(frozen=True, slots=True)
class Finding:
    """One incident a scan raises, with its dedupe key and its audit record's object: the order
    for an order kind, the exchange account for a position or an account."""

    incident: OmsIncident
    key: str | PositionKey | UUID
    object_kind: Literal["order", "exchange_account"]
    object_id: str


@dataclass(slots=True)
class _Raised:
    kind: OrderKind
    at: float


@dataclass(slots=True)
class _Episode:
    since: float
    raised_at: float | None = None


def _kept[K, V](held: OrderedDict[K, V], key: K, value: V, cap: int) -> V:
    """`value` under `key`, newest, the oldest key forgotten past `cap`."""
    held[key] = value
    held.move_to_end(key)
    while len(held) > cap:
        held.popitem(last=False)
    return value


def _forget[K](held: OrderedDict[K, Any], found: Iterable[K]) -> None:
    keep = set(found)
    for key in [key for key in held if key not in keep]:
        del held[key]


def _built(make: Callable[[], OmsIncident], kind: IncidentKind) -> OmsIncident | None:
    """The incident, or None, logged by its kind, for a row `OmsIncident` refuses: one bad row
    never ends the scan."""
    try:
        return make()
    except ValidationError:
        _log().error("oms_incident_refused", kind=kind)
        return None


class Dedupe:
    """The keys raised and the episodes under way (module docstring); pure but for its maps."""

    def __init__(
        self,
        thresholds: Thresholds,
        *,
        cooldown_s: float = COOLDOWN_S,
        max_tracked: int = MAX_TRACKED,
    ) -> None:
        if isinstance(max_tracked, bool) or not isinstance(max_tracked, int) or max_tracked < 1:
            raise ValueError("max_tracked is an int of at least 1")
        self._t, self._cooldown, self._cap = (
            thresholds,
            _seconds("cooldown_s", cooldown_s),
            max_tracked,
        )
        self._orders: OrderedDict[str, _Raised] = OrderedDict()
        self._episodes: OrderedDict[PositionKey, _Episode] = OrderedDict()
        self._accounts: OrderedDict[UUID, _Episode] = OrderedDict()

    def orders(
        self, rows: Sequence[StuckOrderRow], *, complete: bool, now: float, at: datetime
    ) -> tuple[list[Finding], Counter[OrderKind]]:
        """The orders due an incident, and how many are stuck by kind (`oms_stuck_orders`)."""
        stuck: dict[str, tuple[StuckOrderRow, OrderKind]] = {}
        for row in rows:
            kind = order_kind(row, self._t)
            held = stuck.get(row.order_link_id)
            if kind is not None and (held is None or RANK[kind] > RANK[held[1]]):
                stuck[row.order_link_id] = (row, kind)
        if complete:
            _forget(self._orders, stuck)
        due: list[Finding] = []
        for link, (row, kind) in stuck.items():
            raised = self._orders.get(link)
            if raised is not None and RANK[kind] <= RANK[raised.kind]:
                if now - raised.at < self._cooldown:
                    continue
            made = _built(
                functools.partial(
                    incident, kind, account_id=row.account_id, age_s=row.age_s,
                    detected_at=at, order_link_id=link, symbol=row.symbol,
                ),
                kind,
            )  # fmt: skip
            if made is not None:
                due.append(Finding(made, link, "order", str(row.order_id)))
        return due, Counter(kind for _row, kind in stuck.values())

    def naked(
        self, rows: Sequence[NakedPositionRow], *, complete: bool, now: float, at: datetime
    ) -> list[Finding]:
        """The positions due their episode's one incident (BQ-4)."""
        found = {(r.account_id, r.symbol, r.position_idx): r for r in rows}
        if complete:
            _forget(self._episodes, found)
        due: list[Finding] = []
        for key, row in found.items():
            episode = self._episodes.get(key)
            if episode is None:
                episode = _kept(self._episodes, key, _Episode(now), self._cap)
            age = now - episode.since
            if episode.raised_at is not None or not age > self._t.naked_s:
                continue
            made = _built(
                functools.partial(
                    incident, "naked", account_id=row.account_id, age_s=age, detected_at=at,
                    symbol=row.symbol,
                ),
                "naked",
            )  # fmt: skip
            if made is not None:
                due.append(Finding(made, key, "exchange_account", str(row.account_id)))
        return due

    def stale(self, accounts: Iterable[UUID], *, now: float, at: datetime) -> list[Finding]:
        """The stale accounts due an incident (BQ-2): at the first stale scan, then once each
        cool-down; the standing is in memory, so this read is always complete."""
        found = sorted(set(accounts), key=str)
        _forget(self._accounts, found)
        due: list[Finding] = []
        for account in found:
            episode = self._accounts.get(account)
            if episode is None:
                episode = _kept(self._accounts, account, _Episode(now), self._cap)
            if episode.raised_at is not None and now - episode.raised_at < self._cooldown:
                continue
            made = _built(
                functools.partial(
                    incident, "account_stale", account_id=account, age_s=now - episode.since,
                    detected_at=at,
                ),
                "account_stale",
            )  # fmt: skip
            if made is not None:
                due.append(Finding(made, account, "exchange_account", str(account)))
        return due

    def raised(self, finding: Finding, now: float) -> None:
        """`finding`'s sinks ran: its key is raised as of `now`."""
        kind, key = finding.incident.kind, finding.key
        if (order := _AS_ORDER.get(kind)) is not None and isinstance(key, str):
            _kept(self._orders, key, _Raised(order, now), self._cap)
        elif kind == "naked" and isinstance(key, tuple) and (ep := self._episodes.get(key)):
            ep.raised_at = now
        elif kind == "account_stale" and isinstance(key, UUID) and (ep := self._accounts.get(key)):
            ep.raised_at = now


# --- The ports the sinks write through, and the standing's accessor ------------------------------


class StaleAccounts(Protocol):
    """The reconciliation standing's `stale_accounts`: the accounts refused as stale, read only
    (BQ-2)."""

    def stale_accounts(self) -> frozenset[AccountId]: ...


class IncidentRecords(Protocol):
    """The write-ahead `oms.incident` record (24 Sec.15.5): durable or it raises (C-2.9)."""

    async def write(
        self,
        found: OmsIncident,
        *,
        object_kind: Literal["order", "exchange_account"],
        object_id: str,
    ) -> None: ...


class IncidentEvents(Protocol):
    """The incident's `system_events` row (21 Sec.3.10.2)."""

    async def write(self, found: OmsIncident) -> None: ...


class IncidentBus(Protocol):
    """The incident on `{env}.oms.incident`, handed to the serving loop, never awaited."""

    def offer(self, found: OmsIncident) -> None: ...


class AlertPager(Protocol):
    def raise_alert(self, severity: Any, summary: str, *, machine_kind: str) -> None: ...


def _spec(name: str) -> Any:
    return next(spec for spec in CATALOGUE if spec.name == name)


class DetectorMetrics:
    """The detector's series (20 Sec.12.1), each declared in the catalogue, no account label; every
    child of a labelled one bound at once, so each series exists at 0."""

    def __init__(self, metrics: Metrics) -> None:
        def made(name: str, make: Callable[..., BoundedMetric]) -> BoundedMetric:
            spec = _spec(name)
            return make(name, spec.help, spec.labels, max_series=spec.max_series)

        stuck = made("oms_stuck_orders", metrics.gauge)
        self._stuck: dict[OrderKind, MetricChild] = {k: stuck.labels(k) for k in ORDER_KINDS}
        for child in self._stuck.values():
            child.set(0)
        raised = made("oms_incidents_total", metrics.counter)
        self._raised: dict[IncidentKind, MetricChild] = {k: raised.labels(k) for k in KINDS}
        scans = made("oms_detector_scans_total", metrics.counter)
        self._scans: dict[str, MetricChild] = {r: scans.labels(r) for r in SCAN_RESULTS}
        took = _spec("oms_detector_scan_seconds")
        self._took = metrics.histogram(
            took.name, took.help, took.labels, buckets=took.buckets, max_series=took.max_series
        ).child()
        self._age = made("oms_detector_last_scan_age_seconds", metrics.gauge).child()
        self._naked = made("naked_position_alerts_total", metrics.counter).child()

    def stuck(self, counts: Mapping[OrderKind, int]) -> None:
        for kind, child in self._stuck.items():
            child.set(counts.get(kind, 0))

    def raised(self, kind: IncidentKind) -> None:
        self._raised[kind].inc()
        if kind == "naked":  # once per episode (BQ-4), beside reconciliation's repairs
            self._naked.inc()

    def scanned(self, result: str, count: int = 1) -> None:
        self._scans[result].inc(count)

    def took(self, seconds: float) -> None:
        self._took.observe(max(0.0, seconds))

    def age_from(self, read: Callable[[], float]) -> None:
        """`oms_detector_last_scan_age_seconds`, read at each scrape; a child the series cap
        refused, a no-op, has none."""
        set_function = getattr(self._age, "set_function", None)
        if set_function is not None:
            set_function(read)


class IncidentSinks:
    """Where an incident goes, in 24 Sec.8.13's order (module docstring); raises nothing but
    `CancelledError`."""

    def __init__(
        self,
        *,
        records: IncidentRecords,
        events: IncidentEvents,
        bus: IncidentBus,
        pager: AlertPager,
        metrics: DetectorMetrics,
        timeout_s: float = SINK_TIMEOUT_S,
    ) -> None:
        self._records, self._events, self._bus = records, events, bus
        self._pager, self._metrics = pager, metrics
        self._timeout_s = _seconds("timeout_s", timeout_s)

    async def emit(self, finding: Finding) -> None:
        found = finding.incident
        recorded = await self._recorded(finding)
        critical = found.severity == "critical"
        log = _log().critical if critical else _log().error
        log(
            "oms_incident", kind=found.kind, severity=found.severity,
            order_link_id=found.order_link_id, account_id=str(found.account_id),
            symbol=found.symbol, age_s=found.age_s, cv_page=critical,
        )  # fmt: skip
        self._page("page" if critical else "alert", f"oms_incident_{found.kind}")
        self._metrics.raised(found.kind)
        if not recorded:  # the row and the bus never run ahead of the chain (24 Sec.8.13)
            return
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._events.write(found)
        except Exception as exc:
            _log().error("oms_incident_event_failed", kind=found.kind, error=type(exc).__name__)
        try:
            self._bus.offer(found)
        except Exception as exc:
            _log().error("oms_incident_bus_failed", kind=found.kind, error=type(exc).__name__)

    async def _recorded(self, finding: Finding) -> bool:
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._records.write(
                    finding.incident, object_kind=finding.object_kind, object_id=finding.object_id
                )
        except Exception as exc:
            kind = finding.incident.kind
            _log().critical("oms_incident_unrecorded", kind=kind, error=type(exc).__name__,
                            cv_page=True)  # fmt: skip
            self._page("page", "oms_incident_unrecorded")
            return False
        return True

    def _page(self, severity: str, summary: str) -> None:
        try:
            self._pager.raise_alert(severity, summary, machine_kind=_PAGER_KIND)
        except Exception as exc:  # the log line above stays the page of record
            _log().error("oms_incident_page_failed", summary=summary, error=type(exc).__name__)


# --- The scan -----------------------------------------------------------------------------------


class StuckDetector:
    """The scan loop and one scan (module docstring), on the order lane."""

    def __init__(
        self,
        reads: StuckReadStore,
        *,
        environment: Environment,
        thresholds: Thresholds,
        stale: StaleAccounts,
        sinks: IncidentSinks,
        metrics: DetectorMetrics,
        ready: Callable[[], bool],
        monotonic: Callable[[], float],
        now: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = lambda: 0.0,
        chores: Sequence[Callable[[], Awaitable[None]]] = (),
        interval_s: float = SCAN_INTERVAL_S,
        timeout_s: float = SCAN_TIMEOUT_S,
        limit: int = SCAN_LIMIT,
        stall_s: float = STALL_S,
    ) -> None:
        self._interval_s = _seconds("interval_s", interval_s)
        self._timeout_s = _seconds("timeout_s", timeout_s)
        self._stall_s = _seconds("stall_s", stall_s)
        if not self._timeout_s < self._interval_s:
            raise ValueError("a scan's bound is under its interval")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit is an int of at least 1")
        self._reads, self._env, self._limit = reads, environment, limit
        self._stale, self._sinks, self._metrics = stale, sinks, metrics
        self._ready, self._monotonic, self._now = ready, monotonic, now
        self._sleep, self._jitter, self._chores = sleep, jitter, tuple(chores)
        self._dedupe = Dedupe(thresholds)
        #: When the loop first found the runtime `ready`, when its last scan ended, and whether
        #: the loop has ended, on `monotonic`.
        self._since: float | None = None
        self._last: float | None = None
        self._ended = False
        metrics.age_from(self.last_scan_age)

    def last_scan_age(self) -> float:
        """Seconds since the last scan ended, or since the loop found `ready`; 0 before."""
        start = self._last if self._last is not None else self._since
        return 0.0 if start is None else max(0.0, self._monotonic() - start)

    def stalled(self) -> bool:
        """Its loop has ended, or, once `ready`, no scan has ended for `STALL_S` (20 Sec.6.2):
        a plain read, from any thread."""
        return self._ended or (self._since is not None and self.last_scan_age() >= self._stall_s)

    async def run(self) -> None:
        """Waits for `ready`, then scans every interval at its jittered phase; a tick that fell
        due while a scan ran is skipped, never queued. Ends only when cancelled."""
        try:
            while not self._ready():
                await self._sleep(READY_POLL_S)
            start = self._since = self._monotonic()
            tick = 0
            while True:
                due = start + tick * self._interval_s + min(max(self._jitter(), 0.0), SCAN_JITTER_S)
                if (wait := due - self._monotonic()) > 0:
                    await self._sleep(wait)
                await self._scan_once()
                after = max(
                    tick + 1, math.floor((self._monotonic() - start) / self._interval_s) + 1
                )
                if (skipped := after - tick - 1) > 0:
                    self._metrics.scanned("skipped", skipped)
                    _log().warning("oms_detector_ticks_skipped", skipped=skipped)
                tick = after
        finally:
            self._ended = True

    async def _scan_once(self) -> None:
        began, result = self._monotonic(), "failed"
        try:
            async with asyncio.timeout(self._timeout_s):
                result = await self.scan()
        except TimeoutError:
            _log().error("oms_detector_scan_cut", bound_s=self._timeout_s)
        except Exception as exc:
            _log().error("oms_detector_scan_failed", error=type(exc).__name__)
        finally:
            self._last = self._monotonic()
            self._metrics.took(self._last - began)
        self._metrics.scanned(result)
        for chore in self._chores:
            try:
                async with asyncio.timeout(self._timeout_s):
                    await chore()
            except Exception as exc:
                _log().error("oms_detector_chore_failed", error=type(exc).__name__)

    async def scan(self) -> ScanResult:
        """One scan: the reads, the judgement, then each due incident's sinks, the key marked
        raised once they ran; `failed` when a read failed (what it did read is still judged)."""
        now, at = self._monotonic(), self._now()
        due: list[Finding] = []
        result: ScanResult = "ok"
        try:
            rows, complete = await self._reads.stuck_orders(self._env, limit=self._limit)
        except Exception as exc:
            result = "failed"
            _log().error("oms_detector_read_failed", read="orders", error=type(exc).__name__)
        else:
            found, counts = self._dedupe.orders(rows, complete=complete, now=now, at=at)
            self._metrics.stuck(counts)
            due += found
        try:
            naked, complete = await self._reads.naked_positions(self._env, limit=self._limit)
        except Exception as exc:
            result = "failed"
            _log().error("oms_detector_read_failed", read="positions", error=type(exc).__name__)
        else:
            due += self._dedupe.naked(naked, complete=complete, now=now, at=at)
        due += self._dedupe.stale(self._stale.stale_accounts(), now=now, at=at)
        for finding in due:
            await self._sinks.emit(finding)
            self._dedupe.raised(finding, now)
        return result
