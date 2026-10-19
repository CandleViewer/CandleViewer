"""Behavioural contract of the write-ahead step (E29-T03 #847, slice 3 of 7): 24 Sec.8.2 S8 (a
state commits with its event), S7 (a refused or failed write changes nothing) and S4's durable
half (a repeated `exec_id` never counts twice). `test_write_ahead_fake.py` runs it on the fake,
`tests/integration/storage/test_orders_store_pg.py` on Postgres; subclasses supply `h`."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.exchange_payload import REDACTED
from candleviewer.storage.repositories.executions import FillTotals, NewExecution, OrderFill

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
QTY, PX, FEE = Decimal("0.3"), Decimal("63000"), Decimal("0.5")
SHAPE = "Q3w9" * 6  # letters and digits, credential-shaped, built at run time (SR-145)
Row = port.OrderRow
Event = port.NewOrderEvent
Transition = port.OrderTransition


def event(kind: port.OrderEventKind = "ack", **over: Any) -> Event:
    base = {"kind": kind, "source": "ws_private", "event_ts": T0, "payload": {"orderStatus": "New"}}
    return port.NewOrderEvent(**(base | over))


def step(row: Row, to: port.OrderState, new: Event | None = None, **over: Any) -> Transition:
    base = {"account_id": row.exchange_account_id, "order_id": row.id, "from_state": row.state}
    return port.OrderTransition(**(base | {"to_state": to, "event": new or event()} | over))


def fill(row: Row, exec_id: str, qty: str, new: Event | None = None) -> OrderFill:
    """The fill as slice 4's `apply_execution` would compute it from `row`."""
    size = Decimal(qty)
    execution = NewExecution(
        exchange_account_id=row.exchange_account_id, order_id=row.id, exec_id=exec_id,
        symbol="BTCUSDT", side="Buy", exec_qty=size, exec_price=PX, exec_value=size * PX,
        exec_type="Trade", is_maker=False, exec_ts=T0, exec_fee=FEE,
    )  # fmt: skip
    cum, value = row.cum_exec_qty + size, row.cum_exec_value + size * PX
    fee = row.fee_paid + FEE
    totals = FillTotals(cum_exec_qty=cum, cum_exec_value=value, avg_price=PX, fee_paid=fee)
    kind: port.OrderEventKind = "fill" if cum == row.qty else "partial_fill"
    to: port.OrderState = "filled" if cum == row.qty else "partially_filled"
    new = new or event(kind, payload={"execId": exec_id})
    return OrderFill(step=step(row, to, new), execution=execution, totals=totals)


@dataclass(frozen=True)
class Harness:
    orders: OrderRepository
    events: OrderEventRepository
    executions: ExecutionRepository
    new_account: Callable[[], UUID]

    async def order(self, state: port.OrderState = "accepted") -> Row:
        new = port.NewOrder(
            id=uuid4(), exchange_account_id=self.new_account(), order_link_id=f"ext-{uuid4().hex}",
            symbol="BTCUSDT", side="Buy", intent="entry", order_type="Limit", qty=QTY, price=PX,
            stop_loss=Decimal("62000"), state=state,
        )  # fmt: skip
        return await self.orders.create(new, event("local_create", source="local"))

    async def stored(self, row: Row) -> tuple[Row | None, list[int]]:
        """The order as stored now, and its events' `seq`s."""
        events = await self.events.list_for_order(row.exchange_account_id, row.id)
        return await self.orders.get(row.exchange_account_id, row.id), [e.seq for e in events]


_REFUSED_EVENT = {  # a write whose event insert `oe_latency` refuses, after its compare-and-set
    "step": lambda h, row, bad: h.orders.transition(step(row, "submitted", bad)),
    "fill": lambda h, row, bad: h.executions.apply_fill(fill(row, "E1", "0.1", bad)),
}


