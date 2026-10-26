"""Which row takes a private-stream push (E29-T05 #848, S3b; 24-internal-schemas.md Sec.8.12).

Every order and fill here is derived in-test from #4135's transcribed frames, through the adapter's
own parser (`tests/unit/exchange/bybit/_private.py`): a derived row is a test input, never a venue
fact (C-13.5), and E29-K01 records the venue's own TP/SL, status and trail rows. No network.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, get_args
from uuid import UUID

import pytest

from candleviewer.exchange.base.models import Execution, FastExecution, Order
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.oms import pairing as pg
from candleviewer.storage.repositories.orders import UNFINISHED_STATES, OrderRow, OrderState
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.exchange.bybit._private import linear_order, push, raw, row
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, NOW_US, account, link

XID = "9aac161b-8ed6-450d-9cab-c5cc67c21784"  # the transcribed fill's order
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
F = pg.NoAnswer.FAILED
type Push = Order | Execution
#: A Partial-mode stop-loss order of a long (a sell) at 94000; `_record()` is its record.
STOP = {
    "stopOrderType": "PartialStopLoss", "tpslMode": "Partial", "triggerPrice": "94000",
    "qty": "0.5", "side": "Sell", "reduceOnly": True, "orderStatus": "Untriggered",
    "timeInForce": "GTC",
}  # fmt: skip


def _read[T](kind: type[T], frame: str) -> T:
    pushed = pp.classify(frame)
    assert isinstance(pushed, pp.Push)
    [event] = pp.read_push(pushed, account(), now_us=NOW_US)
    assert isinstance(event.payload, kind)
    return event.payload


def _order(**values: Any) -> Order:
    return _read(Order, push("order", linear_order(**values)))


def _fill(**values: Any) -> Execution:
    return _read(Execution, push("execution", row("execution") | values))


def _row(**over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    values |= {"id": UUID(int=1), "exchange_account_id": ACCOUNT_A, "order_link_id": link()}
    return OrderRow(**(values | {"state": "accepted", "exchange_order_id": XID} | over))


def _record(**over: Any) -> RecordedStopRow:
    values: dict[str, Any] = {f.name: None for f in fields(RecordedStopRow)}
    values |= {"id": UUID(int=1), "exchange_account_id": ACCOUNT_A, "created_at": T0}
    values |= {"symbol": "BTCUSDT", "position_idx": 0, "position_side": "Buy", "status": "pending"}
    values |= {"kind": "stop_loss", "tpsl_mode": "Partial", "trigger_price": Decimal(94000)}
    return RecordedStopRow(**(values | {"size": Decimal("0.5")} | over))


def _none(**read: Any) -> pg.Reads:  # steps 1 and 2 found nothing
    return pg.Reads(bound=None, named=None, **read)


FILL = _fill()  # the transcribed fill: a foreign one, its order link id empty
READ = _order(orderId=XID, **STOP)  # its order as a read returns it
#: A fill and an order push, each under one of our order link ids: both reach steps 1 and 2.
OURS = [_fill(orderLinkId=link()), _order(orderId=XID, orderLinkId=link())]


def test_pair_reads_in_the_contracts_order() -> None:
    """Derived: a fill, then an order push; each read is asked once the steps before found none."""
    steps = [pg.Reads(), pg.Reads(bound=None), _none(), _none(order=READ)]
    assert [pg.pair(FILL, s) for s in steps] == [
        pg.NeedBound(XID), pg.NeedNamed(FILL.order_link_id), pg.NeedOrder(XID),
        pg.NeedStops("BTCUSDT", 0),
    ]  # fmt: skip
    assert [pg.pair(READ, s) for s in steps[:3]] == [
        pg.NeedBound(XID), pg.NeedNamed(READ.order_link_id), pg.NeedStops("BTCUSDT", 0),
    ]  # fmt: skip


@pytest.mark.parametrize("push", OURS, ids=["fill", "order"])
@pytest.mark.parametrize("state", get_args(OrderState))
def test_pair_bound_row_takes_the_push_in_any_state(push: Push, state: OrderState) -> None:
    """Derived: a final row's fill still pairs, as the facade's hand-off of an evicted row needs."""
    bound = _row(state=state)
    assert pg.pair(push, pg.Reads(bound=bound)) == pg.ToRow(bound)


def test_pair_bound_row_wins_over_the_row_its_link_names() -> None:
    """Derived: a fill under one of our order link ids, which an unbound row has too."""
    bound, named = _row(), _row(id=UUID(int=2), exchange_order_id=None, state="submitted")
    assert pg.pair(_fill(orderLinkId=link()), pg.Reads(bound, named)) == pg.ToRow(bound)


@pytest.mark.parametrize("push", OURS, ids=["fill", "order"])
@pytest.mark.parametrize("state", ["pending_submit", "submitted", "unknown", "quarantined"])
def test_pair_unbound_live_row_its_link_names_waits_for_its_bind(push: Push, state: str) -> None:
    """Derived: a push under one of our order link ids, whose row has no exchange order id yet."""
    named = _row(state=state, exchange_order_id=None)
    assert pg.pair(push, pg.Reads(None, named)) == pg.WaitOnRow(named)


@pytest.mark.parametrize(
    "over", [{"state": "held"}, {"state": "filled"}, {"exchange_order_id": "other"}], ids=str
)
def test_pair_named_row_held_final_or_bound_is_passed_over(over: dict[str, Any]) -> None:
    """Derived: the row a fill's order link id names is held, final, or bound to another order."""
    named = _row(**({"exchange_order_id": None} | over))
    assert pg.pair(_fill(orderLinkId=link()), pg.Reads(None, named)) == pg.NeedOrder(XID)


