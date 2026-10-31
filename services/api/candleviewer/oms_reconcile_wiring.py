"""Reconciliation's composition (E29-T06 #914 PR 2b; 24-internal-schemas.md Sec.8.5, Sec.8.10,
Sec.8.12, Sec.15.5; 23-ws-protocol.md Sec.15.9; 20-architecture.md Sec.6.2 and Sec.12.1). The OMS
runtime (`oms_wiring`) builds it in its composition's `reconcile` phase, on the order lane, after
the facade and before the private-stream consumer, which takes its driver as its
`ReconciliationRequests` (replacing `NoReconciliation`) and its hand-over store as its
`ExecutionHandovers` (replacing `NoHandoverStore`). No flag gates it (C-4.14).

`build_reconciliation` binds PR 2a's ports to the runtime's stores and adapters:

* the trading reads, on the `poll` lane, through the runtime's `TradingRouter` and its headroom;
* the stored rows and fills, the account-wide recorded-stop copy and the watermark, through the
  pass's own store (`SqlAlchemyReconcileStore`) beside the order store's lookups;
* the hand-over store (`StoreHandovers` over `oms_handovers`, its source `reconcile`);
* the position projection's REST side (`PositionsTruth`), which applies an exchange read over the
  stored position, snapshots it `rest_reconcile` and answers what it held before;
* E29-T04's recorded-stop writer on the `critical` lane (`RecordedStopWriter`);
* the foreign-order freeze, E39-T04's setter (BQ-16), and the exchange-placed records: the very
  instances the stream consumer takes, so a finding pages once whichever caller meets it;
* the adoption's audit (`order.adopted_untracked`) and the report's (`oms.reconcile`,
  `stage: finished`), written ahead through the lane's own audit writer as `system:oms` (C-2.9);
* the notices (`ReconcileNoticesBinding`, 23 Sec.15.9's closed table, offered to the gateway's
  `system` topic on the serving loop: no new bus topic, BQ-6), the pager, and the five metrics of
  20 Sec.12.1 with no account label (`ReconcileMetrics`; `oms_stale_accounts` is the driver's);
* the stream's last message per account (`LastMessages`), the other half of `gap_from`.

The pass, its phases and B19's port (`ReconcilePhases`) then go to the driver (`ReconcileJobs`),
which owns the jobs and their timers. The standing it sets and clears is the one the order-entry
gate consults (`account_stale`, composed by `app.py`), never the protective paths (C-2.6).

Logs carry ids, kinds and outcomes only (C-12.6).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import Order, Position
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.handovers import StoreHandovers
from candleviewer.oms.ports import (
    ForeignOrderLockout,
    StopRequestGate,
    SubmitAudit,
    TradingAccounts,
)
from candleviewer.oms.push_mapping import money_text
from candleviewer.oms.reconcile_job import JobPersistence, ReconcileJobs, RetryHop
from candleviewer.oms.reconcile_phases import ReconcilePhases
from candleviewer.oms.reconcile_report import Notice, ReconcileMetrics
from candleviewer.oms.reconcile_standing import FailureTracker, ReconcileStanding
from candleviewer.oms.reconcile_stops import RecordedStopWriter
from candleviewer.oms.reconciler import (
    ExchangePlaced,
    OrderMachinesPort,
    Pager,
    PositionDriftSeen,
    ReadRouter,
    ReconcilePorts,
    Reconciler,
)
from candleviewer.oms.stream_consumer import StreamEvidence
from candleviewer.oms_stream_wiring import (
    SYSTEM_ACTOR,
    AuditEmitter,
    Notify,
    SystemBroadcast,
    account_notice,
    checked_notice,
)
from candleviewer.statechart.factory import restore as restore_chart
from candleviewer.statechart.persistence import MachineKey, SealedSnapshot
from candleviewer.statechart.plugins import MachineEventSink
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import (
    NewPositionSnapshot,
    PositionRow,
    PositionState,
)
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

__all__ = [
    "ADOPTED_UNTRACKED",
    "RECONCILE",
    "AccountWatermarks",
    "AdoptionRecords",
    "BundleJobs",
    "LastMessages",
    "PassFills",
    "PassOrders",
    "PassStops",
    "PositionsTruth",
    "ReconcileNoticesBinding",
    "ReconcileRecords",
    "ReconcileWiring",
    "build_reconciliation",
]

#: The two audited actions the pass writes (24 Sec.15.5), registered in `audit/actions.py`.
RECONCILE: Final = "oms.reconcile"
ADOPTED_UNTRACKED: Final = "order.adopted_untracked"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_US: Final = timedelta(microseconds=1)
#: A stored position's side, as the exchange's read names it (`Position.side`).
_SIDE: Final[Mapping[str | None, str | None]] = {"Buy": "buy", "Sell": "sell", "None": None}
_STORED_SIDE: Final[Mapping[str | None, Any]] = {"buy": "Buy", "sell": "Sell", None: "None"}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _at(us: int) -> datetime:
    return _EPOCH + us * _US


def _us(at: datetime) -> int:
    return (at - _EPOCH) // _US


# --- The stores' reads (`LocalOrders`, `StoredExecutions`, `RecordedStopCopy`, `Watermarks`) -----


class ReconcileReads(Protocol):
    """`storage.repositories.reconcile_sqlalchemy.SqlAlchemyReconcileStore`."""

    async def unfinished_for(self, account_id: UUID) -> Sequence[OrderRow]: ...

    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]: ...

    async def live_for_account(self, account_id: UUID) -> Sequence[RecordedStopRow]: ...

    async def last_reconciled(self, account_id: UUID) -> datetime | None: ...

    async def advance(self, account_id: UUID, to: datetime) -> bool: ...


class OrderLookups(Protocol):
    """The order store's lookups (`OrderStore`)."""

    async def get_by_exchange_order_id(
        self, account_id: UUID, exchange_order_id: str
    ) -> OrderRow | None: ...

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...

    async def link_id_taken(self, order_link_id: str) -> bool: ...


