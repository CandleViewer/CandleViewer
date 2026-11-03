"""E29-Q04's oracle (#1148, "The oracle is authoritative"): a book equal to the venue passes, and
each kind of field the oracle compares fails it once mutated, on either side, each named in the
one `OracleMismatch` (`_oracle.py`'s list). Plain rows, no runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.models import Execution
from candleviewer.storage.repositories.executions import ExecutionRow
from candleviewer.storage.repositories.positions import PositionRow
from tests.chaos.oms._oracle import Book, OracleMismatch, Truth, check, compare, expected
from tests.unit.oms import reconcile_rig as rr

pytestmark = pytest.mark.chaos

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
D = Decimal
FILLED = {"leaves_qty": D(0), "take_profit": D(65000)}
ORDER = rr.remote(1, state="filled", filled_qty=D(1), avg_fill_price=D(63000), **FILLED)
ROW = rr.row(1, state="filled", cum_exec_qty=D(1), avg_price=D(63000), **FILLED)
FILLS = (rr.fill("e1", qty=D("0.4")), rr.fill("e2", qty=D("0.6"), seq=2))


def stored(fill: Execution) -> ExecutionRow:
    """The `executions` row the OMS keeps of a venue fill."""
    return ExecutionRow(
        exchange_account_id=fill.account_id, exec_id=fill.exec_id, symbol=fill.symbol,
        side="Buy", exec_qty=fill.qty, exec_price=fill.price, exec_value=fill.qty * fill.price,
        exec_type="Trade", is_maker=fill.is_maker, exec_ts=T0, order_id=ROW.id,
        order_link_id=fill.order_link_id, exec_fee=fill.fee, fee_rate=fill.fee_rate,
        id=UUID(int=fill.seq), recv_ts=T0,
    )  # fmt: skip


HELD = PositionRow(
    exchange_account_id=rr.ACCOUNT, symbol="BTCUSDT", size=D(1), side="Buy", avg_price=D(63000),
    stop_loss=D(62000), id=UUID(int=9), recv_ts=T0, updated_at=T0,
)  # fmt: skip
BOOK = Book((ROW,), tuple(map(stored, FILLS)), (HELD,))
TRUTH = Truth((ORDER,), FILLS, (rr.position(qty=D(1)),), {ORDER.order_link_id: 1})
type Mutation = Callable[[], tuple[Book, Truth]]


def row(**over: Any) -> Mutation:
    return lambda: (replace(BOOK, orders=(replace(ROW, **over),)), TRUTH)


def order(**over: Any) -> Mutation:
    return lambda: (BOOK, replace(TRUTH, orders=(ORDER.model_copy(update=over),)))


def fill(**over: Any) -> Mutation:
    mutated = (replace(BOOK.fills[0], **over), BOOK.fills[1])
    return lambda: (replace(BOOK, fills=mutated), TRUTH)


def position(**over: Any) -> Mutation:
    return lambda: (BOOK, replace(TRUTH, positions=(TRUTH.positions[0].model_copy(update=over),)))


def held(**over: Any) -> Mutation:
    return lambda: (replace(BOOK, positions=(replace(HELD, **over),)), TRUTH)


def partial(qty: Decimal) -> Mutation:
    """The position's stop as a Partial-mode stop order of `qty` instead of its own (C-2.6)."""
    stop = rr.remote(
        2, order_link_id=ext_key("x2"), state="untriggered", order_kind="partial_stop_loss",
        tpsl_mode="partial", side="sell",
        order_type="market", price=None, qty=qty, leaves_qty=qty, trigger_price=D(62000),
        stop_loss=None, reduce_only=True,
    )  # fmt: skip
    truth = replace(TRUTH, positions=(TRUTH.positions[0].model_copy(update={"stop_loss": None}),))
    book = replace(BOOK, positions=(replace(HELD, stop_loss=None),))
    return lambda: (book, replace(truth, orders=(ORDER, stop)))


