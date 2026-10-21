"""Creates, batches, stop writes and leverage on the trading port (G-8, #2877; 24 §8.9).

Request bodies follow §8.9's mapping; a batch pairs each request with its item and code, and an
item whose outcome is open goes to `unknown`, never `rejected` (24 §8.6 "Order creates"): 24
§14.4's item contract makes it an ack with `retryable` false and `error_code` `TRANSPORT_ERROR`
or `UNKNOWN_STATE`. A batch whose answer cannot be paired raises `AmbiguousResultError` naming
every item's id. The batch reply is the transcribed one (ruling R2) with its items' ids set to
ours, or its codes set, as the test says: test inputs on a documented shape.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import AmbiguousResultError, UnknownStateError
from candleviewer.exchange.base.models import AmendOrderRequest, TradingStopRequest
from candleviewer.exchange.bybit.trading import BybitTradingPort, _order_ref, _wall_us
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import (
    ACCOUNT_B,
    Venue,
    account,
    link,
    make_port,
    place,
    with_result,
)

BATCH = rest("rest/trading-create-batch-reply.json")
CREATED = rest("rest/trading-create-reply.json")


def _batch(links: list[str], codes: list[tuple[int, str]], ids: list[str]) -> dict[str, Any]:
    items = [
        {**BATCH["result"]["list"][0], "orderLinkId": lk, "orderId": oid}
        for lk, oid in zip(links, ids, strict=True)
    ]
    ext = {"list": [{"code": code, "msg": msg} for code, msg in codes]}
    return {**with_result(BATCH, list=items), "retExtInfo": ext}


async def test_a_create_maps_the_request_as_section_8_9_says() -> None:
    venue = Venue().on("/v5/order/create", with_result(CREATED, orderLinkId=link()))
    request = place(
        take_profit=Decimal("65000"),
        trigger_price=Decimal("59000"),
        trigger_by="mark",
        trigger_direction="fall",
        time_in_force="post_only",
    )
    ack = await make_port(venue).place_order(request)
    [body] = venue.bodies()
    assert body == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "orderType": "Limit",
        "qty": "0.010",
        "price": "60000",
        "timeInForce": "PostOnly",
        "orderLinkId": link(),
        "reduceOnly": False,
        "closeOnTrigger": False,
        "positionIdx": 0,
        "triggerPrice": "59000",
        "triggerBy": "MarkPrice",
        "triggerDirection": 2,
        "takeProfit": "65000",
        "tpTriggerBy": "LastPrice",
        "stopLoss": "58000",
        "slTriggerBy": "MarkPrice",
        "tpslMode": "Full",
    }
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (
        True,
        link(),
        CREATED["result"]["orderId"],
    )


#: Each case: request fields and the wire's spelling of them, written out here, never read from
#: the port's maps (24 §8.9). Every case keeps `place()`'s native stop (C-2.6).
WIRE_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ({"side": "buy"}, {"side": "Buy"}),
    ({"side": "sell"}, {"side": "Sell"}),
    ({"order_type": "limit"}, {"orderType": "Limit", "price": "60000"}),
    ({"order_type": "market"}, {"orderType": "Market"}),
    ({"time_in_force": "gtc"}, {"timeInForce": "GTC"}),
    ({"time_in_force": "ioc"}, {"timeInForce": "IOC"}),
    ({"time_in_force": "fok"}, {"timeInForce": "FOK"}),
    ({"time_in_force": "post_only"}, {"timeInForce": "PostOnly"}),
    (
        {"trigger_price": Decimal("59000"), "trigger_by": "last"},
        {"triggerPrice": "59000", "triggerBy": "LastPrice"},
    ),
    (
        {"trigger_price": Decimal("59000"), "trigger_by": "mark"},
        {"triggerPrice": "59000", "triggerBy": "MarkPrice"},
    ),
    (
        {"trigger_price": Decimal("59000"), "trigger_by": "index"},
        {"triggerPrice": "59000", "triggerBy": "IndexPrice"},
    ),
    ({"trigger_price": Decimal("61000"), "trigger_direction": "rise"}, {"triggerDirection": 1}),
    ({"trigger_price": Decimal("59000"), "trigger_direction": "fall"}, {"triggerDirection": 2}),
    (
        {"take_profit": Decimal("65000"), "tp_trigger_by": "last"},
        {"takeProfit": "65000", "tpTriggerBy": "LastPrice"},
    ),
    (
        {"take_profit": Decimal("65000"), "tp_trigger_by": "mark"},
        {"takeProfit": "65000", "tpTriggerBy": "MarkPrice"},
    ),
    (
        {"take_profit": Decimal("65000"), "tp_trigger_by": "index"},
        {"takeProfit": "65000", "tpTriggerBy": "IndexPrice"},
    ),
    (
        {"stop_loss": Decimal("57000"), "sl_trigger_by": "last"},
        {"stopLoss": "57000", "slTriggerBy": "LastPrice"},
    ),
    (
        {"stop_loss": Decimal("57000"), "sl_trigger_by": "mark"},
        {"stopLoss": "57000", "slTriggerBy": "MarkPrice"},
    ),
    (
        {"stop_loss": Decimal("57000"), "sl_trigger_by": "index"},
        {"stopLoss": "57000", "slTriggerBy": "IndexPrice"},
    ),
    ({"tpsl_mode": "full"}, {"tpslMode": "Full"}),
    ({"tpsl_mode": "partial"}, {"tpslMode": "Partial"}),
    ({"reduce_only": True}, {"reduceOnly": True}),
    ({"close_on_trigger": True}, {"closeOnTrigger": True}),
    ({"close_on_trigger": False}, {"closeOnTrigger": False}),
    ({"position_idx": 0}, {"positionIdx": 0}),
    ({"position_idx": 1}, {"positionIdx": 1}),
    ({"position_idx": 2}, {"positionIdx": 2}),
]
WIRE_IDS = [",".join(f"{k}={v}" for k, v in fields.items()) for fields, _ in WIRE_CASES]


@pytest.mark.parametrize(("fields", "wire"), WIRE_CASES, ids=WIRE_IDS)
async def test_a_create_spells_each_field_as_the_wire_does(
    fields: dict[str, Any], wire: dict[str, Any]
) -> None:
    """A Sell sent as a Buy, or a stop under a name the venue ignores, would be a live fault."""
    venue = Venue().on("/v5/order/create", with_result(CREATED, orderLinkId=link()))
    await make_port(venue).place_order(place(**fields))
    [body] = venue.bodies()
    assert {key: body[key] for key in wire} == wire
    assert body["stopLoss"] and body["slTriggerBy"]  # C-2.6: the native stop rides the create


@pytest.mark.parametrize(("fields", "wire"), WIRE_CASES, ids=WIRE_IDS)
async def test_every_batch_item_spells_each_field_as_the_wire_does(
    fields: dict[str, Any], wire: dict[str, Any]
) -> None:
    links = [link(seq=0), link(seq=1)]
    reply = _batch(links, [(0, "OK"), (0, "OK")], ["e-1", "e-2"])
    venue = Venue().on("/v5/order/create-batch", reply)
    await make_port(venue).place_batch([place(order_link_id=lk, **fields) for lk in links])
    [body] = venue.bodies()
    assert [{key: item[key] for key in wire} for item in body["request"]] == [wire, wire]
    assert all(item["stopLoss"] and item["slTriggerBy"] for item in body["request"])  # C-2.6


async def test_an_amend_sends_each_value_it_changes_under_its_wire_name() -> None:
    """Literal names (24 §8.9, the venue's amend): the record test reads the port's own map, so
    it could not see a renamed or dropped field."""
    reply = with_result(rest("rest/trading-amend-reply.json"), orderLinkId=link())
    venue = Venue().on("/v5/order/amend", reply)
    request = AmendOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=link(),
        qty=Decimal("0.020"),
        price=Decimal("61000"),
        trigger_price=Decimal("59000"),
        take_profit=Decimal("65000"),
        stop_loss=Decimal("58500"),
    )
    ack = await make_port(venue).amend_order(request)
    assert venue.bodies() == [
        {
            "category": "linear",
            "symbol": "BTCUSDT",
            "orderLinkId": link(),
            "qty": "0.020",
            "price": "61000",
            "triggerPrice": "59000",
            "takeProfit": "65000",
            "stopLoss": "58500",
        }
    ]
    assert (ack.ok, ack.order_link_id) == (True, link())


async def test_an_amend_of_an_attached_stop_sends_that_stop_alone_by_order_id() -> None:
    """C-2.6: moving an order's native stop names the order by its exchange id and sends the
    stop and nothing else, so no other value of the order moves with it."""
    reply = rest("rest/trading-amend-reply.json")
    order_id = reply["result"]["orderId"]
    venue = Venue().on("/v5/order/amend", reply)
    request = AmendOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=ext_key(order_id),
        exchange_order_id=order_id,
        stop_loss=Decimal("57000"),
        lane="critical",
    )
    ack = await make_port(venue).amend_order(request)
    assert venue.bodies() == [
        {"category": "linear", "symbol": "BTCUSDT", "orderId": order_id, "stopLoss": "57000"}
    ]
    assert (ack.ok, ack.exchange_order_id) == (True, order_id)


async def test_a_market_create_sends_no_price_and_no_unset_stop_fields() -> None:
    venue = Venue().on("/v5/order/create", with_result(CREATED, orderLinkId=link()))
    request = place(order_type="market", price=Decimal("1"), stop_loss=None, reduce_only=True)
    await make_port(venue).place_order(request)
    [body] = venue.bodies()
    assert not {"price", "stopLoss", "takeProfit", "tpslMode", "triggerPrice"} & set(body)
    assert (body["orderType"], body["reduceOnly"]) == ("Market", True)


async def test_a_batch_pairs_each_request_with_its_item() -> None:
    links = [link(seq=0), link(seq=1)]
    reply = _batch(links, [(0, "OK"), (0, "OK")], ["e-1", "e-2"])
    venue = Venue().on("/v5/order/create-batch", reply)

    acks = await make_port(venue).place_batch([place(order_link_id=lk) for lk in links])

    [body] = venue.bodies()
    assert body["category"] == "linear" and [i["orderLinkId"] for i in body["request"]] == links
    assert all("category" not in item for item in body["request"])
    assert [(a.ok, a.order_link_id, a.exchange_order_id) for a in acks] == [
        (True, links[0], "e-1"),
        (True, links[1], "e-2"),
    ]
    assert all(a.record is not None and a.record.endpoint == "/v5/order/create-batch" for a in acks)


#: 24 §14.4: the `error_code` of an item whose order may exist at the venue.
OPEN_ITEM_CODES = frozenset({"TRANSPORT_ERROR", "UNKNOWN_STATE"})


@pytest.mark.parametrize(
    ("code", "order_id", "error_code", "retryable"),
    [
        (110072, "", "DUPLICATE_CLIENT_ID", False),
        (10016, "", "TRANSPORT_ERROR", False),
        (10019, "", "TRANSPORT_ERROR", False),
        (110079, "", "UNKNOWN_STATE", False),
        (999999, "", "UNKNOWN_STATE", False),
        (110007, "", "INSUFFICIENT_MARGIN", False),
        (10006, "", "RATE_LIMITED", True),
        (0, "", "TRANSPORT_ERROR", False),
    ],
    ids=[
        "duplicate",
        "10016-open",
        "10019-open",
        "110079-open",
        "unmapped-open",
        "margin",
        "rate-limited",
        "accepted-without-id",
    ],
)
async def test_a_batch_items_code_reads_as_the_taxonomy_with_open_outcomes_unknown(
    code: int, order_id: str, error_code: str, retryable: bool
) -> None:
    links = [link(seq=0), link(seq=1)]
    reply = _batch(links, [(0, "OK"), (code, "item text")], ["e-1", order_id])
    acks = await make_port(Venue().on("/v5/order/create-batch", reply)).place_batch(
        [place(order_link_id=lk) for lk in links]
    )
    assert acks[0].ok
    assert (acks[1].ok, acks[1].error_code, acks[1].retryable) == (False, error_code, retryable)
    is_open = code in {10016, 10019, 110079, 999999, 0}
    assert (acks[1].error_code in OPEN_ITEM_CODES and not acks[1].retryable) is is_open


async def test_a_batch_item_accepted_without_its_order_id_is_never_ok() -> None:
    """The orchestrator's ruling 3 on #3972, for a batch: an item answered code 0 with an empty
    `orderId` is an open outcome, its ack not `ok`, with the open-outcome code and never
    retryable, so its order goes to `unknown`, never `submitted`."""
    links = [link(seq=0), link(seq=1)]
    reply = _batch(links, [(0, "OK"), (0, "OK")], ["e-1", ""])
    acks = await make_port(Venue().on("/v5/order/create-batch", reply)).place_batch(
        [place(order_link_id=lk) for lk in links]
    )
    assert [(a.ok, a.exchange_order_id) for a in acks] == [(True, "e-1"), (False, None)]
    assert (acks[1].error_code, acks[1].retryable) == ("TRANSPORT_ERROR", False)
    assert acks[1].error_code in OPEN_ITEM_CODES


async def test_the_transcribed_batch_reply_pairs_with_no_request_so_outcomes_are_open() -> None:
    """The documentation's batch is spot orders under its own ids: none of ours."""
    venue = Venue().on("/v5/order/create-batch", BATCH)
    with pytest.raises(AmbiguousResultError) as caught:
        await make_port(venue).place_batch([place(order_link_id=link(seq=n)) for n in range(2)])
    assert caught.value.order_link_id is None and caught.value.__cause__ is None
    assert caught.value.order_link_ids == (link(seq=0), link(seq=1))


async def test_a_batch_whose_send_goes_unanswered_names_every_item() -> None:
    """The REST client's own ambiguity (here a 5xx after the send) names each item's id."""
    venue = Venue().on("/v5/order/create-batch", rest("rest/error_503.json"), status=503)
    with pytest.raises(AmbiguousResultError) as caught:
        await make_port(venue).place_batch([place(order_link_id=link(seq=n)) for n in range(3)])
    assert caught.value.order_link_id is None
    assert caught.value.order_link_ids == tuple(link(seq=n) for n in range(3))
    assert len(venue.sent) == 1


async def test_a_refused_batch_refuses_every_item() -> None:
    refused = {"retCode": 10001, "retMsg": "params error"}  # the error envelope, another code
    links = [link(seq=0), link(seq=1)]
    acks = await make_port(Venue().on("/v5/order/create-batch", refused)).place_batch(
        [place(order_link_id=lk) for lk in links]
    )
    assert [(a.ok, a.order_link_id, a.error_code) for a in acks] == [
        (False, links[0], "INSTRUMENT_FILTER"),
        (False, links[1], "INSTRUMENT_FILTER"),
    ]


@pytest.mark.parametrize(
    "requests",
    [
        [],
        [place(order_link_id=link(seq=n)) for n in range(11)],
        [place(), place(account(ACCOUNT_B), order_link_id=link(ACCOUNT_B))],
        [place(order_link_id=link(seq=0)), place(order_link_id=link(seq=1), lane="critical")],
    ],
    ids=["empty", "over-max", "two-accounts", "two-lanes"],
)
async def test_a_batch_outside_its_bounds_is_refused_unsent(requests: list[Any]) -> None:
    venue = Venue()
    with pytest.raises(ValueError, match="batch"):
        await make_port(venue).place_batch(requests)
    assert venue.sent == []


async def test_a_stop_write_sends_both_sides_and_answers_with_no_order() -> None:
    venue = Venue().on("/v5/position/trading-stop", rest("rest/trading-trading-stop-reply.json"))
    request = TradingStopRequest(
        account=account(),
        symbol="BTCUSDT",
        take_profit=Decimal("65000"),
        stop_loss=Decimal("58000"),
        trailing_distance=Decimal("150"),
        active_price=Decimal("61000"),
        tpsl_mode="partial",
        position_idx=1,
    )
    ack = await make_port(venue).set_trading_stop(request)
    [body] = venue.bodies()
    assert body == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "tpslMode": "Partial",
        "positionIdx": 1,
        "takeProfit": "65000",
        "tpTriggerBy": "LastPrice",
        "stopLoss": "58000",
        "slTriggerBy": "MarkPrice",
        "trailingStop": "150",
        "activePrice": "61000",
    }
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (True, None, None)