class FillInserts(Protocol):
    async def insert(self, execution: NewExecution) -> bool: ...


class PassOrders:
    """`reconciler.LocalOrders`: the account's unfinished rows from the pass's store, the lookups
    from the order store."""

    def __init__(self, reads: ReconcileReads, orders: OrderLookups) -> None:
        self._reads, self._orders = reads, orders

    async def unfinished_for(self, account_id: UUID) -> Sequence[OrderRow]:
        return await self._reads.unfinished_for(account_id)

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None:
        return await self._orders.get_by_exchange_order_id(account_id, xid)

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None:
        return await self._orders.get_by_link_id(account_id, order_link_id)

    async def link_id_taken(self, order_link_id: str) -> bool:
        return await self._orders.link_id_taken(order_link_id)


class PassFills:
    """`reconciler.StoredExecutions`: which `exec_id`s are stored, and a fill with no order."""

    def __init__(self, reads: ReconcileReads, fills: FillInserts) -> None:
        self._reads, self._fills = reads, fills

    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]:
        return await self._reads.stored(account_id, exec_ids)

    async def insert(self, execution: NewExecution) -> bool:
        return await self._fills.insert(execution)


class PassStops:
    """`reconciler.RecordedStopCopy`: the account's live recorded stops."""

    def __init__(self, reads: ReconcileReads) -> None:
        self._reads = reads

    async def live_for_account(self, account_id: UUID) -> Sequence[RecordedStopRow]:
        return await self._reads.live_for_account(account_id)


class AccountWatermarks:
    """`reconcile_phases.Watermarks`: `exchange_accounts.last_reconciled_at`, in microseconds."""

    def __init__(self, reads: ReconcileReads) -> None:
        self._reads = reads

    async def last_reconciled_us(self, account_id: AccountId) -> int | None:
        at = await self._reads.last_reconciled(account_id)
        return None if at is None else _us(at)

    async def advance(self, account_id: AccountId, to_us: int) -> None:
        if not await self._reads.advance(account_id, _at(to_us)):
            _log().warning("reconcile_watermark_not_moved", account_id=str(account_id))


