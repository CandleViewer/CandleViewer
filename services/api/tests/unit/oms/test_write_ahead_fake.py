"""The write-ahead contract on `InMemoryOrderStore`, and the fake's other calls (E29-T03 #847)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint

from candleviewer.db import models
from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository, fakes
from candleviewer.oms.fakes import InMemoryOrderStore as Fake
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import orders as port
from tests.unit.oms.write_ahead_contract import (
    QTY,
    T0,
    Harness,
    WriteAheadContract,
    created,
    event,
    fill,
    step,
)


def _lost() -> StorageTierUnavailable:
    return StorageTierUnavailable("postgres unreachable (OSError)")


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
        store.fail_next(_lost())
        with pytest.raises(StorageTierUnavailable):
            await h.executions.commit_fill(fill(row, "E1", "0.1"))
        assert await h.stored(row) == (row, [0])
        assert await h.executions.commit_fill(fill(row, "E1", "0.1")) is not None  # once only

    async def test_a_fault_after_the_commit_leaves_the_write_stored(
        self, store: Fake, h: Harness
    ) -> None:
        """`fail_next(..., committed=True)`: the write landed but its answer was lost, as when a
        lost connection cuts a commit off (`orders.py`). A retry meets the stored row, as on
        Postgres: a create meets its key, a step the state it moved the order to."""
        new = h.new_order("pending_submit")
        store.fail_next(_lost(), committed=True)
        with pytest.raises(StorageTierUnavailable):
            await h.orders.create(new, created())
        with pytest.raises(port.OrderConstraintError, match="orders_pkey"):
            await h.orders.create(new, created())
        row = await h.orders.get(new.exchange_account_id, new.id)
        assert row is not None
        store.fail_next(_lost(), committed=True)
        with pytest.raises(StorageTierUnavailable):
            await h.orders.transition(step(row, "submitted"))
        with pytest.raises(port.StaleOrderState):
            await h.orders.transition(step(row, "submitted"))
        assert (await h.stored(row))[1] == [0, 1]

    async def test_reads_stay_inside_their_account(self, h: Harness) -> None:
        row, other = await h.order("pending_amend"), await h.order("filled")
        mine, theirs = row.exchange_account_id, other.exchange_account_id
        assert await h.executions.insert(fill(row, "E1", "0.1").execution)
        assert await h.orders.get_by_link_id(mine, row.order_link_id) == row
        assert await h.orders.get_by_link_id(theirs, row.order_link_id) is None
        assert await h.orders.get(theirs, row.id) is None
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
        fresh = {"id": uuid4(), "order_link_id": f"ext-{uuid4().hex}"}  # `ord_link_fmt`'s shape
        adopted = port.NewOrder(**twin | filled | fresh)
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
        row, page = await h.order(), port.MAX_EVENT_PAGE + 1
        with pytest.raises(ValueError, match="after_seq"):
            await h.events.list_for_order(row.exchange_account_id, row.id, limit=page)

    async def test_an_empty_page_is_refused(self, h: Harness) -> None:
        row = await h.order()
        with pytest.raises(ValueError, match="after_seq"):
            await h.events.list_for_order(row.exchange_account_id, row.id, limit=0)

    async def test_a_page_before_the_first_event_is_refused(self, h: Harness) -> None:
        row = await h.order()
        with pytest.raises(ValueError, match="after_seq"):
            await h.events.list_for_order(row.exchange_account_id, row.id, after_seq=-2)

    async def test_another_task_runs_while_a_call_waits_on_the_store(self, h: Harness) -> None:
        """lows-847s3b (security r2 Low 1): each call yields once, as a driver call suspends, so
        the OMS's per-order lock and its tasks meet the interleaving Postgres gives them."""
        row, ran = await h.order(), []

        async def sibling() -> None:
            ran.append("sibling")

        task = asyncio.ensure_future(sibling())
        await h.orders.transition(step(row, "submitted"))
        assert ran == ["sibling"] and task.done()

    async def test_a_timeout_can_fire_inside_a_call_with_nothing_written(self, h: Harness) -> None:
        """The yield comes before any check, never between a check and its commit: a timeout
        around a store call (`persist_event`'s, S7) fires there, and the write is not made."""
        row = await h.order()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0):
                await h.orders.transition(step(row, "submitted"))
        assert await h.stored(row) == (row, [0])

    async def test_a_link_id_is_taken_in_any_account_and_state(self, h: Harness) -> None:
        """24 Sec.8.3 rule 5's yes/no over `ux_orders_link` (`OrderRepository.exists`)."""
        row = await h.order("cancelled")
        assert await h.orders.exists(row.order_link_id)
        assert not await h.orders.exists(f"ext-{uuid4().hex}")

    async def test_an_insert_stores_a_fill_once(self, h: Harness) -> None:
        row = await h.order()
        stray = replace(fill(row, "E9", "0.1").execution, order_id=None)  # no order: none to own
        fills = (stray, stray, fill(row, "E8", "0.1").execution)
        assert [await h.executions.insert(f) for f in fills] == [True, False, True]


#: The CHECKs the fake leaves to the types, by the name Postgres reports: a value outside its
#: column's `Literal`, or a column only the store writes (`oe_seq`).
_LEFT_TO_TYPES: Final = {
    "orders": {
        "ord_attempts", "ord_idem", "ord_posidx", "ord_side", "ord_tif", "ord_tpslmode",
        "ord_trigby", "ord_trigdir", "ord_type",
    },
    "executions": {"ex_posidx", "ex_side", "ex_type"},
    "order_events": {"oe_seq", "oe_source"},
}  # fmt: skip


def _checks(table: str) -> set[str]:
    constraints = models.metadata.tables[table].constraints
    head = f"ck_{table}_"
    return {str(c.name).removeprefix(head) for c in constraints if isinstance(c, CheckConstraint)}


def test_the_fake_meets_every_check_the_schema_declares() -> None:
    """lows-847s3b (code r2): a migration that adds a CHECK (as the order vocabulary's revision
    added `ord_lifecycle`) fails here until the fake models it or leaves it to the types."""
    assert _checks("orders") == set(fakes._ORDER_CHECKS) | _LEFT_TO_TYPES["orders"]
    assert _checks("executions") == set(fakes._EXECUTION_CHECKS) | _LEFT_TO_TYPES["executions"]
    assert _checks("order_events") == {"oe_latency"} | _LEFT_TO_TYPES["order_events"]
