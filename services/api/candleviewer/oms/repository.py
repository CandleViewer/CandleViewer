"""The OMS's persistence (E29-T01 #845): its five repositories over the `0029_oms_core` tables.

M14 may not import a storage driver (ADR-0003), so the SQL lives in M10
(`storage.repositories.*_sqlalchemy`) behind driver-free store protocols, and the composition root
hands these classes a store. They add the OMS's side:
`DuplicateOrderLinkId` for a second row under one id (#845 Gherkin), the 24 Sec.8.3 rule 5 lookup
the #846 allocator takes (`OrderLinkLookup`), and a log line with the `order_link_id` for every
order, event and fill write (ADR-0006 rule 1). Every read takes the exchange account (C-12.4) but
`exists`, a yes/no the allocator alone needs. The store redacts what the exchange said (`payload`,
`ret_code`, `ret_msg`) before binding it (21 Sec.3.3.5; the #845 security notes). A `WriteTimer`
times every write on `oms_db_write_seconds{table}`. `transition` and `commit_fill` (E29-T03) return
only once a step is committed with its event; any refusal writes nothing (24 Sec.8.2 S7, S8).

E29-T04 (#913) adds the order's first persist (`SubmissionRepository`), the replay anchor
(`IdempotencyAnchorRepository`) and the recorded stops (`RecordedStopRepository`). Each maps its
store's refusals to the OMS's typed errors, raised `from None`, and logs ids only: never the
client's key, the request's fingerprint or a price (21 Sec.12, C-12.6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter
from types import MappingProxyType
from typing import Final, Literal, cast, get_args
from uuid import UUID

import structlog

from candleviewer.observability.metrics import BoundedMetric
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.executions import (
    ExecutionRow,
    ExecutionStore,
    NewExecution,
    OrderFill,
)
from candleviewer.storage.repositories.idempotency_anchors import (
    AnchorOutcome,
    AnchorRow,
    IdempotencyAnchorStore,
)
from candleviewer.storage.repositories.orders import (
    MAX_EVENT_PAGE,
    UX_ORDERS_LINK,
    CommittedStep,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderEventStore,
    OrderRow,
    OrderStore,
    OrderTransition,
)
from candleviewer.storage.repositories.positions import (
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionSnapshotStore,
    PositionState,
    PositionStore,
)
from candleviewer.storage.repositories.recorded_stops import (
    SWEEP_REASON,
    UX_RS_IN_FLIGHT,
    FillPosition,
    InForce,
    InForceWriteAhead,
    InsertWriteAhead,
    NewRecordedStop,
    RecordedStopRow,
    RecordedStopStore,
    ReleaseWriteAhead,
    ResolveOutcome,
    ResolveWriteAhead,
    SettleWriteAhead,
    StopOutcome,
    SweepScope,
    SweepWriteAhead,
    SweptStop,
    check_resolve,
)
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
    SubmissionRefusal,
    SubmissionStore,
)
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    PROFILE_CHANGED,
    TradeGroupStoreRefusedError,
)

from .errors import (
    AnchorTaken,
    AuditNotDurable,
    DuplicateOrderLinkId,
    StopRequestInFlight,
    SubmissionRefused,
)

__all__ = [
    "WRITE_TABLES", "ExecutionRepository", "IdempotencyAnchorRepository", "OrderEventRepository",
    "OrderRepository", "PositionRepository", "PositionSnapshotRepository",
    "RecordedStopRepository", "SubmissionRepository", "WriteTimer",
]  # fmt: skip

WriteTable = Literal[
    "orders", "order_events", "executions", "positions", "position_snapshots",
    "idempotency_anchors", "recorded_stops",
]  # fmt: skip
#: The `table` values of `oms_db_write_seconds`; the metric catalogue caps it at as many series.
WRITE_TABLES: Final = get_args(WriteTable)
#: The trade-group store's refusals a first persist can meet, as the OMS names them (SEC-2A-06).
_SUBMISSION_REFUSALS: Final[Mapping[str, SubmissionRefusal]] = MappingProxyType(
    {ACCOUNT_NOT_LIVE: "account_not_live", PROFILE_CHANGED: "profile_changed"}
)


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class WriteTimer:
    """Observes how long each store write takes on `oms_db_write_seconds{table}`, a failed or
    cancelled write too: it held the order path as long. The composition root (E29-T04) passes the
    histogram; without one, nothing is observed."""

    def __init__(
        self, histogram: BoundedMetric | None = None, *, clock: Callable[[], float] = perf_counter
    ) -> None:
        self._histogram = histogram
        self._clock = clock

    @contextmanager
    def measure(self, table: WriteTable) -> Iterator[None]:
        start = self._clock()
        try:
            yield
        finally:
            if self._histogram is not None:
                self._histogram.labels(table).observe(self._clock() - start)


_UNTIMED: Final = WriteTimer()


class OrderRepository:
    """`orders`, through an `OrderStore`."""

    def __init__(self, store: OrderStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        """The submit hot path: the row and its first event in one transaction (#845); a second
        row under the id raises `DuplicateOrderLinkId`."""
        try:
            with self._timer.measure("orders"):
                row = await self._store.create(order, first_event)
        except OrderConstraintError as exc:
            if exc.constraint != UX_ORDERS_LINK:
                raise
            raise DuplicateOrderLinkId(order.order_link_id) from None
        _log().info(
            "oms_order_created",
            order_link_id=row.order_link_id,
            order_id=str(row.id),
            account_id=str(row.exchange_account_id),
            state=row.state,
        )
        return row

    async def transition(self, step: OrderTransition) -> CommittedStep:
        """The write-ahead step: `StaleOrderState` when another writer moved the order first."""
        with self._timer.measure("orders"):
            done = await self._store.transition(step)
        _log_step("oms_order_transitioned", done)
        return done

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        return await self._store.get(account_id, order_id)

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None:
        return await self._store.get_by_link_id(account_id, order_link_id)

    async def get_by_exchange_order_id(
        self, account_id: UUID, exchange_order_id: str
    ) -> OrderRow | None:
        return await self._store.get_by_exchange_order_id(account_id, exchange_order_id)

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        return await self._store.list_open(account_id, symbol=symbol)

    async def exists(self, order_link_id: str) -> bool:
        """`OrderLinkLookup` (#846 rulings B1, Q1): any row of any account, in any state. A
        yes/no only: no order data leaves, and the unique index stays the final guard. It is
        unscoped, so it serves the allocator only and is never exposed on an API route or WS
        topic (M23)."""
        return await self._store.link_id_taken(order_link_id)


class OrderEventRepository:
    """`order_events`, append-only, through an `OrderEventStore`."""

    def __init__(self, store: OrderEventStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def append(self, account_id: UUID, order_id: UUID, event: NewOrderEvent) -> OrderEventRow:
        with self._timer.measure("order_events"):
            row = await self._store.append(account_id, order_id, event)
        _log().info(
            "oms_order_event_appended",
            order_link_id=row.order_link_id,
            order_id=str(row.order_id),
            seq=row.seq,
            kind=row.kind,
        )
        return row

    async def list_for_order(
        self, account_id: UUID, order_id: UUID, *, after_seq: int = -1, limit: int = MAX_EVENT_PAGE
    ) -> tuple[OrderEventRow, ...]:
        return await self._store.list_for_order(
            account_id, order_id, after_seq=after_seq, limit=limit
        )


class ExecutionRepository:
    """`executions`, append-only and deduplicated on `ux_exec_id`, through an `ExecutionStore`."""

    def __init__(self, store: ExecutionStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def insert(self, execution: NewExecution) -> bool:
        """Store a fill once whatever source reports it (24 Sec.8.2 S4): True when this call
        stored it, False when its account holds the `exec_id` already; `OrderNotFoundError` when
        `order_id` is not an order of that account. Only for a fill that moves no order's totals:
        one that does goes through `commit_fill`, which then reads it as applied."""
        with self._timer.measure("executions"):
            stored = await self._store.insert(execution)
        ids = {
            "order_link_id": execution.order_link_id,
            "order_id": None if execution.order_id is None else str(execution.order_id),
            "account_id": str(execution.exchange_account_id),
            "exec_id": execution.exec_id,
        }
        if stored:
            _log().info("oms_execution_stored", **ids)
        else:
            _log().debug("oms_execution_duplicate", **ids)
        return stored

    async def commit_fill(self, fill: OrderFill) -> CommittedStep | None:
        """A fill's write-ahead step; None when its `exec_id` is stored already (S4)."""
        with self._timer.measure("executions"):
            done = await self._store.commit_fill(fill)
        execution = fill.execution
        if done is None:
            ids = {"order_link_id": execution.order_link_id, "order_id": str(execution.order_id)}
            ids |= {"account_id": str(execution.exchange_account_id), "exec_id": execution.exec_id}
            _log().debug("oms_execution_duplicate", **ids)
        else:
            _log_step("oms_order_filled", done, exec_id=execution.exec_id)
        return done

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        return await self._store.get(account_id, exec_id)


def _log_step(name: str, done: CommittedStep, **extra: str) -> None:
    """A committed step's line: the ids and `state` every OMS line carries (E29-T08), the state
    it left and the step's event."""
    order, event = done.order, done.event
    ids = {"order_link_id": order.order_link_id, "order_id": str(order.id), **extra}
    ids |= {"account_id": str(order.exchange_account_id), "state": order.state}
    _log().info(name, **ids, from_state=event.from_state, seq=event.seq, source=event.source)


class PositionRepository:
    """`positions`, through a `PositionStore`. A position write names no order and comes with every
    position push, so it is timed but not logged."""

    def __init__(self, store: PositionStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def upsert(self, state: PositionState) -> PositionRow:
        """`PositionStore.upsert`: a stale write returns the stored row, and a time more than
        `MAX_FUTURE_SKEW` ahead of the store's clock raises `FutureDatedPositionError`, a clock
        fault the writer must log, count, alert and retry after clock sync (21 Sec.3.3.7)."""
        with self._timer.measure("positions"):
            return await self._store.upsert(state)

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        return await self._store.list_open(account_id)

    async def list_unprotected(self, account_id: UUID) -> tuple[PositionRow, ...]:
        """The account's open positions without an exchange-side stop: the naked-position
        alert's read (24 Sec.8.8 rule 3; `ix_pos_no_sl`)."""
        return await self._store.list_unprotected(account_id)


class PositionSnapshotRepository:
    """Appends to `position_snapshots` through a `PositionSnapshotStore`; timed, not logged."""

    def __init__(self, store: PositionSnapshotStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow:
        with self._timer.measure("position_snapshots"):
            return await self._store.append(snapshot)


class SubmissionRepository:
    """An order's first persist (E29-T04, 24 Sec.8.4 step 5), through a `SubmissionStore`: the
    entry's group and leg, the `validated` row and its event, the recorded stops and the anchor
    in one transaction, timed as an `orders` write."""

    def __init__(self, store: SubmissionStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def create_first(
        self, first: FirstPersist, order: NewOrder, event: NewOrderEvent
    ) -> FirstPersisted:
        """Raise, with nothing written: `ValueError` before any statement when `first` carries
        no write-ahead audit hook, as every first persist is audited (C-2.9, CR-2A-02);
        `DuplicateOrderLinkId` for a second row under the id, `AnchorTaken` when the request's
        key is held, `StopRequestInFlight` when a stop request is in flight for the position,
        `SubmissionRefused` when the account or the leg's profile is not live, `AuditNotDurable`
        when the write-ahead audit outlasts its bound; any other store refusal as it is."""
        if first.write_ahead is None:
            raise ValueError("a first persist is audited write-ahead (C-2.9): no hook was given")
        try:
            with self._timer.measure("orders"):
                persisted = await self._store.create_first(first, order, event)
        except OrderConstraintError as exc:
            if exc.constraint == UX_ORDERS_LINK:
                raise DuplicateOrderLinkId(order.order_link_id) from None
            if exc.constraint == UX_RS_IN_FLIGHT:
                raise StopRequestInFlight("a stop request is in flight for the position") from None
            raise
        except AnchorTakenError as exc:
            raise AnchorTaken(exc.constraint) from None
        except TradeGroupStoreRefusedError as exc:
            reason = _SUBMISSION_REFUSALS.get(exc.reason)
            if reason is None:  # a refusal no first persist can meet: the store's own error
                raise
            raise SubmissionRefused(reason) from None
        except WriteAheadTimeout:
            raise AuditNotDurable("the order's write-ahead audit did not land in time") from None
        row = persisted.order
        _log().info(
            "oms_order_first_persisted",
            order_link_id=row.order_link_id,
            order_id=str(row.id),
            account_id=str(row.exchange_account_id),
            state=row.state,
            anchor_id=str(persisted.anchor_id),
            trade_group_id=None if persisted.group is None else str(persisted.group.group.id),
            recorded_stops=[str(stop.id) for stop in persisted.recorded_stops],
        )
        return persisted


class IdempotencyAnchorRepository:
    """The replay anchor of `placeOrder` (SR-E29-07), through an `IdempotencyAnchorStore`."""

    def __init__(self, store: IdempotencyAnchorStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def find(
        self, created_by: UUID, client_ref: UUID, request_sha256: str
    ) -> AnchorRow | None:
        """The principal's `placeOrder` anchor of the key, its canonical text the column's
        (`ia_ref_fmt`); another principal's reads as missing."""
        return await self._store.find(created_by, "placeOrder", str(client_ref), request_sha256)

    async def record_outcome(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        """The first answer, by compare-and-set from NULL: False when one was recorded first."""
        with self._timer.measure("idempotency_anchors"):
            recorded = await self._store.record_outcome(anchor_id, outcome)
        _log().info(
            "oms_anchor_decided",
            anchor_id=str(anchor_id),
            status=outcome.status,
            code=outcome.code,
            recorded=recorded,
        )
        return recorded


class RecordedStopRepository:
    """The recorded stops (SR-E29-06, 21 Sec.3.3.11), through a `RecordedStopStore`."""

    def __init__(self, store: RecordedStopStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def record(
        self, stops: Sequence[NewRecordedStop], *, write_ahead: InsertWriteAhead
    ) -> tuple[RecordedStopRow, ...]:
        """One request's rows, ahead of it, with `write_ahead`, the writer's audit of the request
        (`sl.attached`, and `tp.modified` for a take-profit side, 21 Sec.3.3.11), awaited before
        the commit: the hook is required, as every stop request is audited (C-2.9), as a first
        persist is. Raise, with nothing written: `ValueError` before the store for a caller the
        types do not hold that passes None; `StopRequestInFlight` when a request is in flight for
        the position; `AuditNotDurable` when the audit outlasts its bound."""
        if write_ahead is None:
            raise ValueError("a stop request is audited write-ahead (C-2.9): no hook was given")
        try:
            with self._timer.measure("recorded_stops"):
                rows = await self._store.insert(stops, write_ahead=write_ahead)
        except OrderConstraintError as exc:
            if exc.constraint != UX_RS_IN_FLIGHT:
                raise
            raise StopRequestInFlight("a stop request is in flight for the position") from None
        except WriteAheadTimeout:
            raise AuditNotDurable("the stop request's audit did not land in time") from None
        _log_stops("oms_stops_recorded", rows)
        return rows

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
        write_ahead: SettleWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        """One request's answer, all its rows together; `StaleRecordedStop` when one is no
        longer in flight, with nothing written. `write_ahead`, the writer's audit of the answer
        (a void is `sl.modified` or `tp.modified`, 21 Sec.3.3.11), is awaited before the commit:
        `AuditNotDurable` when it outlasts its bound, with nothing written (C-2.9, SEC-2A-05). A
        void (`refused`, `not_shown`) needs it: with none, `ValueError` before the store
        (SEC-2A-D1-03), as a first persist with no hook is refused."""
        if outcome != "answered" and write_ahead is None:
            raise ValueError("a void is audited write-ahead (C-2.9): no hook was given")
        try:
            with self._timer.measure("recorded_stops"):
                rows = await self._store.settle(
                    account_id, record_ids, outcome, at=at, write_ahead=write_ahead
                )
        except WriteAheadTimeout:
            raise AuditNotDurable("the settle's write-ahead audit did not land in time") from None
        _log_stops("oms_stops_settled", rows, outcome=outcome)
        return rows

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        return await self._store.for_order(account_id, order_id)

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        """The key's `pending` and `in_force` rows, oldest first (`RecordedStopStore.live_for_key`);
        bound and released rows are listed too."""
        return await self._store.live_for_key(account_id, symbol, position_idx)

    async def for_exchange_order(
        self, account_id: UUID, exchange_order_id: str
    ) -> tuple[RecordedStopRow, ...]:
        """The account's rows bound to the exchange order id, in any status, oldest first
        (`RecordedStopStore.for_exchange_order`); a released row holds none."""
        return await self._store.for_exchange_order(account_id, exchange_order_id)

    async def release_and_bind(
        self,
        account_id: UUID,
        predecessor_id: UUID,
        successor_id: UUID,
        exchange_order_id: str,
        *,
        at: datetime,
        write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]:
        """The release of 24 Sec.8.3 rule 7 with its successor's bind (`RecordedStopStore`);
        returns (released, bound). The audit is required (C-2.9): none is `ValueError` before the
        store, a late one `AuditNotDurable`; `RecordedStopNotBindable` passes through. Ids only."""
        if write_ahead is None:
            raise ValueError("a release is audited write-ahead (C-2.9): no hook was given")
        try:
            with self._timer.measure("recorded_stops"):
                rows = await self._store.release_and_bind(
                    account_id, predecessor_id, successor_id, exchange_order_id,
                    at=at, write_ahead=write_ahead,
                )  # fmt: skip
        except WriteAheadTimeout:
            raise AuditNotDurable("the release's write-ahead audit did not land in time") from None
        _log_stops("oms_stop_released", rows[:1])
        _log_stops("oms_stop_bound", rows[1:])
        return rows

    async def waiting_for_key(
        self,
        account_id: UUID,
        symbol: str,
        position_idx: int,
        *,
        now: datetime,
        bound_s: float | None,
    ) -> tuple[RecordedStopRow, ...]:
        """The key's rows waiting for the complete read (`RecordedStopStore.waiting_for_key`):
        the unanswered ones past their request's bound of `bound_s` seconds at `now`, every
        unanswered one when the bound is missing or unusable (fail closed), and an entry's rows
        once its order ended, or is held, with nothing filled. While any is listed, no other stop
        request for the key may leave (21 Sec.3.3.11); a row in flight inside its bound is not
        listed, as the insert meets it (`StopRequestInFlight`)."""
        return await self._store.waiting_for_key(
            account_id, symbol, position_idx, now=now, bound_s=bound_s
        )

    async def void_orphans(
        self, scope: UUID | SweepScope, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        """R10's startup sweep (21 Sec.3.3.11): the pending stop rows of an entry never placed
        become `void`: one never sent (`UNSENT_ENTRY`: still `pending_submit`, or killed before its
        send, its create `unsent`, no attempt counted, nothing filled), or one its create's own
        answer refused (`REFUSED_ENTRY`: `rejected` out of `submitting`, nothing filled). Each is
        audited write-ahead by `write_ahead` (`sl.modified`, or `tp.modified`, reason
        `SWEEP_REASON`, ids only). It never voids a row blind (C-2.6): an order's killed after its
        send, one's that ended out of `unknown` and one's whose end the exchange did not confirm
        unfilled stay `pending`, waiting for the complete read. Slice 3's startup wiring
        (`oms_wiring.py`) calls it once per account of the process's own environment, never with
        `EVERY_ACCOUNT` (C-2.11: another environment's process may be sending its entry, whose stops
        must stay `pending`, C-2.6), before the order machines hydrate and before order entry
        opens: a never-sent order is an orphan only while no request can still send it.
        `AuditNotDurable` when the audit outlasts its bound, with nothing voided.
        Logged as one WARNING line with the count per account, and a line per row at INFO
        (SEC-2A-07)."""
        try:
            with self._timer.measure("recorded_stops"):
                swept = await self._store.void_orphans(scope, at=at, write_ahead=write_ahead)
        except WriteAheadTimeout:
            raise AuditNotDurable("the sweep's write-ahead audit did not land in time") from None
        if swept:
            per_account = Counter(str(stop.exchange_account_id) for stop in swept)
            _log().warning(
                "oms_stops_unplaced_entries_swept",
                reason=SWEEP_REASON,
                swept=len(swept),
                per_account=dict(sorted(per_account.items())),
            )
        for stop in swept:
            _log().info(
                "oms_stop_unplaced_entry_swept",
                record_id=str(stop.id),
                account_id=str(stop.exchange_account_id),
                order_id=str(stop.order_id),
                kind=stop.kind,
            )
        return swept

    async def waiting_keys(
        self, account_id: UUID, *, now: datetime, bound_s: float | None
    ) -> tuple[tuple[str, int], ...]:
        """`RecordedStopStore.waiting_keys`: the startup pass's input, per account (C-2.11). A
        read, untimed as `for_order` and `waiting_for_key` are: the timer is the writes'
        (`oms_db_write_seconds`, its `table` label bounded by the tables written)."""
        return await self._store.waiting_keys(account_id, now=now, bound_s=bound_s)

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        """The key's rows in force, by kind (`RecordedStopStore.in_force_for_key`); a read, untimed
        as `waiting_keys`."""
        return await self._store.in_force_for_key(account_id, symbol, position_idx)

    async def database_now(self) -> datetime:
        """The database's clock (`RecordedStopStore.database_now`): the startup floor's start."""
        return await self._store.database_now()

    async def put_in_force(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        *,
        at: datetime,
        write_ahead: InForceWriteAhead | None = None,
    ) -> InForce:
        """`RecordedStopStore.put_in_force`; `AuditNotDurable` for a hook past its bound."""
        try:
            with self._timer.measure("recorded_stops"):
                done = await self._store.put_in_force(
                    account_id, rows, at=at, write_ahead=write_ahead
                )
        except WriteAheadTimeout:
            raise AuditNotDurable("the stops' write-ahead audit did not land in time") from None
        _log_stops("oms_stops_replaced", done.replaced)
        _log_stops("oms_stops_in_force", done.in_force)
        return done

    async def resolve(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        outcome: ResolveOutcome,
        *,
        at: datetime,
        position_state: FillPosition | None = None,
        write_ahead: ResolveWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        """`RecordedStopStore.resolve`, its call refused before the store (`check_resolve`: C-2.9,
        CR-S3H0-08); the hook is given the rows and `position_state`. `replaced` trusts the
        caller, as the store does. `AuditNotDurable` for a hook past its bound: nothing voided or
        answered."""
        check_resolve(rows, outcome, at, position_state, write_ahead)
        try:
            with self._timer.measure("recorded_stops"):
                done = await self._store.resolve(
                    account_id, rows, outcome, at=at, position_state=position_state,
                    write_ahead=write_ahead,
                )  # fmt: skip
        except WriteAheadTimeout:
            raise AuditNotDurable("the resolve's write-ahead audit did not land in time") from None
        _log_stops("oms_stops_resolved", done, outcome=outcome)
        return done


def _log_stops(name: str, rows: Sequence[RecordedStopRow], **extra: str) -> None:
    """Ids, kinds and statuses only: a recorded stop's prices and sizes are P1 (21 Sec.12)."""
    for row in rows:
        _log().info(
            name,
            record_id=str(row.id),
            account_id=str(row.exchange_account_id),
            order_id=None if row.order_id is None else str(row.order_id),
            kind=row.kind,
            source=row.source,
            status=row.status,
            **extra,
        )
