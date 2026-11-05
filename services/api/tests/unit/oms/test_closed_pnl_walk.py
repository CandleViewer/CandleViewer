"""The closed-PnL walk (E29-S06 #981 slice 5a; 24 Sec.8.13 step 3). Fills are `WalkFill`s as row
58 reads them, `n` seconds after `START`, the key's confirmed flat; each case names the sizes,
prices and fees it needs. The worked example's figures are the docs-transcribed
`rest/trading-closed-pnl.json` record's (24 Sec.8.13 "A worked example").
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, localcontext
from uuid import UUID

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from candleviewer.oms.closed_pnl_walk import Walk, WalkBudget, WalkClose, walk
from candleviewer.storage.repositories.closed_pnl import WalkFill
from candleviewer.storage.repositories.orders import OrderSide
from tests._corpus import rest

START = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)  # the key's last confirmed flat
ANCHOR = START + timedelta(microseconds=1)  # the record's order's first fill, unless a case says
BUDGET = WalkBudget(fills=64, flats=8)
A, B, C, D = (UUID(int=n) for n in range(1, 5))  # order rows
G1, G2, G3 = (UUID(int=0x60 + n) for n in range(1, 4))  # trade groups
_EXACT = Context(prec=400)
N = Decimal  # an expected figure
_8DP = Decimal("1e-8")


def at(n: int) -> datetime:
    return START + timedelta(seconds=n)


def fill(
    n: int, side: OrderSide, qty: str | Decimal, price: str | Decimal, *,
    fee: str | Decimal = "0", closed: str | Decimal | None = None, pnl: str | None = "0",
    order: UUID | None = A, idx: int = 0, exec_id: str | None = None,
) -> WalkFill:  # fmt: skip
    """The `n`-th fill: `closed` its stated `closedSize`, `pnl` its closed PnL, and `order` None
    for a fill with no order row."""
    return WalkFill(
        exec_id=exec_id or f"e{n:03}", exec_ts=at(n), order_id=order, side=side,
        exec_type="Trade", exec_qty=Decimal(qty), exec_price=Decimal(price),
        exec_fee=Decimal(fee), closed_pnl=None if pnl is None else Decimal(pnl),
        closed_size=None if closed is None else Decimal(closed),
        order_position_idx=None if order is None else idx,
        order_exchange_id=None if order is None else f"x{order.int}",
    )  # fmt: skip


def run(
    *fills: WalkFill, flats: tuple[datetime, ...] = (START,), anchor: datetime = ANCHOR,
    idx: int = 0, hedged: bool = False, budget: WalkBudget = BUDGET,
    groups: dict[UUID, UUID] | None = None,
) -> Walk:  # fmt: skip
    return walk(
        fills, flats, anchor=anchor, position_idx=idx, hedged=hedged, budget=budget,
        order_groups=groups or {},
    )  # fmt: skip


def flags(w: Walk) -> list[tuple[Decimal, bool, bool]]:
    return [(c.closed, c.unreadable, c.disagreeing) for c in w.closes]


def known(value: Decimal | None) -> Decimal:
    assert value is not None
    return value


def total(values: Sequence[Decimal | None]) -> Decimal:
    with localcontext(_EXACT):
        return sum((known(v) for v in values), Decimal(0))


def test_partial_and_full_closes_take_their_share_of_the_entry_value_and_opening_fees() -> None:
    """Opening fills add size, size x price and fee; a close takes `c / open size` of the
    entry value and the opening fees, its own fee whole, and leaves the average entry as it was."""
    f1 = fill(1, "Buy", "2", "100", fee="0.12", closed="0")
    f2 = fill(2, "Buy", "1", "103", fee="0.06")
    f3 = fill(3, "Sell", "1", "110", fee="0.066", closed="1", order=B)
    f4 = fill(4, "Sell", "2", "111", fee="0.1332", closed="2", order=B)
    first, second = (
        WalkClose(
            fill=f, closed=Decimal(c), closing_fee=f.exec_fee, entry_value=Decimal(value),
            opening_fees=Decimal(fees), avg_entry=Decimal(101), opened_at=at(1),
            groups=frozenset(), unreadable=False, disagreeing=False,
        )
        for f, c, value, fees in ((f3, 1, 101, "0.06"), (f4, 2, 202, "0.12"))
    )  # fmt: skip
    assert run(f4, f3, f2, f1) == Walk(start=START, closes=(first, second), clean=True)


def test_a_reversal_closes_the_open_size_and_its_remainder_opens_with_a_fee_share() -> None:
    """The sell of 5 closes the long of 2, takes 2/5 of its fee, and its remainder of 3 opens
    a short at its price with the other 3/5, from its time and in its order's group."""
    f1 = fill(1, "Buy", "2", "100", fee="0.2")
    f2 = fill(2, "Sell", "5", "90", fee="0.45", closed="2", order=B)
    f3 = fill(3, "Buy", "3", "80", fee="0.24", closed="3", order=C)
    w = run(f1, f2, f3, groups={A: G1, B: G2})
    first, second = w.closes
    assert (first.closed, first.closing_fee, first.entry_value, first.opening_fees) == (
        N(2), N("0.18"), N(200), N("0.2"),
    )  # fmt: skip
    assert (second.closed, second.closing_fee, second.entry_value, second.opening_fees) == (
        N(3), N("0.24"), N(270), N("0.27"),
    )  # fmt: skip
    assert (first.groups, second.groups, second.opened_at, second.avg_entry) == (
        frozenset({G1}), frozenset({G2}), at(2), N(90),
    )  # fmt: skip
    assert w.clean and w.open_size == 0


