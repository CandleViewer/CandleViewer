"""The private stream's rows as B1 events (E29-T05 #848, S3a; 24 Sec.8.12).

Each row is derived in-test from #4135's docs-transcribed frames through the adapter's own parser
(`tests/unit/exchange/bybit/_private.py`): a derived row is a test input, never a venue fact
(C-13.5). No network.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, get_args

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from candleviewer.exchange.base.models import Execution, Order, PrivateEvent
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.oms import push_mapping as pm
from candleviewer.oms.order_machine import PUSH_EVENTS
from candleviewer.oms.ports import PositionKey, ProtectionReading
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.exchange.bybit._private import linear_order, push, raw, row, usdt_wallet
from tests.unit.exchange.bybit._trading import ACCOUNT_A, NOW_US, account, link

#: The paired row's ids, unlike the push's own, so the tests prove the row's are the ones used.
ROW_ID = uuid.UUID(int=7)
ROW_LINK = link(seq=1)
XID = "9aac161b-8ed6-450d-9cab-c5cc67c21784"  # the transcribed fill's order
SCHEMA = {name: Draft202012Validator(schema) for name, schema in b01.SCHEMAS.items()}
#: A derived open short with no stop (the venue sends a stop of "0" for none).
OPEN = {"side": "Sell", "size": "0.5", "entryPrice": "28000", "stopLoss": "0"}
#: Derived order rows: (status, time in force) and the event the paired row takes.
ORDER_ROWS = [
    ("New", "GTC", None), ("Untriggered", "GTC", None), ("PartiallyFilled", "GTC", None),
    ("Filled", "GTC", None), ("Filled", "IOC", None),
    ("Triggered", "GTC", "TRIGGERED"),
    ("Cancelled", "GTC", "REMOTE_CANCELLED"), ("Cancelled", "PostOnly", "REMOTE_CANCELLED"),
    ("Cancelled", "RPI", "REMOTE_CANCELLED"),
    ("PartiallyFilledCanceled", "GTC", "REMOTE_CANCELLED"),
    ("Deactivated", "GTC", "REMOTE_CANCELLED"), ("Deactivated", "IOC", "REMOTE_CANCELLED"),
    ("Rejected", "FOK", "REMOTE_CANCELLED"),
    ("Cancelled", "IOC", "EXPIRE"), ("Cancelled", "FOK", "EXPIRE"),
    ("PartiallyFilledCanceled", "IOC", "EXPIRE"), ("PartiallyFilledCanceled", "FOK", "EXPIRE"),
]  # fmt: skip


def _events(frame: str) -> tuple[PrivateEvent, ...]:
    pushed = pp.classify(frame)
    assert isinstance(pushed, pp.Push)
    return pp.read_push(pushed, account(), now_us=NOW_US)


def _one(frame: str) -> PrivateEvent:
    [event] = _events(frame)
    return event


def _order(**values: Any) -> PrivateEvent:
    """A derived linear order push: the documented row with `values` changed."""
    return _one(push("order", linear_order(**values)))


def _position(**values: Any) -> pm.Route:
    return pm.route(_one(push("position", row("position") | values)))


def _as[T: BaseModel](event: PrivateEvent, kind: type[T]) -> T:
    assert isinstance(event.payload, kind)
    return event.payload


@pytest.mark.parametrize(("status", "tif", "event"), ORDER_ROWS)
def test_route_order_row_sends_the_event_its_status_and_time_in_force_name(
    status: str, tif: str, event: Any
) -> None:
    """Derived: every status the adapter reads, with the times in force that decide its end."""
    pushed = _order(orderStatus=status, timeInForce=tif)
    assert pm.route(pushed) == pm.ForPairing(_as(pushed, Order), event)


def test_order_status_events_cover_exactly_the_statuses_the_adapter_reads() -> None:
    """Derived: one order row per status the adapter's row model admits."""
    statuses = get_args(tp.OrderRow.model_fields["orderStatus"].annotation)
    read = {_as(_order(orderStatus=s, timeInForce="GTC"), Order).state for s in statuses}
    assert read == set(pm.ORDER_STATUS_EVENTS)


def test_route_order_status_outside_the_table_is_paired_unmapped_with_no_event() -> None:
    """Derived: a parsed order given a status the adapter's row model would refuse."""
    pushed = _order()
    odd = _as(pushed, Order).model_copy(update={"state": "suspended"})
    routed = pm.route(pushed.model_copy(update={"payload": odd}))
    assert routed == pm.ForPairing(odd, None, unmapped=True)


def test_order_event_status_outside_the_table_raises_naming_no_value() -> None:
    """Derived: as above."""
    odd = _as(_order(), Order).model_copy(update={"state": "suspended"})
    with pytest.raises(ValueError, match="does not map") as caught:
        pm.order_event(odd)
    assert "suspended" not in str(caught.value)


