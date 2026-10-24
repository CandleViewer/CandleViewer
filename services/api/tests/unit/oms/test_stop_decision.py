"""E29-T04 (#913) S3-H H2a: the complete read's decision (21 Sec.3.3.11, 24 Sec.8.8 rule 6), pure:
the request grouping, the matchers and `decide` over a `Reading`."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.base.models import Order, Position
from candleviewer.oms.ports import PositionKey
from candleviewer.oms.stop_resolution import (
    SPAN_HELD,
    TRAIL_HELD,
    EntryState,
    Reading,
    RequestDecision,
    decide,
    group_requests,
    order_matches,
)
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.oms.command_rig import ACCOUNT, LIVE_ACCOUNT, STOP, SYMBOL, T0, T0_US, position

TP = Decimal("64000")
KEY = PositionKey(ACCOUNT, SYMBOL, 0)
SECOND_US = 1_000_000
ENTRY = uuid4()


def stop_row(**over: Any) -> RecordedStopRow:
    base = RecordedStopRow(
        id=uuid4(), exchange_account_id=ACCOUNT, symbol=SYMBOL, position_idx=0,
        position_side="Buy", kind="stop_loss", source="trading_stop", order_id=None,
        tpsl_mode="Full", trigger_price=STOP, size=None, trailing_distance=None,
        trailing_active_price=None, exchange_order_id=None, status="pending",
        audit_record_id=uuid4(), actor_user_id=None, created_at=T0, answered_at=None,
        in_force_at=None, closed_at=None, released_at=None, position_marker=None,
    )  # fmt: skip
    return replace(base, **over)


def request_rows(**over: Any) -> tuple[RecordedStopRow, RecordedStopRow]:
    """One request's two rows: the stop-loss and the take-profit, one INSERT's `created_at`."""
    return stop_row(**over), stop_row(**({"kind": "take_profit", "trigger_price": TP} | over))


def entry_rows(**over: Any) -> tuple[RecordedStopRow, RecordedStopRow]:
    return request_rows(**({"source": "entry_attach", "order_id": ENTRY} | over))


def partial_rows(**over: Any) -> tuple[RecordedStopRow, RecordedStopRow]:
    return request_rows(**({"tpsl_mode": "Partial", "size": Decimal("0.010")} | over))


def tpsl_order(kind: str, trigger: Decimal, *, state: str = "untriggered", **over: Any) -> Order:
    fields: dict[str, Any] = {
        "order_link_id": "ext-tpsl-" + uuid4().hex[:12], "exchange_order_id": uuid4().hex,
        "account_id": ACCOUNT, "symbol": SYMBOL, "side": "sell", "order_type": "market",
        "qty": Decimal("0.010"), "price": None, "state": state, "filled_qty": Decimal(0),
        "leaves_qty": Decimal("0.010"), "avg_fill_price": None, "created_at": T0_US,
        "terminal_at": None, "reduce_only": True, "trigger_price": trigger, "order_kind": kind,
    }  # fmt: skip
    return Order.model_validate(fields | over)


def fired(kind: str, trigger: Decimal, **over: Any) -> Order:
    return tpsl_order(kind, trigger, state="filled", filled_qty=Decimal("0.010"), **over)


def flat() -> Position:
    return position(side=None, qty="0")


def one(
    rows: tuple[RecordedStopRow, ...],
    pos: Position | None = None,
    entry: EntryState | None = None,
    **over: Any,
) -> RequestDecision:
    reading = Reading(pos, {ENTRY: entry} if entry else {}, **over)
    (decision,) = decide(group_requests(KEY, rows), reading)
    return decision


def moves(decision: RequestDecision) -> dict[UUID, str]:
    return {row.id: move for row, move in decision.moves}


# --- grouping and matching ---------------------------------------------------------------------


def test_group_requests_one_insert_is_one_request_and_other_rows_are_dropped() -> None:
    first = request_rows()
    second = request_rows(created_at=T0 + timedelta(seconds=1))
    foreign = stop_row(exchange_account_id=LIVE_ACCOUNT)
    other_key = stop_row(position_idx=1)
    ended = stop_row(status="in_force", created_at=T0 + timedelta(seconds=2))
    rows = [second[1], foreign, first[1], other_key, second[0], ended, first[0]]
    assert [r.rows for r in group_requests(KEY, rows)] == [first, second]


def test_order_matches_only_an_order_of_the_key_since_the_request_and_a_trail_by_kind() -> None:
    row, since = stop_row(), T0_US - 5 * SECOND_US
    assert order_matches(row, tpsl_order("stop_loss", STOP), since_us=since)
    for other in (
        tpsl_order("stop_loss", STOP, position_idx=1),
        tpsl_order("stop_loss", STOP, created_at=since - 1),
        tpsl_order("stop_loss", STOP, side="buy"),
        tpsl_order("take_profit", STOP),
    ):
        assert not order_matches(row, other, since_us=since)
    trail = stop_row(trailing_distance=Decimal("150"), trailing_active_price=Decimal("61000"))
    assert order_matches(trail, tpsl_order("trailing_stop", Decimal("59850")), since_us=since)


def test_a_restore_request_is_held_for_reconciliation() -> None:
    decision = one((stop_row(source="restore"),), flat())
    assert decision.outcome == "held_for_reconciliation" and set(moves(decision).values()) == {
        "kept"
    }


# --- the decision table ------------------------------------------------------------------------


def test_a_full_stop_shown_goes_in_force_and_its_other_side_is_answered() -> None:
    sl, tp = request_rows()
    decision = one((sl, tp), position(stop_loss=STOP))
    assert decision.outcome == "in_force"
    assert moves(decision) == {sl.id: "in_force", tp.id: "answered"}


def test_a_trail_is_never_shown_by_the_trigger_it_moves_and_its_distance_holds_it() -> None:
    trail = stop_row(trailing_distance=Decimal("150"), trailing_active_price=Decimal("61000"))
    at_trigger = position(stop_loss=STOP).model_copy(
        update={"trailing_stop_distance": Decimal("90")}
    )
    assert one((trail,), at_trigger).outcome == "in_flight_resolved"
    by_distance = position(stop_loss=Decimal("59850")).model_copy(
        update={"trailing_stop_distance": Decimal("150")}
    )
    decision = one((trail,), by_distance, "filled")
    assert decision.outcome == "held_for_reconciliation" and decision.pages == ()
    assert decision.held == TRAIL_HELD
    assert "E29-T06's pass" in TRAIL_HELD and "activation price (E29-K01)" in TRAIL_HELD


def test_a_trail_whose_position_shows_no_stop_at_all_is_never_held_and_pages() -> None:
    sl, tp = entry_rows(trailing_distance=Decimal("150"), trailing_active_price=Decimal("61000"))
    tp = replace(tp, trailing_distance=None, trailing_active_price=None)
    decision = one((sl, tp), position(), "filled")
    assert decision.held is None and decision.pages == (sl.id,)
    assert moves(decision)[sl.id] == "entry_filled_stop_absent"


def test_a_partial_side_is_shown_only_by_its_bound_order_open_at_the_venue() -> None:
    sl, tp = partial_rows()
    sl = replace(sl, exchange_order_id="x-bound")
    open_now = tpsl_order("partial_stop_loss", STOP, exchange_order_id="x-bound")
    decision = one((sl, tp), position(), open_orders=(open_now,))
    assert moves(decision) == {sl.id: "in_force", tp.id: "answered"}
    assert one((sl, tp), position()).outcome == "in_flight_resolved"  # bound alone is not shown


def test_a_bound_order_that_fired_is_a_match() -> None:
    sl, tp = partial_rows(source="entry_attach", order_id=ENTRY)
    sl = replace(sl, exchange_order_id="x-bound")
    history = (fired("partial_stop_loss", STOP, exchange_order_id="x-bound"),)
    decision = one((sl, tp), position(), "filled", history=history)
    assert moves(decision)[sl.id] == "answered" and decision.pages == ()


def test_a_bound_order_ended_unfilled_is_the_stop_absent_while_open_and_a_match_once_flat() -> None:
    sl, tp = partial_rows(source="entry_attach", order_id=ENTRY)
    sl = replace(sl, exchange_order_id="x-bound")
    cancelled = tpsl_order(
        "partial_stop_loss", STOP, state="cancelled", exchange_order_id="x-bound"
    )
    decision = one((sl, tp), position(), "filled", history=(cancelled,))
    assert moves(decision)[sl.id] == "entry_filled_stop_absent" and decision.pages == (sl.id,)
    decision = one((sl, tp), flat(), "filled", history=(cancelled,))
    assert moves(decision)[sl.id] == "answered" and decision.pages == ()


def test_a_partial_order_not_materialised_answers_the_request() -> None:
    sl, tp = partial_rows()
    decision = one((sl, tp), position(), open_orders=(tpsl_order("partial_stop_loss", STOP),))
    assert decision.outcome == "answered" and set(moves(decision).values()) == {"answered"}


def test_a_full_stop_that_fired_matches_and_one_cancelled_matches_only_once_flat() -> None:
    rows = request_rows()
    assert one(rows, flat(), history=(fired("stop_loss", STOP),)).outcome == "answered"
    assert one(rows, position(), history=(fired("stop_loss", STOP),)).outcome == "answered"
    cancelled = tpsl_order("stop_loss", STOP, state="cancelled")
    assert one(rows, flat(), history=(cancelled,)).outcome == "answered"
    assert one(rows, position(), history=(cancelled,)).outcome == "in_flight_resolved"
    filled_then_cancelled = tpsl_order(
        "stop_loss", STOP, state="cancelled", filled_qty=Decimal("0.005")
    )
    assert one(rows, position(), history=(filled_then_cancelled,)).outcome == "answered"


def test_nothing_shown_voids_the_whole_request() -> None:
    sl, tp = request_rows()
    decision = one((sl, tp), position())
    assert decision.outcome == "in_flight_resolved" and decision.pages == ()
    assert moves(decision) == {sl.id: "in_flight_resolved", tp.id: "in_flight_resolved"}


def test_a_history_miss_past_the_span_is_held_only_where_it_can_hide_a_match() -> None:
    past = T0_US
    for pos in (flat(), position(side="sell")):
        decision = one(request_rows(), pos, history_from_us=past)
        assert decision.outcome == "held_for_reconciliation" and decision.held == SPAN_HELD
    assert one(request_rows(), position(), history_from_us=past).outcome == "in_flight_resolved"
    demo = one(request_rows(), position(), retention_from_us=past)  # demo, past its 7 d
    assert demo.outcome == "held_for_reconciliation" and demo.held == SPAN_HELD


def test_an_entry_still_resting_keeps_its_rows() -> None:
    decision = one(entry_rows(), flat(), "resting")
    assert decision.outcome == "entry_resting" and set(moves(decision).values()) == {"kept"}


def test_an_entry_gone_unfilled_voids_its_rows_whole() -> None:
    assert one(entry_rows(answered_at=T0), flat(), "gone").outcome == "in_flight_resolved"


def test_a_filled_entry_with_its_stop_shown_and_take_profit_absent() -> None:
    sl, tp = entry_rows(answered_at=T0)
    decision = one((sl, tp), position(stop_loss=STOP), "filled")
    assert decision.outcome == "entry_filled_stop_absent" and decision.pages == ()
    assert moves(decision) == {sl.id: "in_force", tp.id: "entry_filled_stop_absent"}


def test_a_filled_entry_with_its_stop_absent_on_an_open_position_pages() -> None:
    sl, tp = entry_rows(answered_at=T0)
    decision = one((sl, tp), position(take_profit=TP), "filled")
    assert decision.pages == (sl.id,) and decision.position_state == "open"
    assert moves(decision) == {sl.id: "entry_filled_stop_absent", tp.id: "in_force"}


def test_a_filled_entry_on_a_flat_or_reversed_position_voids_without_a_page() -> None:
    for pos in (flat(), position(side="sell")):
        decision = one(entry_rows(answered_at=T0), pos, "filled")
        assert decision.position_state == "flat" and decision.pages == ()
        assert set(moves(decision).values()) == {"entry_filled_stop_absent"}


def test_an_unanswered_entry_that_filled_gets_the_fill_case_and_its_page() -> None:
    sl, tp = entry_rows()
    decision = one((sl, tp), position(), "filled")
    assert decision.outcome == "entry_filled_stop_absent" and decision.pages == (sl.id,)


def test_a_matching_order_beats_the_fill_case() -> None:
    sl, tp = entry_rows(answered_at=T0)
    decision = one((sl, tp), flat(), "filled", history=(fired("stop_loss", STOP),))
    assert moves(decision) == {sl.id: "answered", tp.id: "entry_filled_stop_absent"}


def test_a_later_request_in_force_in_the_same_read_replaces_the_older_side() -> None:
    old_sl, old_tp = entry_rows()
    new_sl, new_tp = request_rows(
        trigger_price=Decimal("59000"), created_at=T0 + timedelta(seconds=1)
    )
    reading = Reading(position(stop_loss=Decimal("59000")), {ENTRY: "filled"})
    old, new = decide(group_requests(KEY, (old_sl, old_tp, new_sl, new_tp)), reading)
    assert moves(new) == {new_sl.id: "in_force", new_tp.id: "answered"}
    assert moves(old) == {old_sl.id: "replaced", old_tp.id: "entry_filled_stop_absent"}
    assert old.pages == ()


def test_a_later_row_already_in_force_replaces_the_older_side_with_no_void_or_page() -> None:
    sl, tp = entry_rows()
    later = stop_row(
        status="in_force", trigger_price=Decimal("59000"), created_at=T0 + timedelta(seconds=1)
    )
    decision = one((sl, tp), position(stop_loss=Decimal("59000")), "filled", in_force=(later,))
    assert moves(decision)[sl.id] == "replaced" and decision.pages == ()
    decision = one(request_rows(), position(), in_force=(later,))
    assert set(moves(decision).values()) == {"replaced", "answered"}
    earlier = replace(later, created_at=T0 - timedelta(seconds=1))
    assert one(request_rows(), position(), in_force=(earlier,)).outcome == "in_flight_resolved"


def test_an_answered_request_the_read_only_matched_is_held_for_reconciliation() -> None:
    decision = one(request_rows(answered_at=T0), flat(), history=(fired("stop_loss", STOP),))
    assert decision.outcome == "held_for_reconciliation"


# --- invariants --------------------------------------------------------------------------------

TRIGGERS = st.sampled_from([STOP, Decimal("59000"), TP])


@given(
    mode=st.sampled_from(["Full", "Partial"]),
    trigger=TRIGGERS,
    shown=st.one_of(st.none(), TRIGGERS),
    side=st.sampled_from(["buy", "sell", None]),
    order_state=st.sampled_from([None, "untriggered", "filled", "cancelled"]),
    entry=st.sampled_from([None, "resting", "filled", "gone"]),
    answered=st.booleans(),
)
def test_property_a_request_is_voided_whole_unless_filled_and_pages_only_an_open_stop_loss(
    mode: Literal["Full", "Partial"],
    trigger: Decimal,
    shown: Decimal | None,
    side: Literal["buy", "sell"] | None,
    order_state: str | None,
    entry: EntryState | None,
    answered: bool,
) -> None:
    sized = {"tpsl_mode": mode, "size": Decimal("0.010") if mode == "Partial" else None}
    rows = entry_rows(trigger_price=trigger, answered_at=T0 if answered else None, **sized)
    kind = "partial_stop_loss" if mode == "Partial" else "stop_loss"
    orders = () if order_state is None else (tpsl_order(kind, trigger, state=order_state),)
    pos = position(side=side, qty="0.010" if side else "0", stop_loss=shown)
    split = {"open_orders": orders} if order_state == "untriggered" else {"history": orders}
    decision = one(rows, pos, entry, **split)
    made = set(moves(decision).values())
    if entry != "filled":
        assert "entry_filled_stop_absent" not in made
        assert "in_flight_resolved" not in made or made == {"in_flight_resolved"}
    for row, move in decision.moves:
        paged = row.id in decision.pages
        assert paged == (
            move == "entry_filled_stop_absent" and row.kind == "stop_loss" and side == "buy"
        )