@pytest.mark.parametrize("push", OURS, ids=["fill", "order"])
def test_pair_named_row_bound_to_the_push_since_step_1_takes_it(push: Push) -> None:
    """Derived: its bind landed between the two reads, so it is the push's row (rule 7)."""
    assert pg.pair(push, pg.Reads(None, _row())) == pg.ToRow(_row())


def test_pair_failed_or_cut_short_read_decides_nothing() -> None:
    """Derived: the bound's timeout reads as a failure, at whichever step it cut in."""
    for reads in (pg.Reads(bound=F), pg.Reads(None, F), _none(order=F), _none(order=READ, stops=F)):
        assert pg.pair(FILL, reads) == pg.Undecided(empty_read=False)


def test_pair_fills_order_read_finding_none_is_undecided_as_an_empty_read() -> None:
    """Derived: a completed read of the fill's order that found none is kept, `empty_read` true."""
    assert pg.pair(FILL, _none(order=None)) == pg.Undecided(empty_read=True)


@pytest.mark.parametrize("placed", [False, True])
def test_pair_push_no_row_or_record_takes_has_no_intent_keyed_by_its_own_id(placed: bool) -> None:
    """Derived: a plain order and a fill of it; `exchange_placed` is set in-test."""
    order = _order().model_copy(update={"exchange_placed": placed})
    fill = _fill(orderId=order.exchange_order_id)
    assert pg.pair(order, _none()) == pg.NoIntent("order", order.exchange_order_id, placed)
    assert pg.pair(fill, _none(order=order)) == pg.NoIntent("execution", fill.exec_id, placed)


def test_pair_stop_claim_matching_a_live_record_goes_to_that_record() -> None:
    """Derived: each kind and mode; a short's `in_force` stop, which a buy order closes; and a fired
    (filled) Full-mode stop's order of another size: no size, no status."""
    full, rec = {"stopOrderType": "StopLoss", "tpslMode": "Full"}, {"tpsl_mode": "Full"}
    cases = [
        ({}, {}),  # a Partial-mode stop-loss of a long, at the record's size
        (full | {"qty": "0.7", "orderStatus": "Filled"}, rec),  # a fired Full-mode stop's order
        (full | {"side": "Buy"}, rec | {"position_side": "Sell", "status": "in_force"}),
        ({"stopOrderType": "PartialTakeProfit"}, {"kind": "take_profit"}),
        ({"stopOrderType": "TakeProfit", "tpslMode": "Full"}, rec | {"kind": "take_profit"}),
    ]
    for over, record in cases:
        stop, recorded = _order(**(STOP | over)), _record(**record)
        assert pg.pair(stop, _none(stops=(recorded,))) == pg.ToRecordedStop(recorded, stop)


