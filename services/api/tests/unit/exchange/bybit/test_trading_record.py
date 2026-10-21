"""The allow-listed record of a trading call (G-8, #2877; SR-E29-08, E29 threat model §6 item 1).

The record is the contract's `ExchangeCallRecord` without `event_id` and `at`: a parity test pins
the field sets, and every record the adapter can build, dumped, validates against the published
schema of `22-api-openapi.yaml` itself (Draft 2020-12), not only against its generated model,
which tolerates a null. It is built from the body the port sent and the parsed reply only, so
every field it states was on the wire; a value that does not fit its contract field is dropped,
never stored.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from candleviewer.api._generated.openapi_models import ExchangeCallRecord
from candleviewer.api._generated.openapi_models import ExchangeRecordFields as ContractFields
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    ExchangeRecord,
    ExchangeRecordFields,
    OrderAck,
    TradingStopRequest,
)
from candleviewer.exchange.bybit import record as rec
from candleviewer.exchange.bybit.trading import (
    BybitTradingPort,
    _amend_body,
    _cancel_all_body,
    _cancel_body,
    _create_item,
    _stop_body,
)
from tests._corpus import rest
from tests.openapi_helpers import deref
from tests.unit.exchange.bybit._trading import Venue, account, link, make_port, place, with_result

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
#: The published `ExchangeCallRecord`, every `$ref` inlined: what the store and the diagnostics
#: response must accept (22-api-openapi.yaml).
_PUBLISHED = Draft202012Validator(
    deref(_SPEC, _SPEC["components"]["schemas"]["ExchangeCallRecord"])
)
_WIRE_KEY = {contract: wire for wire, contract in rec.WIRE_NAMES.items()}
CREATED = rest("rest/trading-create-reply.json")
CANCEL = rest("rest/trading-cancel-reply.json")


def test_the_record_is_the_contracts_without_event_id_and_time() -> None:
    contract = set(ExchangeCallRecord.model_fields) - {"event_id", "at"}
    assert set(ExchangeRecord.model_fields) == contract
    assert set(ExchangeRecordFields.model_fields) == set(ContractFields.model_fields)
    assert ExchangeRecord.model_config.get("extra") == "forbid"
    assert ExchangeRecordFields.model_config.get("extra") == "forbid"
    published = _SPEC["components"]["schemas"]
    assert set(published["ExchangeCallRecord"]["properties"]) - {"event_id", "at"} == contract
    assert set(published["ExchangeRecordFields"]["properties"]) == set(
        ExchangeRecordFields.model_fields
    )


def _contract_valid(record: ExchangeRecord) -> None:
    payload = record.model_dump(mode="json") | {"event_id": 1, "at": "2026-10-21T00:00:00Z"}
    ExchangeCallRecord.model_validate(payload)
    errors = [error.message for error in _PUBLISHED.iter_errors(payload)]
    assert errors == [], errors


def test_an_unset_field_is_absent_from_a_dump_never_null() -> None:
    """The published schema types `side`, `qty`, `category`... non-nullable: a null fails it."""
    fields = ExchangeRecordFields(category="linear", symbol="BTCUSDT")
    record = ExchangeRecord(transport="rest", method="POST", request_redacted=fields)
    dumped = record.model_dump(mode="json")
    assert dumped == {
        "transport": "rest",
        "method": "POST",
        "request_redacted": {"category": "linear", "symbol": "BTCUSDT"},
    }
    assert json.loads(record.model_dump_json()) == dumped
    _contract_valid(record)


def test_a_dump_with_nulls_is_what_the_published_schema_refuses() -> None:
    """The trap the sparse dump closes: the generated model takes a null, the schema does not."""
    padded = dict.fromkeys(ExchangeRecordFields.model_fields) | {"category": "linear"}
    payload = {"event_id": 1, "at": "2026-10-21T00:00:00Z", "transport": "rest"}
    ContractFields.model_validate(padded)
    assert not _PUBLISHED.is_valid(payload | {"request_redacted": padded})


_DEC = st.decimals(min_value=0, max_value=Decimal("1e12"), places=6, allow_nan=False)
_SYMBOL = st.sampled_from(["BTCUSDT", "ETHUSDT", "1000PEPEUSDT", "ETHPERP", "BTCUSD"])


@settings(max_examples=60, deadline=None)
@given(
    qty=_DEC.filter(lambda d: d > 0),
    price=_DEC,
    stop=_DEC.filter(lambda d: d > 0),
    symbol=_SYMBOL,
    msg=st.text(max_size=3000),
    code=st.integers(min_value=-(2**31), max_value=2**31),
    latency=st.integers(min_value=-5, max_value=10**6),
)
def test_every_record_the_adapter_builds_is_a_valid_contract_record(
    qty: Decimal, price: Decimal, stop: Decimal, symbol: str, msg: str, code: int, latency: int
) -> None:
    request = place(symbol=symbol, qty=qty, price=price, stop_loss=stop)
    amend = AmendOrderRequest(
        account=account(), symbol=symbol, order_link_id=link(), qty=qty, stop_loss=stop
    )
    cancel = CancelOrderRequest(account=account(), symbol=symbol, order_link_id=link())
    stop_write = TradingStopRequest(account=account(), symbol=symbol, stop_loss=stop)
    for body in (
        {"category": "linear", **_create_item(request)},
        _amend_body(amend),
        _cancel_body(cancel),
        _cancel_all_body(symbol),
        _stop_body(stop_write),
    ):
        record = rec.record(
            method="POST",
            endpoint="/v5/order/create",
            request=rec.request_fields(body),
            response=rec.reply_fields("x" * 40, "e-1"),
            ret_code=code,
            ret_msg=msg,
            latency_ms=latency,
        )
        _contract_valid(record)
        assert record.request_redacted is not None and record.request_redacted.category == "linear"
        assert (record.request_redacted.symbol is None) is (not symbol.endswith("USDT"))
        assert record.ret_msg == (msg if len(msg) <= 2048 else None)
        assert record.response_redacted is not None
        assert record.response_redacted.order_link_id is None  # over 36: dropped, never cut


def test_a_create_record_holds_the_request_as_it_went_on_the_wire() -> None:
    """`trigger_by` is set but no trigger price is, so the wire carried neither: nor does the
    record."""
    request = place(take_profit=Decimal("65000"), trigger_by="index")
    fields = rec.request_fields({"category": "linear", **_create_item(request)})
    assert fields == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": "0.010",
        "time_in_force": "GTC",
        "order_link_id": link(),
        "reduce_only": False,
        "close_on_trigger": False,
        "position_idx": 0,
        "price": "60000",
        "take_profit": "65000",
        "tp_trigger_by": "LastPrice",
        "stop_loss": "58000",
        "sl_trigger_by": "MarkPrice",
        "tpsl_mode": "Full",
    }


@pytest.mark.parametrize(("direction", "wire"), [("rise", 1), ("fall", 2)])
def test_a_conditional_create_records_its_trigger_direction_by_name(
    direction: str, wire: int
) -> None:
    """Literal expectations, not ones derived from the map under test: `1` is rise and `2` is
    fall on the wire (24 §8.9), and the record names them so."""
    request = place(trigger_price=Decimal("59000"), trigger_direction=direction)
    body = {"category": "linear", **_create_item(request)}
    assert body["triggerDirection"] == wire
    assert rec.request_fields(body)["trigger_direction"] == direction


def test_a_wire_value_the_contract_cannot_spell_is_dropped_never_stored() -> None:
    """A value outside the closed spelling map has no contract name: left out, alone."""
    fields = rec.request_fields({"side": "Sideways", "triggerDirection": 3, "symbol": "BTCUSDT"})
    record = rec.record(
        method="POST", endpoint="/v5/order/create", request=fields, response=None,
        ret_code=0, ret_msg=None, latency_ms=1,
    )  # fmt: skip
    assert record.request_redacted == ExchangeRecordFields(symbol="BTCUSDT")


def test_a_cancel_all_record_holds_its_order_filter() -> None:
    """SR-E29-06: the filter that keeps a position's TP/SL orders is in the record, by name."""
    fields = rec.request_fields(_cancel_all_body(None))
    assert fields == {"category": "linear", "order_filter": "Order"}


