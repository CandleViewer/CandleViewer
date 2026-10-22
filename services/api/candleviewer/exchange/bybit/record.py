"""The allow-listed record of one trading call (SR-E29-08, E29 threat model §6 item 1; G-8, #2877)
and of one private-stream row (G-8b, #3963; 24 §14.2 rule 13).

Built only from the JSON body the port sent and the parsed reply, field by field into the
contract's `ExchangeRecordFields` through a closed map of the wire's names: no header, signature,
`auth` frame or URL query is ever an input, so none can leave M4 in a record, and no field states
a value the wire did not carry. A body key the contract does not name (`settleCoin`) is left
out; a value that does not fit its contract field (a symbol outside USDT linear, an over-long id
or message) is dropped from the record, never stored; the store redacts the record again before
insert (E29-T01). The OMS treats it as opaque (C-2.3). A pushed row's record is built the same
way from the row's own fields alone (`push_fields`, `push_record`): no `ret_msg`, `conn_id`,
`auth` frame or URL is ever an input.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

from pydantic import ValidationError

from candleviewer.exchange.base.models import ExchangeRecord, ExchangeRecordFields

__all__ = [
    "PUSH_NAMES",
    "WIRE_NAMES",
    "push_fields",
    "push_record",
    "record",
    "reply_fields",
    "request_fields",
]

#: A request body's keys (24 §8.9) as the contract names them; any other key is never recorded.
WIRE_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
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
)
#: A pushed order, execution or fast-execution row's keys as the contract names them (24 §14.2 rule
#: 13); any other key is never recorded.
PUSH_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        **{key: WIRE_NAMES[key] for key in WIRE_NAMES if key != "orderFilter"},
        "orderStatus": "order_status",
        "cumExecQty": "filled_qty",
        "leavesQty": "remaining_qty",
        "avgPrice": "avg_fill_price",
        "rejectReason": "reject_reason",
        "execId": "exec_id",
        "execQty": "exec_qty",
        "execPrice": "exec_price",
        "execFee": "fee",
        "isMaker": "is_maker",
    }
)
#: The values the contract spells otherwise; every other value is recorded as sent.
_WIRE_VALUES: Final[Mapping[str, Mapping[object, str]]] = MappingProxyType(
    {
        "side": {"Buy": "buy", "Sell": "sell"},
        "orderType": {"Market": "market", "Limit": "limit"},
        "triggerDirection": {1: "rise", 2: "fall"},
    }
)
_MAX_MSG: Final = 2048
#: A topic the contract can spell (`ExchangeRecord.topic`); any other is left out.
_TOPIC: Final = re.compile(r"[a-z][a-z0-9._-]{0,63}")

type Fields = Mapping[str, object]


def _fields(candidates: Fields) -> ExchangeRecordFields:
    """The candidates that fit their contract fields; any other value is dropped, alone."""
    kept: dict[str, object] = {}
    for key, value in candidates.items():
        if value is None:
            continue
        try:
            ExchangeRecordFields.model_validate({key: value})
        except ValidationError:
            continue
        kept[key] = value
    return ExchangeRecordFields.model_validate(kept)


def request_fields(body: Mapping[str, object]) -> Fields:
    """The request as it went on the wire, in the contract's names: only the keys the body
    carried, so a field the call did not send is never recorded."""
    fields: dict[str, object] = {}
    for key, value in body.items():
        name = WIRE_NAMES.get(key)
        if name is not None:
            spelled = _WIRE_VALUES.get(key)
            fields[name] = value if spelled is None else spelled.get(value)
    return fields


def push_fields(row: Mapping[str, object]) -> Fields:
    """A pushed row in the contract's names: only the allow-listed keys it carried, as it carried
    them (a value that fits no contract field is dropped by `push_record`)."""
    fields: dict[str, object] = {}
    for key, value in row.items():
        name = PUSH_NAMES.get(key)
        if name is not None:
            spelled = _WIRE_VALUES.get(key)
            fields[name] = value if spelled is None else spelled.get(value)
    return fields


def push_record(topic: str, response: Fields) -> ExchangeRecord:
    """One pushed row's record (`transport` `ws_private`): the topic it came on and the row's
    allow-listed fields, nothing else (SR-E29-08)."""
    named = topic if _TOPIC.fullmatch(topic) is not None else None
    return ExchangeRecord(transport="ws_private", topic=named, response_redacted=_fields(response))


def reply_fields(order_link_id: str | None, exchange_order_id: str | None) -> Fields:
    """The reply's own names for the order: the venue's `orderLinkId` as it came."""
    return {"order_link_id": order_link_id, "exchange_order_id": exchange_order_id}


def record(
    *,
    method: Literal["GET", "POST"],
    endpoint: str,
    request: Fields,
    response: Fields | None,
    ret_code: int | None,
    ret_msg: str | None,
    latency_ms: int,
) -> ExchangeRecord:
    """One REST call's record. `ret_msg` is the venue's text, already free of our own key id
    and signature (the REST client masks them); one over the contract's bound is dropped."""
    return ExchangeRecord(
        transport="rest",
        method=method,
        endpoint=endpoint,
        ret_code=ret_code,
        ret_msg=ret_msg if ret_msg is None or len(ret_msg) <= _MAX_MSG else None,
        latency_ms=max(0, latency_ms),
        request_redacted=_fields(request),
        response_redacted=None if response is None else _fields(response),
    )
