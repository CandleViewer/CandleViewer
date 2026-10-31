"""Bybit v5 `allLiquidation.{symbol}` frames (E24-T03 #667; 24 §2.5).

All wire knowledge for the topic lives here (C-2.2). A push is `{topic, type: "snapshot", ts,
data: [{T, s, S, v, p}]}`, at most one per symbol per 500 ms, so `data` carries every print of
that window: each element becomes one `LiquidationEvent`, `batch_index` its position (docs page
`websocket/public/all-liquidation`; the legacy `liquidation.{symbol}` topic is retired).

Strict: the envelope and each element are pydantic models with `extra="forbid"`. Any fault
rejects the whole push with a `ValueError` before a print is written (STRIDE S), so a push
never lands half-stored; prices and sizes pass the shared ingest bounds (`frame_guard`).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.domain.events import uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.frame_guard import (
    FrameRejectedError,
    check_event_ts,
    check_price,
    check_qty,
)
from candleviewer.exchange.base.models import LiquidationEvent

TOPIC_PREFIX: Final = "allLiquidation."
#: A push is one 500 ms window of one symbol; a cascade's is long, never this long.
MAX_PRINTS_PER_PUSH: Final = 1000
MAX_NUMBER_CHARS: Final = 32
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{4,20}$")


class _Print(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    T: int | None = None
    s: str
    S: Literal["Buy", "Sell"]
    v: str = Field(max_length=MAX_NUMBER_CHARS)
    p: str = Field(max_length=MAX_NUMBER_CHARS)


class _Push(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic: str
    type: Literal["snapshot"]
    ts: int
    data: list[_Print] = Field(max_length=MAX_PRINTS_PER_PUSH)


def liquidation_topic(symbol: str) -> str:
    return f"{TOPIC_PREFIX}{symbol}"


def _closing_side(wire: str) -> Literal["buy", "sell"]:
    """`S` is read as the side of the liquidated position's CLOSING order (24 §2.5, the
    project's mapping): `Sell` closes a long. Keep this the one place `S` is interpreted; every
    consumer outside the adapter reads `liquidated_side` (24 §17.4 L6)."""
    return "sell" if wire == "Sell" else "buy"


def _decimal(text: str, what: str, symbol: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise FrameRejectedError("malformed", what, symbol=symbol) from exc


def parse_liquidation_frame(frame: str, ts_ingest_us: int) -> list[LiquidationEvent] | None:
    """Parse one raw WS frame. `None` for any frame that is not an `allLiquidation` push (acks,
    pongs, other topics); `ValueError` (`FrameRejectedError` for plausibility) for one that is
    malformed or implausible, the whole push refused."""
    try:
        msg = json.loads(frame)
    except ValueError:
        return None
    except RecursionError as exc:  # backstop; the pump scans depth before fan-out (#1889)
        raise FrameRejectedError("depth_limit", "frame nests too deep") from exc
    if not isinstance(msg, dict):
        return None
    topic = msg.get("topic")
    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX):
        return None
    symbol = topic[len(TOPIC_PREFIX) :]
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("liquidation frame carries an invalid symbol")
    try:
        push = _Push.model_validate(msg)
    except ValidationError as exc:
        raise ValueError("liquidation frame failed strict validation") from exc
    if push.ts <= 0:
        raise ValueError("liquidation frame missing envelope ts")
    events: list[LiquidationEvent] = []
    for index, item in enumerate(push.data):
        if item.s != symbol:
            raise ValueError("liquidation print names another symbol than its topic")
        ts_ms = push.ts if item.T is None else item.T
        if ts_ms <= 0:
            raise FrameRejectedError("ts_past", "print time", symbol=symbol)
        check_event_ts(ts_ms, push.ts, symbol=symbol)
        price = check_price(_decimal(item.p, "price", symbol), symbol=symbol)
        qty = check_qty(_decimal(item.v, "qty", symbol), symbol=symbol)
        side = _closing_side(item.S)
        events.append(
            LiquidationEvent(
                event_id=EventId(uuid7(ts_ms)),
                ts_event=ts_ms * 1000,
                ts_ingest=ts_ingest_us,
                source="live",
                symbol=symbol,
                price=price,
                qty=qty,
                side=side,
                liquidated_side="long" if side == "sell" else "short",
                notional=price * qty,  # computed once, here, in Decimal (21 §4.6)
                batch_index=index,
                ts_estimated=item.T is None,
            )
        )
    return events


__all__ = [
    "MAX_PRINTS_PER_PUSH",
    "TOPIC_PREFIX",
    "liquidation_topic",
    "parse_liquidation_frame",
]