async def test_a_market_create_records_no_price_and_no_stop_it_never_sent() -> None:
    venue = Venue().on("/v5/order/create", with_result(CREATED, orderLinkId=link()))
    request = place(order_type="market", price=Decimal("1"), stop_loss=None)
    ack = await make_port(venue).place_order(request)
    assert ack.record is not None and ack.record.request_redacted is not None
    recorded = ack.record.request_redacted.model_dump(mode="json")
    assert not {"price", "tpsl_mode", "sl_trigger_by", "tp_trigger_by", "trigger_by"} & set(
        recorded
    )


async def _create(port: BybitTradingPort) -> OrderAck:
    return await port.place_order(
        place(trigger_price=Decimal("59000"), trigger_by="mark", trigger_direction="fall")
    )


async def _amend(port: BybitTradingPort) -> OrderAck:
    """An `ext-` order (the transcribed reply's), amended by its exchange id alone."""
    order_id = CANCEL["result"]["orderId"]
    return await port.amend_order(
        AmendOrderRequest(
            account=account(),
            symbol="BTCUSDT",
            order_link_id=ext_key(order_id),
            exchange_order_id=order_id,
            stop_loss=Decimal("57000"),
        )
    )


async def _cancel(port: BybitTradingPort) -> OrderAck:
    return await port.cancel_order(
        CancelOrderRequest(account=account(), symbol="BTCUSDT", order_link_id=link())
    )


