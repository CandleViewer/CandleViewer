"""M14 `OrderRepository` / `OrderEventRepository` over a stub store (E29-T01 #845).

The facade's own behaviour: `DuplicateOrderLinkId` for the unique index (Gherkin "Idempotency is
enforced by the database", unit half), the 24 Sec.8.3 rule 5 lookup the #846 allocator uses, the
account passed through on every read, and the `order_link_id` logged on every write (ADR-0006
rule 1). The stores themselves are tested in `tests/unit/storage/test_orders_store.py` and against
Postgres in `tests/integration/storage/test_orders_store_pg.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms import DuplicateOrderLinkId, OrderEventRepository, OrderRepository
from candleviewer.oms.errors import OmsError
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator, OrderLinkLookup
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderRow,
)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER = uuid.UUID(int=1), uuid.UUID(int=2)
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id


def _row(**over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    values |= {"id": ORDER, "exchange_account_id": ACCOUNT, "order_link_id": LINK}
    return OrderRow(**(values | {"state": "pending_submit", "qty": Decimal("0.010")} | over))


def _event_row(**over: Any) -> OrderEventRow:
    values: dict[str, Any] = {name: None for name in EVENT_FIELDS}
    values |= {"id": 9, "order_id": ORDER, "seq": 1, "kind": "ack", "order_link_id": LINK}
    return OrderEventRow(**(values | over))


ORDER_IN = NewOrder(
    id=ORDER, exchange_account_id=ACCOUNT, order_link_id=LINK, symbol="BTCUSDT", side="Buy",
    intent="entry", order_type="Market", qty=Decimal("0.010"), stop_loss=Decimal("62000"),
)  # fmt: skip
EVENT_IN = NewOrderEvent(kind="local_create", source="local", event_ts=T0)


class _Store:
    """Stub `OrderStore` and `OrderEventStore`: records calls, returns canned rows."""

    def __init__(self, *, error: Exception | None = None, taken: frozenset[str] = frozenset()):
        self.error, self.taken = error, taken
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if self.error is not None:
            raise self.error

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        self._call("create", order, first_event)
        return _row(stop_loss=order.stop_loss)

    async def get(self, account_id: uuid.UUID, order_id: uuid.UUID) -> OrderRow | None:
        self._call("get", account_id, order_id)
        return _row()

    async def get_by_link_id(self, account_id: uuid.UUID, order_link_id: str) -> OrderRow | None:
        self._call("get_by_link_id", account_id, order_link_id)
        return None

    async def list_open(
        self, account_id: uuid.UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        self._call("list_open", account_id, symbol=symbol)
        return (_row(),)

    async def link_id_taken(self, order_link_id: str) -> bool:
        self._call("link_id_taken", order_link_id)
        return order_link_id in self.taken

    async def append(
        self, account_id: uuid.UUID, order_id: uuid.UUID, event: NewOrderEvent
    ) -> OrderEventRow:
        self._call("append", account_id, order_id, event)
        return _event_row(kind=event.kind, seq=3)

    async def list_for_order(
        self, account_id: uuid.UUID, order_id: uuid.UUID, *, after_seq: int = -1, limit: int = 500
    ) -> tuple[OrderEventRow, ...]:
        self._call("list_for_order", account_id, order_id, after_seq=after_seq, limit=limit)
        return (_event_row(),)


async def test_create_returns_the_stored_row_and_logs_its_order_link_id() -> None:
    store = _Store()
    with capture_logs() as logs:
        row = await OrderRepository(store).create(ORDER_IN, EVENT_IN)
    assert row.stop_loss == Decimal("62000")  # the native stop travels with the row (C-2.6)
    assert store.calls == [("create", (ORDER_IN, EVENT_IN), {})]
    assert logs == [
        {
            "event": "oms_order_created",
            "log_level": "info",
            "order_link_id": LINK,
            "order_id": str(ORDER),
            "account_id": str(ACCOUNT),
            "state": "pending_submit",
        }
    ]


async def test_idempotency_is_enforced_by_the_database_as_duplicate_order_link_id() -> None:
    """Gherkin "Idempotency is enforced by the database": the unique index's refusal surfaces as
    `DuplicateOrderLinkId`, an `OmsError`, and nothing is logged as written."""
    store = _Store(error=OrderConstraintError("ux_orders_link"))
    with capture_logs() as logs, pytest.raises(DuplicateOrderLinkId) as err:
        await OrderRepository(store).create(ORDER_IN, EVENT_IN)
    assert isinstance(err.value, OmsError) and err.value.order_link_id == LINK
    assert str(err.value) == f"order_link_id {LINK} is already stored"
    assert (err.value.__cause__, err.value.__suppress_context__, logs) == (None, True, [])


@pytest.mark.parametrize("constraint", ["ux_orders_exch_id", "orders_pkey", "ord_cum"])
async def test_any_other_constraint_error_passes_through_unchanged(constraint: str) -> None:
    error = OrderConstraintError(constraint)
    with pytest.raises(OrderConstraintError) as err:
        await OrderRepository(_Store(error=error)).create(ORDER_IN, EVENT_IN)
    assert err.value is error


async def test_reads_pass_the_account_through() -> None:
    store = _Store()
    repo = OrderRepository(store)
    assert (await repo.get(ACCOUNT, ORDER)) == _row()
    assert await repo.get_by_link_id(ACCOUNT, LINK) is None
    assert await repo.list_open(ACCOUNT, symbol="ETHUSDT") == (_row(),)
    assert store.calls == [
        ("get", (ACCOUNT, ORDER), {}),
        ("get_by_link_id", (ACCOUNT, LINK), {}),
        ("list_open", (ACCOUNT,), {"symbol": "ETHUSDT"}),
    ]


async def test_exists_is_the_rule_5_lookup_the_allocator_uses() -> None:
    def link(seq: int) -> OrderLinkIdParts:
        return OrderLinkIdParts.generate(
            mode="exchange", environment="demo", group_id=GroupId(uuid.UUID(int=7)),
            account_id=AccountId(ACCOUNT), seq=seq, purpose="entry",
        )  # fmt: skip

    store = _Store(taken=frozenset({link(0).value}))
    lookup: OrderLinkLookup = OrderRepository(store)  # mypy checks the structural match
    allocated = await OrderLinkIdAllocator(lookup).allocate(link(0))
    assert allocated.order_link_id == link(1).value
    assert [c[1] for c in store.calls] == [(link(0).value,), (link(1).value,)]


async def test_append_returns_the_event_and_logs_order_link_id_seq_and_kind() -> None:
    store = _Store()
    event = NewOrderEvent(kind="ack", source="rest", event_ts=T0, payload={"retCode": 0})
    with capture_logs() as logs:
        got = await OrderEventRepository(store).append(ACCOUNT, ORDER, event)
    assert (got.seq, got.kind, store.calls) == (3, "ack", [("append", (ACCOUNT, ORDER, event), {})])
    assert logs == [
        {
            "event": "oms_order_event_appended",
            "log_level": "info",
            "order_link_id": LINK,
            "order_id": str(ORDER),
            "seq": 3,
            "kind": "ack",
        }
    ]


async def test_list_for_order_passes_the_account_and_the_page_through() -> None:
    store = _Store()
    got = await OrderEventRepository(store).list_for_order(ACCOUNT, ORDER, after_seq=4, limit=20)
    assert got == (_event_row(),)
    assert store.calls == [("list_for_order", (ACCOUNT, ORDER), {"after_seq": 4, "limit": 20})]


async def test_a_failed_append_logs_nothing() -> None:
    with capture_logs() as logs, pytest.raises(OrderConstraintError):
        await OrderEventRepository(_Store(error=OrderConstraintError("oe_latency"))).append(
            ACCOUNT, ORDER, EVENT_IN
        )
    assert logs == []