def test_a_confirmed_flat_drops_what_the_walk_holds_and_comes_after_a_fill_dated_at_it() -> None:
    """The buy dated at the start comes before it; the flat at 3 drops the long's last 1,
    which no stored fill closes; the sell dated at the flat at 7 comes before it, so it closes
    the long the buy at 6 opened; and the flat at 9 drops the buy at 8."""
    w = run(
        fill(0, "Buy", "1", "90"), fill(1, "Buy", "2", "100"),
        fill(2, "Sell", "1", "101", closed="1", order=B), fill(4, "Buy", "1", "105", order=C),
        fill(5, "Sell", "1", "106", closed="1", order=D), fill(6, "Buy", "1", "107", order=C),
        fill(7, "Sell", "1", "108", closed="1", order=D), fill(8, "Buy", "1", "109", order=C),
        flats=(at(7), START, at(9), at(3)),
    )  # fmt: skip
    assert [(c.closed, c.entry_value, c.opened_at) for c in w.closes] == [
        (N(1), N(100), at(1)), (N(1), N(105), at(4)), (N(1), N(107), at(6)),
    ]  # fmt: skip
    assert w.clean and w.open_size == 0


_OPEN_AGAIN = (
    fill(4, "Buy", "1", "103", order=C),
    fill(5, "Sell", "1", "104", closed="1", order=D),
)
_UNREADABLE = {
    "no closed PnL": ((
        fill(1, "Buy", "2", "100"), fill(2, "Sell", "1", "101", pnl=None, order=B),
        fill(3, "Sell", "1", "102", closed="1", order=B),
    ), (), False, [(N(1), True, False), (N(1), True, False)]),
    "larger than the open size, no closedSize": ((
        fill(1, "Buy", "1", "100"), fill(2, "Sell", "3", "101", order=B),
        fill(3, "Buy", "2", "99", closed="2", order=C),
    ), (), False, [(N(1), True, False), (N(2), True, False)]),
    "hedge mode, no order row": ((
        fill(1, "Buy", "1", "100"), fill(2, "Buy", "1", "101", order=None),
        fill(3, "Sell", "2", "102", closed="2", order=B),
    ), (), True, [(N(2), True, False)]),
    "no closed PnL, then a confirmed flat": ((
        fill(1, "Buy", "2", "100"), fill(2, "Sell", "1", "101", pnl=None, order=B),
    ), (at(3),), False, [(N(1), True, False)]),
}  # fmt: skip