# --- The positions' REST side (`PositionTruth`) --------------------------------------------------


class OpenPositions(Protocol):
    async def list_open(self, account_id: UUID) -> Sequence[PositionRow]: ...


class PositionUpserts(Protocol):
    """The position store's write; the runtime's publishes each applied row to E29-T13's
    `positions` topic, so a correction reaches every view (BQ-6)."""

    async def upsert(self, state: PositionState) -> PositionRow: ...


class SnapshotWrites(Protocol):
    async def append(self, snapshot: NewPositionSnapshot) -> Any: ...


def _seen(row: PositionRow) -> PositionDriftSeen:
    return PositionDriftSeen(_SIDE.get(row.side), row.size)


def _state(p: Position) -> PositionState:
    return PositionState(
        exchange_account_id=p.account_id, symbol=p.symbol, size=p.qty,
        position_idx=p.position_idx, side=_STORED_SIDE[p.side], avg_price=p.avg_entry_price,
        leverage=p.leverage, mark_price=p.mark_price, liq_price=p.liq_price,
        unrealised_pnl=p.unrealised_pnl, cum_realised_pnl=p.cum_realised_pnl,
        take_profit=p.take_profit, stop_loss=p.stop_loss, trailing_stop=p.trailing_stop_distance,
        exchange_updated_ts=_at(p.updated_at),
    )  # fmt: skip


class PositionsTruth:
    """`reconciler.PositionTruth` (step 4, 21 Sec.3.3.7): what the projection holds for each of the
    account's keys, and an exchange read applied over it, snapshotted `rest_reconcile`, answering
    what it held before when the read changed it; None when equal, or older than the row held
    (the store keeps the newer, so the stream's later push wins)."""

    def __init__(
        self, reads: OpenPositions, writes: PositionUpserts, snapshots: SnapshotWrites
    ) -> None:
        self._reads, self._positions, self._snapshots = reads, writes, snapshots

    async def held(self, account_id: UUID) -> Mapping[tuple[str, int], PositionDriftSeen]:
        rows = await self._reads.list_open(account_id)
        return {(r.symbol, r.position_idx): _seen(r) for r in rows}

    async def apply(self, position: Position, *, pass_id: str) -> PositionDriftSeen | None:
        key = (position.symbol, position.position_idx)
        before = (await self.held(position.account_id)).get(key)
        state = _state(position)
        row = await self._positions.upsert(state)
        if row.exchange_updated_ts != state.exchange_updated_ts:
            return None  # an older read than the row held: the store kept the newer
        seen = before if before is not None else PositionDriftSeen(None, Decimal(0))
        if (seen.side, seen.qty) == (position.side, position.qty):
            return None
        snap = NewPositionSnapshot(
            exchange_account_id=position.account_id, symbol=position.symbol, size=position.qty,
            reason="rest_reconcile", position_idx=position.position_idx,
            avg_price=position.avg_entry_price, mark_price=position.mark_price,
            unrealised_pnl=position.unrealised_pnl, cum_realised_pnl=position.cum_realised_pnl,
            liq_price=position.liq_price,
        )  # fmt: skip
        try:
            await self._snapshots.append(snap)
        except Exception as exc:  # the correction stands; its snapshot is the history's
            _log().error("reconcile_snapshot_failed", account_id=str(position.account_id),
                         symbol=position.symbol, failure=type(exc).__name__)  # fmt: skip
        return seen


# --- The pass's records (C-2.9), notices (23 Sec.15.9) and the stream's mark --------------------


class ReconcileRecords:
    """`reconcile_phases.ReportRecords`: the pass's `oms.reconcile` record, `stage: finished`
    (24 Sec.15.5), as `system:oms`, the account its object; durable or it raises."""

    def __init__(self, emitter: AuditEmitter, *, environment: str) -> None:
        self._emitter, self._environment = emitter, environment

    async def finished(
        self, account_id: AccountId, *, pass_id: str, state: Mapping[str, object]
    ) -> None:
        await self._emitter.emit(
            RECONCILE, actor_label=SYSTEM_ACTOR, actor_user_id=None,
            object_kind="exchange_account", object_id=str(account_id), outcome="success",
            severity="info", reason="finished", after_state=dict(state), request_id=None,
            env=self._environment,
        )  # fmt: skip


