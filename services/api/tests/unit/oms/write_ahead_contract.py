"""Behavioural contract of the write-ahead step (E29-T03 #847): 24 Sec.8.2 S8 (a state commits
with its event), S7 (a refused or failed write changes nothing) and S4's durable half (a repeated
`exec_id` never counts twice). `test_write_ahead_fake.py` runs it on the fake,
`tests/integration/storage/test_orders_store_pg.py` on Postgres; subclasses supply `h`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.exchange_payload import MAX_CODE_CHARS, OVERSIZE, REDACTED
from candleviewer.storage.repositories.executions import FillTotals, NewExecution, OrderFill

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
QTY, PX, FEE = Decimal("0.3"), Decimal("63000"), Decimal("0.5")
SHAPE = "DUMMYKEY_" + "Q3w9" * 6  # synthetic, credential-shaped, built at run time (SR-145)
Row = port.OrderRow
Event = port.NewOrderEvent
Transition = port.OrderTransition


def event(kind: port.OrderEventKind = "ack", **over: Any) -> Event:
    base = {"kind": kind, "source": "ws_private", "event_ts": T0, "payload": {"orderStatus": "New"}}
    return port.NewOrderEvent(**(base | over))


def step(row: Row, to: port.OrderState, new: Event | None = None, **over: Any) -> Transition:
    base = {"account_id": row.exchange_account_id, "order_id": row.id, "from_state": row.state}
    return port.OrderTransition(**(base | {"to_state": to, "event": new or event()} | over))


def fill(row: Row, exec_id: str, qty: str, new: Event | None = None, **over: Any) -> OrderFill:
    """The fill as E29-T03's `apply_execution` would compute it from `row`; `over` changes its
    execution and, as `to_state`, its step."""
    size = Decimal(qty)
    cum = row.cum_exec_qty + size
    to: port.OrderState = over.pop("to_state", "filled" if cum == row.qty else "partially_filled")
    base: dict[str, Any] = {
        "exchange_account_id": row.exchange_account_id, "order_id": row.id, "exec_id": exec_id,
        "order_link_id": row.order_link_id, "symbol": "BTCUSDT", "side": "Buy", "exec_qty": size,
        "exec_price": PX, "exec_value": size * PX, "exec_type": "Trade", "is_maker": False,
        "exec_ts": T0, "exec_fee": FEE,
    }  # fmt: skip
    execution = NewExecution(**(base | over))
    value, fee = row.cum_exec_value + size * PX, row.fee_paid + FEE
    totals = FillTotals(cum_exec_qty=cum, cum_exec_value=value, avg_price=PX, fee_paid=fee)
    new = new or event("fill" if cum == row.qty else "partial_fill", payload={"execId": exec_id})
    moved = step(row, to, new, account_id=execution.exchange_account_id)
    return OrderFill(step=moved, execution=execution, totals=totals)


@dataclass(frozen=True)
class Harness:
    orders: OrderRepository
    events: OrderEventRepository
    executions: ExecutionRepository
    new_account: Callable[[], UUID]

    async def order(self, state: port.OrderState = "accepted", first: Event | None = None) -> Row:
        new = port.NewOrder(
            id=uuid4(), exchange_account_id=self.new_account(), order_link_id=f"ext-{uuid4().hex}",
            symbol="BTCUSDT", side="Buy", intent="entry", order_type="Limit", qty=QTY, price=PX,
            stop_loss=Decimal("62000"), state=state,
        )  # fmt: skip
        return await self.orders.create(new, first or event("local_create", source="local"))

    async def stored(self, row: Row) -> tuple[Row | None, list[int]]:
        """The order as stored now, and its events' `seq`s."""
        events = await self.events.list_for_order(row.exchange_account_id, row.id)
        return await self.orders.get(row.exchange_account_id, row.id), [e.seq for e in events]


