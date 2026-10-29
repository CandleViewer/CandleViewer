"""The private-stream consumer's composition (E29-T05 #848, S8a and S8b; 24-internal-schemas.md
Sec.8.12, 23-ws-protocol.md Sec.15.9, 20-architecture.md Sec.6.2 and Sec.12.1). The OMS runtime
(`oms_wiring`) builds it in its composition's `stream` phase, on the order lane, starts it once
`ready` and stops it first, beside its drain (`StreamWiring.start`, `StreamWiring.stop`).

**On the order lane, with no hop.** `StreamPushes`, `PositionProjection` (never `NoPositionRows`),
`RecordedStopStream` and the successor's check (`Successor`) take the one facade (`OrderMachines`:
`push`, `protecting`, `push_protection`, `materialise`), the OMS order store and the recorded-stop
facade. A fill's order is read on the account's own port (`VenueFillOrders`): its history by the
exchange id, then its open orders on a miss. Each account's stream is subscribed on that same port
(`PortStreams`), which opens it across the lane's bridge from the serving loop's one registry
(`oms_streams.LaneStreams`). The accounts streamed are account health's last good tracking read,
read in place (`HealthAccounts`); the clock's re-sync is an epoch the consumer reads on each item,
over the clock guard's health read in place (`ClockEpoch`), with no poll task (S8b, Q5, Q7).

**The stand-ins** (24 Sec.8.12 "Its ports"), each an `Interim` announced at build as
`SubmissionPorts`' are (a WARNING and `oms_interim_ports{port}` at 1): `NoReconciliation`
(E29-T06), `NoHandoverStore` as `ExecutionHandovers` (E29-T06), `NoPositionProtection` (E32-T02)
and `PagingForeignOrderLockout` (E39-T04), which writes `oms.no_intent_detected` ahead (`finding`,
`key`, `exchange_placed: false`, `frozen: false`) and then pages P1, once per key.
`PagedNoIntentRecords` writes the same record with `exchange_placed: true` for an exchange-placed
order or fill, which never reaches the lockout, before E39-T04 lands and after (24 Sec.8.12 "The
foreign order or fill").

**Across to the serving loop.** Account health's evidence (`ws_heartbeat`, `ws_dropped`,
`wallet_pushed`) and the account notices are notified there (`oms_lane.Serving.notify`), never
awaited, so one account task's calls land in their order. A notice is the closed table's row for its
`reason` (`NOTICES`, 23 Sec.15.9), checked before it leaves (`checked_notice`: an `account_notice`
whose `exchange_account_ids` is a non-empty list of canonical lowercase UUID strings, whose
`message` names no account), then offered through `GatewayHub.broadcast_system`. The credential
report is the runtime's `CredentialRejections` (its `ServedStandings` hop), guarded.

**Every wrapper here raises nothing but `CancelledError`** (the S8 carry L-2): a hop, a notice or a
report that fails is logged by its class and the account id, and the report's failure pages.

**Counts and readiness.** The consumer's, the pushes' and the projection's counting ports are one
counter, `oms_stream_outcomes_total{stage,outcome}`, each stage bound to its own closed `Outcome`
set at build, with no account label; the consumer observes `oms_stream_event_lag_seconds{topic}` on
each row's dequeue, from `ts_ingest` on the host's own clock (`ExchangeWallClock.host_us`);
`StreamReadiness` reads the consumer's fault and the oldest owed reading's age into
`oms_position_reading_owed_age_seconds`, at each scrape from the consumer's start, degraded at
`OWED_DEGRADED_S` (the 2026-10-25 ruling Q7), with a detail that names no account (`/readyz` is
anonymous).

**The clock.** `ExchangeWallClock` is the position store's clock, the projection's record clock and
the consumer's, one instance (S8b): the host's aware UTC time plus the exchange clock's measured
offset (server minus local), 0 while unmeasured, or past the clock guard's critical drift, with one
WARNING (ruling Q9). The offset is read on the
order lane, so its reader is `Ingestion.clock_offset_snapshot_ms` (`ClockGuard.offset_ms_snapshot`,
#913 L1d CR-S3L1B-09), which changes nothing and answers None until the first measurement; never
`Ingestion.clock_offset_ms`, whose host-step check writes the guard's state and spawns a resync on
the calling loop, and which answers 0, never None, before a guard is attached. The successor's
bind is stamped on the OMS's own clock (24 Sec.8.3 rule 7).

Logs carry ids, a reason code or a class only (C-12.6).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, ClassVar, Final, Literal, Protocol, cast, get_args
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.models import AccountRef, Order, PrivateKind
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.observability.metrics import BoundedMetric, MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms import positions as position_stage
from candleviewer.oms import stream_consumer as consumer_stage
from candleviewer.oms import stream_push as push_stage
from candleviewer.oms.ports import (
    AccountNoticeReason,
    CredentialRejections,
    ExecutionHandovers,
    Finding,
    ForeignOrderLockout,
    Interim,
    NoHandoverStore,
    NoPositionProtection,
    NoReconciliation,
    ProtectionReadings,
    ReconciliationRequests,
    RuntimePortName,
    StreamedAccounts,
    TradingAccounts,
    announce_interim_port,
    refuse_live_without_reconciliation,
)
from candleviewer.oms.positions import (
    PositionProjection,
    PositionWrites,
    ProtectingOrders,
    RecordedStops,
    SnapshotWrites,
)
from candleviewer.oms.recorded_stop_stream import (
    Materialiser,
    OrderReads,
    RecordedStopStream,
    Successor,
    SuccessorStops,
)
from candleviewer.oms.recorded_stop_stream import ReleaseAudit as KeyedAudit
from candleviewer.oms.stream_consumer import (
    StreamConsumer,
    StreamEvidence,
    refuse_live_without_position_rows,
)
from candleviewer.oms.stream_push import Pager, PushTarget, StreamPushes
from candleviewer.settings import Environment as ProcessEnvironment
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

#: The action the lockout's stand-in and the exchange-placed records write (24 Sec.15.5).
NO_INTENT_DETECTED: Final = "oms.no_intent_detected"
#: The system actor of an OMS record: `oms_wiring.SYSTEM_ACTOR`, which this module cannot import
#: (the runtime imports this one); a test pins the two equal.
SYSTEM_ACTOR: Final = "system:oms"
#: The keys the lockout's stand-in (and the exchange-placed records) remember having paged, the
#: oldest forgotten past it: a forgotten key pages once more, never less (C-2.18).
MAX_PAGED_KEYS: Final = 4096
#: The clock guard's critical drift (`ingestion.clock.ClockGuard`'s default `hard_threshold_ms`; a
#: test pins the two equal): a measured offset past it is read as unmeasured, never applied.
MAX_OFFSET_MS: Final = 2_000
#: 24 Sec.8.12, the 2026-10-25 ruling Q7: the `oms` check of `/readyz` is degraded while the
#: oldest position reading owed to protection is this old, or older (the alert fires at 60 s).
OWED_DEGRADED_S: Final = 120.0
STAGES: Final = ("consumer", "push", "position")
#: Each stage's closed `Outcome` set, which its module owns, in `STAGES`' order.
_OUTCOMES: Final = (consumer_stage.Outcome, push_stage.Outcome, position_stage.Outcome)
OUTCOMES: Final = "oms_stream_outcomes_total"
LAG: Final = "oms_stream_event_lag_seconds"
OWED_AGE: Final = "oms_position_reading_owed_age_seconds"

type Severity = Literal["info", "warning", "error", "critical"]
#: 23 Sec.15.9's closed table, E29-T05's rows: one severity and one role-neutral message per
#: `reason`, never built from data, naming no account and counting none (SEC-2, SEC-3). A `reason`
#: without a row here is never sent (E29-T06 adds its rows with its code).
NOTICES: Final[Mapping[AccountNoticeReason, tuple[Severity, str]]] = MappingProxyType(
    {
        "oms.account_resyncing": (
            "warning",
            "An account is resynchronising; its orders and positions are being verified.",
        ),
    }
)
_NOTICE_KEYS: Final = frozenset({"kind", "severity", "reason", "message", "exchange_account_ids"})
_TOPICS: Final[frozenset[str]] = frozenset(get_args(PrivateKind.__value__))


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class Notify(Protocol):
    """`oms_lane.Serving.notify`: `fn(*args, **kwargs)` on the serving loop, never awaited."""

    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None: ...


class SystemBroadcast(Protocol):
    """`GatewayHub.broadcast_system`: each authenticated socket queues its Sec.15.9 view."""

    def broadcast_system(self, body: dict[str, Any]) -> int: ...


class AuditEmitter(Protocol):
    """The OMS's audit writer's `emit` (`oms_wiring.AuditWriterPort`), with the columns the
    no-intent record writes: durable or it raises."""

    async def emit(
        self, action: str, *, actor_label: str, actor_user_id: UUID | None = None,
        object_kind: str | None = None, object_id: str | None = None, outcome: Any = ...,
        severity: Any = ..., reason: str | None = None, after_state: dict[str, Any] | None = None,
        request_id: UUID | None = None, env: Any = None,
    ) -> None: ...  # fmt: skip


class StreamFacade(PushTarget, ProtectingOrders, Materialiser, Protocol):
    """`OrderMachines`, structurally: the one facade every push, reading and materialise goes to."""


class StreamStops(SuccessorStops, RecordedStops, Protocol):
    """The recorded-stop facade's reads and binds the stream takes (`oms.repository`), as the
    runtime binds them: the successor's three methods and the projection's record hook."""


class ReadPort(Protocol):
    """The two reads of an environment's trading port a fill's order takes, and the account's
    private stream there (`PortStreams`, S8b)."""

    async def order_history(
        self, account: AccountRef, *, exchange_order_id: str | None = None
    ) -> Sequence[Order]: ...

    async def open_orders(
        self, account: AccountRef, symbol: Symbol | None = None
    ) -> Sequence[Order]: ...

    async def subscribe_private(self, account: AccountRef) -> PrivateStream: ...


class Ports(Protocol):
    """`TradingRouter.port_for`: the account's environment's port, or `EnvironmentMismatch`."""

    def port_for(self, environment: Environment) -> ReadPort: ...


# --- account notices (23 Sec.15.9) --------------------------------------------------------------


def account_notice(account_id: UUID, reason: AccountNoticeReason) -> dict[str, Any]:
    """The frame `body` of one notice: the table's row for `reason`, the account only in
    `exchange_account_ids`; a `ValueError` for a `reason` the table has no row for."""
    row = NOTICES.get(reason)
    if row is None:
        raise ValueError("an account notice reason without a row in the closed table")
    severity, message = row
    return {
        "kind": "account_notice",
        "severity": severity,
        "reason": reason,
        "message": message,
        "exchange_account_ids": [str(account_id)],
    }


def checked_notice(body: Mapping[str, Any]) -> dict[str, Any]:
    """The producer's own check (SEC-1, SEC-5): `body` is an `account_notice` with exactly its five
    keys, its `reason`'s row of the closed table, and a non-empty `list` (never a set, a tuple or a
    `UUID`) of canonical lowercase UUID strings; else a `ValueError` naming no value."""
    if body.get("kind") != "account_notice" or set(body) != _NOTICE_KEYS:
        raise ValueError("not an account_notice of the five keys")
    if NOTICES.get(body["reason"]) != (body["severity"], body["message"]):
        raise ValueError("a severity or message off the closed table")
    ids = body["exchange_account_ids"]
    if type(ids) is not list or not ids:
        raise ValueError("exchange_account_ids is not a non-empty list")
    for value in ids:
        if type(value) is not str or not _canonical(value):
            raise ValueError("an account id that is not a canonical lowercase UUID string")
    return dict(body)


def _canonical(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


class StreamNotices:
    """`AccountNotices` (24 Sec.8.12): the notice built from the closed table and checked, then
    offered to the gateway on the serving loop. Raises nothing but `CancelledError`."""

    def __init__(self, hub: SystemBroadcast, serving: Notify) -> None:
        self._hub, self._serving = hub, serving

    def publish(self, account_id: AccountId, *, reason: AccountNoticeReason) -> None:
        try:
            body = checked_notice(account_notice(account_id, reason))
            self._serving.notify(self._hub.broadcast_system, body)
        except Exception as exc:
            _log().error(
                "stream_notice_refused", account_id=str(account_id), error=type(exc).__name__
            )


# --- the serving loop's hops --------------------------------------------------------------------


class ServedEvidence:
    """`StreamEvidence` from the lane: account health's evidence calls notified to the serving
    loop, whose monitor and wallet cache are that loop's, never awaited, so they land in the
    order they are made. What each answers is not read. Raises nothing but `CancelledError`."""

    def __init__(self, feed: StreamEvidence, serving: Notify) -> None:
        self._feed, self._serving = feed, serving

    def ws_heartbeat(self, account_id: AccountId) -> None:
        self._hop(self._feed.ws_heartbeat, account_id)

    def ws_dropped(self, account_id: AccountId) -> None:
        self._hop(self._feed.ws_dropped, account_id)

    def wallet_pushed(self, account_id: AccountId, snapshot: Any) -> None:
        self._hop(self._feed.wallet_pushed, account_id, snapshot)

    def _hop(self, fn: Callable[..., object], account_id: AccountId, *rest: Any) -> None:
        try:
            self._serving.notify(fn, account_id, *rest)
        except Exception as exc:
            _log().error(
                "stream_evidence_hop_failed", account_id=str(account_id), error=type(exc).__name__
            )


class GuardedRejections:
    """The runtime's `CredentialRejections` as the consumer reports a refused key: a report that
    raises is logged CRITICAL and paged, never raised into the account's stream. Raises nothing but
    `CancelledError`."""

    def __init__(self, credentials: CredentialRejections, pager: Pager) -> None:
        self._credentials, self._pager = credentials, pager

    async def refused(
        self, account_id: AccountId, *, error_code: str, exchange_ret_code: int | None
    ) -> None:
        try:
            await self._credentials.refused(
                account_id, error_code=error_code, exchange_ret_code=exchange_ret_code
            )
        except Exception as exc:
            error = type(exc).__name__
            _log().critical("stream_auth_report_failed", account_id=str(account_id), error=error)
            _page(
                self._pager, f"a refused credential's report failed: {error}", "oms.stream_consumer"
            )


def _page(pager: Pager, summary: str, machine_kind: str) -> bool:
    """Whether the page was raised: a pager that raises loses the page, never its caller."""
    try:
        pager.raise_alert("page", summary, machine_kind=machine_kind)
    except Exception as exc:
        _log().critical("stream_pager_failed", summary=summary, error=type(exc).__name__)
        return False
    return True


# --- the lockout's stand-in and the exchange-placed records (24 Sec.8.12, Sec.15.5) --------------


class NoIntentWriter:
    """`oms.no_intent_detected` through the OMS's audit writer, as `system:oms`, its object the
    account: `finding`, `key`, `exchange_placed` and `frozen: false` in its detail (ids only,
    C-12.6). Durable or it raises (C-2.9)."""

    def __init__(self, emitter: AuditEmitter, *, environment: str) -> None:
        self._emitter, self._environment = emitter, environment

    async def write(
        self, account_id: AccountId, *, finding: Finding, key: str, exchange_placed: bool
    ) -> None:
        await self._emitter.emit(
            NO_INTENT_DETECTED, actor_label=SYSTEM_ACTOR, actor_user_id=None,
            object_kind="exchange_account", object_id=str(account_id), outcome="success",
            severity="critical", reason=finding, request_id=None, env=self._environment,
            after_state={
                "account_id": str(account_id), "finding": finding, "key": key,
                "exchange_placed": exchange_placed, "frozen": False,
            },
        )  # fmt: skip


class _PagedOnce:
    """Writes the record ahead, then pages P1, once per (account, finding, key): one paged already
    changes nothing, so a key first opened `undecided` and then decided (`execution`) is recorded
    for each finding (24 Sec.8.12). A write that fails raises before any page, and a page that
    fails, after its record, is not remembered either: the next push records and pages again, once
    more and never less."""

    machine_kind: ClassVar[str]

    def __init__(self, writer: NoIntentWriter, pager: Pager, *, max_keys: int = MAX_PAGED_KEYS):
        self._writer, self._pager, self._max = writer, pager, max_keys
        self._paged: OrderedDict[tuple[AccountId, Finding, str], None] = OrderedDict()

    async def _once(
        self, account_id: AccountId, finding: Finding, key: str, *, placed: bool
    ) -> None:
        seen = (account_id, finding, key)
        if seen in self._paged:
            return
        await self._writer.write(account_id, finding=finding, key=key, exchange_placed=placed)
        self._paged[seen] = None
        if len(self._paged) > self._max:
            self._paged.popitem(last=False)
        _log().critical(
            "stream_no_intent_detected", account_id=str(account_id), finding=finding,
            exchange_placed=placed,
        )  # fmt: skip
        summary = f"no OMS intent ({finding}, exchange_placed={placed}): account {account_id}"
        if not _page(self._pager, summary, self.machine_kind):
            self._paged.pop(seen, None)


class PagingForeignOrderLockout(_PagedOnce, Interim):
    """`ForeignOrderLockout` until E39-T04 (#4208) binds the freeze: the record ahead with
    `exchange_placed: false`, then a P1 page, and no freeze (SR-E27-19 stays open)."""

    port: ClassVar[RuntimePortName] = "foreign_order_lockout"
    replaced_by: ClassVar[str] = "E39-T04 (#4208)"
    serves: ClassVar[str] = "an audit record and a P1 page per finding; no freeze"
    machine_kind: ClassVar[str] = "oms.foreign_order_lockout"

    async def open(self, account_id: AccountId, *, finding: Finding, key: str) -> None:
        await self._once(account_id, finding, key, placed=False)


class PagedNoIntentRecords(_PagedOnce):
    """`NoIntentRecords`: an exchange-placed order or fill, which never reaches the lockout, gets
    the record with `exchange_placed: true`, then a P1 page."""

    machine_kind: ClassVar[str] = "oms.stream_push"

    async def exchange_placed(self, account_id: UUID, *, finding: Finding, key: str) -> None:
        await self._once(AccountId(account_id), finding, key, placed=True)


# --- counts, the lag and readiness (24 Sec.8.12 "Its metrics") ----------------------------------


def _spec_metric(metrics: Metrics, name: str) -> BoundedMetric:
    spec = next(spec for spec in CATALOGUE if spec.name == name)
    build = {"counter": metrics.counter, "gauge": metrics.gauge}.get(spec.kind)
    if build is not None:
        return build(spec.name, spec.help, spec.labels, max_series=spec.max_series)
    return metrics.histogram(
        spec.name, spec.help, spec.labels, buckets=spec.buckets or (), max_series=spec.max_series
    )


class StageCounts:
    """One stage's counting port: each outcome of its closed set bound at build, and an outcome
    outside it logged and dropped, never a new series. Raises nothing but `CancelledError`."""

    def __init__(self, counter: BoundedMetric, stage: str, outcomes: tuple[str, ...]) -> None:
        self.stage, self.outcomes = stage, outcomes
        self._children = {outcome: counter.labels(stage, outcome) for outcome in outcomes}

    def count(self, outcome: str) -> None:
        child = self._children.get(outcome)
        if child is None:
            _log().error("stream_outcome_unbound", stage=self.stage)
            return
        child.inc()


@dataclass(frozen=True, slots=True)
class StreamMetrics:
    consumer: StageCounts
    push: StageCounts
    position: StageCounts
    lags: Mapping[str, MetricChild]
    owed: MetricChild

    @classmethod
    def bind(cls, metrics: Metrics) -> StreamMetrics:
        counter, lag = _spec_metric(metrics, OUTCOMES), _spec_metric(metrics, LAG)
        consumer, push, position = (
            StageCounts(counter, stage, get_args(outcome.__value__))
            for stage, outcome in zip(STAGES, _OUTCOMES, strict=True)
        )
        lags = MappingProxyType({topic: lag.labels(topic) for topic in sorted(_TOPICS)})
        owed = _spec_metric(metrics, OWED_AGE).child()
        return cls(consumer, push, position, lags, owed)

    def lag(self, topic: str, seconds: float) -> None:
        """One row's lag by its kind (S8b observes it on dequeue); a kind outside the closed set,
        or a negative lag, is no sample."""
        child = self.lags.get(topic)
        if child is not None and seconds >= 0:
            child.observe(seconds)


class OwedReadings(Protocol):
    def oldest_unhanded_age_s(self) -> float: ...


def _none_owed() -> float:
    return 0.0


def _scraped(gauge: MetricChild, read: Callable[[], float]) -> None:
    """`read` at each scrape of `gauge` (`Gauge.set_function`); a child the series cap refused, a
    no-op, has none."""
    set_function = getattr(gauge, "set_function", None)
    if set_function is not None:
        set_function(read)


class Faulted(Protocol):
    @property
    def fault(self) -> str | None: ...


class StreamReadiness:
    """The readiness hooks S8b gives `/readyz` (Q7): the owed reading's age, read into its gauge,
    and why the consumer is degraded, or None; the detail names no account."""

    def __init__(self, consumer: Faulted, positions: OwedReadings, gauge: MetricChild) -> None:
        self._consumer, self._positions, self._gauge = consumer, positions, gauge
        self._age = 0.0

    def owed_age_s(self) -> float:
        """The oldest owed reading's age, set on the gauge; read from another thread, a read that
        fails (the lane's write met, or anything else) keeps the last age and is logged by its
        class, never raised into `/readyz`."""
        try:
            self._age = self._positions.oldest_unhanded_age_s()
        except Exception as exc:  # try at the next read
            _log().warning("stream_owed_age_unread", error=type(exc).__name__)
            return self._age
        self._gauge.set(self._age)
        return self._age

    def degraded(self) -> str | None:
        if self._consumer.fault is not None:
            return "the private-stream consumer has faulted"
        if self.owed_age_s() >= OWED_DEGRADED_S:
            return "a position reading has been owed to protection too long"
        return None

    def bind(self) -> None:
        """From the consumer's start (S8b): the owed gauge reads `owed_age_s` at each scrape, not
        only when `/readyz` reads it, so the 60 s page sees an age no probe asked for."""
        _scraped(self._gauge, self.owed_age_s)

    def unbind(self) -> None:
        """At the consumer's stop: the gauge reads 0 again, no longer the stopped projection."""
        _scraped(self._gauge, _none_owed)


# --- the consumer's ports (S8b) -----------------------------------------------------------------


class PortStreams:
    """`PrivateStreams` (24 Sec.8.12 "Its ports"): the account's stream on its own environment's
    port (`TradingRouter.port_for`), the order lane's, which opens it across the lane's bridge from
    the serving loop's one registry (`oms_streams.LaneStreams`, 20 Sec.6.2); an environment the
    router has no port for is its `EnvironmentMismatch`."""

    def __init__(self, ports: Ports) -> None:
        self._ports = ports

    async def subscribe(self, account: AccountRef) -> PrivateStream:
        return await self._ports.port_for(account.environment).subscribe_private(account)


class TrackedAccounts(Protocol):
    """Account health's last good tracking read (`AccountHealthRuntime.streamed`)."""

    def streamed(self) -> frozenset[UUID]: ...


class HealthAccounts:
    """`StreamedAccounts` (the orchestrator's Q5): the set account health monitors, its last good
    tracking read, never an account it tracks for a replayed or owed dead-man's-switch call alone,
    read in place from the lane: one read of a frozenset the serving loop replaces whole, never a
    hop, so no stall of that loop faults the consumer. It raises until health's boot pass. The
    set is answered as health holds it, never copied: the same object until health's next read
    replaces it, equal or not, which is how the consumer tells one read from the next (its hold
    on a disabled account, 24 Sec.8.12)."""

    def __init__(self, health: TrackedAccounts) -> None:
        self._health = health

    async def streamed_accounts(self) -> frozenset[AccountId]:
        return cast("frozenset[AccountId]", self._health.streamed())  # ids: `AccountId` is a UUID


class ClockReading(Protocol):
    """The clock guard's verdict (`ClockHealth.assert_healthy`), read in place: attribute reads of
    values the guard replaces whole (20 Sec.6.2 "read in place")."""

    def assert_healthy(self) -> None: ...


class ClockEpoch:
    """`ClockEpochs` (the orchestrator's Q7): how often the exchange clock has come back into sync,
    read on each item the consumer takes, with no poll task. Each read reads the clock guard's
    health in place, and the epoch moves once each time a read finds it healthy after one that
    did not: an unhealthy-to-healthy edge, never every healthy read. A read that raises anything
    (unmeasured, drifted, or no guard at all) is not healthy. On the order lane alone, where every
    account's task runs, so the first account to read an edge moves the epoch for all. It starts
    healthy, so a clock still unmeasured when the consumer starts and measured soon after is an
    edge too: each account then re-applies once, a no-op while it holds no row."""

    def __init__(self, clock: ClockReading) -> None:
        self._clock, self._epoch, self._healthy = clock, 0, True

    def epoch(self) -> int:
        try:
            self._clock.assert_healthy()
        except Exception:  # not in sync: the next healthy read is the edge
            self._healthy = False
            return self._epoch
        if not self._healthy:
            self._healthy, self._epoch = True, self._epoch + 1
        return self._epoch


# --- the clock (Q9) -----------------------------------------------------------------------------


class ExchangeWallClock:
    """`positions.WallClock`: the host's aware UTC time plus the exchange clock's measured offset
    (server minus local, in ms; bind `Ingestion.clock_offset_snapshot_ms`, never
    `clock_offset_ms`, module docstring); 0 while unmeasured, while the read fails or while the
    offset is past `MAX_OFFSET_MS`, with one WARNING for each such run."""

    def __init__(
        self, offset_ms: Callable[[], int | None],
        *, now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:  # fmt: skip
        self._offset_ms, self._now = offset_ms, now
        self._unmeasured = False

    def __call__(self) -> datetime:
        return self._now() + timedelta(milliseconds=self._offset())

    def now_us(self) -> int:
        """The same time in microseconds since the epoch (the consumer's wallet check)."""
        return (self() - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1)

    def host_us(self) -> int:
        """The host's own time in microseconds since the epoch, with no offset: the clock the
        adapter stamps `PrivateEvent.ts_ingest` on, so the consumer's lag (S8b) never takes the
        venue's skew."""
        return (self._now() - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1)

    def _offset(self) -> int:
        try:
            offset = self._offset_ms()
        except Exception:  # unread is unmeasured
            offset = None
        if offset is None or abs(offset) > MAX_OFFSET_MS:
            if not self._unmeasured:
                self._unmeasured = True
                _log().warning("stream_wall_clock_unmeasured", measured=offset is not None)
            return 0
        self._unmeasured = False
        return offset


# --- the lane's reads ---------------------------------------------------------------------------


class StreamReadsBinding:
    """`StreamReads`: the order store's two reads and the recorded-stop facade's `live_for_key`."""

    def __init__(self, orders: OrderReads, stops: StreamStops) -> None:
        self._orders, self._stops = orders, stops

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None:
        return await self._orders.get_by_exchange_order_id(account_id, xid)

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None:
        return await self._orders.get_by_link_id(account_id, order_link_id)

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        return await self._stops.live_for_key(account_id, symbol, position_idx)


class VenueFillOrders:
    """`FillOrders`: a fill's order on its account's port, its history by the exchange id first,
    then its open orders on a miss; the account's own order only, else None. A failure raises (the
    caller's bound decides nothing on it)."""

    def __init__(self, accounts: TradingAccounts, ports: Ports) -> None:
        self._accounts, self._ports = accounts, ports

    async def order_of(self, account_id: UUID, xid: str, symbol: str) -> Order | None:
        ref = await self._accounts.trading_account(AccountId(account_id))
        port = self._ports.port_for(ref.environment)
        found = _the(await port.order_history(ref, exchange_order_id=xid), account_id, xid)
        if found is None:
            found = _the(await port.open_orders(ref, Symbol(symbol)), account_id, xid)
        return found


def _the(orders: Sequence[Order], account_id: UUID, xid: str) -> Order | None:
    return next(
        (o for o in orders if (o.account_id, o.exchange_order_id) == (account_id, xid)), None
    )


# --- the composition ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamWiring:
    """What `build_stream_consumer` composed: the consumer the OMS runtime starts and stops (S8b),
    its parts, the stand-ins as bound (the live refusals read them), the metrics and the readiness
    hooks."""

    consumer: StreamConsumer
    pushes: StreamPushes
    positions: PositionProjection
    stops: RecordedStopStream
    successors: Successor
    reconciliation: ReconciliationRequests
    stand_ins: Mapping[RuntimePortName, object]
    metrics: StreamMetrics
    readiness: StreamReadiness
    clock: ExchangeWallClock

    def refuse_live(self, environment: ProcessEnvironment) -> None:
        """The live start-up self-checks, on the bindings as bound, before any wrapper (24
        Sec.8.12): `NoReconciliation` and `NoPositionRows` each refuse a live start.
        `build_stream_consumer` runs them on its own environment before it returns."""
        refuse_live_without_reconciliation(environment, self.reconciliation)
        refuse_live_without_position_rows(environment, self.positions)

    def start(self) -> None:
        """S8b, on the loop that consumes (the order lane): the consumer starts, and from then the
        owed gauge reads the projection at each scrape; once, and never after `stop()`."""
        if self.consumer.start():
            self.readiness.bind()

    async def stop(self) -> None:
        """The consumer's stop, within its own bound (`stream_consumer.STOP_TIMEOUT_S`, counted
        `stop_timeout` past it), then the owed gauge reads 0 again, whatever the stop met."""
        try:
            await self.consumer.stop()
        finally:
            self.readiness.unbind()


def build_stream_consumer(
    *, facade: StreamFacade, orders: OrderReads, stops: StreamStops,
    positions: PositionWrites, snapshots: SnapshotWrites, accounts: StreamedAccounts,
    trading: TradingAccounts, ports: Ports, health: StreamEvidence,
    hub: SystemBroadcast, serving: Notify, credentials: CredentialRejections,
    audit: KeyedAudit, emitter: AuditEmitter, environment: ProcessEnvironment, pager: Pager,
    metrics: Metrics, now: Callable[[], datetime], offset_ms: Callable[[], int | None],
    clock_health: ClockReading, clock: ExchangeWallClock | None = None,
    wall_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    reconciliation: ReconciliationRequests | None = None,
    handovers: ExecutionHandovers | None = None, readings: ProtectionReadings | None = None,
    lockout: ForeignOrderLockout | None = None,
) -> StreamWiring:  # fmt: skip
    """The consumer and its parts, built and not started (module docstring). `environment` is the
    process's: its records' `env`, and the live refusals, run here on the bindings as bound, so a
    live process with a stand-in that refuses live never gets a consumer. Each account's stream is
    subscribed on `ports`, its environment's port (`PortStreams`). `now` is the OMS's clock (the
    successor's bind); `offset_ms` the exchange clock's offset, bound to
    `Ingestion.clock_offset_snapshot_ms` and never `clock_offset_ms` (the lane reads it); `wall_now`
    the host's aware UTC time (`ExchangeWallClock`); `clock`, when given, the position store's own
    `ExchangeWallClock`, which the projection and the consumer then read too (S8b), else one is
    built over those two; `clock_health` the clock guard's verdict, the re-sync epoch's source
    (`ClockEpoch`). A stand-in a caller does not name is bound; each is announced, a real port at
    0."""
    writer = NoIntentWriter(emitter, environment=environment.value)
    reconciliation = NoReconciliation() if reconciliation is None else reconciliation
    handovers = NoHandoverStore() if handovers is None else handovers
    readings = NoPositionProtection() if readings is None else readings
    lockout = PagingForeignOrderLockout(writer, pager) if lockout is None else lockout
    stand_ins: dict[RuntimePortName, object] = {
        "reconciliation": reconciliation,
        "execution_handovers": handovers,
        "protection_readings": readings,
        "foreign_order_lockout": lockout,
    }
    for name, port in stand_ins.items():
        announce_interim_port(name, port, metrics=metrics)
    counts = StreamMetrics.bind(metrics)
    clock = ExchangeWallClock(offset_ms, now=wall_now) if clock is None else clock
    projection = PositionProjection(
        orders=facade, positions=positions, snapshots=snapshots, readings=readings,
        counts=counts.position, pager=pager, stops=stops, order_rows=orders,
        monotonic=monotonic, now=clock,
    )  # fmt: skip
    recorded = RecordedStopStream(
        machines=facade, reads=orders, accounts=trading, positions=projection,
        counts=counts.push, pager=pager,
    )  # fmt: skip
    successor = Successor(
        stops=stops, audit=audit, positions=projection, counts=counts.push, clock=now
    )
    pushes = StreamPushes(
        target=facade, reads=StreamReadsBinding(orders, stops),
        fill_orders=VenueFillOrders(trading, ports), lockout=lockout, handovers=handovers,
        stops=recorded, successors=successor, no_intent=PagedNoIntentRecords(writer, pager),
        counts=counts.push, pager=pager, monotonic=monotonic,
    )  # fmt: skip
    consumer = StreamConsumer(
        accounts=accounts, trading=trading, streams=PortStreams(ports),
        health=ServedEvidence(health, serving), reconciliation=reconciliation,
        notices=StreamNotices(hub, serving), credentials=GuardedRejections(credentials, pager),
        positions=projection, pushes=pushes, counts=counts.consumer, pager=pager,
        now_us=clock.now_us, lags=counts, host_us=clock.host_us, epochs=ClockEpoch(clock_health),
    )  # fmt: skip
    wired = StreamWiring(
        consumer, pushes, projection, recorded, successor, reconciliation,
        MappingProxyType(stand_ins), counts, StreamReadiness(consumer, projection, counts.owed),
        clock,
    )  # fmt: skip
    wired.refuse_live(environment)
    return wired