@pytest.mark.parametrize(
    ("fills", "later", "hedged", "unread"), _UNREADABLE.values(), ids=list(_UNREADABLE)
)
def test_an_unreadable_fill_leaves_sizes_only_until_the_walk_next_goes_flat(
    fills: tuple[WalkFill, ...], later: tuple[datetime, ...], hedged: bool,
    unread: list[tuple[Decimal, bool, bool]],
) -> None:  # fmt: skip
    """The fill's close, and every close until the walk is flat by its own count or at a
    confirmed flat, give `c` alone; the position after it is read again."""
    w = run(*fills, *_OPEN_AGAIN, flats=(START, *later), hedged=hedged)
    assert flags(w) == [*unread, (N(1), False, False)]
    absent = [(c.entry_value, c.opening_fees, c.avg_entry, c.opened_at) for c in w.closes[:-1]]
    assert absent == [(None, None, None, None)] * len(absent)
    assert (w.closes[-1].entry_value, w.closes[-1].opened_at, w.clean) == (N(103), at(4), False)


def test_a_reversal_the_walk_reads_ends_an_unreadable_span_where_it_crosses_zero() -> None:
    """The sell of 3 states the 1 it closes, so the walk is flat there and the short its
    remainder opens is read; an unreadable fill's remainder opens unreadable (above)."""
    w = run(
        fill(1, "Buy", "2", "100"), fill(2, "Sell", "1", "101", pnl=None, order=B),
        fill(3, "Sell", "3", "102", closed="1", order=B),
        fill(4, "Buy", "2", "99", closed="2", order=C),
    )  # fmt: skip
    assert flags(w) == [(N(1), True, False), (N(1), True, False), (N(2), False, False)]
    assert (w.closes[-1].entry_value, w.closes[-1].opened_at) == (N(204), at(3))


_DISAGREEING = {
    "other than min(exec_qty, open size) on the other side": ((
        fill(1, "Buy", "2", "100"), fill(2, "Sell", "1", "101", closed="0.5", order=B),
        fill(3, "Sell", "1", "102", closed="0.25", order=B),
        fill(4, "Buy", "1", "103", closed="0", order=C),
        fill(5, "Sell", "1", "104", closed="1", order=D),
    ), 3),
    "above 0 on a fill that opens": ((
        fill(1, "Buy", "1", "100", closed="0.5"), fill(2, "Sell", "1", "101", closed="1", order=B),
        fill(4, "Buy", "1", "103", closed="0", order=C),
        fill(5, "Sell", "1", "104", closed="1", order=D),
    ), 2),
}  # fmt: skip


@pytest.mark.parametrize(("fills", "spanned"), _DISAGREEING.values(), ids=list(_DISAGREEING))
def test_a_disagreeing_closed_size_ends_only_at_a_confirmed_flat(
    fills: tuple[WalkFill, ...], spanned: int
) -> None:
    """From that fill each close is `c = min(exec_qty, open size)`, whatever it states, and
    disagreeing; the walk's own flats end nothing, and the confirmed flat at 5 ends the span."""
    later = (fill(6, "Buy", "1", "105", order=C), fill(7, "Sell", "1", "106", closed="1", order=D))
    w = run(*fills, *later, flats=(START, at(5)))
    assert flags(w) == [(N(1), True, True)] * spanned + [(N(1), False, False)]
    assert (w.closes[-1].entry_value, w.clean) == (N(105), False)


@pytest.mark.parametrize(
    ("closed", "unreadable", "disagreeing"),
    [("1", False, False), (None, True, False), ("3", True, True), ("0", True, True)],
)
def test_a_stated_closed_size_is_read_against_min_of_exec_qty_and_the_open_size(
    closed: str | None, unreadable: bool, disagreeing: bool
) -> None:
    """A sell of 3 against a long of 1 closes 1 whatever it states; it reads only when it
    states that 1."""
    w = run(fill(1, "Buy", "1", "100"), fill(2, "Sell", "3", "101", closed=closed, order=B))
    assert flags(w) == [(N(1), unreadable, disagreeing)]
    assert (w.open_size, w.clean) == (N(2), closed == "1")


@pytest.mark.parametrize(
    ("idx", "hedged", "unreadable"), [(0, False, False), (0, True, True), (1, False, True)]
)
def test_a_fill_with_no_order_row_is_unreadable_in_hedge_mode(
    idx: int, hedged: bool, unreadable: bool
) -> None:
    """On a symbol held in hedge mode, or on a key at `position_idx` 1 or 2, a fill with no
    order row may be the other key's."""
    w = run(fill(1, "Buy", "1", "100", idx=idx), fill(2, "Sell", "1", "101", order=None),
            idx=idx, hedged=hedged)  # fmt: skip
    assert flags(w) == [(N(1), unreadable, False)] and w.clean is not unreadable


