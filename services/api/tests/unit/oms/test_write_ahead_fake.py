"""The write-ahead contract on `InMemoryOrderStore`, and the fake's other calls (E29-T03 #847)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository
from candleviewer.oms.fakes import InMemoryOrderStore as Fake
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import orders as port
from tests.unit.oms.write_ahead_contract import QTY, T0, Harness, WriteAheadContract, event, fill


class TestInMemoryStore(WriteAheadContract):
    @pytest.fixture
    def store(self) -> Fake:
        return Fake(clock=lambda: T0)

    @pytest.fixture
    def h(self, store: Fake) -> Harness:
        repos = OrderRepository(store), OrderEventRepository(store)
        return Harness(*repos, ExecutionRepository(store.executions), uuid4)

    async def test_an_outage_at_commit_writes_nothing(self, store: Fake, h: Harness) -> None:
        """`fail_next`, the S7 hook for the unit suites of `persist_event` and the OMS facade: the
        write raises at its commit and the fill, its totals, state and event are all unwritten."""
        row = await h.order()
        store.fail_next(StorageTierUnavailable("postgres unreachable (OSError)"))
        with pytest.raises(StorageTierUnavailable):
            await h.executions.commit_fill(fill(row, "E1", "0.1"))
        assert await h.stored(row) == (row, [0])
        assert await h.executions.commit_fill(fill(row, "E1", "0.1")) is not None  # once only

    async def test_reads_stay_inside_their_account(self, h: Harness) -> None:
        row, other = await h.order("pending_amend"), await h.order("filled")
        mine, theirs = row.exchange_account_id, other.exchange_account_id
        assert await h.executions.insert(fill(row, "E1", "0.1").execution)
        assert await h.orders.get_by_link_id(mine, row.order_link_id) == row
        assert [await h.orders.list_open(a) for a in (mine, theirs)] == [(row,), ()]
        assert await h.orders.list_open(mine, symbol="ETHUSDT") == ()
        assert await h.events.list_for_order(theirs, row.id) == ()
        assert [await h.executions.get(a, "E1") is None for a in (mine, theirs)] == [False, True]

    async def test_an_insert_naming_another_accounts_order_is_refused(self, h: Harness) -> None:
        """As on Postgres: the execution's account must hold its order, and nothing is stored."""
        row = await h.order()
        elsewhere = replace(fill(row, "E1", "0.1").execution, exchange_account_id=uuid4())
        with pytest.raises(port.OrderNotFoundError):
            await h.executions.insert(elsewhere)
        assert await h.executions.get(elsewhere.exchange_account_id, "E1") is None

    async def test_an_adopted_order_leaves_what_it_has_not_filled(self, h: Harness) -> None:
        """Reconciliation inserts an adopted order as it stands (21 Sec.3.3.4), and `leaves_qty`
        is computed as the generated column is."""
        row = await h.order()
        twin = {name: getattr(row, name) for name in port.NewOrder.__dataclass_fields__}
        filled = {"cum_exec_qty": Decimal("0.1"), "state": "partially_filled"}
        adopted = port.NewOrder(**twin | filled | {"id": uuid4(), "order_link_id": "ext-adopted"})
        said = event("reconcile_diff", source="reconcile")
        assert (await h.orders.create(adopted, said)).leaves_qty == QTY - Decimal("0.1")

    async def test_a_second_order_under_a_link_id_is_refused(self, store: Fake, h: Harness) -> None:
        row = await h.order()
        twin = {name: getattr(row, name) for name in port.NewOrder.__dataclass_fields__}
        with pytest.raises(port.OrderConstraintError, match="ux_orders_link"):
            await store.create(port.NewOrder(**twin | {"id": uuid4()}), event())

    async def test_an_append_takes_the_next_seq(self, h: Harness) -> None:
        row = await h.order()
        account = row.exchange_account_id
        assert (await h.events.append(account, row.id, event())).seq == 1
        assert [e.seq for e in await h.events.list_for_order(account, row.id, limit=1)] == [0]
        assert [e.seq for e in await h.events.list_for_order(account, row.id, after_seq=0)] == [1]

    async def test_an_unbounded_page_is_refused(self, h: Harness) -> None:
        row = await h.order()
        with pytest.raises(ValueError, match="after_seq"):
            await h.events.list_for_order(row.exchange_account_id, row.id, limit=0)

    async def test_an_insert_stores_a_fill_once(self, h: Harness) -> None:
        row = await h.order()
        stray = replace(fill(row, "E9", "0.1").execution, order_id=None)  # no order: none to own
        fills = (stray, stray, fill(row, "E8", "0.1").execution)
        assert [await h.executions.insert(f) for f in fills] == [True, False, True]
