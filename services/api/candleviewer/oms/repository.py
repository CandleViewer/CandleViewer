"""The OMS's order persistence (E29-T01 #845): `OrderRepository`, `OrderEventRepository`.

M14 may not import a storage driver (ADR-0003), so the SQL lives in M10
(`storage.repositories.orders_sqlalchemy`) behind the driver-free `OrderStore` and
`OrderEventStore`, and the composition root hands these classes a store. They add the OMS's side:
`DuplicateOrderLinkId` for a second row under one id (#845 Gherkin), the 24 Sec.8.3 rule 5 lookup
the #846 allocator takes (`OrderLinkLookup`), and a log line with the `order_link_id` for every
write (ADR-0006 rule 1). Every read takes the exchange account (C-12.4) but `exists`, a yes/no
the allocator alone needs. The store redacts what the exchange said (`payload`, `ret_code`,
`ret_msg`) before binding it (21 Sec.3.3.5; the #845 security notes).
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

import structlog

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

from .errors import DuplicateOrderLinkId

__all__ = ["OrderEventRepository", "OrderRepository"]


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class OrderRepository:
    """`orders`, through an `OrderStore`."""

    def __init__(self, store: OrderStore) -> None:
        self._store = store

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        """The submit hot path: the row and its first event in one transaction (#845); a second
        row under the id raises `DuplicateOrderLinkId`."""
        try:
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

    def __init__(self, store: OrderEventStore) -> None:
        self._store = store

    async def append(self, account_id: UUID, order_id: UUID, event: NewOrderEvent) -> OrderEventRow:
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
