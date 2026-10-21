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

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter
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
    UX_RS_IN_FLIGHT,
    NewRecordedStop,
    RecordedStopRow,
    RecordedStopStore,
    StopOutcome,
    SweepWriteAhead,
    SweptStop,
)
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
    SubmissionStore,
)
from candleviewer.storage.repositories.trade_groups import TradeGroupStoreRefusedError

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
        """Raise, with nothing written: `DuplicateOrderLinkId` for a second row under the id,
        `AnchorTaken` when the request's key is held, `StopRequestInFlight` when a stop request
        is in flight for the position, `SubmissionRefused` when the account or the leg's profile
        is not live, `AuditNotDurable` when the write-ahead audit outlasts its bound; any other
        store refusal as it is."""
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
            raise SubmissionRefused(exc.reason) from None
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

    async def record(self, stops: Sequence[NewRecordedStop]) -> tuple[RecordedStopRow, ...]:
        """One request's rows, ahead of it: `StopRequestInFlight` when a request is in flight
        for the position, with nothing written."""
        try:
            with self._timer.measure("recorded_stops"):
                rows = await self._store.insert(stops)
        except OrderConstraintError as exc:
            if exc.constraint != UX_RS_IN_FLIGHT:
                raise
            raise StopRequestInFlight("a stop request is in flight for the position") from None
        _log_stops("oms_stops_recorded", rows)
        return rows

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
    ) -> tuple[RecordedStopRow, ...]:
        """One request's answer, all its rows together; `StaleRecordedStop` when one is no
        longer in flight, with nothing written."""
        with self._timer.measure("recorded_stops"):
            rows = await self._store.settle(account_id, record_ids, outcome, at=at)
        _log_stops("oms_stops_settled", rows, outcome=outcome)
        return rows

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        return await self._store.for_order(account_id, order_id)

    async def void_orphans(
        self, account_id: UUID | None, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        """R10's startup sweep (21 Sec.3.3.11): the pending stop rows of an entry never placed
        become `void`: one never sent (`UNSENT_ENTRY`: still `pending_submit`, its create
        `unsent`, no attempt counted, nothing filled), or one its create's own answer refused
        (`REFUSED_ENTRY`: `rejected` out of `submitting`, nothing filled). Each is audited
        write-ahead by `write_ahead` (`sl.modified`, or `tp.modified`, reason
        `unplaced_entry_swept`, ids only). It never voids a row blind (C-2.6): a killed order's,
        one's that ended out of `unknown` and one's whose end the exchange did not confirm
        unfilled stay `pending`, waiting for the complete read. Slice 3's startup wiring
        (`oms_wiring.py`) calls it once per process, with `account_id` None, before the order
        machines hydrate and before order entry opens: a never-sent order is an orphan only while
        no request can still send it. `AuditNotDurable` when the audit outlasts its bound, with
        nothing voided."""
        try:
            with self._timer.measure("recorded_stops"):
                swept = await self._store.void_orphans(account_id, at=at, write_ahead=write_ahead)
        except WriteAheadTimeout:
            raise AuditNotDurable("the sweep's write-ahead audit did not land in time") from None
        for stop in swept:
            _log().warning(
                "oms_stop_unplaced_entry_swept",
                record_id=str(stop.id),
                account_id=str(stop.exchange_account_id),
                order_id=str(stop.order_id),
                kind=stop.kind,
            )
        return swept


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