_OTHER = uuid4()  # an account that holds none of the orders
#: Events whose insert `oe_latency` refuses, after the step's update (and a fill's insert).
_LATE_ACK, _LATE_FILL = event(latency_ms=-1), event("partial_fill", latency_ms=-1)
_REFUSED: dict[str, tuple[Callable[[Harness, Row], Awaitable[object]], type[Exception], Any]] = {
    "late_step_event": (lambda h, r: h.orders.transition(step(r, "submitted", _LATE_ACK)),
                        port.OrderConstraintError, "oe_latency"),
    "late_fill_event": (lambda h, r: h.executions.commit_fill(fill(r, "E1", "0.1", _LATE_FILL)),
                        port.OrderConstraintError, "oe_latency"),
    "step_elsewhere": (lambda h, r: h.orders.transition(step(r, "submitted", account_id=_OTHER)),
                       port.OrderNotFoundError, None),  # C-12.4
    "fill_elsewhere": (lambda h, r: h.executions.commit_fill(
        fill(r, "E1", "0.1", exchange_account_id=_OTHER)), port.OrderNotFoundError, None),
    "fill_elsewhere_no_qty": (lambda h, r: h.executions.commit_fill(fill(  # locked before a CHECK
        r, "E1", "0.1", exchange_account_id=_OTHER, exec_qty=Decimal(0))),
        port.OrderNotFoundError, None),
    "fill_kind": (lambda h, r: h.orders.transition(step(r, "partially_filled", event("fill"))),
                  ValueError, "commit_fill"),  # a fill comes with its execution (OM-R02)
    "filled": (lambda h, r: h.orders.transition(step(r, "filled", event("exchange_push"))),
               ValueError, "commit_fill"),
    "fill_appended": (lambda h, r: h.events.append(r.exchange_account_id, r.id, event("fill")),
                      ValueError, "commit_fill"),
    # refused before any statement (`require_no_fill`), so before the account is looked at
    "fill_appended_elsewhere": (lambda h, r: h.events.append(_OTHER, r.id, event("fill")),
                                ValueError, "commit_fill"),
    "filled_elsewhere": (lambda h, r: h.orders.transition(
        step(r, "filled", event("exchange_push"), account_id=_OTHER)), ValueError, "commit_fill"),
    "above_qty": (lambda h, r: h.executions.commit_fill(fill(r, "E1", "0.4")),
                  port.FillRefused, "above_qty"),  # OM-T04: refused, never clamped
    "paper_mismatch": (lambda h, r: h.executions.commit_fill(fill(r, "E1", "0.1", is_paper=True)),
                       port.FillRefused, "paper_mismatch"),
    "state_mismatch": (lambda h, r: h.executions.commit_fill(
        fill(r, "E1", "0.1", to_state="filled")), port.FillRefused, "state_mismatch"),
    "no_qty": (lambda h, r: h.executions.commit_fill(fill(r, "E1", "0.1", exec_qty=Decimal(0))),
               port.OrderConstraintError, "ex_qty"),
    "no_price": (lambda h, r: h.executions.commit_fill(fill(r, "E1", "0.1", exec_price=Decimal(0))),
                 port.OrderConstraintError, "ex_px"),
}  # fmt: skip
_REDELIVER: dict[str, Callable[[Harness, OrderFill], Awaitable[object]]] = {
    "insert": lambda h, f: h.executions.insert(f.execution),
    "commit_fill": lambda h, f: h.executions.commit_fill(f),
}


