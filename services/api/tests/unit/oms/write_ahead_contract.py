"""Behavioural contract of the write-ahead step (E29-T03 #847): 24 Sec.8.2 S8 (a state commits
with its event), S7 (a refused or failed write changes nothing) and S4's durable half (a repeated
`exec_id` never counts twice); and, so the fake takes only what Postgres takes (C-13.3), the
constraint an order write meets first, money at its column's scale and events as fresh copies.
`test_write_ahead_fake.py` runs it on the fake, `tests/integration/storage/test_orders_store_pg.py`
on Postgres; subclasses supply `h`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository
from candleviewer.oms.execution import apply_fields
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.recovery import RebuiltOrder, rebuild
from candleviewer.statechart.bindings.b01_order import GATES, PASSED, Step
from candleviewer.storage.errors import StorageQueryFailed
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


def created() -> Event:
    """The first event of an order the OMS creates."""
    return event("local_create", source="local")


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


def named(done: OrderFill) -> OrderFill:
    """*done* with its step naming the chart state its `to_state` persists, as B1's writer does."""
    chart = port.LIFECYCLE_STATE_OF[done.step.to_state]
    return replace(done, step=replace(done.step, lifecycle_state=chart))


async def b1_order(h: Harness, *, rejected: bool) -> Row:
    """An order whose steps B1's step writer wrote (`OrderStepWriter`, as `persist_event` hands
    them over): sent and acked, filled in part, amended and filled; or refused by the exchange."""
    order = h.new_order("pending_submit")
    writer = OrderStepWriter(h.orders, h.executions, clock=lambda: T0)
    writer.expect(order)
    ids = {"order_id": str(order.id), "order_link_id": order.order_link_id}
    ids |= {"account_id": str(order.exchange_account_id), "symbol": order.symbol, "side": "buy"}
    terms = {"qty": "0.3", "price": "63000", "trigger_price": None, "take_profit": None}
    ctx: dict[str, Any] = ids | terms | {"stop_loss": "62000", "reduce_only": False}
    ctx |= {"filled_qty": "0", "cum_exec_value": "0", "avg_price": None, "fee_paid": "0"}
    ctx |= {"exchange_order_id": None, "reject_code": None}

    async def write(frm: str | None, to: str, trigger: str, said: dict[str, Any]) -> None:
        order_ids = (ids["order_id"], ids["account_id"], ids["order_link_id"])
        await writer(Step(*order_ids, frm, to, trigger, said, dict(ctx)))

    async def filled(frm: str, to: str, exec_id: str, qty: str) -> None:
        execution = ids | {"exec_id": exec_id, "exchange_order_id": "x-b1", "exec_type": "trade"}
        execution |= {"qty": qty, "price": "63000", "fee": "0", "fee_rate": "0.0002"}
        held = {k: Decimal(ctx[k]) for k in ("qty", "filled_qty", "cum_exec_value", "fee_paid")}
        fill = {"qty": Decimal(qty), "price": PX, "fee": Decimal(0), "fee_rate": Decimal("0.0002")}
        after = apply_fields(held, fill)
        ctx.update({k: str(v) for k, v in after.items() if k != "qty"})
        await write(frm, to, "EXEC", execution)

    order_fields = ids | terms | {"stop_loss": "62000", "reduce_only": False}
    gates = dict.fromkeys(GATES, PASSED)
    await write(None, "validated", "VALIDATE", {"gates": gates, "order": order_fields})
    await write("validated", "submitting", "SEND", {})
    if rejected:
        ctx["reject_code"] = "RATE_LIMITED"
        said = {"ok": False, "error_code": "RATE_LIMITED"}
        await write("submitting", "rejected", "done.invoke.place", said)
    else:
        ctx["exchange_order_id"] = "x-b1"
        await write(
            "submitting",
            "submitted",
            "done.invoke.place",
            {"ok": True, "exchange_order_id": "x-b1"},
        )
        await filled("submitted", "partially_filled", "E1", "0.1")
        await write("partially_filled", "amend_pending", "AMEND", {"price": "64000"})
        ctx["price"] = "64000"
        said = {"ok": True, "terms": {"price": "64000"}}
        await write("amend_pending", "partially_filled", "done.invoke.amend", said)
        await filled("partially_filled", "filled", "E2", "0.2")
    row = await h.orders.get(order.exchange_account_id, order.id)
    assert row is not None
    return row


