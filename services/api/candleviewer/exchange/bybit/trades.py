"""Bybit v5 tape parsing: `publicTrade.{symbol}` WS frames and the REST
`/v5/market/recent-trade` page (E08-S04; C-2.2 keeps venue vocabulary here).

Mapping per `docs/plan/24-internal-schemas.md` §2.1. Bybit's `S` / `side` is
the **taker** side ("Buy" = the taker lifted the ask). `T` is ms -> µs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from candleviewer.exchange.base.frame_guard import (
    MAX_FUTURE_SKEW_MS,
    MAX_PRICE,
    MAX_QTY,
    MAX_TS_MS,
    FrameRejectedError,
    check_event_ts,
    check_price,
    check_qty,
)
from candleviewer.exchange.base.trade_print import (
    MAX_PRINTS_PER_BATCH,
    MAX_TRADE_ID_LEN,
    TradePrint,
)

TOPIC_PREFIX = "publicTrade."
RECENT_TRADE_PATH = "/v5/market/recent-trade"
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,20}$")
_ZERO = Decimal(0)
_SIDES: dict[str, Literal["buy", "sell"]] = {"Buy": "buy", "Sell": "sell"}


def trade_topic(symbol: str) -> str:
    return f"{TOPIC_PREFIX}{symbol}"


def _print(
    symbol: str,
    tid: object,
    ts_ms: object,
    p: object,
    v: object,
    s: object,
    bt: object,
    envelope_ms: int | None = None,
) -> TradePrint:
    if not isinstance(tid, str) or not 0 < len(tid) <= MAX_TRADE_ID_LEN:
        raise ValueError("trade id missing or over length cap")
    side = _SIDES.get(s) if isinstance(s, str) else None
    if side is None:
        raise ValueError("unknown taker side")
    ts = int(str(ts_ms))
    if ts <= 0:
        raise ValueError("bad trade timestamp")
    if ts > MAX_TS_MS or (envelope_ms is not None and ts > envelope_ms + MAX_FUTURE_SKEW_MS):
        check_event_ts(ts, envelope_ms, symbol=symbol)
    try:
        price, qty = Decimal(str(p)), Decimal(str(v))
    except InvalidOperation as exc:
        raise FrameRejectedError("malformed", "unparseable trade number", symbol=symbol) from exc
    # Hot path (C-2.20): one chained comparison each; reason derived on failure only.
    if not (price.is_finite() and _ZERO < price <= MAX_PRICE):
        check_price(price, symbol=symbol)
    if not (qty.is_finite() and _ZERO < qty <= MAX_QTY):
        check_qty(qty, symbol=symbol)
    return TradePrint(symbol, tid, ts * 1000, price, qty, side, bt is True)


def parse_trade_frame(frame: str) -> list[TradePrint] | None:
    """`None` for non-trade frames; `ValueError` (a `FrameRejectedError` with a
    reason once the check is a plausibility one) for a malformed trade frame."""
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
    data = msg.get("data")
    if not _SYMBOL_RE.fullmatch(symbol) or not isinstance(data, list):
        raise ValueError("trade frame carries an invalid symbol or data")
    if len(data) > MAX_PRINTS_PER_BATCH:
        raise ValueError("trade frame exceeds batch cap")
    env_ts = msg.get("ts")
    envelope_ms = env_ts if isinstance(env_ts, int) and not isinstance(env_ts, bool) else None
    out = []
    for d in data:
        if not isinstance(d, dict) or d.get("s") != symbol:
            raise ValueError("trade record malformed")
        out.append(
            _print(
                symbol,
                d.get("i"),
                d.get("T"),
                d.get("p"),
                d.get("v"),
                d.get("S"),
                d.get("BT"),
                envelope_ms,
            )
        )
    return out


def parse_recent_trades(symbol: str, body: Mapping[str, Any]) -> list[TradePrint]:
    rows = (body.get("result") or {}).get("list")
    if not isinstance(rows, list) or len(rows) > MAX_PRINTS_PER_BATCH:
        raise ValueError("recent-trade page malformed or over batch cap")
    return [
        _print(
            symbol,
            r.get("execId"),
            r.get("time"),
            r.get("price"),
            r.get("size"),
            r.get("side"),
            r.get("isBlockTrade"),
        )
        for r in rows
        if isinstance(r, dict) and r.get("symbol") == symbol
    ]


def recent_trades_fetcher(
    get_public: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[[str], Awaitable[Sequence[TradePrint]]]:
    """Bind a REST client's `get_public`; always `limit=1000` (§2.1)."""

    async def fetch(symbol: str) -> Sequence[TradePrint]:
        params = {"category": "linear", "symbol": symbol, "limit": 1000}
        return parse_recent_trades(symbol, await get_public(RECENT_TRADE_PATH, params=params))

    return fetch