class WriteAheadContract:
    async def test_a_step_commits_its_state_with_its_event(self, h: Harness) -> None:
        """S8: the state and its event (both states, the source, the exchange's message redacted,
        OM-R02) commit together, before the step returns."""
        row = await h.order("pending_submit")
        said = {"retCode": 0, "headers": {"X-BAPI-SIGN": SHAPE}}
        done = await h.orders.transition(step(row, "accepted", event(source="rest", payload=said)))
        got = done.event
        assert (got.seq, got.from_state, got.to_state) == (1, "pending_submit", "accepted")
        assert (got.source, got.payload) == ("rest", {"retCode": 0, "headers": REDACTED})
        assert await h.stored(row) == (done.order, [0, 1]) and done.order.state == "accepted"

    async def test_a_missed_compare_and_set_writes_nothing(self, h: Harness) -> None:
        row = await h.order("accepted")
        late = step(row, "cancelled", event(payload={"x": "MARKER"}), from_state="pending_cancel")
        with pytest.raises(port.StaleOrderState) as err:
            await h.orders.transition(late)
        assert (err.value.order_id, err.value.expected) == (row.id, "pending_cancel")
        assert "MARKER" not in str(err.value)  # the order and the state, never the payload
        assert await h.stored(row) == (row, [0])

    async def test_of_two_concurrent_steps_exactly_one_wins(self, h: Harness) -> None:
        row = await h.order("accepted")
        steps = (step(row, "pending_cancel"), step(row, "pending_amend"))
        results = await asyncio.gather(*map(h.orders.transition, steps), return_exceptions=True)
        (won,) = [r for r in results if isinstance(r, port.CommittedStep)]
        assert [type(r) for r in results if r is not won] == [port.StaleOrderState]
        assert await h.stored(row) == (won.order, [0, 1])

    @pytest.mark.parametrize("write", sorted(_REFUSED_EVENT))
    async def test_a_refused_event_rolls_the_unit_back(self, h: Harness, write: str) -> None:
        """S7, a rollback mid-unit: the state, a fill's totals and its execution are as before."""
        row = await h.order("accepted")
        with pytest.raises(port.OrderConstraintError, match="oe_latency"):
            await _REFUSED_EVENT[write](h, row, event("partial_fill", latency_ms=-1))
        assert await h.stored(row) == (row, [0])
        assert await h.executions.get(row.exchange_account_id, "E1") is None

    async def test_a_step_outside_the_account_writes_nothing(self, h: Harness) -> None:
        row = await h.order("accepted")
        with pytest.raises(port.OrderNotFoundError):
            await h.orders.transition(step(row, "pending_cancel", account_id=h.new_account()))
        assert await h.stored(row) == (row, [0])

    async def test_a_fill_commits_with_its_execution_and_event(self, h: Harness) -> None:
        row = await h.order("accepted")
        done = await h.executions.apply_fill(fill(row, "E1", "0.1"))
        assert done is not None
        new, got, q = done.order, done.event, Decimal("0.1")
        assert (got.kind, got.from_state, got.to_state) == ("partial_fill", "accepted", new.state)
        assert (new.state, new.avg_price, new.fee_paid) == ("partially_filled", PX, FEE)
        assert (new.cum_exec_qty, new.leaves_qty, new.cum_exec_value) == (q, 2 * q, Decimal(6300))
        stored = await h.executions.get(row.exchange_account_id, "E1")
        assert stored is not None and (stored.order_id, stored.exec_qty) == (row.id, q)
        assert await h.stored(row) == (new, [0, 1])

    async def test_duplicate_fill_never_double_counts(self, h: Harness) -> None:
        """Gherkin "Duplicate fill never double-counts", its durable half (S4): E1 for 0.1 was
        applied; delivered again, with totals computed after it, it changes nothing (None)."""
        row = await h.order("accepted")
        first = await h.executions.apply_fill(fill(row, "E1", "0.1"))
        assert first is not None
        assert await h.executions.apply_fill(fill(first.order, "E1", "0.1")) is None
        assert await h.stored(row) == (first.order, [0, 1])

    async def test_a_fill_above_qty_is_refused_before_writing(self, h: Harness) -> None:
        """OM-T04: totals above `qty` are hostile data, refused, never clamped."""
        row = await h.order("accepted")
        with pytest.raises(port.FillAboveQty) as err:
            await h.executions.apply_fill(fill(row, "E1", "0.4"))
        assert err.value.order_id == row.id
        assert await h.executions.get(row.exchange_account_id, "E1") is None
        assert await h.stored(row) == (row, [0])
        done = await h.executions.apply_fill(fill(row, "E1", "0.3"))  # exactly `qty`: accepted
        assert done is not None and done.order.state == "filled"
        assert done.order.leaves_qty == Decimal(0)

    @pytest.mark.parametrize("state", ["accepted", "partially_filled"])
    async def test_of_two_concurrent_fills_one_wins(self, h: Harness, state: Any) -> None:
        """The loser came from a row the winner changed: its state (from `accepted`) or only its
        `cum_exec_qty`. It writes nothing, its execution neither, so it is no duplicate later."""
        row = await h.order(state)
        fills = (fill(row, "E1", "0.1"), fill(row, "E2", "0.1"))
        results = await asyncio.gather(*map(h.executions.apply_fill, fills), return_exceptions=True)
        (i,) = [i for i, r in enumerate(results) if isinstance(r, port.CommittedStep)]
        won, lost = results[i], fills[1 - i].execution.exec_id
        assert isinstance(won, port.CommittedStep)
        assert isinstance(results[1 - i], port.StaleOrderState)
        assert await h.executions.get(row.exchange_account_id, lost) is None
        again = await h.executions.apply_fill(fill(won.order, lost, "0.1"))
        assert again is not None and again.order.cum_exec_qty == Decimal("0.2")