@pytest.mark.parametrize("flats", [(), (at(2),), (at(3),)])
def test_a_key_with_no_confirmed_flat_before_the_anchor_has_no_start(
    flats: tuple[datetime, ...],
) -> None:
    """A flat dated at or after the record's order's first fill is no start, and the walk
    never starts at the key's first stored fill."""
    w = run(fill(1, "Buy", "1", "100"), fill(2, "Sell", "1", "101", order=B),
            flats=flats, anchor=at(2))  # fmt: skip
    assert w == Walk(start=None)


def test_the_start_is_the_last_confirmed_flat_before_the_anchor_never_one_at_it() -> None:
    """The flat at 2 starts the walk for the order whose first fill is at 4, so the buy at
    1 is before it, and the flat at 4 comes after that fill."""
    w = run(
        fill(1, "Buy", "1", "100"), fill(3, "Buy", "1", "103", order=C),
        fill(4, "Sell", "1", "104", order=B), flats=(at(4), START, at(2)), anchor=at(4),
    )  # fmt: skip
    assert (w.start, [c.entry_value for c in w.closes]) == (at(2), [N(103)])


@pytest.mark.parametrize(("fills", "flats", "capped"), [(4, 2, False), (5, 2, True), (4, 3, True)])
def test_a_walk_past_its_budget_is_capped_gives_nothing_and_is_never_clean(
    fills: int, flats: int, capped: bool
) -> None:
    """C-2.18: a walk handed more fills or flats than its budget gives no figure, never a part."""
    stored = (
        fill(1, "Buy", "1", "100"), fill(2, "Sell", "1", "101", order=B),
        fill(3, "Buy", "1", "102", order=C), fill(4, "Sell", "1", "103", order=D),
        fill(5, "Buy", "1", "104", order=C),
    )[:fills]  # fmt: skip
    w = run(*stored, flats=(START, at(9), at(10))[:flats], budget=WalkBudget(fills=4, flats=2))
    assert (w.capped, w.clean, len(w.closes), w.start) == (
        (True, False, 0, None) if capped else (False, True, 2, START)
    )


@pytest.mark.parametrize(
    ("groups", "second", "named"),
    [
        ({A: G1, B: G1}, B, {G1}),  # one group
        ({A: G1, B: G2}, B, {G1, G2}),  # several: the composition names none
        ({}, B, set()),  # none
        ({A: G1}, B, {G1}),  # an order on no leg names none
        ({A: G1}, None, {G1}),  # nor does a fill with no order row
    ],
)
def test_a_close_carries_the_groups_its_positions_opening_fills_orders_name(
    groups: dict[UUID, UUID], second: UUID | None, named: set[UUID]
) -> None:
    """The groups since the walk was last flat; the next position names its own."""
    w = run(
        fill(1, "Buy", "1", "100"), fill(2, "Buy", "1", "101", order=second),
        fill(3, "Sell", "2", "102", closed="2", order=C), fill(4, "Buy", "1", "103", order=D),
        fill(5, "Sell", "1", "104", closed="1", order=C), groups=groups | {D: G3},
    )  # fmt: skip
    assert [c.groups for c in w.closes] == [named, {G3}]


def test_a_fill_whose_order_row_is_on_another_key_is_not_walked() -> None:
    """The key is the fill's order row's `position_idx` (24 step 3)."""
    w = run(
        fill(1, "Buy", "1", "100", idx=1), fill(2, "Buy", "1", "120", order=B, idx=2),
        fill(3, "Sell", "1", "110", closed="1", order=C, idx=1), idx=1,
    )  # fmt: skip
    assert ([(c.closed, c.entry_value) for c in w.closes], w.open_size) == ([(N(1), N(100))], N(0))


def test_fills_of_one_time_are_walked_in_exec_id_order() -> None:
    sell = fill(2, "Sell", "2", "101", closed="2", order=B, exec_id="e002-b")
    buy = fill(2, "Buy", "1", "102", order=C, exec_id="e002-a")
    w = run(fill(1, "Buy", "1", "100"), sell, buy)
    assert [(c.fill.exec_id, c.closed, c.entry_value) for c in w.closes] == [
        ("e002-b", N(2), N(202))
    ]