#: Each kind of field the oracle compares, mutated on one side: the (item, field) it must name.
MUTATIONS: dict[str, tuple[Mutation, tuple[str, str]]] = {
    "link": (order(order_link_id=rr.LINK.format(2)), ("order", "order_link_id")),
    "bound-id": (row(exchange_order_id="x9"), ("order", "exchange_order_id")),
    "state": (row(lifecycle_state="partially_filled"), ("order", "lifecycle_state")),
    "status": (order(state="cancelled"), ("order", "lifecycle_state")),
    "qty": (row(qty=D(2)), ("order", "qty")),
    "filled": (row(cum_exec_qty=D("0.4")), ("order", "filled_qty")),
    "average": (row(avg_price=D(63001)), ("order", "avg_fill_price")),
    "price": (order(price=D(62999)), ("order", "price")),
    "trigger": (row(trigger_price=D(62500)), ("order", "trigger_price")),
    "stop": (row(stop_loss=D(61000)), ("order", "stop_loss")),
    "take-profit": (order(take_profit=None), ("order", "take_profit")),
    "reduce-only": (row(reduce_only=True), ("order", "reduce_only")),
    "side": (row(side="Sell"), ("order", "side")),
    "position-idx": (order(position_idx=1), ("order", "position_idx")),
    "fills-sum": (lambda: (replace(BOOK, fills=BOOK.fills[:1]), TRUTH), ("order", "executions")),
    "venue-fills": (order(filled_qty=D("0.9")), ("order", "venue's own fills")),
    "fill-missing": (lambda: (BOOK, replace(TRUTH, fills=FILLS[1:])), ("execution", "exec_id")),
    "fill-qty": (fill(exec_qty=D("0.5")), ("execution", "qty")),
    "fill-price": (fill(exec_price=D(63100)), ("execution", "price")),
    "fill-fee": (fill(exec_fee=D("0.02")), ("execution", "fee")),
    "fill-order": (fill(order_id=UUID(int=2)), ("execution", "exchange_order_id")),
    "position-open": (lambda: (replace(BOOK, positions=()), TRUTH), ("position", "open")),
    "position-side": (held(side="Sell"), ("position", "side")),
    "position-size": (position(qty=D(2)), ("position", "size")),
    "entry-price": (held(avg_price=D(62000)), ("position", "avg_entry_price")),
    "position-stop": (held(stop_loss=D(61500)), ("position", "stop_loss")),
    "naked": (position(stop_loss=None), ("position", "native stop")),
    "stop-under": (partial(D("0.6")), ("position", "stop size")),
    "stop-over": (partial(D("1.2")), ("position", "stop size")),
    "no-venue-order": (lambda: (BOOK, replace(TRUTH, orders=())), ("order", "venue order")),
    "no-row": (lambda: (replace(BOOK, orders=()), TRUTH), ("order", "row")),
    "second-create": (
        lambda: (BOOK, replace(TRUTH, creates={ORDER.order_link_id: 2})), ("order", "creates")
    ),
}  # fmt: skip


def test_a_book_equal_to_the_venue_passes() -> None:
    assert compare(BOOK, TRUTH) == []


def test_a_partial_mode_stop_sized_to_the_position_protects_it() -> None:
    assert [d for d in compare(*partial(D(1))()) if d.item.startswith("position")] == []


@pytest.mark.parametrize("name", MUTATIONS)
def test_each_kind_of_mutated_field_fails_it(name: str) -> None:
    mutated, named = MUTATIONS[name]
    assert named in {(d.item.split()[0], d.field) for d in compare(*mutated())}


@pytest.mark.parametrize(
    ("state", "tif", "untracked", "lifecycle"),
    [("untriggered", "gtc", False, "submitted"), ("deactivated", "gtc", False, "cancelled"),
     ("partially_filled_canceled", "ioc", False, "expired"), ("cancelled", "fok", False, "expired"),
     ("partially_filled", "gtc", True, "untracked"), ("filled", "gtc", True, "filled")],
)  # fmt: skip
def test_a_venue_status_reads_as_24s_table_says(
    state: str, tif: str, untracked: bool, lifecycle: str
) -> None:
    order = ORDER.model_copy(update={"state": state, "time_in_force": tif})
    assert expected(order, untracked=untracked) == lifecycle


class Checked:
    def __init__(self, book: Book) -> None:
        self.checked, self._book = False, book

    async def settle(self) -> None:
        return None

    async def book(self) -> Book:
        return self._book

    async def truth(self) -> Truth:
        return TRUTH


async def test_check_raises_one_mismatch_naming_every_field_and_marks_the_world() -> None:
    world = Checked(replace(BOOK, orders=(replace(ROW, qty=D(2), side="Sell"),)))
    with pytest.raises(OracleMismatch) as raised:
        await check(world)
    assert world.checked and {d.field for d in raised.value.diffs} == {"qty", "side"}
    assert str(raised.value).count("\n") == 1  # one line a field