@dataclass(frozen=True)
class Harness:
    orders: OrderRepository
    events: OrderEventRepository
    executions: ExecutionRepository
    new_account: Callable[[], UUID]

    def new_order(self, state: port.OrderState = "accepted", **over: Any) -> port.NewOrder:
        """An order to create: in a new account, under a new `ext-` link id, unless `over` says."""
        account = over.pop("exchange_account_id", None) or self.new_account()
        base: dict[str, Any] = {
            "id": uuid4(), "exchange_account_id": account, "order_link_id": f"ext-{uuid4().hex}",
            "symbol": "BTCUSDT", "side": "Buy", "intent": "entry", "order_type": "Limit",
            "qty": QTY, "price": PX, "stop_loss": Decimal("62000"), "state": state,
        }  # fmt: skip
        return port.NewOrder(**(base | over))

    async def order(
        self, state: port.OrderState = "accepted", first: Event | None = None, **over: Any
    ) -> Row:
        return await self.orders.create(self.new_order(state, **over), first or created())

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
    "append_elsewhere": (lambda h, r: h.events.append(_OTHER, r.id, event()),
                         port.OrderNotFoundError, None),  # C-12.4
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
    # Postgres meets the `symbol_code` domain as the row is built, then the CHECKs by name
    "no_qty_no_price": (lambda h, r: h.executions.commit_fill(fill(
        r, "E1", "0.1", exec_qty=Decimal(0), exec_price=Decimal(0))), port.OrderConstraintError,
        "ex_px"),
    "no_symbol": (lambda h, r: h.executions.commit_fill(fill(
        r, "E1", "0.1", symbol="btcusdt", exec_qty=Decimal(0))), port.OrderConstraintError,
        "symbol_code_check"),
}  # fmt: skip
_REDELIVER: dict[str, Callable[[Harness, OrderFill], Awaitable[object]]] = {
    "insert": lambda h, f: h.executions.insert(f.execution),
    "commit_fill": lambda h, f: h.executions.commit_fill(f),
}
_NOBODY, _XID = uuid4(), "exchange-order-1"  # an id no stored order holds; an exchange order id
#: Orders Postgres refuses beside one holding `_XID` in their account, by the first constraint it
#: meets (`0029_oms_core`): the `symbol_code` domain, the CHECKs by name, the unique indexes, then
#: the foreign keys at the statement's end. Each case but the last breaks a later one too.
_UNSTORABLE: dict[str, dict[str, Any]] = {
    "symbol_code_check": {"symbol": "btcusdt", "qty": Decimal(0)},
    "ord_cum": {"cum_exec_qty": QTY + Decimal("0.1"), "stop_loss": Decimal(0)},  # INV-1
    "ord_limit_px": {"price": Decimal(0), "order_link_id": "ext-adopted"},
    "ord_link_fmt": {"order_link_id": f"ext-{'0' * 32}\n", "take_profit": Decimal(0)},
    "ord_no_self": {"id": _NOBODY, "parent_order_id": _NOBODY, "qty": Decimal(0)},
    "ord_qty": {"qty": Decimal(0), "exchange_order_id": _XID},
    "ord_sl_px": {"stop_loss": Decimal(0), "take_profit": Decimal(0)},
    "ord_tp_px": {"take_profit": Decimal(0), "exchange_order_id": _XID},
    "ux_orders_exch_id": {"exchange_order_id": _XID, "parent_order_id": _NOBODY},
    "orders_parent_order_id_fkey": {"parent_order_id": _NOBODY},
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

    async def test_a_create_and_an_append_write_their_events_states(self, h: Harness) -> None:
        """`OrderStore.create` writes the first event from no state to the order's state, and
        `OrderEventStore.append` one that moves none (`orders.py`), as stored and as returned."""
        row = await h.order("accepted")
        account = row.exchange_account_id
        added = await h.events.append(account, row.id, event())
        first, second = await h.events.list_for_order(account, row.id)
        states = [(e.from_state, e.to_state) for e in (first, second, added)]
        assert states == [(None, "accepted"), (None, None), (None, None)]

    async def test_a_create_a_step_and_a_fill_leave_the_chart_state_null(self, h: Harness) -> None:
        """`orders.lifecycle_state` (`0034_order_vocabulary`) has no default: a create, a step
        and a fill that name no chart state leave it NULL, as returned and as stored, so
        `ord_lifecycle` holds on every row (B1's step writer always names it, #847)."""
        row = await h.order("pending_submit")
        moved = await h.orders.transition(step(row, "accepted"))
        done = await h.executions.commit_fill(fill(moved.order, "E1", "0.1"))
        assert done is not None
        assert [r.lifecycle_state for r in (row, moved.order, done.order)] == [None, None, None]
        assert await h.stored(row) == (done.order, [0, 1, 2])

    async def test_every_write_keeps_the_chart_state_beside_state(self, h: Harness) -> None:
        """`orders.lifecycle_state` holds the B1 state that `state` persists (24 Sec.8.2 mapping,
        `ord_lifecycle`), and a step stores the exchange order id B1 bound (SR-E29-03): set by the
        create, a step and a fill that name them (#847)."""
        row = await h.order("pending_submit", lifecycle_state="validated")
        bind = step(row, "submitted", lifecycle_state="submitting", exchange_order_id="x-1")
        moved = await h.orders.transition(bind)
        done = await h.executions.commit_fill(named(fill(moved.order, "E1", "0.1")))
        assert done is not None and row.lifecycle_state == "validated"
        assert (moved.order.lifecycle_state, moved.order.exchange_order_id) == ("submitting", "x-1")
        assert (done.order.lifecycle_state, done.order.exchange_order_id) == (
            "partially_filled",
            "x-1",
        )
        assert (await h.stored(row))[0] == done.order

    @pytest.mark.parametrize("write", ["transition", "commit_fill"])
    async def test_a_step_that_leaves_the_chart_state_behind_is_refused(
        self, h: Harness, write: str
    ) -> None:
        """`ord_lifecycle` (24 Sec.8.2's mapping): a step that names no chart state moves
        `state` away from the `lifecycle_state` the row holds, a pair the mapping does not admit,
        so it is refused by name, with nothing written, on either store."""
        row = await h.order("accepted", lifecycle_state="submitted")
        with pytest.raises(port.OrderConstraintError, match="ord_lifecycle"):
            if write == "transition":
                await h.orders.transition(step(row, "pending_cancel"))
            else:
                await h.executions.commit_fill(fill(row, "E1", "0.1"))
        assert await h.stored(row) == (row, [0])
        assert await h.executions.get(row.exchange_account_id, "E1") is None

    async def test_a_step_binding_an_id_another_order_holds_changes_nothing(
        self, h: Harness
    ) -> None:
        """`ux_orders_exch_id`: one exchange order binds to one row of its account (SR-E29-03)."""
        held = await h.order("accepted", exchange_order_id="x-1")
        row = await h.order("pending_submit", exchange_account_id=held.exchange_account_id)
        with pytest.raises(port.OrderConstraintError, match="ux_orders_exch_id"):
            await h.orders.transition(step(row, "submitted", exchange_order_id="x-1"))
        assert await h.stored(row) == (row, [0])

    async def test_an_accepted_amend_stores_its_terms(self, h: Harness) -> None:
        """S2: a step stores the terms an accepted amend changed; a `qty` under the filled quantity
        is `ord_cum`'s to refuse, and nothing is written (#847)."""
        row = await h.order("pending_amend")
        terms = {"price": Decimal("64000"), "stop_loss": Decimal("62500"), "qty": Decimal("0.2")}
        done = await h.orders.transition(step(row, "accepted", terms=terms))
        stored = (done.order.price, done.order.stop_loss, done.order.qty, done.order.leaves_qty)
        assert stored == (Decimal(64000), Decimal(62500), Decimal("0.2"), Decimal("0.2"))
        filled = await h.executions.commit_fill(fill(done.order, "E1", "0.1"))
        assert filled is not None
        moved = step(filled.order, "pending_amend", terms={"qty": Decimal("0.05")})
        with pytest.raises(port.OrderConstraintError, match="ord_cum"):
            await h.orders.transition(moved)
        assert (await h.stored(row))[0] == filled.order

    @pytest.mark.parametrize("write", ["create", "transition", "commit_fill", "insert"])
    async def test_text_holding_nul_is_refused_with_nothing_written(
        self, h: Harness, write: str
    ) -> None:
        """OM-T04: exchange text the redaction never sees (an
        `exec_id`, an `exchange_order_id`) cannot hold NUL in Postgres text. The statement is
        refused whole (SQLSTATE 22021 as the server decodes the value), so a hostile push is a
        write that fails every retry, never one the fake takes (C-13.3), and nothing is written.
        A read binding that text is refused the same way."""
        row, nul = await h.order(), "x\x001"
        mine: dict[str, Any] = {"exchange_account_id": row.exchange_account_id}
        with pytest.raises(StorageQueryFailed):
            if write == "create":  # in the account the late check reads
                await h.order(**mine, exchange_order_id=nul, id=(late := uuid4()))
            elif write == "transition":
                await h.orders.transition(step(row, "submitted", exchange_order_id=nul))
            elif write == "commit_fill":
                await h.executions.commit_fill(fill(row, nul, "0.1"))
            else:
                await h.executions.insert(fill(row, nul, "0.1").execution)
        assert await h.stored(row) == (row, [0])
        with pytest.raises(StorageQueryFailed):  # Postgres decodes the bound text first
            await h.executions.get(row.exchange_account_id, nul)
        if write == "create":
            assert await h.orders.get(row.exchange_account_id, late) is None

    @pytest.mark.parametrize("rejected", [False, True])
    async def test_the_fold_of_an_orders_events_equals_its_row(
        self, h: Harness, rejected: bool
    ) -> None:
        """OM-T03 on every store, Postgres included (the ticket's rebuild against a populated
        Postgres): the events B1's steps wrote rebuild the row alone, its state, bound id, amended
        terms, fill totals and reject columns as the store returns them."""
        row = await b1_order(h, rejected=rejected)
        events = await h.events.list_for_order(row.exchange_account_id, row.id)
        assert rebuild(events) == RebuiltOrder.of_row(row)
        assert (row.state, row.reject_code) == (
            ("rejected", "RATE_LIMITED") if rejected else ("filled", None)
        )

    async def test_a_latency_of_zero_is_stored(self, h: Harness) -> None:
        """`oe_latency` refuses a negative `latency_ms` (`_REFUSED`), not zero."""
        row = await h.order("pending_submit")
        done = await h.orders.transition(step(row, "submitted", event(latency_ms=0)))
        assert done.event.latency_ms == 0

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

    async def test_a_stored_event_never_changes(self, h: Harness) -> None:
        """C-2.9 (`trg_oe_append` on Postgres): whatever a caller does to what it wrote or was
        returned, each write and read returns a fresh copy, its payload in `jsonb`'s key order
        (shortest first)."""
        row = await h.order("pending_submit")
        account, said = row.exchange_account_id, {"orderStatus": "New", "code": 0}
        done = await h.orders.transition(step(row, "submitted", event(source="rest", payload=said)))
        added = await h.events.append(account, row.id, event())
        read = await h.events.list_for_order(account, row.id)
        new, ack = {"orderStatus": "New"}, {"code": 0, "orderStatus": "New"}
        assert [list(done.event.payload), added.payload] == [["code", "orderStatus"], new]
        said["code"] = done.event.payload["code"] = added.payload["code"] = read[1].payload["x"] = 9
        stored = [e.payload for e in await h.events.list_for_order(account, row.id)]
        assert stored == [new, ack, new]

    async def test_money_is_returned_at_its_columns_scale(self, h: Harness) -> None:
        """As asyncpg reads numeric(38,18), and numeric(18,10) for `fee_rate`: digit for digit at
        the column's scale, an order's money, `leaves_qty`, a fill's totals and its execution."""
        row = await h.order(price=Decimal("63099.80"))
        done = await h.executions.commit_fill(fill(row, "E1", "0.1", fee_rate=Decimal("0.00055")))
        stored = await h.executions.get(row.exchange_account_id, "E1")
        assert done is not None and stored is not None
        new = done.order
        got = (row.price, row.leaves_qty, new.avg_price, new.leaves_qty, stored.fee_rate)
        assert [str(value) for value in got] == [
            "63099.800000000000000000", "0.300000000000000000", "63000.000000000000000000",
            "0.200000000000000000", "0.0005500000",
        ]  # fmt: skip

    async def test_an_exchange_reported_order_is_created_with_its_message(self, h: Harness) -> None:
        """OM-R02 from the first state: an adopted order's event carries what the exchange said,
        refused before any statement."""
        with pytest.raises(ValueError, match="OM-R02"):
            await h.order("untracked", event("reconcile_diff", source="reconcile", payload={}))

    @pytest.mark.parametrize("constraint", sorted(_UNSTORABLE))
    async def test_an_order_postgres_refuses_is_refused_by_name(
        self, h: Harness, constraint: str
    ) -> None:
        """The constraint Postgres reports, and nothing is stored beside the account's order."""
        row = await h.order(exchange_order_id=_XID)
        again = h.new_order(exchange_account_id=row.exchange_account_id, **_UNSTORABLE[constraint])
        with pytest.raises(port.OrderConstraintError) as err:
            await h.orders.create(again, created())
        assert err.value.constraint == constraint
        assert await h.orders.list_open(row.exchange_account_id) == (row,)

    async def test_a_create_meets_its_events_check_before_a_foreign_key(self, h: Harness) -> None:
        """The first event's `oe_latency` is met as it is inserted, the foreign keys at the end of
        the statement."""
        late = event("local_create", source="local", latency_ms=-1)
        with pytest.raises(port.OrderConstraintError, match="oe_latency"):
            await h.orders.create(h.new_order(parent_order_id=_NOBODY), late)

    async def test_an_order_postgres_takes_is_stored(self, h: Harness) -> None:
        """A NULL leaves a CHECK unknown, which passes it, and `ux_orders_exch_id` is per account:
        a Limit order with no price under one of our ids, a Market one priced 0, one filled to its
        `qty`, the exchange id in another account, and a take-profit child with no stop."""
        row = await h.order(exchange_order_id=_XID)
        mine: dict[str, Any] = {"exchange_account_id": row.exchange_account_id}
        ours = f"cvl-0{uuid4().hex[:21]}-{uuid4().hex[:4]}-00en"  # `OUR_ID`'s shape
        news = [
            h.new_order(**mine, price=None, order_link_id=ours),
            h.new_order(**mine, order_type="Market", price=Decimal(0)),
            h.new_order("filled", **mine, cum_exec_qty=QTY),
            h.new_order(exchange_order_id=_XID),
            h.new_order(**mine, parent_order_id=row.id, intent="take_profit", stop_loss=None),
        ]
        made = [await h.orders.create(new, created()) for new in news]
        assert [await h.orders.get(n.exchange_account_id, n.id) for n in news] == made

    @pytest.mark.parametrize("retried", [True, False])
    async def test_a_create_under_a_stored_id_changes_nothing(
        self, h: Harness, retried: bool
    ) -> None:
        """Postgres checks the unique indexes in the order they were made, the key first: a create
        retried after it landed (24 Sec.8.3 rule 1 reuses its ids), or another account's order
        under the id and a new link id, meets `orders_pkey`, and the stored order stays."""
        row = await h.order()
        mine: dict[str, Any] = {
            "order_link_id": row.order_link_id,
            "exchange_account_id": row.exchange_account_id,
        }
        again = h.new_order(id=row.id, **(mine if retried else {}))
        with pytest.raises(port.OrderConstraintError) as err:
            await h.orders.create(again, created())
        assert err.value.constraint == "orders_pkey"
        assert await h.stored(row) == (row, [0])
        assert await h.orders.get(again.exchange_account_id, row.id) == (row if retried else None)

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
        assert got.payload == {"execId": "E1"}
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

    async def test_a_stored_exec_id_is_no_insert_whatever_order_it_names(self, h: Harness) -> None:
        """`ON CONFLICT DO NOTHING` comes before the order's account is looked at: a stored
        `exec_id` is False even naming another account's order, and neither account changes."""
        row, other = await h.order(), await h.order()
        execution = fill(row, "E1", "0.1").execution
        assert await h.executions.insert(execution)
        assert not await h.executions.insert(replace(execution, order_id=other.id))
        assert [await h.stored(r) for r in (row, other)] == [(row, [0]), (other, [0])]
        kept = await h.executions.get(row.exchange_account_id, "E1")
        assert kept is not None and kept.order_id == row.id
        assert await h.executions.get(other.exchange_account_id, "E1") is None

    @pytest.mark.parametrize("write", sorted(_REDELIVER))
    async def test_an_exec_id_is_new_in_each_account(self, h: Harness, write: str) -> None:
        """`ux_exec_id` is per account: the `exec_id` of one account's fill, reported by another
        account, is a new fill there (stored by `insert`, applied by `commit_fill`), and the first
        account's fill and order stay as they were."""
        mine, theirs = await h.order(), await h.order()
        first = await h.executions.commit_fill(fill(mine, "E1", "0.1"))
        assert first is not None
        assert await _REDELIVER[write](h, fill(theirs, "E1", "0.1"))  # True, or the applied step
        kept = [await h.executions.get(r.exchange_account_id, "E1") for r in (mine, theirs)]
        assert [x and x.order_id for x in kept] == [mine.id, theirs.id]
        assert await h.stored(mine) == (first.order, [0, 1])

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