def test_the_walk_refuses_a_key_it_cannot_hold_a_fill_given_twice_and_an_empty_budget() -> None:
    with pytest.raises(ValueError, match="cpr_posidx"):
        run(idx=3)
    with pytest.raises(ValueError, match="each fill once"):
        run(fill(1, "Buy", "1", "100"), fill(1, "Buy", "1", "100"))
    for fills, flats in ((0, 1), (1, 0)):
        with pytest.raises(ValueError, match="budget"):
            WalkBudget(fills=fills, flats=flats)


def test_the_walk_keeps_every_digit_of_a_numeric_38_18_product() -> None:
    """Exact intermediates (the orchestrator's ruling): size x price keeps its 36 decimals, which
    a 28-digit context would round."""
    qty, price = "0.123456789012345678", "12345.678901234567890123"
    [close] = run(fill(1, "Buy", qty, price), fill(2, "Sell", qty, "1", closed=qty)).closes
    with localcontext(_EXACT):
        assert (
            close.entry_value
            == known(close.avg_entry) * Decimal(qty)
            == Decimal(qty) * Decimal(price)
        )


_RECORD = rest("rest/trading-closed-pnl.json")["result"]["list"][0]


def compose(closes: Sequence[WalkClose]) -> Decimal:
    """24 steps 2, 4 to 6 as the composition reads them: gross (the closed PnL its fills hold),
    plus `fee_pnl` (minus their closing shares and the opening fees they take), plus funding (0,
    none settled), quantized once `ROUND_HALF_UP` to 8 dp."""
    with localcontext(_EXACT):
        gross = total([c.fill.closed_pnl for c in closes])
        fee = -(total([c.closing_fee for c in closes]) + total([c.opening_fees for c in closes]))
        return (gross + fee + Decimal(0)).quantize(_8DP, ROUND_HALF_UP)


def test_the_worked_example_composed_from_the_walk_is_the_records_closed_pnl() -> None:
    """24 Sec.8.13: a long of 3 (entry value 3584.9255) closed by one order's 4 fills (exit value
    3541.795), every fill a taker's at 0.0006, the closed PnL each holds summing to -43.1305."""
    opens = (
        fill(1, "Buy", "1", "1194.9", fee="0.71694"), fill(2, "Buy", "1", "1195", fee="0.717"),
        fill(3, "Buy", "1", "1195.0255", fee="0.7170153"),
    )  # fmt: skip
    sells = (
        ("1", "1180.5", "0.7083", "-14.47516667"),
        ("1", "1180.6", "0.70836", "-14.37516667"),
        ("0.5", "1180.69", "0.354207", "-7.142583335"),
        ("0.5", "1180.7", "0.35421", "-7.137583325"),
    )  # fmt: skip
    closes = run(*opens, *(fill(4 + n, "Sell", q, p, fee=f, closed=q, pnl=g, order=B)
                           for n, (q, p, f, g) in enumerate(sells))).closes  # fmt: skip
    assert compose(closes) == Decimal("-47.4065323") == Decimal(_RECORD["closedPnl"])
    with localcontext(_EXACT):
        exits = total([c.closed * c.fill.exec_price for c in closes])
    size, value = total([c.closed for c in closes]), total([c.entry_value for c in closes])
    assert (size, value, exits, len(closes)) == (
        Decimal(_RECORD["qty"]), Decimal(_RECORD["cumEntryValue"]),
        Decimal(_RECORD["cumExitValue"]), int(_RECORD["fillCount"]),
    )  # fmt: skip
    with localcontext(_EXACT):
        assert (value / size).quantize(_8DP, ROUND_HALF_UP) == Decimal(_RECORD["avgEntryPrice"])
        assert (exits / size).quantize(_8DP, ROUND_HALF_UP) == Decimal(_RECORD["avgExitPrice"])


def _side(buy: bool) -> OrderSide:
    return "Buy" if buy else "Sell"


def _other(side: OrderSide) -> OrderSide:
    return _side(side == "Sell")