class AdoptionRecords:
    """`reconciler.AdoptionAudit`: `order.adopted_untracked`, written ahead of the row (24
    Sec.15.5, BQ-17): the new row its object, the order as the venue reported it, never a payload
    or a credential (C-12.6)."""

    def __init__(self, emitter: AuditEmitter, *, environment: str) -> None:
        self._emitter, self._environment = emitter, environment

    async def adopted(
        self, account_id: AccountId, *, row_id: UUID, order: Order, pass_id: str
    ) -> None:
        price = None if order.price is None else money_text(order.price)
        await self._emitter.emit(
            ADOPTED_UNTRACKED, actor_label=SYSTEM_ACTOR, actor_user_id=None, object_kind="order",
            object_id=str(row_id), outcome="success", severity="warning", reason="reconcile",
            after_state={
                "account_id": str(account_id), "exchange_order_id": order.exchange_order_id,
                "order_link_id": order.order_link_id, "symbol": order.symbol, "side": order.side,
                "qty": money_text(order.qty), "order_type": order.order_type, "price": price,
                "exchange_placed": order.exchange_placed, "pass_id": pass_id,
            },
            request_id=None, env=self._environment,
        )  # fmt: skip


class ReconcileNoticesBinding:
    """`reconcile_phases.ReconcileNotices`: 23 Sec.15.9's row for the notice, checked against the
    closed table, offered to the gateway's `system` topic on the serving loop, never awaited.
    Raises nothing but `CancelledError`: a notice that is refused is logged by its class."""

    def __init__(self, hub: SystemBroadcast, serving: Notify) -> None:
        self._hub, self._serving = hub, serving

    def publish(self, account_id: AccountId, notice: Notice) -> None:
        try:
            body = checked_notice(account_notice(account_id, notice.reason, notice.severity))
            self._serving.notify(self._hub.broadcast_system, body)
        except Exception as exc:
            _log().error(
                "reconcile_notice_refused", account_id=str(account_id), error=type(exc).__name__
            )


class LastMessages:
    """`reconcile_phases.StreamMarks` and the stream's `StreamEvidence` in front of the feed: each
    piece of evidence the consumer gives (a row's dequeue, a heartbeat) marks the account's last
    private-stream message on the OMS's clock, then goes on (24 Sec.8.5 `gap_from`). Read and
    written on the order lane, where the consumer runs."""

    def __init__(self, feed: StreamEvidence, now_us: Callable[[], int]) -> None:
        self._feed, self._now_us = feed, now_us
        self._last: dict[AccountId, int] = {}

    def last_message_us(self, account_id: AccountId) -> int | None:
        return self._last.get(account_id)

    def ws_heartbeat(self, account_id: AccountId) -> object:
        self._last[account_id] = self._now_us()
        return self._feed.ws_heartbeat(account_id)

    def ws_dropped(self, account_id: AccountId) -> object:
        return self._feed.ws_dropped(account_id)

    def wallet_pushed(self, account_id: AccountId, snapshot: Any) -> object:
        return self._feed.wallet_pushed(account_id, snapshot)


# --- The persistence bundle as the driver takes it (`JobPersistence`) -----------------------------


class JobBundle(Protocol):
    """The statechart persistence bundle (`statechart_wiring.StatechartPersistence`)."""

    snapshots: Any
    persister: Any

    def restorer(self, lane: Any) -> Any: ...

    async def plugins_for(self, key: MachineKey, lane: Any) -> tuple[Any, ...]: ...


