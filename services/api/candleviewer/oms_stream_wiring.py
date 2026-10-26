"""The private-stream consumer's composition (E29-T05 #848, S8a; 24-internal-schemas.md Sec.8.12,
23-ws-protocol.md Sec.15.9, 20-architecture.md Sec.12.1). Built and unit-tested here; the OMS
runtime starts it (S8b), so until then nothing outside the tests calls `build_stream_consumer`.

**On the order lane, with no hop.** `StreamPushes`, `PositionProjection` (never `NoPositionRows`),
`RecordedStopStream` and the successor's check (`Successor`) take the one facade (`OrderMachines`:
`push`, `protecting`, `push_protection`, `materialise`), the OMS order store and the recorded-stop
facade. A fill's order is read on the account's own port (`VenueFillOrders`): its history by the
exchange id, then its open orders on a miss.

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
set at build, with no account label; `oms_stream_event_lag_seconds{topic}` is bound for the lag
(S8b observes it); `StreamReadiness` reads the consumer's fault and the oldest owed reading's age
into `oms_position_reading_owed_age_seconds`, degraded at `OWED_DEGRADED_S` (the 2026-10-25 ruling
Q7), with a detail that names no account (`/readyz` is anonymous).

**The clock.** `ExchangeWallClock` is the projection's record clock and the consumer's: the host's
aware UTC time plus the exchange clock's measured offset (server minus local,
`Ingestion.clock_offset_ms`), 0 while unmeasured with one WARNING (ruling Q9). The successor's bind
is stamped on the OMS's own clock (24 Sec.8.3 rule 7).

Logs carry ids, a reason code or a class only (C-12.6).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, ClassVar, Final, Literal, Protocol, get_args
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.models import AccountRef, Order, PrivateKind
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
    PrivateStreams,
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
    """The two reads of an environment's trading port a fill's order takes."""

    async def order_history(
        self, account: AccountRef, *, exchange_order_id: str | None = None
    ) -> Sequence[Order]: ...

    async def open_orders(
        self, account: AccountRef, symbol: Symbol | None = None
    ) -> Sequence[Order]: ...


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


def _page(pager: Pager, summary: str, machine_kind: str) -> None:
    try:
        pager.raise_alert("page", summary, machine_kind=machine_kind)
    except Exception as exc:  # the page is lost, never its caller
        _log().critical("stream_pager_failed", summary=summary, error=type(exc).__name__)


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
    """Writes the record ahead, then pages P1, once per (account, key): a key paged already
    changes nothing. A write that fails raises before any page, and the key is not remembered."""

    machine_kind: ClassVar[str]

    def __init__(self, writer: NoIntentWriter, pager: Pager, *, max_keys: int = MAX_PAGED_KEYS):
        self._writer, self._pager, self._max = writer, pager, max_keys
        self._paged: OrderedDict[tuple[AccountId, str], None] = OrderedDict()

    async def _once(
        self, account_id: AccountId, finding: Finding, key: str, *, placed: bool
    ) -> None:
        seen = (account_id, key)
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
        _page(self._pager, summary, self.machine_kind)


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
        meets the lane's write keeps the last age."""
        try:
            self._age = self._positions.oldest_unhanded_age_s()
        except RuntimeError:  # the projection's dict changed under the read: try at the next
            return self._age
        self._gauge.set(self._age)
        return self._age

    def degraded(self) -> str | None:
        if self._consumer.fault is not None:
            return "the private-stream consumer has faulted"
        if self.owed_age_s() >= OWED_DEGRADED_S:
            return "a position reading has been owed to protection too long"
        return None


# --- the clock (Q9) -----------------------------------------------------------------------------


class ExchangeWallClock:
    """`positions.WallClock`: the host's aware UTC time plus the exchange clock's measured offset
    (server minus local, in ms); 0 while unmeasured, or while the read fails, with one WARNING
    for each such run."""

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

    def _offset(self) -> int:
        try:
            offset = self._offset_ms()
        except Exception:  # unread is unmeasured
            offset = None
        if offset is None:
            if not self._unmeasured:
                self._unmeasured = True
                _log().warning("stream_wall_clock_unmeasured")
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
    """What `build_stream_consumer` composed: the consumer S8b starts and stops, its parts, the
    stand-ins as bound (the live refusals read them), the metrics and the readiness hooks."""

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
        Sec.8.12): `NoReconciliation` and `NoPositionRows` each refuse a live start."""
        refuse_live_without_reconciliation(environment, self.reconciliation)
        refuse_live_without_position_rows(environment, self.positions)


def build_stream_consumer(
    *, facade: StreamFacade, orders: OrderReads, stops: StreamStops,
    positions: PositionWrites, snapshots: SnapshotWrites, accounts: StreamedAccounts,
    trading: TradingAccounts, ports: Ports, streams: PrivateStreams, health: StreamEvidence,
    hub: SystemBroadcast, serving: Notify, credentials: CredentialRejections,
    audit: KeyedAudit, emitter: AuditEmitter, environment: str, pager: Pager, metrics: Metrics,
    now: Callable[[], datetime], offset_ms: Callable[[], int | None],
    monotonic: Callable[[], float] = time.monotonic,
    reconciliation: ReconciliationRequests | None = None,
    handovers: ExecutionHandovers | None = None, readings: ProtectionReadings | None = None,
    lockout: ForeignOrderLockout | None = None,
) -> StreamWiring:  # fmt: skip
    """The consumer and its parts, built and not started (module docstring). `now` is the OMS's
    clock (the successor's bind); `offset_ms` the exchange clock's offset (`ExchangeWallClock`).
    A stand-in a caller does not name is bound; each is announced, a real port at 0."""
    writer = NoIntentWriter(emitter, environment=environment)
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
    counts, clock = StreamMetrics.bind(metrics), ExchangeWallClock(offset_ms)
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
        accounts=accounts, trading=trading, streams=streams,
        health=ServedEvidence(health, serving), reconciliation=reconciliation,
        notices=StreamNotices(hub, serving), credentials=GuardedRejections(credentials, pager),
        positions=projection, pushes=pushes, counts=counts.consumer, pager=pager,
        now_us=clock.now_us,
    )  # fmt: skip
    return StreamWiring(
        consumer, pushes, projection, recorded, successor, reconciliation,
        MappingProxyType(stand_ins), counts, StreamReadiness(consumer, projection, counts.owed),
        clock,
    )  # fmt: skip