def _scaled(places: int, top: int) -> st.SearchStrategy[Decimal]:
    return st.integers(1, top).map(lambda n: Decimal(n).scaleb(-places))


_SIDE = st.booleans().map(_side)
_SIZE, _PRICE = _scaled(3, 10**6), _scaled(2, 10**8)  # 0.001 to 1000, 0.01 to 10^6
_FEE = st.integers(-(10**6), 10**7).map(lambda n: Decimal(n).scaleb(-6))  # a rebate or a fee
_RATE = st.integers(-2, 10).map(lambda n: Decimal(n).scaleb(-4))  # a fee rate, rebates below 0
_DIGITS = _scaled(18, 10**22)  # to 10^4, every place a numeric(38,18) column holds
_OPENS = st.lists(st.tuples(_SIZE, _PRICE, _FEE), min_size=1, max_size=5)
_CUTS = st.lists(st.integers(1, 99), max_size=5)
_ANY = st.tuples(_SIDE, _SIZE, _PRICE, _FEE, st.none() | _SIZE, st.booleans())


_Row = tuple[OrderSide, Decimal, Decimal, Decimal, Decimal | None, bool]


def _any(rows: list[_Row], first: int) -> list[WalkFill]:
    """Fills of either side, each stating a `closedSize` or none, holding a closed PnL or none."""
    return [
        fill(first + n, s, q, p, fee=f, closed=stated, pnl="0" if held else None)
        for n, (s, q, p, f, stated, held) in enumerate(rows)
    ]


def _cut(
    fills: list[WalkFill], side: OrderSide, left: Decimal, cuts: list[int], step: str
) -> Decimal:
    """Append closes of `cuts` percent of what is left, each at least `step` and less than all of
    it: what they leave."""
    with localcontext(_EXACT):
        for n, pct in enumerate(cuts, 20):
            part = (left * pct / 100).quantize(Decimal(step), ROUND_DOWN)
            if 0 < part < left:
                fills.append(fill(n, _other(side), part, "1", closed=part, order=B))
                left -= part
    return left


def _totals(w: Walk) -> tuple[Decimal, ...]:
    names = ("closed", "entry_value", "opening_fees", "closing_fee")
    return tuple(total([getattr(c, name) for c in w.closes]) for name in names)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(rows=st.lists(st.tuples(_SIDE, _SIZE, _PRICE, _FEE), min_size=1, max_size=12))
def test_property_the_sizes_closed_and_left_open_are_the_sizes_opened(
    rows: list[tuple[OrderSide, Decimal, Decimal, Decimal]],
) -> None:
    """Each size a fill moves opens or closes, read or not: the sum of `c` and the open size left
    is the size opened, which is the fills' signed sum."""
    w = run(*(fill(n, s, q, p, fee=f) for n, (s, q, p, f) in enumerate(rows, 1)))
    closed = total([c.closed for c in w.closes])
    with localcontext(_EXACT):
        opened = sum((q for _, q, _, _ in rows), Decimal(0)) - closed
        signed = sum((q if s == "Buy" else -q for s, q, _, _ in rows), Decimal(0))
    assert closed + w.open_size == opened and w.open_size == abs(signed)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(opens=_OPENS, cuts=_CUTS, side=_SIDE)
def test_property_a_partial_close_leaves_the_average_entry_as_it_was(
    opens: list[tuple[Decimal, Decimal, Decimal]], cuts: list[int], side: OrderSide
) -> None:
    """Within 1e-50 of it: each division rounds at its 80th digit, far past the 8 dp the
    composition reads."""
    fills = [fill(n, side, q, p, fee=f) for n, (q, p, f) in enumerate(opens, 1)]
    with localcontext(_EXACT):
        size = sum((q for q, _, _ in opens), Decimal(0))
        average = sum((q * p for q, p, _ in opens), Decimal(0)) / size
    _cut(fills, side, size, cuts, "0.001")
    for close in run(*fills).closes:
        with localcontext(_EXACT):
            assert abs(known(close.avg_entry) - average) <= average * Decimal("1e-50")


