"""Bybit v5 `orderbook.{depth}.{symbol}` WS mapping (E08-S05; C-2.2 keeps venue
vocabulary here).

Mapping per `docs/plan/24-internal-schemas.md` section 2.2. Bybit pushes a
`snapshot` on subscribe (and `u == 1` after a service restart) and `delta`
frames whose `u` increases by exactly one; a `size` of `"0"` deletes a level.
There is no checksum, so a delta carries `prev_update_id = u - 1` and the
book engine treats any mismatch with its own last applied id as a gap.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from candleviewer.exchange.base.frame_guard import (
    MAX_PRICE,
    MAX_QTY,
    FrameRejectedError,
    check_event_ts,
    check_price,
    check_qty,
)
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot

TOPIC_PREFIX = "orderbook."
BOOK_DEPTHS = (1, 50, 200, 500)
MAX_LEVELS_PER_FRAME = 1_000
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,20}$")
_ZERO = Decimal(0)

TickSize = Callable[[str], Decimal | None]


def book_topic(symbol: str, depth: int = 200) -> str:
    if depth not in BOOK_DEPTHS:
        raise ValueError(f"unsupported book depth {depth}")
    return f"{TOPIC_PREFIX}{depth}.{symbol}"


def _levels(raw: object, tick: Decimal, symbol: str) -> tuple[BookLevel, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_LEVELS_PER_FRAME:
        raise ValueError("book side malformed or over level cap")
    out: list[BookLevel] = []
    for row in raw:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("book level malformed")
        try:
            price, qty = Decimal(str(row[0])), Decimal(str(row[1]))
        except InvalidOperation as exc:
            raise ValueError("unparseable book number") from exc
        # Hot path (C-2.20): one chained comparison per value; the precise
        # reason is derived only on failure. Bounded before the division.
        if not (price.is_finite() and _ZERO < price <= MAX_PRICE):
            check_price(price, symbol=symbol)
        if not (qty.is_finite() and _ZERO <= qty <= MAX_QTY):  # "0" deletes a level
            check_qty(qty, allow_zero=True, symbol=symbol)
        ticks, rem = divmod(price, tick)
        if rem:  # #1890: never quantise an off-grid price onto a neighbour row
            raise FrameRejectedError("off_tick", "price not on tick grid", symbol=symbol)
        out.append(BookLevel(price=price, qty=qty, price_ticks=int(ticks)))
    return tuple(out)


def parse_book_frame(frame: str, tick_size: TickSize) -> BookSnapshot | BookDelta | None:
    """`None` for non-book frames; `ValueError` (a `FrameRejectedError` with a
    reason and the symbol once known) for a malformed or implausible frame."""
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
    parts = topic[len(TOPIC_PREFIX) :].split(".")
    if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) not in BOOK_DEPTHS:
        raise ValueError("book frame carries an invalid topic")
    depth, symbol = int(parts[0]), parts[1]
    data = msg.get("data")
    if not _SYMBOL_RE.fullmatch(symbol) or not isinstance(data, dict) or data.get("s") != symbol:
        raise ValueError("book frame carries an invalid symbol or data")
    tick = tick_size(symbol)
    if tick is None or tick <= 0:
        raise ValueError("no tick size for symbol")
    try:
        u, seq, ts_ms = int(data["u"]), int(data.get("seq", 0)), int(msg["ts"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("book frame missing u/ts") from exc
    if u <= 0 or ts_ms <= 0:
        raise ValueError("bad book sequence or timestamp")
    check_event_ts(ts_ms, None, symbol=symbol)
    try:
        cts_ms = int(msg.get("cts", ts_ms))
    except (TypeError, ValueError) as exc:
        raise ValueError("book frame carries a bad cts") from exc
    ts_match = check_event_ts(cts_ms, ts_ms, symbol=symbol) * 1000
    common = {
        "event_id": uuid.uuid4(),
        "ts_event": ts_ms * 1000,
        "ts_ingest": ts_ms * 1000,
        "source": "live",
        "symbol": symbol,
        "depth": depth,
        "bids": _levels(data.get("b", []), tick, symbol),
        "asks": _levels(data.get("a", []), tick, symbol),
        "update_id": u,
        "cross_seq": seq,
        "ts_match": ts_match,
    }
    if msg.get("type") == "snapshot" or u == 1:
        return BookSnapshot.model_validate({**common, "reason": "subscribe"})
    if msg.get("type") != "delta":
        raise ValueError("unknown book frame type")
    return BookDelta.model_validate({**common, "prev_update_id": u - 1})
