"""The stuck-order detector's test rig (E29-T08 #916; 24-internal-schemas.md Sec.8.13): the real
detector, judgement and sinks over the in-memory reads, a manual clock, the real reconciliation
standing and a recording double for each port. Shared by the detector's unit tests and the ticket's
acceptance tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from prometheus_client import generate_latest

from candleviewer.observability.metrics import Metrics
from candleviewer.oms.incidents import OmsIncident
from candleviewer.oms.reconcile_standing import ReconcileStanding
from candleviewer.oms.stuck_detector import (
    DetectorMetrics,
    IncidentSinks,
    StuckDetector,
    Thresholds,
)
from candleviewer.storage.repositories.stuck import (
    InMemoryStuckReads,
    NakedPositionRow,
    StuckOrderRow,
)
from tests.unit.oms.order_rig import Pager

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
ACCOUNT, OTHER = UUID(int=0xA1), UUID(int=0xA2)
#: 24 Sec.8.3's example id, numbered as the facade rig numbers its orders.
LINK = "cvd-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-{:02d}en"


def link(n: int) -> str:
    return LINK.format(n)


def order(
    n: int = 1,
    *,
    state: str = "submitted",
    in_flight: bool = True,
    age_s: float = 31.0,
    account: UUID = ACCOUNT,
) -> StuckOrderRow:
    """Order *n* as the scan reads it; by default a create in flight for 31 s (`submitting`)."""
    return StuckOrderRow(UUID(int=n), account, link(n), "BTCUSDT", state, in_flight, age_s)


def position(symbol: str = "BTCUSDT", *, account: UUID = ACCOUNT, idx: int = 0) -> NakedPositionRow:
    return NakedPositionRow(account, symbol, idx, "Buy")


@dataclass
class Clock:
    """The scan's monotonic clock and its wall clock, moved together by `advance`."""

    at: float = 1_000.0

    def monotonic(self) -> float:
        return self.at

    def now(self) -> datetime:
        return T0 + timedelta(seconds=self.at - 1_000.0)

    def advance(self, seconds: float) -> None:
        self.at += seconds


@dataclass
class Records:
    """The write-ahead `oms.incident` record's double; `refuse` makes it raise, and past `free`
    writes each one waits for `gate` (an answer that does not come)."""

    written: list[tuple[OmsIncident, str, str]] = field(default_factory=list)
    refuse: bool = False
    calls: list[str] = field(default_factory=list)
    free: int = 1 << 30
    gate: asyncio.Event = field(default_factory=asyncio.Event)

    async def write(
        self,
        found: OmsIncident,
        *,
        object_kind: Literal["order", "exchange_account"],
        object_id: str,
    ) -> None:
        self.calls.append("record")
        if self.refuse:
            raise RuntimeError("the audit WAL refused the record")
        if len(self.written) >= self.free:
            await self.gate.wait()
        self.written.append((found, object_kind, object_id))


@dataclass
class Events:
    rows: list[OmsIncident] = field(default_factory=list)
    refuse: bool = False
    calls: list[str] | None = None

    async def write(self, found: OmsIncident) -> None:
        if self.calls is not None:
            self.calls.append("event")
        if self.refuse:
            raise RuntimeError("the system_events insert failed")
        self.rows.append(found)


@dataclass
class Bus:
    offered: list[OmsIncident] = field(default_factory=list)
    calls: list[str] | None = None
    refuse: bool = False

    def offer(self, found: OmsIncident) -> None:
        if self.calls is not None:
            self.calls.append("bus")
        if self.refuse:
            raise RuntimeError("the serving loop has closed")
        self.offered.append(found)


@dataclass
class Standing:
    """The standing's read-only accessor over a set the test sets."""

    stale: set[UUID] = field(default_factory=set)

    def stale_accounts(self) -> frozenset[Any]:
        return frozenset(self.stale)


@dataclass
class StuckRig:
    detector: StuckDetector
    reads: InMemoryStuckReads
    clock: Clock
    records: Records
    events: Events
    bus: Bus
    pager: Pager
    metrics: Metrics
    standing: Standing | ReconcileStanding

    def count(self, name: str, **labels: str) -> float:
        lines = generate_latest(self.metrics.registry).decode().splitlines()
        wanted = [f'{key}="{value}"' for key, value in labels.items()]
        return sum(
            float(line.rsplit(" ", 1)[1])
            for line in lines
            if (line.startswith(name + "{") or line.startswith(name + " "))
            and all(w in line for w in wanted)
        )

    def kinds(self) -> list[str]:
        return [found.kind for found, _kind, _id in self.records.written]


def build(
    *,
    thresholds: Thresholds | None = None,
    standing: Standing | ReconcileStanding | None = None,
    ready: Callable[[], bool] = lambda: True,
    sleep: Any = None,
    limit: int = 200,
    reads: InMemoryStuckReads | None = None,
    sink_timeout_s: float = 2.0,
    **scan: Any,
) -> StuckRig:
    """The rig; `scan` goes to the detector as it is (`timeout_s`, `interval_s`, `chores`)."""
    clock, reads = Clock(), reads if reads is not None else InMemoryStuckReads()
    records, events, bus, pager, metrics = Records(), Events(), Bus(), Pager(), Metrics("dev")
    counted = DetectorMetrics(metrics)
    sinks = IncidentSinks(
        records=records, events=events, bus=bus, pager=pager, metrics=counted,
        timeout_s=sink_timeout_s,
    )  # fmt: skip
    held = standing if standing is not None else Standing()
    extra: dict[str, Any] = scan if sleep is None else {"sleep": sleep, **scan}
    detector = StuckDetector(
        reads, environment="demo", thresholds=thresholds or Thresholds(), stale=held, sinks=sinks,
        metrics=counted, ready=ready, monotonic=clock.monotonic, now=clock.now, limit=limit,
        **extra,
    )  # fmt: skip
    return StuckRig(detector, reads, clock, records, events, bus, pager, metrics, held)