def test_pair_fill_of_a_stop_order_matching_a_record_goes_to_that_record() -> None:
    """Derived: the fill's order, read by its exchange order id, is the record's stop."""
    recorded = _record()
    assert pg.pair(FILL, _none(order=READ, stops=(recorded,))) == pg.ToRecordedStop(recorded, READ)


CREATED = datetime.fromtimestamp(READ.created_at / 1_000_000, UTC)  # the venue created `READ`


@pytest.mark.parametrize("push", [READ, FILL], ids=["order", "fill"])
@pytest.mark.parametrize(
    "recorded", [CREATED, CREATED + pg.ATTACH_SKEW], ids=["before", "within_skew"]
)
def test_pair_entrys_attach_first_binds_its_stop_created_at_the_entrys_fill(
    push: Push, recorded: datetime
) -> None:
    """The S7b ruling, legitimate case: an entry's attached stop arrives as a new order once the
    entry fills, after its record is written ahead, so the venue created it after the record (or
    within `ATTACH_SKEW` of the two clocks): its first push, or its fill's read, binds it."""
    attach = _record(source="entry_attach", order_id=UUID(int=9), created_at=recorded)
    read = {} if push is READ else {"order": READ}
    assert pg.pair(push, _none(stops=(attach,), **read)) == pg.ToRecordedStop(attach, READ)


@pytest.mark.parametrize("push", [READ, FILL], ids=["order", "fill"])
def test_pair_entrys_attach_never_first_binds_an_order_changed_in_place_to_match_it(
    push: Push,
) -> None:
    """The S7b ruling, forbidden case: an order the venue held more than `ATTACH_SKEW` before the
    entry's attach was recorded can match it only by an in-place change, so it is never that
    attach's stop (as no successor is): an older record of another source it matches binds it,
    and with none it has no intent."""
    late = CREATED + pg.ATTACH_SKEW + timedelta(microseconds=1)
    attach = _record(id=UUID(int=2), source="entry_attach", order_id=UUID(int=9), created_at=late)
    older = _record(source="trading_stop", created_at=late - timedelta(hours=1))
    read = {} if push is READ else {"order": READ}
    assert pg.pair(push, _none(stops=(attach, older), **read)) == pg.ToRecordedStop(older, READ)
    none = pg.pair(push, _none(stops=(attach,), **read))
    assert isinstance(none, pg.NoIntent)
    assert none.finding == ("order" if push is READ else "execution")
    assert pg.first_bindable(READ, (attach, older)) == (older,)


def test_matching_record_misses_on_each_field_it_matches() -> None:
    """Derived: `READ` matches `_record()`; one field of either is changed."""
    misses: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({"stopOrderType": "PartialTakeProfit"}, {}),  # the kind
        ({}, {"tpsl_mode": "Full"}),  # the mode
        ({"tpslMode": "Full"}, {}),  # the order's stated mode
        ({"side": "Buy"}, {}),  # not the side that closes the position
        ({"triggerPrice": "94000.1"}, {}),
        ({"qty": "0.4"}, {}),  # the Partial size
        ({"stopOrderType": "TrailingStop"}, {}),  # a trailing order never matches (Q3)
        ({}, {"trailing_distance": Decimal(100)}),  # nor a trailing record
        ({}, {"exchange_order_id": "other"}),  # bound
        ({}, {"released_at": T0}),
        ({}, {"status": "ended"}),  # not live
    ]
    for order, record in misses:
        assert pg.matching_record(_order(**(STOP | order)), [_record(**record)]) is None


def test_matching_record_latest_of_several_binds_never_two() -> None:
    """Derived: of two matches the later by creation time binds, a tie going to the greater id."""
    old, new = _record(id=UUID(int=2)), _record(id=UUID(int=1), created_at=T0.replace(second=1))
    tied = [_record(id=UUID(int=3)), _record(id=UUID(int=4))]
    assert pg.matching_record(READ, [old, new]) == new
    assert pg.matching_record(READ, tied) == pg.matching_record(READ, tied[::-1]) == tied[1]