async def test_a_stop_write_with_one_side_sends_that_side_only() -> None:
    venue = Venue().on("/v5/position/trading-stop", rest("rest/trading-trading-stop-reply.json"))
    request = TradingStopRequest(account=account(), symbol="BTCUSDT", stop_loss=Decimal("58000"))
    await make_port(venue).set_trading_stop(request)
    [body] = venue.bodies()
    assert "takeProfit" not in body and body["stopLoss"] == "58000"


async def test_a_refused_stop_write_is_a_rejection_with_no_order() -> None:
    refused = rest("rest/trading-error-110001.json")
    venue = Venue().on("/v5/position/trading-stop", refused)
    ack = await make_port(venue).set_trading_stop(
        TradingStopRequest(account=account(), symbol="BTCUSDT", stop_loss=Decimal("58000"))
    )
    assert (ack.ok, ack.order_link_id, ack.error_code) == (False, None, "ORDER_NOT_FOUND")


async def test_leverage_sets_both_sides() -> None:
    venue = Venue().on("/v5/position/set-leverage", rest("rest/trading-set-leverage-reply.json"))
    await make_port(venue).set_leverage(account(), "BTCUSDT", Decimal("5"))
    assert venue.bodies() == [
        {"category": "linear", "symbol": "BTCUSDT", "buyLeverage": "5", "sellLeverage": "5"}
    ]