class WriteAheadContract:
    async def test_a_step_commits_its_state_with_its_event(self, h: Harness) -> None:
        """S8: the state and its event (both states, the source, the exchange's message redacted,
        OM-R02) commit together, before the step returns."""
        row = await h.order("pending_submit")
        said = {"code": 0, "headers": {"signature": SHAPE}}
        done = await h.orders.transition(step(row, "accepted", event(source="rest", payload=said)))
        got = done.event
        assert (got.seq, got.from_state, got.to_state) == (1, "pending_submit", "accepted")
        assert (got.source, got.payload) == ("rest", {"code": 0, "headers": REDACTED})
        assert await h.stored(row) == (done.order, [0, 1]) and done.order.state == "accepted"

    async def test_a_reject_is_stored_redacted(self, h: Harness) -> None:
        """#845 decision 2 on every store: `reject_code` and `ret_code` take the string rule within
        64 characters, `reject_message` and `ret_msg` the message rule too (18 letters alone pass
        the string rule)."""
        row = await h.order("pending_submit")
        code, text = "1" * (MAX_CODE_CHARS + 1), "bad " + "Qx" * 9
        said = event("reject", source="rest", payload={"code": 1}, ret_code=code, ret_msg=text)
        moved = step(row, "rejected", said, reject_code=code, reject_message=text)
        done = await h.orders.transition(moved)
        assert (done.order.reject_code, done.order.reject_message) == (OVERSIZE, REDACTED)
        assert (done.event.ret_code, done.event.ret_msg) == (OVERSIZE, REDACTED)
        assert await h.stored(row) == (done.order, [0, 1])

    async def test_an_exchange_reported_order_is_created_with_its_message(self, h: Harness) -> None:
        """OM-R02 from the first state: an adopted order's event carries what the exchange said,
        refused before any statement."""
        with pytest.raises(ValueError, match="OM-R02"):
            await h.order("untracked", event("reconcile_diff", source="reconcile", payload={}))

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

    @pytest.mark.parametrize("write", sorted(_REFUSED))
    async def test_a_refused_write_changes_nothing(self, h: Harness, write: str) -> None:
        """S7, whatever refuses it (a constraint mid-unit, the account, OM-R02, OM-T04): the
        order, its events and the execution, in either account, stay as they were."""
        run, error, match = _REFUSED[write]
        row = await h.order("accepted")
        with pytest.raises(error, match=match):
            await run(h, row)
        assert await h.stored(row) == (row, [0])
        accounts = (row.exchange_account_id, _OTHER)
        assert [await h.executions.get(a, "E1") for a in accounts] == [None, None]

    async def test_a_fill_commits_with_its_execution_and_event(self, h: Harness) -> None:
        row = await h.order("accepted")
        done = await h.executions.commit_fill(fill(row, "E1", "0.1"))
        assert done is not None
        new, got, q = done.order, done.event, Decimal("0.1")
        assert (got.kind, got.from_state, got.to_state) == ("partial_fill", "accepted", new.state)
        assert (new.state, new.avg_price, new.fee_paid) == ("partially_filled", PX, FEE)
        assert (new.cum_exec_qty, new.leaves_qty, new.cum_exec_value) == (q, 2 * q, Decimal(6300))
        stored = await h.executions.get(row.exchange_account_id, "E1")
        assert stored is not None and (stored.order_id, stored.exec_qty) == (row.id, q)
        assert await h.stored(row) == (new, [0, 1])

    @pytest.mark.parametrize("qty", ["0.1", "0.3"])  # a partial fill, and the one that fills
    async def test_duplicate_fill_never_double_counts(self, h: Harness, qty: str) -> None:
        """Gherkin "Duplicate fill never double-counts", its durable half (S4): E1 was applied;
        delivered again, with totals computed after it (past `qty` once it filled the order),
        it changes nothing (None), so a duplicate is never taken for hostile data."""
        row = await h.order("accepted")
        first = await h.executions.commit_fill(fill(row, "E1", qty))
        assert first is not None
        assert await h.executions.commit_fill(fill(first.order, "E1", qty)) is None
        assert await h.stored(row) == (first.order, [0, 1])

    async def test_two_concurrent_deliveries_of_one_fill_apply_it_once(self, h: Harness) -> None:
        """S4 in a race: `execution` and `execution.fast` deliver E1 at once, from one row."""
        row = await h.order("accepted")
        same = fill(row, "E1", "0.1")
        results = await asyncio.gather(*(h.executions.commit_fill(same) for _ in "ab"))
        (won,) = [r for r in results if r is not None]
        assert None in results and won.order.cum_exec_qty == Decimal("0.1")
        assert await h.stored(row) == (won.order, [0, 1])

    @pytest.mark.parametrize("write", sorted(_REDELIVER))
    async def test_a_redelivered_fill_meets_its_checks_first(self, h: Harness, write: str) -> None:
        """Postgres checks a row's CHECKs before its `exec_id` conflict; so does the fake."""
        row = await h.order("accepted")
        assert await h.executions.commit_fill(fill(row, "E1", "0.1")) is not None
        with pytest.raises(port.OrderConstraintError, match="ex_qty"):
            await _REDELIVER[write](h, fill(row, "E1", "0.1", exec_qty=Decimal(0)))

    async def test_a_fill_stored_by_insert_is_never_applied(self, h: Harness) -> None:
        """`insert` is for a fill that moves no order: `commit_fill` then reads it as applied."""
        row = await h.order("accepted")
        assert await h.executions.insert(fill(row, "E1", "0.1").execution)
        assert await h.executions.commit_fill(fill(row, "E1", "0.1")) is None
        assert await h.stored(row) == (row, [0])

    @pytest.mark.parametrize("state", ["accepted", "partially_filled"])
    async def test_of_two_concurrent_fills_one_wins(self, h: Harness, state: Any) -> None:
        """The loser came from a row the winner changed: its state (from `accepted`) or only its
        `cum_exec_qty`. It writes nothing, its execution neither, so it is no duplicate later."""
        row = await h.order(state)
        fills = (fill(row, "E1", "0.1"), fill(row, "E2", "0.1"))
        commit = h.executions.commit_fill
        results = await asyncio.gather(*map(commit, fills), return_exceptions=True)
        (i,) = [i for i, r in enumerate(results) if isinstance(r, port.CommittedStep)]
        won, stale, lost = results[i], results[1 - i], fills[1 - i].execution.exec_id
        assert isinstance(won, port.CommittedStep) and isinstance(stale, port.StaleOrderState)
        assert (stale.order_id, stale.expected) == (row.id, state)  # the state it was built on
        assert await h.executions.get(row.exchange_account_id, lost) is None
        again = await h.executions.commit_fill(fill(won.order, lost, "0.1"))
        assert again is not None and again.order.cum_exec_qty == Decimal("0.2")