def test_pair_foreign_reduce_only_fill_beside_a_live_record_has_no_intent() -> None:
    """SR-E29-03, derived: a plain reduce-only sell of the long's symbol is no stop claim, so the
    fill's own symbol, side and direction pair nothing beside a live Full-mode stop-loss record."""
    reads = _none(order=_order(orderId=XID, reduceOnly=True), stops=(_record(tpsl_mode="Full"),))
    assert pg.pair(FILL, reads) == pg.NoIntent("execution", FILL.exec_id, False)


def test_pair_stop_claim_no_live_record_matches_has_no_intent() -> None:
    """Derived: a foreign stop, and the accepted residual (Q3): `Order` carries no trail, so a fired
    native trail the OMS recorded reads as no OMS intent until E29-K01 gives `Order` the trail."""
    trail = _order(**(STOP | {"stopOrderType": "TrailingStop"}))
    assert pg.pair(trail, _none()) == pg.NeedStops("BTCUSDT", 0)  # still a claim
    for stops in ((), (_record(trailing_distance=Decimal(100)),)):
        assert pg.pair(trail, _none(stops=stops)) == pg.NoIntent(
            "order", trail.exchange_order_id, False
        )


def _refusals() -> list[Any]:
    """Every read a defective store could answer wrongly, under each push kind that reaches it."""
    other, mine = {"exchange_account_id": ACCOUNT_B}, link()
    keys: tuple[dict[str, Any], ...] = ({"position_idx": 1}, {"symbol": "ETHUSDT"}, other)
    both = {
        "bound-other-account": pg.Reads(bound=_row(**other)),
        "bound-other-order": pg.Reads(bound=_row(exchange_order_id="other")),
        "named-other-account-unbound": pg.Reads(
            None, _row(**other, order_link_id=mine, exchange_order_id=None)
        ),
        "named-other-account-bound": pg.Reads(None, _row(**other, order_link_id=mine)),
        "named-other-link-unbound": pg.Reads(
            None, _row(order_link_id=link(seq=9), exchange_order_id=None)
        ),
        "named-other-link-bound": pg.Reads(None, _row(order_link_id=link(seq=9))),
    }
    fills = {
        "order-other-id": _none(order=_order(orderId="other")),
        "order-other-account": _none(
            order=_order(orderId=XID).model_copy(update={"account_id": ACCOUNT_B})
        ),
        **{
            f"stops-{n}": _none(order=READ, stops=(_record(**key),))
            for n, key in zip(("idx", "symbol", "account"), keys, strict=True)
        },
    }
    cases = [pytest.param(OURS[0], r, id=f"fill-{n}") for n, r in (both | fills).items()]
    return cases + [pytest.param(OURS[1], r, id=f"order-{n}") for n, r in both.items()]


@pytest.mark.parametrize(("push", "reads"), _refusals())
def test_pair_read_answering_another_accounts_or_orders_row_is_refused(
    push: Push, reads: pg.Reads
) -> None:
    """Derived: a store or adapter defect, never paired (C-12.4), for a fill and an order push alike
    (so an ownership check special-cased to one of them dies); a fill's order and stops too."""
    with pytest.raises(pg.PairingRefused):
        pg.pair(push, reads)


def test_pair_only_an_order_or_a_trade_execution_is_paired() -> None:
    """Derived: a non-trade execution, and the transcribed fast one (no `Execution` at all)."""
    fast: Any = _read(FastExecution, raw("execution-fast"))
    for bad in (fast, _fill(execType="AdlTrade")):
        with pytest.raises(TypeError):
            pg.pair(bad, pg.Reads())


def test_takes_waiting_is_every_unfinished_state_but_held() -> None:
    """Derived: a row in each `OrderState`, none bound."""
    rows = [_row(state=s, exchange_order_id=None) for s in get_args(OrderState)]
    assert {r.state for r in rows if pg.takes_waiting(r)} == UNFINISHED_STATES - {"held"}