async def _cancel_all(port: BybitTradingPort) -> OrderAck:
    return (await port.cancel_all(account(), "BTCUSDT"))[0]


async def _stop(port: BybitTradingPort) -> OrderAck:
    return await port.set_trading_stop(
        TradingStopRequest(
            account=account(), symbol="BTCUSDT", stop_loss=Decimal("58000"), tpsl_mode="partial"
        )
    )


_SENDS: dict[str, tuple[str, Any, Any]] = {
    "create": ("/v5/order/create", with_result(CREATED, orderLinkId=link()), _create),
    "amend": ("/v5/order/amend", rest("rest/trading-amend-reply.json"), _amend),
    "cancel": ("/v5/order/cancel", with_result(CANCEL, orderLinkId=link()), _cancel),
    "cancel-all": ("/v5/order/cancel-all", rest("rest/trading-cancel-all-reply.json"), _cancel_all),
    "trading-stop": (
        "/v5/position/trading-stop",
        rest("rest/trading-trading-stop-reply.json"),
        _stop,
    ),
}


@pytest.mark.parametrize("call", sorted(_SENDS))
async def test_every_record_field_was_on_the_wire_and_every_named_key_is_recorded(
    call: str,
) -> None:
    path, reply, send = _SENDS[call]
    venue = Venue().on(path, reply)
    ack = await send(make_port(venue))
    [body] = venue.bodies()
    assert ack.record is not None and ack.record.request_redacted is not None
    recorded = ack.record.request_redacted.model_dump(mode="json")
    for name, value in recorded.items():
        wire = _WIRE_KEY[name]
        assert wire in body, name
        assert rec.request_fields({wire: body[wire]}) == {name: value}
    assert {rec.WIRE_NAMES[key] for key in body if key in rec.WIRE_NAMES} == set(recorded)
    _contract_valid(ack.record)


async def test_the_ack_carries_the_record_of_its_call_and_nothing_else() -> None:
    reply = with_result(CREATED, orderLinkId=link())
    ack = await make_port(Venue().on("/v5/order/create", reply)).place_order(place())
    record = ack.record
    assert record is not None
    assert (record.transport, record.method, record.endpoint) == (
        "rest",
        "POST",
        "/v5/order/create",
    )
    assert (record.ret_code, record.ret_msg, record.http_status) == (0, "OK", None)
    assert record.response_redacted == ExchangeRecordFields(
        order_link_id=link(), exchange_order_id=reply["result"]["orderId"]
    )
    dumped: dict[str, Any] = record.model_dump()
    assert not {"headers", "signature", "url", "query", "body"} & set(dumped)
    _contract_valid(record)


