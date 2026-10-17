"""The OMS's persistence (E29-T01 #845): its five repositories over the `0029_oms_core` tables.

M14 may not import a storage driver (ADR-0003), so the SQL lives in M10
(`storage.repositories.*_sqlalchemy`) behind driver-free store protocols, and the composition root
hands these classes a store. They add the OMS's side:
`DuplicateOrderLinkId` for a second row under one id (#845 Gherkin), the 24 Sec.8.3 rule 5 lookup
the #846 allocator takes (`OrderLinkLookup`), and a log line with the `order_link_id` for every
order, event and fill write (ADR-0006 rule 1). Every read takes the exchange account (C-12.4) but
`exists`, a yes/no the allocator alone needs. The store redacts what the exchange said (`payload`,
`ret_code`, `ret_msg`) before binding it (21 Sec.3.3.5; the #845 security notes). A `WriteTimer`
times every write on `oms_db_write_seconds{table}`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Final, Literal, cast, get_args
from uuid import UUID

import structlog

from candleviewer.observability.metrics import BoundedMetric
from candleviewer.storage.repositories.executions import ExecutionRow, ExecutionStore, NewExecution
from candleviewer.storage.repositories.orders import (
    MAX_EVENT_PAGE,
    UX_ORDERS_LINK,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderEventStore,
    OrderRow,
    OrderStore,
)
from candleviewer.storage.repositories.positions import (
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionSnapshotStore,
    PositionState,
    PositionStore,
)

from .errors import DuplicateOrderLinkId

__all__ = [
    "WRITE_TABLES", "ExecutionRepository", "OrderEventRepository", "OrderRepository",
    "PositionRepository", "PositionSnapshotRepository", "WriteTimer",
]  # fmt: skip

WriteTable = Literal["orders", "order_events", "executions", "positions", "position_snapshots"]
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
        `order_id` is not an order of that account."""
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

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        return await self._store.get(account_id, exec_id)


class PositionRepository:
    """`positions`, through a `PositionStore`. A position write names no order and comes with every
    position push, so it is timed but not logged."""

    def __init__(self, store: PositionStore, timer: WriteTimer = _UNTIMED) -> None:
        self._store = store
        self._timer = timer

    async def upsert(self, state: PositionState) -> PositionRow:
        """`PositionStore.upsert`: a stale write returns the stored row, and a time more than
        `MAX_FUTURE_SKEW` ahead of the store's clock raises `FutureDatedPositionError`."""
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