def test_push_payload_carries_the_rows_link_status_cumulative_fill_and_the_venue_time() -> None:
    """Derived: a cancelled order with a part fill. Its time is the venue's own (1672364262457),
    not the frame's creation time (Q4)."""
    pushed = _order(orderStatus="Cancelled", timeInForce="GTC", cumExecQty="0.4")
    order = _as(pushed, Order)
    assert pm.push_payload(order, order_link_id=ROW_LINK, ts_event=pushed.ts_event) == {
        "exchange_order_id": "5cf98598-39a7-459e-97bf-76ca765ee020",
        "order_link_id": ROW_LINK,
        "order_status": "cancelled",
        "cum_exec_qty": "0.4",
        "updated_time": 1672364262457,
    }


@pytest.mark.parametrize(("updated_at", "expected"), [(None, 1672364262474), (0, 0)])
def test_push_payload_only_an_order_with_no_venue_time_takes_the_pushs_creation_time(
    updated_at: int | None, expected: int
) -> None:
    """Derived: the same order without a venue time. The fallback is strictly `updated_at is
    None`: an epoch time is still the venue's."""
    pushed = _order(orderStatus="Cancelled", timeInForce="GTC")
    order = _as(pushed, Order).model_copy(update={"updated_at": updated_at})
    payload = pm.push_payload(order, order_link_id=ROW_LINK, ts_event=pushed.ts_event)
    assert payload["updated_time"] == expected


@pytest.mark.parametrize(
    ("status", "tif", "name"),
    [("Triggered", "GTC", "TRIGGERED"), ("Cancelled", "IOC", "EXPIRE"),
     ("Cancelled", "GTC", "REMOTE_CANCELLED")],
)  # fmt: skip
def test_push_payload_each_order_row_event_passes_b1s_closed_schema(
    status: str, tif: str, name: str
) -> None:
    """Derived: one row of each event an order row sends."""
    pushed = _order(orderStatus=status, timeInForce=tif)
    routed = pm.route(pushed)
    assert isinstance(routed, pm.ForPairing) and routed.event == name
    payload = pm.push_payload(_as(pushed, Order), order_link_id=ROW_LINK, ts_event=pushed.ts_event)
    SCHEMA[name].validate(payload)


def test_route_trade_execution_is_paired_for_an_exec() -> None:
    pushed = _one(raw("execution"))
    assert pm.route(pushed) == pm.ForPairing(_as(pushed, Execution), "EXEC")


def test_exec_payload_carries_the_rows_ids_and_the_fill_exactly() -> None:
    fill = _as(_one(raw("execution")), Execution)
    assert pm.exec_payload(fill, order_id=ROW_ID, order_link_id=ROW_LINK) == {
        "exec_id": "0ab1bdf7-4219-438b-b30a-32ec863018f7", "exchange_order_id": XID,
        "order_id": str(ROW_ID), "order_link_id": ROW_LINK, "account_id": str(ACCOUNT_A),
        "symbol": "BTCUSDT", "side": "sell", "qty": "0.5", "price": "95900.1",
        "fee": "26.3725275", "fee_rate": "0.00055", "fee_currency": "USDT", "closed_pnl": None,
        "exec_type": "trade", "is_maker": False, "ts_exec": 1746270400353000,
        "ts_ingest": NOW_US, "seq": 140612148849382,
    }  # fmt: skip


def test_exec_payload_passes_b1s_exec_schema_and_names_the_rows_pairing_keys() -> None:
    """Derived: the documented fill with a closed PnL, which no adapter row carries yet."""
    fill = _as(_one(raw("execution")), Execution)
    fill = fill.model_copy(update={"closed_pnl": Decimal("-1.50")})
    payload = pm.exec_payload(fill, order_id=ROW_ID, order_link_id=ROW_LINK)
    SCHEMA["EXEC"].validate(payload)
    assert payload["closed_pnl"] == "-1.5"
    assert {key: payload[key] for key in b01.PAIRING} == {
        "exchange_order_id": XID, "order_id": str(ROW_ID), "order_link_id": ROW_LINK,
        "account_id": str(ACCOUNT_A), "symbol": "BTCUSDT", "side": "sell",
    }  # fmt: skip


def test_payloads_pass_every_id_through_unsanitised_for_b1_to_judge() -> None:
    """Derived: ids with a leading or trailing space and a control character. The mapping
    sanitises nothing (OM-T04), so B1's `text_id` judges exactly what the venue sent."""
    odd = " 0ab1bdf7-4219\u0001 "
    fill = _as(_one(raw("execution")), Execution).model_copy(
        update={"exec_id": odd, "exchange_order_id": odd}
    )
    paid = pm.exec_payload(fill, order_id=ROW_ID, order_link_id=odd)
    assert (paid["exec_id"], paid["exchange_order_id"], paid["order_link_id"]) == (odd, odd, odd)
    pushed = _order(orderStatus="Cancelled", timeInForce="GTC")
    order = _as(pushed, Order).model_copy(update={"exchange_order_id": odd})
    sent = pm.push_payload(order, order_link_id=odd, ts_event=pushed.ts_event)
    assert (sent["exchange_order_id"], sent["order_link_id"]) == (odd, odd)


