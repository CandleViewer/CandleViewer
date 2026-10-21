"""The allow-listed record of a trading call (G-8, #2877; SR-E29-08, E29 threat model §6 item 1).

The record is the contract's `ExchangeCallRecord` without `event_id` and `at`: a parity test pins
the field sets, and every record the adapter can build validates as the contract's. It is built
from the neutral request and the parsed reply only; a value that does not fit its contract field
is dropped, never stored.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api._generated.openapi_models import ExchangeCallRecord
from candleviewer.api._generated.openapi_models import ExchangeRecordFields as ContractFields
from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    ExchangeRecord,
    ExchangeRecordFields,
    TradingStopRequest,
)
from candleviewer.exchange.bybit import record as rec
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import Venue, account, link, make_port, place, with_result


def test_the_record_is_the_contracts_without_event_id_and_time() -> None:
    contract = set(ExchangeCallRecord.model_fields) - {"event_id", "at"}
    assert set(ExchangeRecord.model_fields) == contract
    assert set(ExchangeRecordFields.model_fields) == set(ContractFields.model_fields)
    assert ExchangeRecord.model_config.get("extra") == "forbid"
    assert ExchangeRecordFields.model_config.get("extra") == "forbid"


def _contract_valid(record: ExchangeRecord) -> None:
    payload = record.model_dump(mode="json") | {"event_id": 1, "at": "2026-10-21T00:00:00Z"}
    ExchangeCallRecord.model_validate(payload)


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
    for fields in (
        rec.create_fields(request),
        rec.amend_fields(amend),
        rec.cancel_fields(
            CancelOrderRequest(account=account(), symbol=symbol, order_link_id=link())
        ),
        rec.cancel_all_fields(symbol, "Order"),
        rec.trading_stop_fields(
            TradingStopRequest(account=account(), symbol=symbol, stop_loss=stop)
        ),
    ):
        record = rec.record(
            method="POST",
            endpoint="/v5/order/create",
            request=fields,
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


def test_a_create_record_holds_the_request_as_the_contract_names_it() -> None:
    fields = rec.create_fields(place(take_profit=Decimal("65000"), trigger_by="index"))
    assert fields == {
        "category": "linear",
        "order_link_id": link(),
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": "0.010",
        "price": "60000",
        "time_in_force": "GTC",
        "reduce_only": False,
        "close_on_trigger": False,
        "position_idx": 0,
        "trigger_price": None,
        "trigger_by": "IndexPrice",
        "trigger_direction": None,
        "take_profit": "65000",
        "stop_loss": "58000",
        "tp_trigger_by": "LastPrice",
        "sl_trigger_by": "MarkPrice",
        "tpsl_mode": "Full",
    }


async def test_the_ack_carries_the_record_of_its_call_and_nothing_else() -> None:
    reply = with_result(rest("rest/trading-create-reply.json"), orderLinkId=link())
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