@settings(max_examples=150, deadline=None, derandomize=True)
@given(opens=_OPENS, qty=_SIZE, price=_PRICE, rate=_RATE, cut=st.integers(1, 999), side=_SIDE)
def test_property_splitting_a_closing_fill_changes_no_total(
    opens: list[tuple[Decimal, Decimal, Decimal]], qty: Decimal, price: Decimal, rate: Decimal,
    cut: int, side: OrderSide,
) -> None:  # fmt: skip
    """A closing fill as two fills of its time, each charged its own value at its rate: the same
    sizes close, and the entry value, opening fees and closing fees taken sum the same, once a
    last fill closes what is left."""
    other, first = _other(side), (qty * cut / 1000).quantize(Decimal("0.001"), ROUND_DOWN)
    assume(0 < first < qty)
    size, rest = total([q for q, _, _ in opens]), qty - first

    def part(q: Decimal, closed: Decimal, exec_id: str) -> WalkFill:
        with localcontext(_EXACT):
            fee = rate * q * price
        return fill(10, other, q, price, fee=fee, closed=closed, order=B, exec_id=exec_id)

    held = [fill(n, side, q, p, fee=f) for n, (q, p, f) in enumerate(opens, 1)]
    c1, left = min(first, size), abs(size - qty)
    last = side if qty > size else other  # the side that closes what is left
    tail = [fill(11, last, left, "1", closed=left, order=C)] if left else []
    whole = run(*held, part(qty, min(qty, size), "e010"), *tail)
    split = run(*held, part(first, c1, "e010-a"), part(rest, min(rest, size - c1), "e010-b"), *tail)
    assert whole.clean and split.clean and whole.open_size == split.open_size == 0
    assert _totals(whole) == _totals(split)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(before=st.lists(_ANY, max_size=6), after=st.lists(_ANY, max_size=6))
def test_property_a_confirmed_flat_walks_as_the_two_sides_walked_apart(
    before: list[_Row], after: list[_Row]
) -> None:
    """A confirmed flat drops what the walk holds and ends every span, so the fills after it
    walk as from a start there."""
    flat, first, second = at(50), _any(before, 1), _any(after, 100)
    whole = run(*first, *second, flats=(START, flat))
    one, two = run(*first), run(*second, flats=(flat,), anchor=flat + timedelta(microseconds=1))
    assert whole.closes == one.closes + two.closes
    assert (whole.open_size, whole.clean) == (two.open_size, one.clean and two.clean)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(opens=st.lists(st.tuples(_DIGITS, _DIGITS, _DIGITS), min_size=1, max_size=4), cuts=_CUTS,
       side=_SIDE)  # fmt: skip
def test_property_a_position_closed_in_full_gives_back_every_digit_it_opened_with(
    opens: list[tuple[Decimal, Decimal, Decimal]], cuts: list[int], side: OrderSide
) -> None:
    """Exact intermediates: the closes take the entry value and the opening fees to the last
    digit, and every figure is a `Decimal`."""
    fills = [fill(n, side, q, p, fee=f) for n, (q, p, f) in enumerate(opens, 1)]
    with localcontext(_EXACT):
        size = sum((q for q, _, _ in opens), Decimal(0))
        value = sum((q * p for q, p, _ in opens), Decimal(0))
        fees = sum((f for _, _, f in opens), Decimal(0))
    left = _cut(fills, side, size, cuts, "1e-18")
    w = run(*fills, fill(40, _other(side), left, "1", closed=left, order=C))
    figures = [(c.closed, c.closing_fee, c.entry_value, c.opening_fees, c.avg_entry)
               for c in w.closes]  # fmt: skip
    assert all(type(v) is Decimal for row in figures for v in row)
    taken = (total([c.closed for c in w.closes]), total([c.entry_value for c in w.closes]),
             total([c.opening_fees for c in w.closes]))  # fmt: skip
    assert taken == (size, value, fees)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(rows=st.lists(st.tuples(st.integers(1, 3), _SIDE, _SIZE), min_size=1, max_size=8),
       data=st.data())  # fmt: skip
def test_property_fills_are_walked_by_time_then_exec_id_whatever_order_they_come_in(
    rows: list[tuple[int, OrderSide, Decimal]], data: st.DataObject
) -> None:
    fills = [fill(t, s, q, "100", exec_id=f"e{k:03}") for k, (t, s, q) in enumerate(rows)]
    w = run(*fills)
    assert run(*data.draw(st.permutations(fills))) == w