class BundleJobs:
    """`reconcile_job.JobPersistence` over the bundle, on the order lane: the restore goes through
    `statechart.persistence`'s `Restorer` (the factory's `restore`) only."""

    def __init__(self, bundle: JobBundle) -> None:
        self._bundle = bundle

    async def load(self, key: MachineKey) -> SealedSnapshot | None:
        sealed: SealedSnapshot | None = await self._bundle.snapshots.load(key)
        return sealed

    async def restore(self, key: MachineKey, sealed: SealedSnapshot) -> Any:
        return (await restore_chart(self._bundle.restorer("order"), key, sealed)).interpreter

    async def plugins(self, key: MachineKey) -> tuple[Any, ...]:
        return await self._bundle.plugins_for(key, "order")

    async def persist(self, interp: Any, key: MachineKey) -> None:
        await self._bundle.persister.persist(interp, key=key)


def job_persistence(bundle: object | None) -> JobPersistence | None:
    """The bundle's persistence for the jobs, where the bundle carries it (a real one does); None
    builds every job afresh and persists none, as a process with no bundle does."""
    members = ("snapshots", "persister", "restorer", "plugins_for")
    if bundle is None or not all(hasattr(bundle, name) for name in members):
        return None
    return BundleJobs(bundle)  # type: ignore[arg-type]  # its members checked above


# --- The composition ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconcileWiring:
    """What `build_reconciliation` composed: the driver the runtime starts and stops, its phases
    and pass, and the stream's mark, which the consumer's evidence goes through."""

    jobs: ReconcileJobs
    phases: ReconcilePhases
    reconciler: Reconciler
    marks: LastMessages


def build_reconciliation(
    *, environment: Environment, standing: ReconcileStanding, router: ReadRouter,
    accounts: TradingAccounts, reads: ReconcileReads, orders: OrderLookups, fills: FillInserts,
    handovers: StoreHandovers, machines: OrderMachinesPort, positions: OpenPositions,
    published: PositionUpserts, snapshots: SnapshotWrites, gate: StopRequestGate,
    audit: SubmitAudit, emitter: AuditEmitter,
    lockout: ForeignOrderLockout, exchange_placed: ExchangePlaced, hub: SystemBroadcast,
    serving: Notify, feed: StreamEvidence, metrics: Metrics, pager: Pager,
    sink: MachineEventSink, persistence: JobPersistence | None, now_us: Callable[[], int],
    stale_after_s: float, remediates: Callable[[Environment], bool],
) -> ReconcileWiring:  # fmt: skip
    """The pass, its phases and the driver over the runtime's stores and adapters (module
    docstring), built and not started; `ReconcileJobs.start` opens the jobs. A live or demo
    environment whose capability record does not remediate is a `ValueError` here, so the OMS's
    composition fails closed (24 Sec.14.3, C-2.6, C-4.14)."""
    if environment in ("live", "demo") and not remediates(environment):
        raise ValueError("a live or demo reconciliation job always remediates (24 Sec.14.3)")
    counted = ReconcileMetrics(metrics)
    writer = RecordedStopWriter(router=router, gate=gate, audit=audit)
    ports = ReconcilePorts(
        accounts=accounts, router=router, orders=PassOrders(reads, orders),
        executions=PassFills(reads, fills), stops=PassStops(reads), handovers=handovers,
        machines=machines, positions=PositionsTruth(positions, published, snapshots),
        protective=writer,
        lockout=lockout, exchange_placed=exchange_placed,
        adoptions=AdoptionRecords(emitter, environment=environment), pager=pager,
    )  # fmt: skip
    reconciler = Reconciler(ports, now_us=now_us, on_naked=counted.naked)
    marks, hop = LastMessages(feed, now_us), RetryHop()
    phases = ReconcilePhases(
        reconciler, standing=standing, tracker=FailureTracker(window_s=stale_after_s),
        marks=marks, watermarks=AccountWatermarks(reads),
        records=ReconcileRecords(emitter, environment=environment),
        notices=ReconcileNoticesBinding(hub, serving), retries=hop, metrics=counted,
        pager=pager, now_us=now_us,
    )  # fmt: skip
    jobs = ReconcileJobs(
        phases, standing=standing, environment=environment, remediates=remediates,
        metrics=metrics, pager=pager, sink=sink, persistence=persistence,
    )  # fmt: skip
    hop.bind(jobs)
    return ReconcileWiring(jobs, phases, reconciler, marks)