async def test_a_refusal_record_holds_the_venue_code_and_no_reply_fields() -> None:
    port = make_port(Venue().on("/v5/order/cancel", rest("rest/trading-error-110001.json")))
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id="x-1")
    record = (await port.cancel_order(request)).record
    assert record is not None and record.response_redacted is None
    assert (record.ret_code, record.ret_msg) == (110001, "Order does not exist")
    assert record.request_redacted == ExchangeRecordFields(
        category="linear", exchange_order_id="x-1", symbol="BTCUSDT"
    )
    _contract_valid(record)


def test_the_wire_names_are_the_contracts_in_full() -> None:
    """Literal: the record tests above read this map, so it is pinned here on its own."""
    assert dict(rec.WIRE_NAMES) == {
        "category": "category",
        "symbol": "symbol",
        "side": "side",
        "orderType": "order_type",
        "qty": "qty",
        "price": "price",
        "timeInForce": "time_in_force",
        "orderLinkId": "order_link_id",
        "orderId": "exchange_order_id",
        "reduceOnly": "reduce_only",
        "closeOnTrigger": "close_on_trigger",
        "positionIdx": "position_idx",
        "triggerPrice": "trigger_price",
        "triggerBy": "trigger_by",
        "triggerDirection": "trigger_direction",
        "takeProfit": "take_profit",
        "stopLoss": "stop_loss",
        "tpTriggerBy": "tp_trigger_by",
        "slTriggerBy": "sl_trigger_by",
        "tpslMode": "tpsl_mode",
        "trailingStop": "trailing_stop",
        "activePrice": "activation_price",
        "orderFilter": "order_filter",
    }


@pytest.mark.parametrize(
    ("wire", "recorded"),
    [
        ({"side": "Buy"}, {"side": "buy"}),
        ({"side": "Sell"}, {"side": "sell"}),
        ({"orderType": "Limit"}, {"order_type": "limit"}),
        ({"orderType": "Market"}, {"order_type": "market"}),
    ],
)
def test_the_record_spells_a_side_and_an_order_type_as_the_contract_does(
    wire: dict[str, str], recorded: dict[str, str]
) -> None:
    assert rec.request_fields(wire) == recorded


@pytest.mark.parametrize(
    ("message", "recorded"), [("m" * 2048, "m" * 2048), ("m" * 2049, None)], ids=["2048", "2049"]
)
def test_a_venue_message_is_kept_up_to_the_contracts_bound_and_never_cut(
    message: str, recorded: str | None
) -> None:
    record = rec.record(
        method="POST", endpoint="/v5/order/cancel", request={}, response=None,
        ret_code=110001, ret_msg=message, latency_ms=1,
    )  # fmt: skip
    assert record.ret_msg == recorded
    _contract_valid(record)


#: A message past the contract's 2048 characters, as a test input on the transcribed envelopes.
LONG = "x" * 3000


async def test_an_over_long_message_on_a_refusal_still_answers_the_ack() -> None:
    """The venue answered: the call answers too, its record without the message, never a
    validation error raised out of the port after the exchange acted."""
    refused = {**rest("rest/trading-error-110001.json"), "retMsg": LONG}
    port = make_port(Venue().on("/v5/order/cancel", refused))
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id="x-1")
    ack = await port.cancel_order(request)
    assert (ack.ok, ack.error_code) == (False, "ORDER_NOT_FOUND")
    assert ack.record is not None and ack.record.ret_msg is None
    _contract_valid(ack.record)


async def test_an_over_long_message_on_an_accepted_create_still_answers_the_ack() -> None:
    created = {**with_result(CREATED, orderLinkId=link()), "retMsg": LONG}
    ack = await make_port(Venue().on("/v5/order/create", created)).place_order(place())
    assert (ack.ok, ack.exchange_order_id) == (True, CREATED["result"]["orderId"])
    assert ack.record is not None and ack.record.ret_msg is None
    _contract_valid(ack.record)