@pytest.mark.parametrize(
    ("path", "write"),
    [
        (
            "/v5/position/set-leverage",
            lambda port: port.set_leverage(account(), "BTCUSDT", Decimal("5")),
        ),
        (
            "/v5/position/trading-stop",
            lambda port: port.set_trading_stop(
                TradingStopRequest(account=account(), symbol="BTCUSDT")
            ),
        ),
    ],
    ids=["set_leverage", "set_trading_stop"],
)
async def test_a_position_write_without_a_result_object_is_unknown(
    path: str, write: Callable[[BybitTradingPort], Awaitable[object]]
) -> None:
    broken = {**rest("rest/trading-set-leverage-reply.json"), "result": []}
    with pytest.raises(UnknownStateError):
        await write(make_port(Venue().on(path, broken)))


async def test_a_conditional_create_sends_only_the_trigger_fields_it_has() -> None:
    venue = Venue().on("/v5/order/create", with_result(CREATED, orderLinkId=link()))
    await make_port(venue).place_order(place(trigger_price=Decimal("59000")))
    [body] = venue.bodies()
    assert body["triggerPrice"] == "59000"
    assert not {"triggerBy", "triggerDirection"} & set(body)


async def test_a_batch_reply_that_cannot_be_read_leaves_every_outcome_open() -> None:
    unreadable = {**BATCH, "result": "not an object"}
    venue = Venue().on("/v5/order/create-batch", unreadable)
    with pytest.raises(AmbiguousResultError) as caught:
        await make_port(venue).place_batch([place()])
    assert caught.value.order_link_ids == (link(),)