def test_exec_payload_empty_fee_currency_is_left_out() -> None:
    """Derived: B1 keeps no empty text, and the step writer stores USDT for none."""
    fill = _as(_one(push("execution", row("execution") | {"feeCurrency": ""})), Execution)
    payload = pm.exec_payload(fill, order_id=ROW_ID, order_link_id=ROW_LINK)
    assert "fee_currency" not in payload
    SCHEMA["EXEC"].validate(payload)


@pytest.mark.parametrize(
    ("kind", "reason"),
    [("AdlTrade", "not_a_trade"), ("BustTrade", "not_a_trade"), ("Settle", "not_a_trade"),
     ("SessionSettlePnl", "not_a_trade"), ("fast", "fast_execution"), ("wallet", "wallet")],
)  # fmt: skip
def test_route_row_b1_takes_nothing_from_names_why(kind: str, reason: Any) -> None:
    """Derived: each non-trade type from the documented fill, and a USDT wallet row; the fast
    fill is as transcribed."""
    frames = {"fast": raw("execution-fast"), "wallet": push("wallet", usdt_wallet())}
    frame = frames.get(kind) or push("execution", row("execution") | {"execType": kind})
    assert pm.route(_one(frame)) == pm.NoB1Event(reason)


def test_route_flat_position_reads_observed_with_no_stop() -> None:
    """C-2.6: a close never pages."""
    assert pm.route(_one(raw("position"))) == pm.ForProtection(
        PositionKey(ACCOUNT_A, "BTCUSDT", 2),
        ProtectionReading("SL_OBSERVED", 1697682317038, None, Decimal("0")),
    )


@pytest.mark.parametrize(
    ("stop", "event", "kept"), [("0", "SL_LOST", None), ("29000", "SL_OBSERVED", Decimal("29000"))]
)
def test_route_open_position_reads_lost_exactly_when_it_has_no_stop(
    stop: str, event: str, kept: Decimal | None
) -> None:
    """C-2.6: a naked position is read as one. Derived: an open short, with and without a stop."""
    routed = _position(**OPEN | {"stopLoss": stop})
    assert isinstance(routed, pm.ForProtection)
    reading = routed.reading
    assert (reading.event, reading.stop_loss, reading.size) == (event, kept, Decimal("0.5"))


@pytest.mark.parametrize(
    ("over", "stop", "size"),
    [({}, None, "0"), (OPEN, None, "0.5"), (OPEN | {"stopLoss": "29000"}, "29000", "0.5")],
    ids=["flat", "lost", "observed"],
)
def test_reading_payload_is_the_readings_exact_dict_and_passes_b1s_schema(
    over: dict[str, str], stop: str | None, size: str
) -> None:
    """Derived: a flat row (as transcribed), an open row with no stop and one with a stop. B1's
    reading schemas require no key, so the exact dict is what pins the stop and the size."""
    routed = _position(**over)
    assert isinstance(routed, pm.ForProtection)
    payload = pm.reading_payload(routed.reading)
    SCHEMA[routed.reading.event].validate(payload)
    assert payload == {"updated_time": 1697682317038, "stop_loss": stop, "size": size}  # ms


def test_route_payload_of_no_known_kind_is_refused_not_read_as_a_wallet_row() -> None:
    """Derived: a payload past `PrivateEvent`'s validator (built unvalidated) is a defect."""
    event = _one(push("wallet", usdt_wallet())).model_copy(update={"payload": object()})
    with pytest.raises(AssertionError):
        pm.route(event)


def test_route_three_fills_in_one_message_are_three_execs_in_row_order() -> None:
    """Derived: three fills of the documented order, distinct in id, sequence and quantity."""
    changes = [{"execId": f"e{n}", "seq": n, "execQty": f"0.{n}"} for n in (1, 2, 3)]
    events = _events(push("execution", *(row("execution") | c for c in changes)))
    fills = [_as(e, Execution) for e in events]
    assert [pm.route(e) for e in events] == [pm.ForPairing(f, "EXEC") for f in fills]
    payloads = [pm.exec_payload(f, order_id=ROW_ID, order_link_id=ROW_LINK) for f in fills]
    assert [p["exec_id"] for p in payloads] == ["e1", "e2", "e3"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("12345678901234567890.123456789012345678", "12345678901234567890.123456789012345678"),
     ("0.00010", "0.0001"), ("1E+2", "100"), ("-0", "0"), ("0E-10", "0"), ("-0.5", "-0.5")],
)  # fmt: skip
def test_money_text_is_exact_fixed_point_with_no_trailing_zero(text: str, expected: str) -> None:
    assert pm.money_text(Decimal(text)) == expected


def test_stream_events_are_push_events_the_facade_takes() -> None:
    assert set(get_args(pm.StreamEvent.__value__)) <= PUSH_EVENTS
