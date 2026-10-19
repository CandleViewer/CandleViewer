"""The write-ahead contract on `InMemoryOrderStore`, the ports' own checks and the fake's other
calls (E29-T03 #847, slice 3 of 7)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.exchange_payload import REDACTED
from tests.unit.oms.write_ahead_contract import T0, Harness, WriteAheadContract, event, fill, step


def _harness(store: InMemoryOrderStore) -> Harness:
    repos = OrderRepository(store), OrderEventRepository(store)
    return Harness(*repos, ExecutionRepository(store.executions), uuid4)


class TestInMemoryStore(WriteAheadContract):
    @pytest.fixture
    def h(self) -> Harness:
        return _harness(InMemoryOrderStore(clock=lambda: T0))


async def test_the_ports_refuse_a_step_or_fill_that_cannot_be_written() -> None:
    """OM-R02: a step the exchange reported carries its message; a fill names its step's order;
    totals are `Decimal` values the columns hold exactly."""
    row = await _harness(InMemoryOrderStore()).order()
    with pytest.raises(ValueError, match="OM-R02"):
        step(row, "accepted", event(source="reconcile", payload={}))
    step(row, "accepted", event(source="paper", payload={}))  # not the exchange: nothing to carry
    echo = f"error sign! origin_string[1760630400000{'R4x8' * 6}5000]"  # #845 decision 2
    reject = step(row, "rejected", reject_code="10004", reject_message=echo).changes()
    assert (reject["reject_code"], reject["reject_message"]) == ("10004", REDACTED)
    good = fill(row, "E1", "0.1")
    with pytest.raises(ValueError, match="another account or order"):
        replace(good, execution=replace(good.execution, order_id=uuid4()))
    with pytest.raises(TypeError, match=r"^fee_paid "):
        replace(good.totals, fee_paid=cast(Any, 0.5))


async def test_a_store_outage_at_commit_leaves_nothing() -> None:
    """`fail_next`, the S7 hook for slices 5 and 6: the write raises at its commit and the fill,
    its totals, state and event are all left unwritten."""
    store = InMemoryOrderStore(clock=lambda: T0)
    h = _harness(store)
    row = await h.order()
    store.fail_next(StorageTierUnavailable("postgres unreachable (OSError)"))
    with pytest.raises(StorageTierUnavailable):
        await h.executions.apply_fill(fill(row, "E1", "0.1"))
    assert await h.stored(row) == (row, [0])
    assert await h.executions.apply_fill(fill(row, "E1", "0.1")) is not None  # once only


async def test_the_fakes_other_calls_keep_the_stores_rules() -> None:
    store = InMemoryOrderStore(clock=lambda: T0)
    h = _harness(store)
    row, other = await h.order("pending_amend"), await h.order("filled")
    mine, theirs = row.exchange_account_id, other.exchange_account_id
    assert await h.orders.get_by_link_id(mine, row.order_link_id) == row
    assert [await h.orders.list_open(a) for a in (mine, theirs)] == [(row,), ()]
    twin = {name: getattr(row, name) for name in port.NewOrder.__dataclass_fields__}
    with pytest.raises(port.OrderConstraintError, match="ux_orders_link"):
        await store.create(port.NewOrder(**twin | {"id": uuid4()}), event())
    assert (await h.events.append(mine, row.id, event())).seq == 1
    assert await h.events.list_for_order(theirs, row.id) == ()
    with pytest.raises(ValueError, match="after_seq"):
        await h.events.list_for_order(mine, row.id, limit=0)
    stray = replace(fill(row, "E9", "0.1").execution, order_id=None)  # no order: none to own
    assert [await h.executions.insert(stray) for _ in "ab"] == [True, False]
    assert await h.executions.insert(fill(row, "E8", "0.1").execution)


async def test_each_step_logs_its_correlation_key() -> None:
    """ADR-0006 rule 1: every write logs its `order_link_id`; a duplicate fill at debug."""
    h = _harness(InMemoryOrderStore(clock=lambda: T0))
    row = await h.order()
    with capture_logs() as logs:
        moved = await h.orders.transition(step(row, "pending_cancel"))
        for _ in "ab":
            await h.executions.apply_fill(fill(moved.order, "E1", "0.1"))
    seen = [(e["event"], e["order_id"], e.get("order_link_id"), e.get("seq")) for e in logs]
    link, order = row.order_link_id, str(row.id)
    assert seen == [
        ("oms_order_transitioned", order, link, 1), ("oms_order_filled", order, link, 2),
        ("oms_execution_duplicate", order, None, None),
    ]  # fmt: skip