def test_an_exit_with_no_way_to_name_its_order_is_refused_by_the_wire_mapping() -> None:
    assert _order_ref(link(), None) == {"orderLinkId": link()}
    assert _order_ref(ext_key("x-1"), "x-1") == {"orderId": "x-1"}
    for ref in ((None, None), (ext_key("x-1"), None)):
        with pytest.raises(ValueError, match="exchange_order_id"):
            _order_ref(*ref)


def test_the_default_clock_reads_the_wall_in_microseconds() -> None:
    assert abs(_wall_us() - time.time() * 1_000_000) < 60_000_000


@pytest.mark.parametrize(
    ("value", "wire"),
    [
        (Decimal("1E+2"), "100"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("0E-8"), "0.00000000"),
    ],
    ids=["positive-exponent", "negative-exponent", "zero-exponent"],
)
async def test_a_decimal_goes_on_the_wire_as_plain_text_never_in_exponent_form(
    value: Decimal, wire: str
) -> None:
    """Sizing code can hand over `Decimal("1E+2")`; the venue refuses exponent text, and a
    refused stop write is the costly case. Every money field of a create and a stop write goes
    out as plain decimal text."""
    venue = (
        Venue()
        .on("/v5/order/create", with_result(CREATED, orderLinkId=link()))
        .on("/v5/position/trading-stop", rest("rest/trading-trading-stop-reply.json"))
    )
    port = make_port(venue)
    await port.place_order(place(qty=value, price=value, stop_loss=value, take_profit=value))
    await port.set_trading_stop(
        TradingStopRequest(
            account=account(),
            symbol="BTCUSDT",
            stop_loss=value,
            take_profit=value,
            trailing_distance=value,
            active_price=value,
        )
    )
    create, stop = venue.bodies()
    assert [create[k] for k in ("qty", "price", "stopLoss", "takeProfit")] == [wire] * 4
    assert [stop[k] for k in ("stopLoss", "takeProfit", "trailingStop", "activePrice")] == [
        wire
    ] * 4
