"""The allow-listed record of one trading call (SR-E29-08, E29 threat model §6 item 1; G-8, #2877).

Built only from the neutral request and the parsed reply, field by field into the contract's
`ExchangeRecordFields`: no header, signature, `auth` frame or URL query is ever an input, so none
can leave M4 in a record. A value that does not fit its contract field (a symbol outside USDT
linear, an over-long id or message) is dropped from the record, never stored; the store redacts
the record again before insert (E29-T01). The OMS treats it as opaque (C-2.3).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Final, Literal

from pydantic import ValidationError

from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    ExchangeRecord,
    ExchangeRecordFields,
    PlaceOrderRequest,
    TradingStopRequest,
)

__all__ = [
    "amend_fields",
    "cancel_all_fields",
    "cancel_fields",
    "create_fields",
    "record",
    "reply_fields",
    "trading_stop_fields",
]

_TIF: Final = {"gtc": "GTC", "ioc": "IOC", "fok": "FOK", "post_only": "PostOnly"}
_TRIGGER: Final = {"last": "LastPrice", "mark": "MarkPrice", "index": "IndexPrice"}
_TPSL: Final = {"full": "Full", "partial": "Partial"}
_MAX_MSG: Final = 2048

type Fields = Mapping[str, object]


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


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


def create_fields(req: PlaceOrderRequest) -> Fields:
    return {
        "category": "linear",
        "order_link_id": req.order_link_id,
        "symbol": req.symbol,
        "side": req.side,
        "order_type": req.order_type,
        "qty": _text(req.qty),
        "price": _text(req.price),
        "time_in_force": _TIF[req.time_in_force],
        "reduce_only": req.reduce_only,
        "close_on_trigger": req.close_on_trigger,
        "position_idx": req.position_idx,
        "trigger_price": _text(req.trigger_price),
        "trigger_by": None if req.trigger_by is None else _TRIGGER[req.trigger_by],
        "trigger_direction": req.trigger_direction,
        "take_profit": _text(req.take_profit),
        "stop_loss": _text(req.stop_loss),
        "tp_trigger_by": _TRIGGER[req.tp_trigger_by],
        "sl_trigger_by": _TRIGGER[req.sl_trigger_by],
        "tpsl_mode": _TPSL[req.tpsl_mode],
    }


def amend_fields(req: AmendOrderRequest) -> Fields:
    return {
        "category": "linear",
        "order_link_id": req.order_link_id,
        "exchange_order_id": req.exchange_order_id,
        "symbol": req.symbol,
        "qty": _text(req.qty),
        "price": _text(req.price),
        "trigger_price": _text(req.trigger_price),
        "take_profit": _text(req.take_profit),
        "stop_loss": _text(req.stop_loss),
    }


def cancel_fields(req: CancelOrderRequest) -> Fields:
    return {
        "category": "linear",
        "order_link_id": req.order_link_id,
        "exchange_order_id": req.exchange_order_id,
        "symbol": req.symbol,
    }


def cancel_all_fields(symbol: str | None, order_filter: str) -> Fields:
    return {"category": "linear", "symbol": symbol, "order_filter": order_filter}


def trading_stop_fields(req: TradingStopRequest) -> Fields:
    return {
        "category": "linear",
        "symbol": req.symbol,
        "position_idx": req.position_idx,
        "take_profit": _text(req.take_profit),
        "stop_loss": _text(req.stop_loss),
        "trailing_stop": _text(req.trailing_distance),
        "activation_price": _text(req.active_price),
        "tp_trigger_by": _TRIGGER[req.tp_trigger_by],
        "sl_trigger_by": _TRIGGER[req.sl_trigger_by],
        "tpsl_mode": _TPSL[req.tpsl_mode],
    }


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
